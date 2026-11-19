"""M4.1 local-only upgrade: one authorized phase, strict inspection, no retries.

Fresh approval is deliberately unavailable: the pinned DRUNIX SCC has no safe
absence signal. This runner never calls approveformyorg or business invocations.
"""
import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import ssl
import stat
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]

def module(name):
    spec = importlib.util.spec_from_file_location(name, HERE / (name + '.py'))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result

checks = module('deployment-checks')
inspect = module('lifecycle-inspect')
POLICY = "AND('Org1MSP.peer','Org2MSP.peer')"
FUNCTIONS = ['GetContractInfo', 'GetRegisteredProperty', 'GetOperation', 'RegisterApprovedProperty']
M4_FUNCTIONS = FUNCTIONS + ['IssueANSH', 'GetIssuanceState', 'GetBalance', 'GetIssuanceOperation']
PHASES = ['package', 'preflight', 'install-org1', 'install-org2', 'approve-org1',
          'approve-org2', 'readiness', 'commit', 'verify']
PARAMS = dict(channel='mychannel', chaincode='tokansh', current_version='1.0',
              current_sequence=1, version='1.1', sequence=2, policy=POLICY, init_required=False)
UUID = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$')

class Stop(Exception):
    pass

def require(ok, message='Malformed or conflicting upgrade input'):
    if not ok:
        raise Stop(message)

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def fields(value, expected):
    require(isinstance(value, dict) and set(value) == set(expected))

def sha(value):
    require(isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value) is not None)
    return value

def identifier(value):
    require(isinstance(value, str) and UUID.fullmatch(value) is not None)
    return value

def release_id(value):
    require(isinstance(value, str) and re.fullmatch('[A-Za-z0-9_-]{8,80}', value) is not None)
    return value

def external(value, network=None):
    require(isinstance(value, str) and value.startswith('/') and not any(c in value for c in '\0\r\n'))
    path = Path(value).resolve()
    require(not path.is_relative_to(REPO) and (network is None or not path.is_relative_to(network)),
            'Release files must be outside both repositories')
    return path

def private(path, directory=False):
    info = path.lstat()
    require(not stat.S_ISLNK(info.st_mode) and info.st_uid == os.getuid() and info.st_mode & 0o077 == 0,
            'Release files/directories must be operator-owned and owner-only')
    require(stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))

def save(path, value):
    # Exclusive creation: never overwrite baselines, artifacts or mutation receipts.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as out:
        json.dump(value, out, sort_keys=True, separators=(',', ':'), allow_nan=False)
        out.write('\n')
        out.flush()
        os.fsync(out.fileno())
    syncdir(path.parent)

def syncdir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)

def definitions(value):
    fields(value, ['chaincode_definitions'])
    require(isinstance(value['chaincode_definitions'], list))
    result = {}
    for row in value['chaincode_definitions']:
        inspect.definition(row, True)  # strict shape/types, not its v1-only match result
        require(row['name'] not in result, 'Duplicate chaincode definition')
        result[row['name']] = {**row, 'init_required': row.get('init_required', False)}
    require('basic' in result and 'tokansh' in result, 'Required committed definition missing')
    return result

def expected_definition(value, version, sequence):
    inspect.definition(value, True)
    expected = dict(name='tokansh', version=version, sequence=sequence,
                    endorsement_plugin='escc', validation_plugin='vscc',
                    validation_parameter=inspect.POLICY, collections={}, init_required=False)
    require({**value, 'init_required': value.get('init_required', False)} == expected,
            'Unexpected TokANSH lifecycle definition or endorsement policy')

def approval(value, version, sequence, package_id=None):
    inspect.definition(value, False)
    source = value.get('source')
    fields(source, ['Type']); fields(source['Type'], ['LocalPackage'])
    fields(source['Type']['LocalPackage'], ['package_id'])
    package = source['Type']['LocalPackage']['package_id']
    inspect.package(package)
    row = {k: v for k, v in value.items() if k != 'source'}
    expected_definition(dict(row, name='tokansh'), version, sequence)
    require(package_id is None or package == package_id, 'Conflicting approval package')
    return {**value, 'init_required': value.get('init_required', False)}

