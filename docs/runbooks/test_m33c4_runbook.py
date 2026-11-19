"""Offline checks of executable local-only snippets; never run operator/RPC commands."""
import ast
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[2]
TEXT=Path(__file__).with_name('M3.3c.4-LIVE-REGISTRATION.md').read_text()
sys.path.insert(0,str(ROOT/'backend'))
from app.registration import FIELDS, SIGNER, validate


def snippet(name):
    return re.search(r'```python '+re.escape(name)+r'\n(.*?)\n```',TEXT,re.S)[1]


class RunbookTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)
        self.property_id=str(uuid4())
        self.draft=dict(id=self.property_id,issuer_id='00000000-0000-4000-8000-000000000002',
            status='DRAFT',proposed_supply=100,unit_price='10.00',currency='INR')
        (self.path/'draft.json').write_text(json.dumps({'data':self.draft}))

    def generate(self):
        with patch.dict(os.environ,{'RUN_DIR':str(self.path)}):
            exec(compile(snippet('snapshot-command'),'snapshot-command','exec'),{})
        return json.loads((self.path/'command.json').read_text())

    def test_snapshot_digest_and_actual_command_validator(self):
        c=self.generate();self.assertEqual(c,validate(c));self.assertEqual(list(c),list(FIELDS))
        b=(self.path/'snapshot.json').read_bytes()
        self.assertEqual(c['approval_digest'],hashlib.sha256(b).hexdigest())
        self.assertEqual(b,json.dumps(json.loads(b),sort_keys=True,separators=(',',':'),ensure_ascii=True).encode())
        self.assertEqual((c['property_id'],c['approved_supply'],c['issue_price_minor']),(self.property_id,100,'1000'))
        self.assertNotEqual(c['operation_id'],c['approval_reference'])
        with self.assertRaises(FileExistsError):self.generate()

    def test_readonly_preparation_summary_and_corruption(self):
        c=self.generate();raw=json.dumps(c,separators=(',',':'));digest=hashlib.sha256(raw.encode()).hexdigest()
        artifact=dict(version=1,command=c,request_digest=digest,transaction_id='test-only-txid',signer=SIGNER,
            channel='mychannel',chaincode='tokansh',transaction='test-only-bytes',creator='test-only-creator',mac='test-only-mac')
        dbfile=self.path/'test.db'
        columns=['operation_id','property_id','state','transaction_id','signer','channel','chaincode',
                 'validation_code','block_number','command_json','artifact_json','request_digest']
        values=[c['operation_id'],c['property_id'],'PREPARED',artifact['transaction_id'],SIGNER,'mychannel','tokansh',None,None,raw,json.dumps(artifact),digest]
        with sqlite3.connect(dbfile) as db:
            db.execute('CREATE TABLE ledger_operations ('+','.join(columns)+')')
            db.execute('INSERT INTO ledger_operations VALUES ('+','.join('?' for _ in columns)+')',values)
        env=dict(DB_FILE=str(dbfile),OPERATION_ID=c['operation_id'],RUN_DIR=str(self.path))
        code=compile(snippet('preparation-summary'),'preparation-summary','exec')
        with patch.dict(os.environ,env),contextlib.redirect_stdout(io.StringIO()) as out:exec(code,{})
        self.assertNotIn('test-only-bytes',out.getvalue());self.assertNotIn('test-only-mac',out.getvalue())
        for field,value in [('artifact_json',None),('artifact_json','{broken'),
                ('artifact_json','{}'),('state','UNKNOWN'),('transaction_id',''),('property_id','wrong')]:
            with sqlite3.connect(dbfile) as db:
                db.execute('DELETE FROM ledger_operations')
                db.execute('INSERT INTO ledger_operations VALUES ('+','.join('?' for _ in columns)+')',values)
                db.execute('UPDATE ledger_operations SET '+field+'=?',(value,))
            with patch.dict(os.environ,env),contextlib.redirect_stdout(io.StringIO()),self.assertRaises((AssertionError,TypeError,ValueError,KeyError)):
                exec(code,{})
        with sqlite3.connect(dbfile) as db:db.execute('DELETE FROM ledger_operations')
        with patch.dict(os.environ,env),contextlib.redirect_stdout(io.StringIO()),self.assertRaises(AssertionError):exec(code,{})
        with sqlite3.connect(dbfile) as db:db.execute('INSERT INTO ledger_operations VALUES ('+','.join('?' for _ in columns)+')',values)
        with sqlite3.connect(dbfile) as db:db.execute("UPDATE ledger_operations SET request_digest='corrupt'")
        with patch.dict(os.environ,env),contextlib.redirect_stdout(io.StringIO()),self.assertRaises(AssertionError):exec(code,{})

    def migrated_database(self):
        from alembic import command
        from alembic.config import Config
        db=self.path/'schema.db'
        config=Config(str(ROOT/'backend/alembic.ini'))
        config.set_main_option('script_location',str(ROOT/'backend/migrations'))
        config.attributes['database_url']='sqlite:///'+str(db)
        command.upgrade(config,'head')
        return db

    def inspect_database(self,db,configured=None):
        env={**os.environ,'DB_FILE':str(db),'DATABASE_URL':'sqlite:///'+str(configured or db),
             'PYTHONPATH':str(ROOT/'backend'),'PYTHONDONTWRITEBYTECODE':'1'}
        return subprocess.run([sys.executable,'-B','-'],input=snippet('database-preflight'),
            text=True,capture_output=True,env=env,timeout=30)

    def test_database_readonly_success_missing_and_wrong_path(self):
        absent=self.path/'does-not-exist'/'missing.db'
        self.assertNotEqual(self.inspect_database(absent).returncode,0)
        self.assertFalse(absent.parent.exists())
        db=self.migrated_database();before=db.read_bytes()
        result=self.inspect_database(db)
        self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(db.read_bytes(),before)
        other=self.path/'wrong.db';other.write_bytes(before)
        self.assertNotEqual(self.inspect_database(db,other).returncode,0)
        self.assertEqual(db.read_bytes(),before)
        # Prove the snippet opens its connection in mode=ro and rejects writes.
        probe=snippet('database-preflight').replace("db.execute('PRAGMA query_only=ON')",
            "db.execute('CREATE TABLE forbidden(x)')")
        with patch.dict(os.environ,{'DB_FILE':str(db),'DATABASE_URL':'sqlite:///'+str(db)}),self.assertRaises(sqlite3.OperationalError):
            exec(compile(probe,'readonly-probe','exec'),{})
        self.assertEqual(db.read_bytes(),before)

    def test_database_malformed_revision_and_schema_rejected(self):
        db=self.migrated_database();original=db.read_bytes()
        statements=["DELETE FROM alembic_version", "UPDATE alembic_version SET version_num='wrong'",
            'DROP TABLE alembic_version', 'DROP TABLE ledger_operations',
            'ALTER TABLE ledger_operations DROP COLUMN artifact_json',
            'ALTER TABLE ledger_operations ADD COLUMN unexpected TEXT',
            'CREATE TABLE unexpected(x)', 'CREATE VIEW unexpected_view AS SELECT 1',
            'ALTER TABLE ledger_operations RENAME COLUMN transaction_id TO wrong_name']
        for sql in statements:
            db.write_bytes(original)
            with sqlite3.connect(db) as connection:connection.execute(sql)
            result=self.inspect_database(db)
            with self.subTest(sql=sql):self.assertNotEqual(result.returncode,0)
        db.write_bytes(b'not-a-sqlite-database')
        self.assertNotEqual(self.inspect_database(db).returncode,0)

    def test_case_sensitive_registration_constraint_validation(self):
        db=self.migrated_database()
        with sqlite3.connect(db) as connection:
            ddl=connection.execute("SELECT sql FROM sqlite_master WHERE name='ledger_operations'").fetchone()[0]
        import ast
        migration=ast.parse((ROOT/'backend/migrations/versions/0002_registration.py').read_text())
        clause=next(n.args[0].value for n in ast.walk(migration) if isinstance(n,ast.Call)
            and isinstance(n.func,ast.Attribute) and n.func.attr=='CheckConstraint')
        self.assertIn(clause,ddl)
        marker='CONSTRAINT ck_ledger_operation_state CHECK ('+clause+')'
        self.assertIn(marker,ddl)
        replacements=[
            marker.replace("'CREATED'","'created'"),
            marker.replace(clause,clause.lower()),
            marker.replace("'UNKNOWN'","'OTHER'"),
            marker.replace(",'UNKNOWN'",''),
            marker.replace(clause,clause+' OR 1=1'),
            marker.replace('ck_ledger_operation_state','wrong_constraint'),
            marker+', CHECK (1=1)']
        variants=[ddl.replace(marker,text) for text in replacements]
        # Removing the table constraint must also remove its preceding comma.
        variants.append(ddl.replace(', \n\t'+marker,''))
        self.assertNotIn(marker,variants[-1])
        for sql in variants:
            with sqlite3.connect(db) as connection:
                connection.execute('DROP TABLE ledger_operations');connection.execute(sql)
            result=self.inspect_database(db)
            with self.subTest(ddl=sql):self.assertNotEqual(result.returncode,0,result.stdout)

    def constraint_parser(self):
        tree=ast.parse(snippet('database-preflight'))
        functions=ast.Module(body=[n for n in tree.body if isinstance(n,ast.FunctionDef)],type_ignores=[])
        from app.registration import STATES
        namespace={'re':re,'STATES':STATES}
        exec(compile(functions,'offline-constraint-parser','exec'),namespace)
        migration=ast.parse((ROOT/'backend/migrations/versions/0002_registration.py').read_text())
        clause=next(n.args[0].value for n in ast.walk(migration) if isinstance(n,ast.Call)
            and isinstance(n.func,ast.Attribute) and n.func.attr=='CheckConstraint')
        return namespace['registration_constraint'],'CONSTRAINT ck_ledger_operation_state CHECK ('+clause+')'

    def test_sql_comments_rejected_outside_quoted_tokens(self):
        parse,check=self.constraint_parser()
        valid='CREATE TABLE ledger_operations (state VARCHAR(32) NOT NULL, '+check+')'
        cases=[
            'CREATE TABLE ledger_operations (state VARCHAR(32) NOT NULL /*, '+check+', */)',
            'CREATE TABLE ledger_operations (state VARCHAR(32) NOT NULL --, '+check+',\n)',
            '/* hidden, commas, ('+check+') */ '+valid,
            '-- hidden, '+check+'\n'+valid,
            valid+' /* following valid CHECK */',valid+' -- following valid CHECK',
            valid.replace(check,'/* before */ '+check),
            valid.replace(check,check+' /* after */'),
            valid+' /* unterminated',valid.replace(check,'/* '+check),
        ]
        for sql in cases:
            with self.subTest(sql=sql),self.assertRaisesRegex(SystemExit,'SQL comments'):
                parse(sql)
        # A full migrated-schema fixture containing the original comma bypass
        # must also be rejected by the actual read-only preflight.
        db=self.migrated_database()
        with sqlite3.connect(db) as connection:
            ddl=connection.execute("SELECT sql FROM sqlite_master WHERE name='ledger_operations'").fetchone()[0]
            changed=ddl.replace(', \n\t'+check,' /*, '+check+', */')
            self.assertNotEqual(ddl,changed)
            connection.execute('DROP TABLE ledger_operations');connection.execute(changed)
        result=self.inspect_database(db)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('SQL comments',result.stderr)

    def test_comment_like_sequences_inside_quoted_tokens_preserved(self):
        parse,check=self.constraint_parser()
        cases=[
            'CREATE TABLE ledger_operations (state TEXT, note TEXT DEFAULT \'-- /* example */\', '+check+')',
            'CREATE TABLE ledger_operations (state TEXT, "note--/*,*/" TEXT, '+check+')',
            'CREATE TABLE ledger_operations (state TEXT, note TEXT DEFAULT \'it\'\'s -- /* text */\', '+check+')',
            'CREATE TABLE ledger_operations (state TEXT, "quoted""--/*name*/" TEXT, '+check+')',
        ]
        for sql in cases:
            with self.subTest(sql=sql):
                # SQLite itself accepts these quoted-token examples.
                with sqlite3.connect(':memory:') as db:db.execute(sql)
                parse(sql)
        with self.assertRaises(SystemExit):
            parse(cases[0].replace("'CREATED'","'created'"))
        with self.assertRaises(SystemExit):
            parse(cases[0].replace(check,"CHECK (state IS NOT NULL)"))

    def test_alembic_version_metadata_rejected(self):
        db=self.migrated_database()
        for columns in ['version_num TEXT NOT NULL PRIMARY KEY',
                'version_num VARCHAR(32) NOT NULL', 'version_num VARCHAR(32) PRIMARY KEY',
                'wrong_name VARCHAR(32) NOT NULL PRIMARY KEY',
                'version_num VARCHAR(32) NOT NULL PRIMARY KEY, unexpected TEXT']:
            with sqlite3.connect(db) as connection:
                connection.execute('DROP TABLE alembic_version')
                connection.execute('CREATE TABLE alembic_version ('+columns+')')
                connection.execute("INSERT INTO alembic_version VALUES ("+','.join('?' for _ in columns.split(','))+')',
                    ('0002_registration',)+((None,) if ',' in columns else ()))
            with self.subTest(columns=columns):self.assertNotEqual(self.inspect_database(db).returncode,0)

    def test_backup_overwrite_prevention_and_restoration_consistency(self):
        db=self.migrated_database()
        # WAL fixture demonstrates backup includes committed state outside main DB.
        with sqlite3.connect(db) as live_fixture:
            live_fixture.execute('PRAGMA journal_mode=WAL')
            live_fixture.execute("CREATE TABLE test_evidence (value TEXT)")
            live_fixture.execute("INSERT INTO test_evidence VALUES ('before-backup')");live_fixture.commit()
            expected=list(live_fixture.iterdump())
            env=dict(DB_FILE=str(db),RUN_DIR=str(self.path),REPO=str(ROOT),
                DRUNIX_REPOSITORY=str(ROOT.parent/'drunix'),BACKUP_TAG='prepared')
            code=compile(snippet('private-backup'),'private-backup','exec')
            with patch.dict(os.environ,env):exec(code,{})
            backup=self.path/'prepared.sqlite';frozen=backup.read_bytes()
            self.assertEqual(backup.stat().st_mode & 0o777,0o600)
            live_fixture.execute("INSERT INTO test_evidence VALUES ('after-backup')");live_fixture.commit()
            with patch.dict(os.environ,env),self.assertRaises(AssertionError):exec(code,{})
            self.assertEqual(backup.read_bytes(),frozen)
            restored=self.path/'restored-fixture.db'
            with sqlite3.connect('file:'+str(backup)+'?mode=ro',uri=True) as saved,sqlite3.connect(restored) as target:
                saved.backup(target)
                self.assertEqual(list(target.iterdump()),expected)
                self.assertEqual(target.execute('PRAGMA integrity_check').fetchall(),[('ok',)])
            self.assertEqual(live_fixture.execute('SELECT count(*) FROM test_evidence').fetchone(),(2,))
            with patch.dict(os.environ,{**env,'BACKUP_TAG':'before-draft','DB_FILE':str(self.path/'missing.db')}),self.assertRaises(AssertionError):exec(code,{})
            self.assertFalse((self.path/'before-draft.sqlite').exists())

    def test_scoped_admin_selection_application_identity_and_query_failure(self):
        blocks=re.findall(r'```bash\n(.*?)\n```',TEXT,re.S)
        admin=next(b for b in blocks if b.startswith('approval_read()'))
        application=next(b for b in blocks if b.startswith('peer_read()')).split('\npeer_read 1')[0]
        fake=self.path/'peer'
        fake.write_text('#!/bin/sh\npython3 -c \'import os,json; print(json.dumps({k:v for k,v in os.environ.items() if k.startswith(("CORE_PEER_","DRUNIX_"))}))\'\nexit "${TEST_EXIT:-0}"\n')
        fake.chmod(0o700)
        network=self.path/'network'
        for org in (1,2):
            (network/f'drunix-network/test-network/organizations/peerOrganizations/org{org}.example.com/users/Admin@org{org}.example.com/msp').mkdir(parents=True)
        env={**os.environ,'DRUNIX_REPOSITORY':str(network),'PEER':str(fake),
            'DRUNIX_MSP_ID':'Org1MSP','DRUNIX_CERT_PATH':str(self.path/'User1/msp/signcerts/cert.pem'),
            'CORE_PEER_LOCALMSPID':'parent-sentinel','PYTHONDONTWRITEBYTECODE':'1'}
        for org,port in [(1,7061),(2,9061)]:
            script=admin+f'\napproval_read {org} || exit $?\necho "$CORE_PEER_LOCALMSPID:$DRUNIX_MSP_ID"\n'
            r=subprocess.run(['bash','-c',script],env=env,text=True,capture_output=True,timeout=10)
            self.assertEqual(r.returncode,0,r.stderr)
            data=json.loads(r.stdout.splitlines()[0])
            self.assertEqual(data['CORE_PEER_LOCALMSPID'],f'Org{org}MSP')
            self.assertIn(f'Admin@org{org}.example.com/msp',data['CORE_PEER_MSPCONFIGPATH'])
            self.assertEqual(data['CORE_PEER_ADDRESS'],f'localhost:{port}')
            self.assertEqual(data['CORE_PEER_TLS_SERVERHOSTOVERRIDE'],f'peer1.org{org}.example.com')
            self.assertIn(f'peer0.org{org}.example.com/tls/ca.crt',data['CORE_PEER_TLS_ROOTCERT_FILE'])
            self.assertTrue(r.stdout.endswith('parent-sentinel:Org1MSP\n'))
            failure=subprocess.run(['bash','-c',script+'echo forbidden'],env={**env,'TEST_EXIT':'9'},text=True,capture_output=True,timeout=10)
            self.assertEqual(failure.returncode,9);self.assertNotIn('forbidden',failure.stdout)
        r=subprocess.run(['bash','-c',application+'\npeer_read 2 0 9051 chaincode query'],env=env,text=True,capture_output=True,timeout=10)
        self.assertEqual(r.returncode,0,r.stderr)
        data=json.loads(r.stdout)
        self.assertEqual(data['CORE_PEER_LOCALMSPID'],'Org1MSP')
        self.assertIn('User1/msp',data['CORE_PEER_MSPCONFIGPATH'])
        self.assertNotIn('alembic current\n',TEXT)

    def test_all_python_blocks_compile(self):
        for name,code in re.findall(r'```python ([^\n]+)\n(.*?)\n```',TEXT,re.S):
            compile(code,name,'exec')

    def test_shell_syntax_without_execution(self):
        for block in re.findall(r'```bash\n(.*?)\n```',TEXT,re.S):
            r=subprocess.run(['bash','-n'],input=block,text=True,capture_output=True,timeout=10)
            self.assertEqual(r.returncode,0,r.stderr)

    def test_cli_actions_and_states_match_source(self):
        source=(ROOT/'backend/app/registration_operator.py').read_text()
        for action in re.findall(r'-m app.registration_operator ([a-z-]+)',TEXT):
            self.assertIn("'"+action+"'",source)
        for state in ('CREATED','PREPARED','SUBMISSION_PENDING','SUBMITTED','COMMITTED_VALID','COMMITTED_INVALID','UNKNOWN'):
            self.assertIn('| '+state+' |',TEXT)
        self.assertIn('CLI has no submit-without-status mode',TEXT)
        self.assertIn('Tooling gap:',TEXT)
        self.assertIn('Do not restore a PREPARED backup after D',TEXT)


if __name__=='__main__':unittest.main()
