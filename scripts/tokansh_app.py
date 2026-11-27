"""Small Linux/WSL application supervisor. No ledger writes or database bootstrap."""
import argparse
import errno
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import sqlite3
import stat
import subprocess
import sys
import time
from urllib.parse import quote
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

REPO = Path(__file__).resolve().parents[1]
PORTS = {'gateway': 8001, 'backend': 8000, 'frontend': 5173}
REQUIRED_SCHEMA_REVISION = '0004_marketplace'
INFO = dict(contract='tokansh', schema_version=1,
            functions=['GetContractInfo', 'GetRegisteredProperty', 'GetOperation', 'RegisterApprovedProperty'],
            supply_interpretation='LIFETIME_CUMULATIVE_ISSUANCE_CEILING')
# Exact M4.1 interface from chaincode GetContractInfo; schema_version remains 1.
INFO_V11 = {**INFO, 'functions': INFO['functions'] +
            ['IssueANSH', 'GetIssuanceState', 'GetBalance', 'GetIssuanceOperation']}

# Historical nine-function metadata remains readable for compatibility, but
# it does not advertise the current issuance policy.
INFO_V12_LEGACY = {**INFO_V11, 'functions': INFO_V11['functions'] + ['TransferANSH']}
# Exact current interface; no arbitrary function supersets are accepted.
INFO_V12 = {**INFO_V12_LEGACY, 'supply_interpretation': 'ONE_TIME_FULL_SUPPLY_ISSUANCE'}
SUPPORTED_CONTRACT_METADATA = (INFO, INFO_V11, INFO_V12_LEGACY, INFO_V12)


class Failure(Exception):
    pass


def require(ok, message):
    if not ok:
        raise Failure(message)


def private(path, directory=False):
    require(not path.is_symlink(), f'Refusing symlink: {path}')
    info = path.stat()
    require(info.st_uid == os.getuid() and not stat.S_IMODE(info.st_mode) & 0o077,
            f'Owner-only permissions required: {path}')
    require(stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode), f'Unexpected file type: {path}')


def identity(pid):
    try:
        fields = Path(f'/proc/{pid}/stat').read_text().rsplit(') ', 1)[1].split()
        if fields[0] == 'Z':
            return None
        return dict(pid=pid, start=fields[19], boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                    exe=os.readlink(f'/proc/{pid}/exe'))
    except (OSError, IndexError):
        return None


def port_free(port):
    # Both wildcard families: catches an existing non-loopback/wildcard listener.
    for family, address in [(socket.AF_INET, ('0.0.0.0', port)), (socket.AF_INET6, ('::', port))]:
        try:
            probe = socket.socket(family)
        except OSError as error:
            if family == socket.AF_INET6 and error.errno == errno.EAFNOSUPPORT:
                continue
            raise
        with probe:
            # Go/Uvicorn/Node listeners permit address reuse on restart. A bare
            # bind would falsely reject their closed connections in TIME_WAIT.
            # Do not enable SO_REUSEPORT: active listeners must still conflict.
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if family == socket.AF_INET6:
                probe.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
            try:
                probe.bind(address)
            except OSError as error:
                if error.errno == errno.EADDRINUSE:
                    return False
                raise Failure(f'Cannot probe port {port} (OS error {error.errno}); inspect local networking.') from None
    return True


def port_listening(port):
    # Linux/WSL kernel state, not a connection attempt or PID ownership guess.
    for name in ('tcp', 'tcp6'):
        try:
            rows = Path('/proc/net/'+name).read_text().splitlines()[1:]
            for row in rows:
                fields = row.split()
                if int(fields[1].rsplit(':', 1)[1], 16) == port and fields[3] == '0A':
                    return True
        except FileNotFoundError:
            if name == 'tcp6':
                continue
            raise Failure('Cannot inspect TCP listeners; refusing to guess port availability.') from None
        except (OSError, ValueError, IndexError):
            raise Failure('Cannot inspect TCP listeners; refusing to guess port availability.') from None
    return False


def wait_port_free(port, timeout=3):
    deadline = time.monotonic()+timeout
    while not port_free(port):
        require(not port_listening(port), f'Port {port} has an unmanaged listening service. Inspect its owner; it will not be killed.')
        remaining = deadline-time.monotonic()
        require(remaining > 0, f'Port {port} remains unavailable after {timeout} seconds without a confirmed listener. Inspect local socket state; no service was killed.')
        time.sleep(min(0.1, remaining))