def readiness(value):
    require(isinstance(value, dict) and {'approvals'} <= value.keys() <= {'approvals', 'mismatches'})
    fields(value['approvals'], ['Org1MSP', 'Org2MSP'])
    if 'mismatches' in value:
        require(isinstance(value['mismatches'], dict) and value['mismatches'] == {})
    require(all(v is True for v in value['approvals'].values()) and not value.get('mismatches'),
            'Both exact organization approvals are required')

def assets(value):
    require(isinstance(value, list) and len(value) == 6, 'Expected six basic assets')
    seen = set()
    for row in value:
        fields(row, ['ID', 'Color', 'Size', 'Owner', 'AppraisedValue'])
        require(all(isinstance(row[k], str) and row[k] for k in ('ID', 'Color', 'Owner')))
        require(all(type(row[k]) is int for k in ('Size', 'AppraisedValue')))
        require(row['ID'] not in seen); seen.add(row['ID'])
    return sorted(value, key=lambda a: a['ID'])

def info(value, upgraded):
    fields(value, ['contract', 'schema_version', 'functions', 'supply_interpretation'])
    require(value['contract'] == 'tokansh' and type(value['schema_version']) is int and value['schema_version'] == 1
            and value['functions'] == (M4_FUNCTIONS if upgraded else FUNCTIONS)
            and value['supply_interpretation'] == 'LIFETIME_CUMULATIVE_ISSUANCE_CEILING', 'Unexpected contract metadata')

def records(prop, op, property_id, operation_id):
    fields(prop, ['schema_version', 'property_id', 'issuer_id', 'approval_reference', 'approval_digest',
        'approved_supply', 'issue_price_minor', 'currency', 'registered_by_msp', 'registered_by_principal',
        'registration_operation_id', 'registration_transaction_id', 'proposal_timestamp'])
    fields(op, ['schema_version', 'operation_id', 'authorizing_msp', 'authorizing_principal', 'function',
        'request_digest', 'property_id', 'original_transaction_id', 'result'])
    fields(op['result'], ['property_id', 'operation_id', 'transaction_id'])
    for value in (prop['property_id'], prop['issuer_id'], prop['approval_reference'], prop['registration_operation_id']):
        identifier(value)
    sha(prop['approval_digest']); sha(op['request_digest'])
    require(type(prop['schema_version']) is int and prop['schema_version'] == 1
            and type(op['schema_version']) is int and op['schema_version'] == 1)
    require(type(prop['approved_supply']) is int and 1 <= prop['approved_supply'] <= 9007199254740991
            and isinstance(prop['issue_price_minor'], str) and re.fullmatch('[1-9][0-9]{0,15}', prop['issue_price_minor'])
            and prop['currency'] == 'INR' and isinstance(prop['proposal_timestamp'],str) and bool(prop['proposal_timestamp']))
    require(prop['property_id'] == op['property_id'] == property_id
            and prop['registration_operation_id'] == op['operation_id'] == operation_id
            and prop['registered_by_msp'] == op['authorizing_msp'] == 'Org1MSP'
            and isinstance(prop['registered_by_principal'], str) and bool(prop['registered_by_principal'])
            and prop['registered_by_principal'] == op['authorizing_principal']
            and op['function'] == 'RegisterApprovedProperty'
            and isinstance(prop['registration_transaction_id'], str) and bool(prop['registration_transaction_id'])
            and prop['registration_transaction_id'] == op['original_transaction_id']
            and op['result'] == dict(property_id=property_id, operation_id=operation_id,
                                     transaction_id=op['original_transaction_id']), 'Registration records disagree')

def channel(value):
    return checks.channel(value)

