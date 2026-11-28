"""Offline process tests: temporary HOME, fake services, no real DB/network calls."""
import contextlib
import copy
import fcntl
import importlib.util
import io
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('app_launcher',Path(__file__).with_name('tokansh_app.py'))
app=importlib.util.module_from_spec(spec);spec.loader.exec_module(app)


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.home=Path(self.tmp.name)
        self.mock=patch.object(Path,'home',return_value=self.home);self.mock.start();self.addCleanup(self.mock.stop)
        self.supervisor=app.App()
        # Never spawn real Gateway/FastAPI/Vite or evaluate chaincode.
        self.addCleanup(self.cleanup)

    def cleanup(self):
        for name in app.PORTS:self.supervisor.stop_one(name)
        # Explicit test-child handles also reap fixtures if a failed assertion
        # deliberately left invalid ownership metadata.
        for child in self.supervisor.children.values():
            if child.poll() is None:child.terminate()
            child.wait(timeout=5)

    def launch(self,name='gateway'):
        self.supervisor.launch(name,[sys.executable,'-B','-c','import time; time.sleep(60)'],self.home,dict(os.environ))
        return self.supervisor.owned(name)

    def test_start_stop_ownership_and_stale_pid(self):
        record=self.launch();self.assertIsNotNone(record)
        self.assertEqual(app.identity(record['pid']),record)
        self.supervisor.stop_one('gateway')
        self.assertFalse(self.supervisor.record_path('gateway').exists())
        self.assertIsNone(app.identity(record['pid']))
        self.assertEqual(self.supervisor.root.stat().st_mode&0o777,0o700)

    def test_foreign_reused_pid_never_signalled(self):
        foreign=subprocess.Popen([sys.executable,'-B','-c','import time;time.sleep(60)'])
        try:
            record=app.identity(foreign.pid);record['start']='wrong-start'
            path=self.supervisor.record_path('gateway');path.write_text(json.dumps(record));path.chmod(0o600)
            with patch.object(signal,'pidfd_send_signal') as send:self.supervisor.stop_one('gateway');send.assert_not_called()
            self.assertIsNone(foreign.poll())
        finally:foreign.terminate();foreign.wait(timeout=5)

    def test_pid_change_between_handle_open_and_signal(self):
        record=self.launch()
        try:
            with patch.object(app,'identity',side_effect=[record,None]),patch.object(signal,'pidfd_send_signal') as send:
                self.supervisor.stop_one('gateway');send.assert_not_called()
        finally:
            path=self.supervisor.record_path('gateway');path.write_text(json.dumps(record));path.chmod(0o600)

    def test_port_conflict_and_symlink_refusal(self):
        with socket.socket() as listener:
            listener.bind(('127.0.0.1',0));listener.listen()
            self.assertFalse(app.port_free(listener.getsockname()[1]))
        target=self.home/'target';target.write_text('unchanged')
        path=self.supervisor.record_path('gateway');path.symlink_to(target)
        with self.assertRaises(app.Failure):self.supervisor.owned('gateway')
        path.unlink();self.assertEqual(target.read_text(),'unchanged')
        path.symlink_to(self.home/'nonexistent')
        with self.assertRaises(app.Failure):self.supervisor.owned('gateway')
        path.unlink();self.assertFalse((self.home/'nonexistent').exists())

    def test_time_wait_is_not_a_listener_or_startup_conflict(self):
        with socket.socket() as server:
            server.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
            server.bind(('127.0.0.1',0));server.listen()
            port=server.getsockname()[1]
            with socket.create_connection(('127.0.0.1',port)) as client:
                accepted,_=server.accept()
                with accepted:
                    # Server actively closes, then client completes FIN exchange.
                    accepted.shutdown(socket.SHUT_WR)
                    self.assertEqual(client.recv(1),b'')
                client.shutdown(socket.SHUT_WR)
        with socket.socket() as old_probe:
            with self.assertRaises(OSError) as failure:old_probe.bind(('0.0.0.0',port))
            self.assertEqual(failure.exception.errno,app.errno.EADDRINUSE)
        self.assertFalse(app.port_listening(port))
        self.assertTrue(app.port_free(port))
        with patch.object(app.time,'sleep') as sleep:
            app.wait_port_free(port);sleep.assert_not_called()

    def test_live_listener_is_refused_immediately_without_signals(self):
        with socket.socket() as listener:
            listener.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
            listener.bind(('127.0.0.1',0));listener.listen()
            port=listener.getsockname()[1]
            self.assertTrue(app.port_listening(port))
            with patch.object(app.time,'sleep') as sleep,patch.object(signal,'pidfd_send_signal') as send:
                with self.assertRaisesRegex(app.Failure,'unmanaged listening'):app.wait_port_free(port)
                sleep.assert_not_called();send.assert_not_called()

    def test_transient_port_wait_is_bounded_and_detects_new_listener(self):
        with patch.object(app,'port_free',side_effect=[False,False,True]),patch.object(app,'port_listening',return_value=False),patch.object(app.time,'sleep') as sleep:
            app.wait_port_free(8001);self.assertEqual(sleep.call_count,2)
        with patch.object(app,'port_free',return_value=False),patch.object(app,'port_listening',return_value=False),patch.object(app.time,'monotonic',side_effect=[0,3]),patch.object(app.time,'sleep') as sleep:
            with self.assertRaisesRegex(app.Failure,'remains unavailable'):app.wait_port_free(8001)
            sleep.assert_not_called()
        with patch.object(app,'port_free',return_value=False),patch.object(app,'port_listening',side_effect=[False,True]),patch.object(app.time,'sleep') as sleep:
            with self.assertRaisesRegex(app.Failure,'unmanaged listening'):app.wait_port_free(8001)
            self.assertEqual(sleep.call_count,1)

    def test_idempotent_start_and_rollback_only_new_processes(self):
        env=dict(TOKANSH_GATEWAY_SECRET='a'*64)
        fake=(self.home/'frontend/node_modules/vite/bin');fake.mkdir(parents=True);(fake/'vite.js').touch()
        record={'pid':123}
        with patch.object(app,'configuration',return_value=env),patch.object(app,'REPO',self.home),patch.object(app,'linux_node',return_value='/test-node'),patch.object(self.supervisor,'owned',return_value=record),patch.object(self.supervisor,'wait_health'),patch.object(app,'http_json',return_value={'data':app.INFO}),patch.object(self.supervisor,'launch') as launch:
            with contextlib.redirect_stdout(io.StringIO()):self.supervisor.start()
            launch.assert_not_called()
        ownership={'gateway':record}
        def launch(name,*args):ownership[name]=record
        def health(name):
            if name=='frontend':raise app.Failure('test startup failure')
        with patch.object(app,'configuration',return_value=env),patch.object(app,'REPO',self.home),patch.object(app,'linux_node',return_value='/test-node'),patch.object(app,'port_free',return_value=True),patch.object(self.supervisor,'owned',side_effect=lambda name:ownership.get(name)),patch.object(self.supervisor,'launch',side_effect=launch),patch.object(self.supervisor,'wait_health',side_effect=health),patch.object(app,'http_json',return_value={'data':app.INFO}),patch.object(self.supervisor,'stop_one') as stop:
            with contextlib.redirect_stdout(io.StringIO()),self.assertRaises(app.Failure):self.supervisor.start()
            self.assertEqual([c.args[0] for c in stop.call_args_list],['frontend','backend'])

    def test_configuration_and_database_are_readonly(self):
        import sqlite3
        config=self.home/'.config/tokansh';config.mkdir(parents=True,mode=0o700)
        data=self.home/'.local/share/tokansh';data.mkdir(parents=True,mode=0o700)
        cert=self.home/'identity';cert.write_text('test-only')
        path=config/'local.env'
        values=dict(TOKANSH_GATEWAY_SECRET='a'*64,TOKANSH_OPERATOR_SECRET='b'*64,
            DRUNIX_CERT_PATH=str(cert),DRUNIX_KEY_PATH=str(cert),DRUNIX_TLS_CA_PATH=str(cert),
            DRUNIX_MSP_ID='Org1MSP',DRUNIX_PEER_ENDPOINT='dns:///127.0.0.1:7051',DRUNIX_TLS_SERVER_NAME='peer0.org1.example.com')
        path.write_text(''.join(f'{k}={v}\n' for k,v in values.items()));path.chmod(0o600)
        db=data/'tokansh.db'
        with self.assertRaises(app.Failure):app.configuration()
        self.assertFalse(db.exists())
        with sqlite3.connect(db) as connection:
            connection.execute('CREATE TABLE alembic_version(version_num TEXT)')
            connection.execute("INSERT INTO alembic_version VALUES ('0005_showcase_metadata')")
            for table in ('properties','application_operations','property_events'):connection.execute('CREATE TABLE '+table+'(id TEXT)')
            connection.execute('CREATE TABLE ledger_operations(operation_id TEXT,property_id TEXT,state TEXT,artifact_json TEXT,transaction_id TEXT)')
        db.chmod(0o600);before=db.read_bytes()
        with patch.dict(os.environ,{},clear=True):result=app.configuration()
        self.assertEqual(db.read_bytes(),before)
        self.assertEqual(result['DATABASE_URL'],'sqlite:///'+str(db))
        path.chmod(0o644)
        with self.assertRaises(app.Failure):app.configuration()

    def test_outdated_database_revision_is_rejected(self):
        import sqlite3
        config=self.home/'.config/tokansh';config.mkdir(parents=True,mode=0o700)
        data=self.home/'.local/share/tokansh';data.mkdir(parents=True,mode=0o700)
        cert=self.home/'identity';cert.write_text('test-only')
        path=config/'local.env'
        values=dict(TOKANSH_GATEWAY_SECRET='a'*64,TOKANSH_OPERATOR_SECRET='b'*64,
            DRUNIX_CERT_PATH=str(cert),DRUNIX_KEY_PATH=str(cert),DRUNIX_TLS_CA_PATH=str(cert),
            DRUNIX_MSP_ID='Org1MSP',DRUNIX_PEER_ENDPOINT='dns:///127.0.0.1:7051',DRUNIX_TLS_SERVER_NAME='peer0.org1.example.com')
        path.write_text(''.join(f'{k}={v}\n' for k,v in values.items()));path.chmod(0o600)
        db=data/'tokansh.db'
        with sqlite3.connect(db) as connection:
            connection.execute('CREATE TABLE alembic_version(version_num TEXT)')
            connection.execute("INSERT INTO alembic_version VALUES ('0003_demo_cash')")
        db.chmod(0o600)
        with patch.dict(os.environ,{},clear=True):
            with self.assertRaisesRegex(app.Failure,'0005_showcase_metadata'):
                app.configuration()

    def test_concurrent_command_lock_and_health_timeout(self):
        with (self.supervisor.root/'lock').open('a') as lock:
            os.chmod(self.supervisor.root/'lock',0o600)
            fcntl.flock(lock,fcntl.LOCK_EX | fcntl.LOCK_NB)
            with patch.object(sys,'argv',['tokansh_app.py','status']),self.assertRaisesRegex(app.Failure,'Another lifecycle'):
                app.main()
        with patch.object(app.time,'monotonic',side_effect=[0,31]),patch.object(app,'http_json') as http:
            with self.assertRaisesRegex(app.Failure,'timed out'):self.supervisor.wait_health('gateway')
            http.assert_not_called()

    def test_http_helper_credentials_and_redirect_rejection(self):
        from unittest.mock import MagicMock
        opener=MagicMock();response=opener.open.return_value.__enter__.return_value
        response.status=200;response.read.return_value=json.dumps({'data':app.INFO}).encode()
        with patch.object(app,'build_opener',return_value=opener) as build:
            self.assertEqual(app.http_json(8001,'/v1/tokansh/contract-info','test-only-secret'),{'data':app.INFO})
            handlers=build.call_args.args
            self.assertEqual(handlers[0].proxies,{})
            self.assertIsNone(handlers[1].redirect_request(None,None,None,None,None,None))
            request=opener.open.call_args.args[0]
            self.assertEqual(request.get_method(),'GET')
            self.assertEqual(request.get_header('Authorization'),'Bearer test-only-secret')
            self.assertEqual(request.full_url,'http://127.0.0.1:8001/v1/tokansh/contract-info')
        response.read.return_value=b'not-json'
        with patch.object(app,'build_opener',return_value=opener),self.assertRaises(ValueError):app.http_json(8001,'/health')

    def test_bad_contract_blocks_start(self):
        fake=self.home/'frontend/node_modules/vite/bin';fake.mkdir(parents=True);(fake/'vite.js').touch()
        with patch.object(app,'configuration',return_value={'TOKANSH_GATEWAY_SECRET':'a'*64}),patch.object(app,'REPO',self.home),patch.object(app,'linux_node',return_value='/test-node'),patch.object(self.supervisor,'owned',return_value={'pid':123}),patch.object(self.supervisor,'wait_health'),patch.object(app,'http_json',return_value={'data':{**app.INFO,'schema_version':True}}):
            with self.assertRaises(app.Failure):self.supervisor.start()

    def check_metadata_start(self, response, accepted):
        fake=self.home/'frontend/node_modules/vite/bin';fake.mkdir(parents=True,exist_ok=True);(fake/'vite.js').touch()
        with patch.object(app,'configuration',return_value={'TOKANSH_GATEWAY_SECRET':'a'*64}),patch.object(app,'REPO',self.home),patch.object(app,'linux_node',return_value='/test-node'),patch.object(self.supervisor,'owned',return_value={'pid':123}),patch.object(self.supervisor,'wait_health'),patch.object(app,'http_json',return_value=response),patch.object(self.supervisor,'launch') as launch,patch.object(self.supervisor,'stop_one') as stop:
            with contextlib.redirect_stdout(io.StringIO()):
                if accepted:self.supervisor.start()
                else:
                    with self.assertRaises(app.Failure):self.supervisor.start()
            launch.assert_not_called();stop.assert_not_called()

    def test_exact_reviewed_contract_interfaces_start(self):
        for info in (app.INFO,app.INFO_V11,app.INFO_V12_LEGACY,app.INFO_V12):
            with self.subTest(functions=len(info['functions'])):
                self.check_metadata_start({'data':copy.deepcopy(info)},True)

    def test_v12_metadata_remains_exact(self):
        for key,value in [('contract','basic'),('schema_version',True),('schema_version',1.0),
                          ('supply_interpretation','MINTED_SUPPLY'),
                          ('functions',app.INFO_V12['functions']+['BurnANSH']),
                          ('functions',app.INFO_V12['functions'][:-1]+['transferANSH']),
                          ('functions',app.INFO_V12['functions']+['TransferANSH']),
                          ('functions',list(reversed(app.INFO_V12['functions']))),('extra',1)]:
            with self.subTest(key=key,value=value):
                self.check_metadata_start({'data':{**app.INFO_V12,key:value}},False)
        for key in app.INFO_V12:
            info=copy.deepcopy(app.INFO_V12);del info[key]
            self.check_metadata_start({'data':info},False)

    def test_unreviewed_or_malformed_contract_interfaces_block_start(self):
        cases=[None,[],{}, {'data':None}, {'data':[]},
               {'data':app.INFO_V11,'meta':{}}, {'data':{**app.INFO_V11,'extra':'unknown'}}]
        changes=[('contract','basic'),('contract',1),('schema_version',True),('schema_version',1.0),
                 ('schema_version','1'),('schema_version',2),('supply_interpretation','MINTED_SUPPLY'),
                 ('supply_interpretation',None),('functions',None),('functions',[]),
                 ('functions','IssueANSH'),('functions',tuple(app.INFO_V11['functions'])),
                 ('functions',app.INFO_V11['functions'][:-1]),
                 ('functions',app.INFO_V11['functions']+['BurnANSH']),
                 ('functions',app.INFO_V11['functions'][:-1]+['GetBalance']),
                 ('functions',list(reversed(app.INFO_V11['functions']))),
                 ('functions',app.INFO_V11['functions'][:-1]+['getIssuanceOperation'])]
        cases += [{'data':{**app.INFO_V11,key:value}} for key,value in changes]
        for key in app.INFO_V11:
            info=copy.deepcopy(app.INFO_V11);del info[key];cases.append({'data':info})
        for number,response in enumerate(cases):
            with self.subTest(case=number):self.check_metadata_start(response,False)


if __name__=='__main__':unittest.main()