def configuration():
    from dotenv import dotenv_values
    from sqlalchemy.engine import make_url
    path = Path.home()/'.config/tokansh/local.env'
    require(path.is_file(), f'Missing configuration: {path}')
    private(path.parent, True); private(path)
    # A dotenv file, not executable shell code. Configuration wins over shell drift.
    env = dict(os.environ)
    env.update({k: v for k, v in dotenv_values(path).items() if v is not None})
    for name in ('TOKANSH_GATEWAY_SECRET', 'TOKANSH_OPERATOR_SECRET'):
        require(re.fullmatch('[0-9a-fA-F]{64}', env.get(name, '')) is not None,
                f'{name} must contain an existing 32-byte secret encoded as 64 hex characters.')
    require(env['TOKANSH_GATEWAY_SECRET'].lower() != env['TOKANSH_OPERATOR_SECRET'].lower(), 'Gateway/operator secrets must be distinct.')
    for key in ('DRUNIX_CERT_PATH', 'DRUNIX_KEY_PATH', 'DRUNIX_TLS_CA_PATH'):
        require(Path(env.get(key, '')).is_file(), f'{key} must select existing identity/TLS material.')
    require(env.get('DRUNIX_MSP_ID') == 'Org1MSP', 'The approved signer requires Org1MSP.')
    fixed = dict(DRUNIX_LISTEN_ADDRESS='127.0.0.1:8001', DRUNIX_GATEWAY_URL='http://127.0.0.1:8001',
                 APP_HOST='127.0.0.1', APP_PORT='8000', DRUNIX_CHANNEL='mychannel', DRUNIX_CHAINCODE='basic',
                 DRUNIX_EVALUATE_TIMEOUT='5s')
    for key, value in fixed.items():
        require(env.get(key, value) == value, f'{key} must be {value} for this launcher.')
        env[key] = value
    require(bool(env.get('DRUNIX_PEER_ENDPOINT')) and bool(env.get('DRUNIX_TLS_SERVER_NAME')), 'Configure the existing DRUNIX endpoint and TLS server name.')
    expected = Path.home()/'.local/share/tokansh/tokansh.db'
    require(expected.is_file(), 'Persistent SQLite file is missing; no automatic initialization is allowed.')
    private(expected.parent, True); private(expected)
    url = make_url(env.get('DATABASE_URL', 'sqlite:///'+str(expected)))
    require(url.drivername in ('sqlite', 'sqlite+pysqlite') and not url.query and not url.host,
            'DATABASE_URL must be an absolute SQLite file URL.')
    selected = Path(url.database or '')
    require(selected.is_absolute() and selected.is_file() and selected.samefile(expected), 'DATABASE_URL must select ~/.local/share/tokansh/tokansh.db.')
    env['DATABASE_URL'] = 'sqlite:///'+str(expected.resolve())
    try:
        with sqlite3.connect('file:'+quote(str(expected.resolve()))+'?mode=ro', uri=True) as db:
            db.execute('PRAGMA query_only=ON')
            require(db.execute('SELECT version_num FROM alembic_version').fetchall() == [(REQUIRED_SCHEMA_REVISION,)],
                    f'SQLite migration revision must be {REQUIRED_SCHEMA_REVISION}; migrate only under separate authorization.')
            for table in ('properties', 'application_operations', 'property_events', 'ledger_operations'):
                db.execute(f'SELECT * FROM {table} LIMIT 0')
            db.execute('SELECT operation_id,property_id,state,artifact_json,transaction_id FROM ledger_operations LIMIT 0')
    except sqlite3.Error:
        raise Failure('SQLite schema is unavailable; inspect it manually. No migration was attempted.') from None
    return env


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def http_json(port, path, secret=None):
    headers = {'Authorization': 'Bearer '+secret} if secret else {}
    opener = build_opener(ProxyHandler({}), NoRedirect())
    with opener.open(Request(f'http://127.0.0.1:{port}{path}', headers=headers), timeout=6) as response:
        require(response.status == 200, 'HTTP readiness failed.')
        body = response.read(1_048_577)
        require(len(body) <= 1_048_576, 'HTTP readiness response too large.')
        if port == 5173:
            require(b'<html' in body.lower(), 'Frontend did not return HTML.')
            return None
        return json.loads(body)