def snapshot(value, deployment_id):
    fields(value, ['schema_version', 'deployment_id', 'channel', 'property_id', 'operation_id', 'cp_certificate_sha256', 'organizations'])
    require(type(value['schema_version']) is int and value['schema_version'] == 1
            and value['deployment_id'] == deployment_id and value['channel'] == 'mychannel')
    identifier(value['property_id']); identifier(value['operation_id'])
    fields(value['cp_certificate_sha256'], ['Org1MSP', 'Org2MSP'])
    for pin in value['cp_certificate_sha256'].values(): sha(pin)
    fields(value['organizations'], ['1', '2'])
    for org in value['organizations'].values():
        fields(org, ['channel', 'definitions', 'basic', 'property', 'operation', 'info', 'approval_v1'])
        channel(org['channel'])
        defs = definitions({'chaincode_definitions': list(org['definitions'].values())})
        require(defs == org['definitions'])
        expected_definition(defs['tokansh'], '1.0', 1)
        assets(org['basic']); info(org['info'], False)
        records(org['property'], org['operation'], value['property_id'], value['operation_id'])
        approval(org['approval_v1'], '1.0', 1)
    a, b = value['organizations'].values()
    for field in ('channel', 'definitions', 'basic', 'property', 'operation', 'info'):
        require(a[field] == b[field], 'Baseline organizations disagree')
    return value

def preserve(baseline, actual, upgraded):
    expected_definition(actual['organizations']['1']['definitions']['tokansh'], '1.1' if upgraded else '1.0', 2 if upgraded else 1)
    a, b = actual['organizations'].values()
    for field in ('channel', 'definitions', 'basic', 'property', 'operation', 'info'):
        require(a[field] == b[field], 'Organizations disagree')
    for org in ('1', '2'):
        old, new = baseline['organizations'][org], actual['organizations'][org]
        for field in ('basic', 'property', 'operation', 'approval_v1'):
            require(old[field] == new[field], 'Preservation mismatch: ' + field)
        require({k:v for k,v in old['definitions'].items() if k != 'tokansh'} ==
                {k:v for k,v in new['definitions'].items() if k != 'tokansh'}, 'Unexpected other-chaincode definition change')
        start, end = channel(old['channel']), channel(new['channel'])
        require(end['height'] >= start['height'], 'Channel height regressed')
        if end['height'] == start['height']: require(end == start, 'Hashes changed at baseline height')
        if upgraded: require(end['height'] > start['height'], 'Upgrade must advance ledger height')
        info(new['info'], upgraded)

class Runner:
    def __init__(self, network, release):
        self.network, self.release = network, release
        self.net = network / 'drunix-network/test-network'
        self.peer = network / 'build/bin/peer'
        self.evidence = Path(tempfile.mkdtemp(prefix='upgrade-evidence-', dir=release))
        self.count = 0
        # Do not inherit peer overrides, connection profiles, proxy settings or application secrets.
        self.env = {k: v for k, v in os.environ.items() if k in ('PATH', 'HOME', 'GOCACHE', 'GOMODCACHE', 'TMPDIR')}
        self.env.update(FABRIC_CFG_PATH=str(network/'drunix-network/config'), CORE_PEER_TLS_ENABLED='true', FABRIC_LOGGING_SPEC='info')

    def env_for(self, org, lite=False, application=False):
        port = {('1', False):7061, ('2', False):9061, ('1', True):7051, ('2', True):9051}[(org, lite)]
        signer = '1' if application else org
        user = 'User1' if application else 'Admin'
        msp = self.net / f'organizations/peerOrganizations/org{signer}.example.com/users/{user}@org{signer}.example.com/msp'
        require(msp.is_dir(), 'Configured existing MSP directory missing')
        return dict(self.env, CORE_PEER_LOCALMSPID=f'Org{signer}MSP', CORE_PEER_MSPCONFIGPATH=str(msp),
            CORE_PEER_TLS_ROOTCERT_FILE=str(self.net/f'organizations/peerOrganizations/org{org}.example.com/peers/peer0.org{org}.example.com/tls/ca.crt'),
            CORE_PEER_ADDRESS=f'localhost:{port}', CORE_PEER_TLS_SERVERHOSTOVERRIDE=f'peer{0 if lite else 1}.org{org}.example.com')

    def run(self, args, env=None, cwd=None, timeout=30):
        self.count += 1
        # Raw diagnostics remain private external evidence, never console/Git.
        with (self.evidence/f'{self.count:03}.stdout').open('xb') as out, (self.evidence/f'{self.count:03}.stderr').open('xb') as err:
            try:
                result = subprocess.run([str(a) for a in args], env=env or self.env, cwd=cwd,
                                        stdout=out, stderr=err, timeout=timeout, check=False)
            except (OSError, subprocess.TimeoutExpired):
                raise Stop('UNKNOWN: command unavailable or timed out; inspect private evidence, no retry') from None
        require(result.returncode == 0, 'UNKNOWN: CLI failed; absence/effect not established, no retry')
        return (self.evidence/f'{self.count:03}.stdout').read_text()

    def query(self, args, org='1', lite=False, application=False):
        return checks.parse_json(self.run([self.peer]+args, self.env_for(org, lite, application)))

    def pins(self):
        pins = {}
        for org in ('1', '2'):
            cert = self.net/f'organizations/peerOrganizations/org{org}.example.com/peers/peer1.org{org}.example.com/tls/server.crt'
            pins['Org'+org+'MSP'] = hashlib.sha256(ssl.PEM_cert_to_DER_cert(cert.read_text())).hexdigest()
        return pins

    def height(self, org):
        text = self.run([self.peer, 'channel', 'getinfo', '-c', 'mychannel'], self.env_for(org))
        require(text.startswith('Blockchain info: '))
        return channel(checks.parse_json(text[len('Blockchain info: '):]))

    def approval(self, org, sequence, version, package_id=None):
        value = self.query(['lifecycle','chaincode','queryapproved','-C','mychannel','--name','tokansh','--sequence',str(sequence),'--output','json'], org)
        approval(value, version, sequence, package_id)
        return {**value, 'init_required': value.get('init_required', False)}

    def capture(self, deployment_id, property_id, operation_id):
        result = dict(schema_version=1, deployment_id=deployment_id, channel='mychannel',
            property_id=identifier(property_id), operation_id=identifier(operation_id), cp_certificate_sha256=self.pins(), organizations={})
        before = {org:self.height(org) for org in ('1','2')}
        require(before['1'] == before['2'], 'Committing peers disagree')
        for org in ('1','2'):
            defs = definitions(self.query(['lifecycle','chaincode','querycommitted','-C','mychannel','--output','json'], org))
            lite = definitions(self.query(['lifecycle','chaincode','querycommitted','-C','mychannel','--output','json'], org, True))
            require(defs == lite, 'Lite/Committing peer definitions disagree')
            query = lambda cc, args, app=False: self.query(['chaincode','query','-C','mychannel','-n',cc,'-c',json.dumps({'Args':args})], org, True, app)
            prop = query('tokansh', ['GetRegisteredProperty',property_id], True)
            op = query('tokansh', ['GetOperation','Org1MSP',operation_id], True)
            records(prop, op, property_id, operation_id)
            result['organizations'][org] = dict(channel=before[org], definitions=defs,
                basic=assets(query('basic',['GetAllAssets'])), property=prop, operation=op,
                info=query('tokansh',['GetContractInfo'], True), approval_v1=self.approval(org,1,'1.0'))
        require(before == {org:self.height(org) for org in ('1','2')}, 'Channel changed during snapshot; stop for review')
        return result

    def installed(self, org, package_id):
        value = self.query(['lifecycle','chaincode','queryinstalled','--output','json'], org, True)
        result = inspect.installed(value, package_id)
        require(result in (inspect.MATCH, inspect.ABSENT), 'Conflicting or invalid installation state')
        return result

    def ready(self):
        args = definition_args()
        for org in ('1','2'):
            readiness(self.query(['lifecycle','chaincode','checkcommitreadiness']+args+['--output','json'], org))

    def mutate_once(self, phase, args, env, binding):
        marker = self.release / ('attempt-' + phase + '.json')
        require(not marker.exists(), 'Prior mutation attempt exists; inspect outcome, do not repeat')
        # Durable UNKNOWN intent precedes process creation. Never overwritten/deleted,
        # even if the process dies before/after acknowledgement. Later inspection is separate.
        save(marker, dict(state='UNKNOWN', phase=phase, context_sha256=binding,
                          note='One lifecycle attempt authorized; outcome requires independent inspection'))
        self.run(args, env, timeout=60)
        save(self.release/('acknowledged-'+phase+'.json'), dict(state='ACKNOWLEDGED_NOT_VERIFIED', context_sha256=binding))

    def tls_commit(self):
        for org in ('1','2'):
            cert = self.net/f'organizations/peerOrganizations/org{org}.example.com/peers/peer1.org{org}.example.com/tls/server.crt'
            ca = self.net/f'organizations/peerOrganizations/org{org}.example.com/peers/peer0.org{org}.example.com/tls/ca.crt'
            self.run(['openssl','x509','-in',cert,'-noout','-checkhost','localhost'])
            self.run(['openssl','x509','-in',cert,'-noout','-checkend','0'])
            self.run(['openssl','verify','-CAfile',ca,cert])