def linux_node():
    candidates = [shutil.which('node')]
    candidates += [str(p) for p in sorted((Path.home()/'.nvm/versions/node').glob('*/bin/node'), reverse=True)]
    for candidate in candidates:
        if candidate and os.access(candidate, os.X_OK) and not str(Path(candidate).resolve()).startswith('/mnt/'):
            return str(Path(candidate).resolve())
    raise Failure('Linux Node.js is missing from PATH/NVM. Load your existing WSL Node installation.')


class App:
    def __init__(self):
        self.children = {}
        self.root = Path.home()/'.local/state/tokansh/app'
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        private(self.root, True)

    def record_path(self, name):
        return self.root/(name+'.json')

    def owned(self, name):
        path = self.record_path(name)
        if not path.exists() and not path.is_symlink():
            return None
        private(path)
        try:
            record = json.loads(path.read_text())
            pid = record['pid']
            require(type(pid) is int and pid > 1, 'Malformed PID record; inspect runtime files manually.')
            return record if identity(pid) == record else None
        except (ValueError, KeyError):
            raise Failure('Malformed PID record; inspect runtime files manually.') from None

    def stop_one(self, name):
        signalled = False
        record = self.owned(name)
        if record:
            # Open a stable process handle BEFORE rechecking identity. PID reuse
            # between the check and signal can never target a different process.
            try:
                fd = os.pidfd_open(record['pid'])
            except ProcessLookupError:
                fd = None
            if fd is not None:
                try:
                    if identity(record['pid']) == record:
                        signal.pidfd_send_signal(fd, signal.SIGTERM)
                        signalled = True
                        deadline = time.monotonic()+8
                        while identity(record['pid']) == record and time.monotonic() < deadline:
                            time.sleep(0.1)
                        if identity(record['pid']) == record:
                            signal.pidfd_send_signal(fd, signal.SIGKILL)
                            deadline = time.monotonic()+2
                            while identity(record['pid']) == record and time.monotonic() < deadline:
                                time.sleep(0.1)
                            require(identity(record['pid']) != record, f'{name} did not exit; PID record retained for inspection.')
                except ProcessLookupError:
                    pass
                finally:
                    os.close(fd)
        child = self.children.get(name)
        if child is not None and signalled:
            try:child.wait(timeout=2)
            except subprocess.TimeoutExpired:raise Failure(f'{name} has not exited; PID record retained.') from None
            self.children.pop(name)
        elif child is not None and child.poll() is not None:
            child.wait();self.children.pop(name)
        self.record_path(name).unlink(missing_ok=True)

    def launch(self, name, argv, cwd, env):
        path = self.root/(name+'.log')
        if path.exists() or path.is_symlink():
            private(path)
        with path.open('ab') as log:
            os.chmod(path, 0o600)
            proc = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                    stdout=log, stderr=log, start_new_session=True)
        self.children[name] = proc
        record = identity(proc.pid)
        if record is None:
            raise Failure(f'{name} exited immediately; inspect {path}.')
        try:
            temporary = self.root/(name+'.new')
            if temporary.exists() or temporary.is_symlink():private(temporary)
            with temporary.open('w') as file:
                json.dump(record, file);file.flush();os.fsync(file.fileno())
            os.chmod(temporary, 0o600)
            temporary.replace(self.record_path(name))
        except BaseException:
            # Popen is still our child here, not a PID-file lookup.
            proc.terminate();proc.wait(timeout=8)
            raise

    def wait_health(self, name):
        deadline = time.monotonic()+30
        while time.monotonic() < deadline:
            require(self.owned(name), f'{name} exited; inspect {self.root/name}.log.')
            try:
                data = http_json(PORTS[name], '/' if name == 'frontend' else '/health')
                if name != 'frontend':
                    require(data.get('data', {}).get('status') == 'UP', 'Malformed health response.')
                return
            except Exception:
                time.sleep(0.25)
        raise Failure(f'{name} health check timed out; inspect {self.root/name}.log and port {PORTS[name]}.')

    def start(self):
        env = configuration()
        for name, port in PORTS.items():
            if not self.owned(name):
                wait_port_free(port)
                self.record_path(name).unlink(missing_ok=True)
        node = linux_node()
        require((REPO/'frontend/node_modules/vite/bin/vite.js').is_file(), 'Existing frontend dependencies are missing; install them manually.')
        binary = self.root/'gateway'
        if not self.owned('gateway'):
            require(shutil.which('go'), 'Go is missing from PATH.')
            buildenv = {**env, 'GOPROXY': 'off', 'GOSUMDB': 'off', 'GOTOOLCHAIN': 'local'}
            for path in (self.root/'build.log', self.root/'gateway.new'):
                if path.exists() or path.is_symlink():private(path)
            print('Building Gateway from pinned cached dependencies (maximum 120 seconds)...', flush=True)
            with (self.root/'build.log').open('ab') as log:
                os.chmod(self.root/'build.log', 0o600)
                try:
                    subprocess.run(['go', 'build', '-mod=readonly', '-o', str(self.root/'gateway.new'), './cmd/gateway'],
                                   cwd=REPO/'gateway', env=buildenv, stdout=log, stderr=log, check=True, timeout=120)
                except (subprocess.SubprocessError, OSError):
                    raise Failure(f'Gateway build failed/timed out. Check {self.root}/build.log; use the existing pinned toolchain/dependency cache.') from None
            (self.root/'gateway.new').replace(binary)
        frontend_env = {k: v for k, v in env.items() if k in ('HOME', 'PATH', 'LANG', 'TERM', 'TMPDIR', 'VITE_API_MODE', 'VITE_API_BASE_URL')}
        commands = {'gateway': ([str(binary)], REPO/'gateway', env),
                    'backend': ([sys.executable, '-m', 'uvicorn', 'app.main:create_app', '--factory', '--host', '127.0.0.1', '--port', '8000'], REPO/'backend', env),
                    'frontend': ([node, str(REPO/'frontend/node_modules/vite/bin/vite.js'), '--host', '127.0.0.1', '--port', '5173', '--strictPort'], REPO/'frontend', frontend_env)}
        started = []
        try:
            for name in PORTS:
                if not self.owned(name):
                    print(f'Starting {name} on port {PORTS[name]}...', flush=True)
                    self.launch(name, *commands[name]);started.append(name)
                self.wait_health(name)
                if name == 'gateway':
                    try:
                        data = http_json(8001, '/v1/tokansh/contract-info', env['TOKANSH_GATEWAY_SECRET'])
                        require(isinstance(data, dict) and isinstance(data.get('data'), dict) and type(data['data'].get('schema_version')) is int and data in tuple({'data': info} for info in SUPPORTED_CONTRACT_METADATA), 'Unexpected TokANSH contract metadata.')
                    except Exception:
                        raise Failure('Gateway contract evaluation failed. Check identity, secrets, TLS and separately managed DRUNIX availability; no fallback or ledger write occurred.') from None
            require(all(self.owned(n) for n in PORTS), 'An application process exited during startup.')
        except BaseException:
            for name in reversed(started):
                self.stop_one(name)
            raise
        print('TokANSH started: frontend http://127.0.0.1:5173; API :8000; Gateway :8001. Read connectivity verified; business transaction readiness is not established.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['start', 'stop', 'restart', 'status', 'logs'])
    args = parser.parse_args()
    os.umask(0o077)
    require(hasattr(os, 'pidfd_open') and hasattr(signal, 'pidfd_send_signal'), 'Linux/WSL pidfd support is required; refusing unsafe PID-only signalling.')
    app = App()
    lockpath = app.root/'lock'
    if lockpath.exists() or lockpath.is_symlink():private(lockpath)
    with lockpath.open('a') as lock:
        try:fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:raise Failure('Another lifecycle command is running; wait for it to finish.') from None
        if args.action in ('stop', 'restart'):
            for name in reversed(PORTS):app.stop_one(name)
            print('Managed application processes stopped. DRUNIX and SQLite were not modified.')
        if args.action in ('start', 'restart'):app.start()
        if args.action == 'status':
            for name, port in PORTS.items():
                path = app.record_path(name)
                state = 'RUNNING (owned)' if app.owned(name) else ('STALE record' if path.exists() else 'STOPPED')
                port_state = 'available' if port_free(port) else 'occupied'
                print(f'{name}: {state}; port {port} {port_state}')
        if args.action == 'logs':
            for name in ('build', *PORTS):
                path = app.root/(name+'.log');print(f'--- {name}: {path} ---')
                if path.exists() or path.is_symlink():
                    private(path)
                    with path.open('rb') as log:
                        log.seek(0, 2);log.seek(max(0, log.tell()-16384))
                        print(log.read().decode(errors='replace'))


if __name__ == '__main__':
    try:main()
    except Exception:
        # Never print exception reprs containing configuration/credentials.
        error = sys.exc_info()[1]
        print(str(error) if isinstance(error, Failure) else 'Local lifecycle operation failed; check file permissions and runtime logs.', file=sys.stderr)
        sys.exit(1)