def definition_args():
    return ['--channelID','mychannel','--name','tokansh','--version','1.1','--sequence','2',
            '--signature-policy',POLICY,'--endorsement-plugin','escc','--validation-plugin','vscc','--init-required=false']

def orderer_args(runner):
    return ['-o','localhost:7050','--ordererTLSHostnameOverride','orderer.example.com','--tls','--cafile',
        str(runner.net/'organizations/ordererOrganizations/example.com/orderers/orderer.example.com/tls/ca.crt')]


def context(path, expected_sha, deployment_id):
    path = external(str(path)); private(path); private(path.parent, True)
    require(digest(path) == sha(expected_sha), 'Reviewed context hash mismatch')
    m = checks.load(path)
    fields(m, set(PARAMS) | {'schema_version','deployment_id','network_root','release_directory','package_path','package_sha256',
        'package_id','package_identity_path','package_identity_sha256','baseline_path','baseline_sha256','cp_certificate_sha256','source_revision'})
    require(type(m['schema_version']) is int and m['schema_version'] == 1 and m['deployment_id'] == release_id(deployment_id))
    require(all(type(m[k]) is type(v) and m[k] == v for k,v in PARAMS.items()), 'Unreviewed lifecycle parameters')
    network = external(m['network_root'])
    release = external(m['release_directory'], network); private(release, True)
    require(path.parent == release, 'Context must belong to its release directory')
    for key in ('package_path','baseline_path','package_identity_path'):
        p = external(m[key], network); private(p)
        require(p.parent == release and digest(p) == sha(m[key.replace('_path','_sha256')]), 'Release input hash/path mismatch')
    require(m['package_id'] == 'tokansh_1.1:' + m['package_sha256'], 'Unexpected package identity')
    identity = checks.load(m['package_identity_path'])
    fields(identity, ['schema_version','deployment_id','source_revision','source_files','package_sha256','package_id','package_size_bytes','label'])
    require(type(identity['schema_version']) is int and identity['schema_version'] == 1
            and identity['deployment_id'] == deployment_id and identity['source_revision'] == m['source_revision']
            and isinstance(m['source_revision'],str) and re.fullmatch('[0-9a-f]{40}',m['source_revision'])
            and identity['package_id'] == m['package_id'] and identity['package_sha256'] == m['package_sha256']
            and identity['label'] == 'tokansh_1.1' and type(identity['package_size_bytes']) is int
            and identity['package_size_bytes'] == Path(m['package_path']).stat().st_size)
    require(isinstance(identity['source_files'],dict) and {'go.mod','go.sum','main.go','contract/issuance.go'} <= identity['source_files'].keys())
    for name, value in identity['source_files'].items():
        require(isinstance(name,str) and not Path(name).is_absolute() and '..' not in Path(name).parts)
        sha(value)
    baseline = snapshot(checks.load(m['baseline_path']), deployment_id)
    require(m['cp_certificate_sha256'] == baseline['cp_certificate_sha256'])
    return m, baseline, network, release


def execute(phase, runner, m, baseline, binding):
    require(runner.pins() == m['cp_certificate_sha256'], 'Local network certificate binding mismatch')
    require(runner.run([runner.peer,'lifecycle','chaincode','calculatepackageid',m['package_path']]).strip() == m['package_id'])
    actual = runner.capture(m['deployment_id'],baseline['property_id'],baseline['operation_id'])
    current = actual['organizations']['1']['definitions']['tokansh']
    upgraded = current['version'] == '1.1' and current['sequence'] == 2
    preserve(baseline, actual, upgraded)
    save(runner.evidence/'snapshot.json', actual)
    org = phase[-1] if phase[-1:] in ('1','2') else None
    if phase.startswith('install-'):
        if runner.installed(org,m['package_id']) == inspect.MATCH:
            print('MATCH: reviewed package installed; no mutation'); return
        require(not upgraded, 'Already upgraded; missing installation requires independent review')
        runner.mutate_once(phase,[runner.peer,'lifecycle','chaincode','install',m['package_path']],runner.env_for(org,True),binding)
        print('Installation command acknowledged; STOP. Inspect installation separately.'); return
    if phase.startswith('approve-'):
        require(runner.installed(org,m['package_id']) == inspect.MATCH, 'Package not installed')
        runner.approval(org,2,'1.1',m['package_id'])
        print('MATCH: exact sequence-2 approval exists; no mutation. Fresh approval remains disabled.'); return
    for member in ('1','2'):
        require(runner.installed(member,m['package_id']) == inspect.MATCH, 'Package not installed')
        runner.approval(member,2,'1.1',m['package_id'])
    if phase == 'verify':
        require(upgraded, 'Target definition not committed')
        print('PASS: both CPs/LPs agree; target definition, approvals, installations and preserved records verified.'); return
    require(not upgraded, 'Target already committed; use separately authorized verify')
    runner.ready()
    if phase == 'readiness':
        print('PASS: exact approvals/readiness; STOP. Commit is not authorized.'); return
    require(phase == 'commit')
    runner.tls_commit()
    # Final fresh preservation/definition inspection immediately before mutation.
    final = runner.capture(m['deployment_id'],baseline['property_id'],baseline['operation_id'])
    preserve(baseline,final,False)
    require(final['organizations']['1']['channel'] == actual['organizations']['1']['channel'],
            'Unexpected channel change during commit inspection')
    env = runner.env_for('1'); env.pop('CORE_PEER_TLS_SERVERHOSTOVERRIDE')
    args = [runner.peer,'lifecycle','chaincode','commit']+orderer_args(runner)+definition_args()
    for member,port in (('1',7061),('2',9061)):
        args += ['--peerAddresses',f'localhost:{port}','--tlsRootCertFiles',str(runner.net/f'organizations/peerOrganizations/org{member}.example.com/peers/peer0.org{member}.example.com/tls/ca.crt')]
    runner.mutate_once(phase,args+['--waitForEvent','--waitForEventTimeout','30s'],env,binding)
    print('Commit command acknowledged, not independently verified. STOP; authorize verify separately.')


def prepare_package(runner, deployment_id, revision):
    require(runner.run(['git','branch','--show-current'],cwd=REPO).strip() == 'feat/frontend-connected-mode')
    require(runner.run(['git','rev-parse','HEAD'],cwd=REPO).strip() == revision and re.fullmatch('[0-9a-f]{40}',revision))
    require(not runner.run(['git','status','--porcelain'],cwd=REPO).strip(), 'Reviewed source must be committed and clean before packaging')
    identity_path = runner.release/'package-identity.json'
    require(not any((runner.release/name).exists() for name in ('package-identity.json','tokansh_1.1.tar.gz','reproducibility-check.tar.gz','validated-chaincode','staged-chaincode')), 'Do not overwrite a release')
    root = REPO/'chaincode/tokansh'
    paths = runner.run(['git','ls-files','chaincode/tokansh'],cwd=REPO).splitlines()
    staged = runner.release/'staged-chaincode'; staged.mkdir(mode=0o700)
    hashes = {}
    for name in paths:
        source = REPO/name
        require(source.is_file() and not source.is_symlink())
        relative = source.relative_to(root)
        require(not any(c in str(relative) for c in '\0\r\n'))
        target = staged/relative; target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(source,target); hashes[str(relative)] = digest(source)
    require('contract/issuance.go' in hashes, 'Reviewed M4 source missing')
    env = dict(runner.env,GOTOOLCHAIN='local',GOPROXY='off',GOSUMDB='off',GOFLAGS='-mod=readonly')
    runner.run(['go','mod','vendor'],env,staged,120)
    require(digest(staged/'go.mod') == hashes['go.mod'] and digest(staged/'go.sum') == hashes['go.sum'])
    env['GOFLAGS'] = '-mod=vendor'
    for args in (['go','test','-count=1','-timeout=60s','./...'],['go','test','-race','-count=1','-timeout=60s','./...'],['go','vet','./...'],['go','build','-o',str(runner.release/'validated-chaincode'),'.']):
        runner.run(args,env,staged,180)
    package = runner.release/'tokansh_1.1.tar.gz'
    repeat = runner.release/'reproducibility-check.tar.gz'
    for destination in (package,repeat):
        runner.run([runner.peer,'lifecycle','chaincode','package',destination,'--path',staged,'--lang','golang','--label','tokansh_1.1'])
    require(digest(package) == digest(repeat), 'Packaging was not reproducible')
    package_id = runner.run([runner.peer,'lifecycle','chaincode','calculatepackageid',package]).strip()
    require(package_id == 'tokansh_1.1:'+digest(package))
    require(all(digest(staged/name) == value for name,value in hashes.items()), 'Staged reviewed source changed')
    require(not runner.run(['git','status','--porcelain'],cwd=REPO).strip(), 'Source repository changed during packaging')
    save(identity_path,dict(schema_version=1,deployment_id=deployment_id,source_revision=revision,source_files=hashes,
        package_sha256=digest(package),package_id=package_id,package_size_bytes=package.stat().st_size,label='tokansh_1.1'))
    print('PASS: staged tests/build and reproducible package. Review package-identity.json; no installation performed.')


def main(argv=None):
    os.umask(0o077)
    argv = list(sys.argv[1:] if argv is None else argv)
    require(len(argv) >= 2 and argv[0] in PHASES and argv[1] == '--authorize-'+argv[0],
            'Exactly one phase and its explicit organization-specific acknowledgement are required')
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('phase',choices=PHASES)
    for name in ('context','context-sha256','deployment-id','network-root','release-directory','source-revision',
                 'property-id','operation-id','preservation-baseline','preservation-sha256'):
        p.add_argument('--'+name)
    args = p.parse_args([argv[0]] + argv[2:])
    deployment_id = release_id(args.deployment_id)
    if args.phase in ('preflight','package'):
        require(not args.context and not args.context_sha256, 'Do not reuse an old deployment context')
        network = external(args.network_root); release = external(args.release_directory,network)
        private(release,True)
        m = baseline = None
    else:
        m,baseline,network,release = context(args.context,args.context_sha256,deployment_id)
    # Local advisory lock only; trusted operator/filesystem remains the boundary.
    lock_fd = os.open(release/'upgrade.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(lock_fd, 'a') as lock:
        private(release/'upgrade.lock')
        try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError: raise Stop('Another release phase is running') from None
        runner = Runner(network,release)
        print('Phase='+args.phase+'; private evidence='+str(runner.evidence))
        if args.phase == 'package':
            prepare_package(runner,deployment_id,args.source_revision)
        elif args.phase == 'preflight':
            require(not (release/'baseline.json').exists(), 'Never replace the reviewed baseline')
            initial = external(args.preservation_baseline,network); private(initial)
            require(digest(initial) == sha(args.preservation_sha256), 'Accepted preservation baseline hash mismatch')
            old = checks.load(initial)
            current = snapshot(runner.capture(deployment_id,args.property_id,args.operation_id),deployment_id)
            for org in ('1','2'):
                previous = checks.named_definition(old['Org'+org+'_definitions']['observed'],'basic')
                require({**previous,'init_required':previous.get('init_required',False)} == current['organizations'][org]['definitions']['basic'])
                require(assets(old['Org'+org+'_basic']['observed']) == current['organizations'][org]['basic'], 'Accepted basic baseline mismatch')
                start,end = channel(old['Org'+org+'_channel']['observed']),current['organizations'][org]['channel']
                require(end['height'] >= start['height'])
                if end['height'] == start['height']: require(end == start)
            save(release/'baseline.json',current)
            print('PASS: read-only preflight captured; review and freeze baseline hash before selecting a context.')
        else:
            execute(args.phase,runner,m,baseline,args.context_sha256)
    print('STOP. No following phase is implicitly authorized.')

if __name__ == '__main__':
    try:
        main()
    except (Stop,SystemExit,OSError,ValueError,TypeError,KeyError,AttributeError) as error:
        if isinstance(error,SystemExit) and error.code == 0: raise
        print('STOP: '+(str(error) if isinstance(error,Stop) else 'Invalid input or inspection; no further mutation authorized'),file=sys.stderr)
        sys.exit(1)
