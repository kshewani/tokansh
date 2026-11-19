"""Offline upgrade decision tests. Synthetic CLI responses only; no network tools."""
import base64
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import fixtures

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('upgrade', HERE/'upgrade-workflow.py')
u = importlib.util.module_from_spec(spec); spec.loader.exec_module(u)
PID = '20000000-0000-4000-8000-000000000001'
OP = '10000000-0000-4000-8000-000000000001'


def definition(version='1.0', sequence=1):
    return dict(name='tokansh',version=version,sequence=sequence,endorsement_plugin='escc',
                validation_plugin='vscc',validation_parameter=u.inspect.POLICY,collections={},init_required=False)


def approved(package, version='1.0', sequence=1):
    row = definition(version,sequence); row.pop('name')
    return dict(row,source={'Type':{'LocalPackage':{'package_id':package}}})


def baseline(deployment_id='offline-upgrade-001'):
    old = fixtures.baseline()
    prop = dict(schema_version=1,property_id=PID,issuer_id='30000000-0000-4000-8000-000000000001',
        approval_reference='40000000-0000-4000-8000-000000000001',approval_digest='a'*64,
        approved_supply=100,issue_price_minor='1000000',currency='INR',registered_by_msp='Org1MSP',
        registered_by_principal='test-only-principal',registration_operation_id=OP,
        registration_transaction_id='test-only-registration',proposal_timestamp='2026-11-19T00:00:00Z')
    op = dict(schema_version=1,operation_id=OP,authorizing_msp='Org1MSP',authorizing_principal=prop['registered_by_principal'],
        function='RegisterApprovedProperty',request_digest='b'*64,property_id=PID,
        original_transaction_id=prop['registration_transaction_id'],
        result=dict(property_id=PID,operation_id=OP,transaction_id=prop['registration_transaction_id']))
    organizations = {}
    for org in ('1','2'):
        basic = old['Org'+org+'_definitions']['observed']['chaincode_definitions'][0]
        organizations[org] = dict(channel=old['Org'+org+'_channel']['observed'],
            definitions={'basic':dict(basic,init_required=False),'tokansh':definition()},
            basic=old['Org'+org+'_basic']['observed'],property=copy.deepcopy(prop),operation=copy.deepcopy(op),
            info=dict(contract='tokansh',schema_version=1,functions=u.FUNCTIONS,supply_interpretation='LIFETIME_CUMULATIVE_ISSUANCE_CEILING'),
            approval_v1=approved('tokansh_1.0:'+'d'*64))
    return dict(schema_version=1,deployment_id=deployment_id,channel='mychannel',property_id=PID,operation_id=OP,
                cp_certificate_sha256={org:hashlib.sha256(b'test-only-cert').hexdigest() for org in ('Org1MSP','Org2MSP')},organizations=organizations)


class FakeRunner(u.Runner):
    """Only the subprocess boundary is replaced; real inspection/mutation gates run."""
    def __init__(self, network, release, package, captured):
        super().__init__(network,release)
        self.package = package
        self.captured = copy.deepcopy(captured)
        self.installed_rows = {'1':[], '2':[]}
        self.approvals = {org:approved(package,'1.1',2) for org in ('1','2')}
        self.readiness = {'approvals':{'Org1MSP':True,'Org2MSP':True}}
        self.calls = []
        self.mutation_error = False
        self.cli_error = None
        self.installed_raw = None

    def run(self, args, env=None, cwd=None, timeout=30):
        args = [str(v) for v in args]
        env = env or self.env
        self.calls.append((args,env.copy()))
        org = '2' if env.get('CORE_PEER_ADDRESS','').endswith((':9051',':9061')) else '1'
        row = self.captured['organizations'][org]
        if 'calculatepackageid' in args: return self.package
        if 'getinfo' in args: return 'Blockchain info: '+json.dumps(row['channel'])
        if 'querycommitted' in args: return json.dumps({'chaincode_definitions':list(row['definitions'].values())})
        if 'queryapproved' in args:
            if self.cli_error: raise u.Stop(self.cli_error)
            value = row['approval_v1'] if args[args.index('--sequence')+1]=='1' else self.approvals[org]
            if isinstance(value,Exception): raise value
            return json.dumps(value)
        if 'queryinstalled' in args:
            return self.installed_raw if self.installed_raw is not None else json.dumps({'installed_chaincodes':self.installed_rows[org]})
        if 'checkcommitreadiness' in args: return json.dumps(self.readiness)
        if 'query' in args:
            call = json.loads(args[args.index('-c')+1])['Args'][0]
            key = {'GetAllAssets':'basic','GetRegisteredProperty':'property','GetOperation':'operation','GetContractInfo':'info'}[call]
            return json.dumps(row[key])
        if any(v in args for v in ('install','commit')):
            if self.mutation_error: raise u.Stop('UNKNOWN: simulated timeout')
            return 'test-only acknowledgement'
        if args[0]=='openssl': return 'test-only successful static TLS check'
        raise AssertionError('Unreviewed command in fake runner: '+str(args))

    def installed_all(self):
        for org in ('1','2'):
            self.installed_rows[org] = [dict(package_id=self.package,label='tokansh_1.1')]

    def mutations(self):
        return [a for a,_ in self.calls if any(v in a for v in ('install','approveformyorg','commit'))]


class UpgradeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); self.release=self.root/'release'; self.release.mkdir(mode=0o700)
        self.network=self.root/'network'
        for org in ('1','2'):
            base=self.network/f'drunix-network/test-network/organizations/peerOrganizations/org{org}.example.com'
            for user in ('Admin','User1'):
                (base/f'users/{user}@org{org}.example.com/msp').mkdir(parents=True)
            cert=base/f'peers/peer1.org{org}.example.com/tls/server.crt'; cert.parent.mkdir(parents=True)
            cert.write_text('-----BEGIN CERTIFICATE-----\ndGVzdC1vbmx5LWNlcnQ=\n-----END CERTIFICATE-----\n')
        self.b = baseline()
        archive=self.release/'tokansh_1.1.tar.gz';archive.write_bytes(b'offline-test-only-package');archive.chmod(0o600)
        package='tokansh_1.1:'+u.digest(archive)
        identity=self.release/'package-identity.json'
        u.save(identity,dict(schema_version=1,deployment_id=self.b['deployment_id'],source_revision='a'*40,
            source_files={k:'c'*64 for k in ('go.mod','go.sum','main.go','contract/issuance.go')},
            package_sha256=u.digest(archive),package_id=package,package_size_bytes=archive.stat().st_size,label='tokansh_1.1'))
        self.baseline_path=self.release/'baseline.json';u.save(self.baseline_path,self.b)
        self.m = dict(u.PARAMS,schema_version=1,deployment_id=self.b['deployment_id'],network_root=str(self.network),
            release_directory=str(self.release),package_path=str(archive),package_sha256=u.digest(archive),package_id=package,
            package_identity_path=str(identity),package_identity_sha256=u.digest(identity),
            baseline_path=str(self.baseline_path),baseline_sha256=u.digest(self.baseline_path),
            cp_certificate_sha256=self.b['cp_certificate_sha256'],source_revision='a'*40)
        self.manifest=self.release/'context.json';u.save(self.manifest,self.m)
        self.runner=FakeRunner(self.network,self.release,package,self.b)
        self.no_process=patch.object(u.subprocess,'run',side_effect=AssertionError('Offline test must not execute network tools'))
        self.no_process.start();self.addCleanup(self.no_process.stop)

    def execute(self, phase):
        # A CLI invocation owns a fresh evidence directory; keep durable attempt markers.
        self.runner.evidence = Path(tempfile.mkdtemp(prefix='phase-', dir=self.release))
        self.runner.count = 0
        u.execute(phase,self.runner,self.m,self.b,u.digest(self.manifest))

    def assert_stops(self, phase):
        with self.assertRaises((u.Stop,SystemExit,ValueError,TypeError,KeyError)):
            self.execute(phase)

    def test_context_binds_release_hashes_environment_and_parameters(self):
        self.assertEqual(u.context(self.manifest,u.digest(self.manifest),self.m['deployment_id'])[0],self.m)
        for key,value in [('baseline_sha256','0'*64),('package_sha256','0'*64),('package_id','tokansh_1.1:'+'f'*64),
                ('sequence',1),('sequence',True),('version','1.0'),('policy',"OR('Org1MSP.peer','Org2MSP.peer')"),
                ('deployment_id','different-release'),('source_revision','b'*40),('cp_certificate_sha256',{}),
                ('package_identity_sha256','0'*64),('release_directory',str(self.network))]:
            m=copy.deepcopy(self.m);m[key]=value
            self.manifest.write_text(json.dumps(m))
            with self.subTest(key=key),self.assertRaises((u.Stop,SystemExit)):
                u.context(self.manifest,u.digest(self.manifest),self.m['deployment_id'])
        self.manifest.write_text(json.dumps(self.m))
        with self.assertRaises(u.Stop): u.context(self.manifest,'0'*64,self.m['deployment_id'])
        self.runner.captured['cp_certificate_sha256']['Org2MSP']='e'*64
        # Actual local certificate files are checked independently of captured metadata.
        cert=self.network/'drunix-network/test-network/organizations/peerOrganizations/org2.example.com/peers/peer1.org2.example.com/tls/server.crt'
        cert.write_text('-----BEGIN CERTIFICATE-----\nY2hhbmdlZA==\n-----END CERTIFICATE-----\n')
        self.assert_stops('install-org1');self.assertEqual(self.runner.mutations(),[])

    def test_install_exact_absence_single_attempt_and_no_phase_chaining(self):
        self.execute('install-org1')
        self.assertEqual(len(self.runner.mutations()),1)
        self.assertEqual(self.runner.mutations()[0][1:4],['lifecycle','chaincode','install'])
        marker=u.checks.load(self.release/'attempt-install-org1.json')
        self.assertEqual(marker['state'],'UNKNOWN')
        self.assert_stops('install-org1')  # no inspection result proving installation yet
        self.assertEqual(len(self.runner.mutations()),1)
        self.runner.installed_all()
        self.execute('install-org1')  # exact match: inspection-only, even after uncertain attempt
        self.assertEqual(len(self.runner.mutations()),1)
        self.assertFalse((self.release/'attempt-install-org2.json').exists())
        self.assertEqual((self.release/'attempt-install-org1.json').stat().st_mode & 0o777,0o600)

    def test_install_invalid_conflicting_and_duplicate_responses_cannot_mutate(self):
        row=dict(package_id=self.m['package_id'],label='tokansh_1.1')
        responses=['{}','{bad','{"installed_chaincodes":[],"installed_chaincodes":[]}',
            json.dumps({'installed_chaincodes':[row,row]}),json.dumps({'installed_chaincodes':[dict(label='tokansh_1.1',package_id='tokansh_1.1:'+'f'*64)]}),
            json.dumps({'installed_chaincodes':[dict(row,label=True)]})]
        for raw in responses:
            self.runner.installed_raw=raw
            with self.subTest(raw=raw):self.assert_stops('install-org1')
        self.assertEqual(self.runner.mutations(),[])

    def test_approval_matching_absent_conflicting_and_ambiguous(self):
        self.runner.installed_all()
        self.execute('approve-org1');self.execute('approve-org2')
        for value in [{},None,approved('tokansh_1.1:'+'f'*64,'1.1',2),approved(self.m['package_id'],'1.0',1),
                u.Stop('UNKNOWN: absent parameters OR missing source'),u.Stop('UNKNOWN: timeout')]:
            self.runner.approvals['1']=value
            self.assert_stops('approve-org1')
        self.assertEqual(self.runner.mutations(),[])
        self.assertFalse((self.release/'attempt-approve-org1.json').exists())
        for args,env in self.runner.calls:
            if 'queryapproved' in args:
                address=env['CORE_PEER_ADDRESS'];org='1' if address.endswith(':7061') else '2'
                self.assertIn(f'Admin@org{org}.example.com/msp',env['CORE_PEER_MSPCONFIGPATH'])
        for args,env in self.runner.calls:
            if 'query' in args and args[args.index('-n')+1]=='tokansh':
                self.assertIn('User1@org1.example.com/msp',env['CORE_PEER_MSPCONFIGPATH'])
                self.assertEqual(env['CORE_PEER_LOCALMSPID'],'Org1MSP')

    def test_readiness_and_commit_preservation_fail_closed(self):
        self.runner.installed_all()
        for value in [{},{'approvals':{'Org1MSP':True,'Org2MSP':False}},
                {'approvals':{'Org1MSP':True,'Org2MSP':'true'}},
                {'approvals':{'Org1MSP':True,'Org2MSP':True},'mismatches':[]},
                {'approvals':{'Org1MSP':True,'Org2MSP':True},'mismatches':None}]:
            self.runner.readiness=value;self.assert_stops('readiness');self.assert_stops('commit')
        self.assertEqual(self.runner.mutations(),[])
        self.runner.readiness={'approvals':{'Org1MSP':True,'Org2MSP':True}}
        self.execute('readiness');self.assertEqual(self.runner.mutations(),[])
        for target,field in [('property','approved_supply'),('operation','request_digest')]:
            original=copy.deepcopy(self.runner.captured)
            for org in ('1','2'):
                self.runner.captured['organizations'][org][target][field] = 101 if target == 'property' else 'c'*64
            self.assert_stops('commit');self.assertEqual(self.runner.mutations(),[])
            self.runner.captured=original

    def test_committed_definition_shape_policy_and_conflicts(self):
        valid={'chaincode_definitions':[definition(),self.b['organizations']['1']['definitions']['basic']]}
        for value in [{},{'chaincode_definitions':None},{'chaincode_definitions':[definition(),definition()]},
                {'chaincode_definitions':[dict(definition(),name=None)]}]:
            with self.assertRaises((u.Stop,SystemExit,KeyError)):u.definitions(value)
        self.assertIn('tokansh',u.definitions(valid))
        self.runner.installed_all()
        for field,value in [('sequence',3),('version','2.0'),('validation_parameter','d3Jvbmc='),('init_required',True),('collections',{'config':[]})]:
            original=copy.deepcopy(self.runner.captured)
            for org in ('1','2'):self.runner.captured['organizations'][org]['definitions']['tokansh'][field]=value
            self.assert_stops('commit')
            self.runner.captured=original
        self.assertEqual(self.runner.mutations(),[])

    def test_commit_one_attempt_tls_destinations_and_separate_verification(self):
        self.runner.installed_all();self.execute('commit')
        self.assertEqual(len(self.runner.mutations()),1)
        args,env=next((a,e) for a,e in self.runner.calls if 'commit' in a)
        self.assertNotIn('CORE_PEER_TLS_SERVERHOSTOVERRIDE',env)
        self.assertEqual(args.count('--peerAddresses'),2)
        self.assertIn('localhost:7061',args);self.assertIn('localhost:9061',args)
        self.assertIn('orderer.example.com',args)
        self.assert_stops('commit');self.assertEqual(len(self.runner.mutations()),1)
        # No automatic post-upgrade queries: the existing snapshot is still v1.
        self.assertEqual(self.runner.captured,self.b)

    def test_tls_failure_and_lite_peer_disagreement_prevent_commit(self):
        self.runner.installed_all()
        original_run = self.runner.run
        def fail_tls(args, *a, **kw):
            if str(args[0]) == 'openssl':
                raise u.Stop('UNKNOWN: TLS hostname check failed')
            return original_run(args, *a, **kw)
        with patch.object(self.runner, 'run', side_effect=fail_tls):
            self.assert_stops('commit')
        self.assertEqual(self.runner.mutations(), [])
        self.assertFalse((self.release/'attempt-commit.json').exists())
        def disagree(args, env=None, **kw):
            result = original_run(args, env, **kw)
            if 'querycommitted' in args and env.get('CORE_PEER_ADDRESS') == 'localhost:9051':
                value = json.loads(result)
                for row in value['chaincode_definitions']:
                    if row['name'] == 'tokansh': row['version'] = 'unexpected'
                return json.dumps(value)
            return result
        with patch.object(self.runner, 'run', side_effect=disagree):
            self.assert_stops('commit')
        self.assertEqual(self.runner.mutations(), [])

    def test_basic_asset_order_is_canonical_but_changed_asset_stops(self):
        for org in ('1', '2'):
            self.runner.captured['organizations'][org]['basic'].reverse()
        self.runner.installed_all()
        self.execute('readiness')
        for org in ('1', '2'):
            self.runner.captured['organizations'][org]['basic'][0]['Owner'] = 'different-owner'
        self.assert_stops('commit')
        self.assertEqual(self.runner.mutations(), [])

    def test_uncertain_mutation_is_durable_and_never_retried(self):
        self.runner.mutation_error=True
        self.assert_stops('install-org2')
        self.assertEqual(len(self.runner.mutations()),1)
        self.assertTrue((self.release/'attempt-install-org2.json').is_file())
        self.runner.mutation_error=False
        self.assert_stops('install-org2');self.assertEqual(len(self.runner.mutations()),1)

    def test_post_upgrade_requires_both_peers_records_metadata_and_approvals(self):
        self.runner.installed_all()
        for org in ('1','2'):
            row=self.runner.captured['organizations'][org]
            row['definitions']['tokansh']=definition('1.1',2)
            row['info']['functions']=u.M4_FUNCTIONS
            row['channel']['height']+=3
            row['channel']['currentBlockHash']=base64.b64encode(b'c'*32).decode()
            row['channel']['previousBlockHash']=base64.b64encode(b'd'*32).decode()
        self.execute('verify');self.assertEqual(self.runner.mutations(),[])
        saved=copy.deepcopy(self.runner.captured)
        for field in ('property','operation','basic','channel','definitions','info'):
            self.runner.captured=copy.deepcopy(saved)
            row=self.runner.captured['organizations']['2']
            row[field]={} if field!='basic' else []
            self.assert_stops('verify')
        self.runner.captured=saved
        self.runner.approvals['2']=approved('tokansh_1.1:'+'f'*64,'1.1',2)
        self.assert_stops('verify')
        self.assertEqual(self.runner.mutations(),[])

    def test_cli_timeout_errors_are_private_and_have_no_retry(self):
        # Exercise the actual subprocess boundary with a mock, not a live command.
        with patch.object(u.subprocess,'run',side_effect=subprocess.TimeoutExpired('offline-peer',1)) as run:
            with self.assertRaisesRegex(u.Stop,'UNKNOWN'):u.Runner.run(self.runner,['offline-peer'],timeout=1)
            self.assertEqual(run.call_count,1)
        with patch.object(u.subprocess,'run',return_value=subprocess.CompletedProcess([],9)) as run:
            with self.assertRaisesRegex(u.Stop,'UNKNOWN'):u.Runner.run(self.runner,['offline-peer'])
            self.assertEqual(run.call_count,1)

    def test_parser_duplicate_keys_and_incomplete_baselines_fail_closed(self):
        with self.assertRaises(SystemExit):u.checks.parse_json('{"sequence":2,"sequence":2}')
        for field in self.b:
            value=copy.deepcopy(self.b);del value[field]
            with self.assertRaises((u.Stop,KeyError)):u.snapshot(value,self.b['deployment_id'])
        for field in ('schema_version','channel','property_id','operation_id'):
            value=copy.deepcopy(self.b);value[field]=None
            with self.assertRaises(u.Stop):u.snapshot(value,self.b['deployment_id'])

    def test_phase_authorization_and_no_overwriting_baseline(self):
        for args in [[],['all','--authorize-all'],['commit','--authorize-readiness'],
                ['install-org1','--authorize-install-org2'],['approve-org1','--authorize-approve-org1','commit']]:
            with self.assertRaises((u.Stop,SystemExit)):u.main(args)
        original=self.baseline_path.read_bytes()
        with self.assertRaises(FileExistsError):u.save(self.baseline_path,{'overwritten':True})
        self.assertEqual(self.baseline_path.read_bytes(),original)

    def test_main_dispatches_one_valid_phase_with_private_context(self):
        with patch.object(u,'Runner',return_value=self.runner):
            u.main(['install-org1','--authorize-install-org1','--context',str(self.manifest),
                '--context-sha256',u.digest(self.manifest),'--deployment-id',self.m['deployment_id']])
        self.assertEqual(len(self.runner.mutations()),1)
        self.assertFalse((self.release/'attempt-commit.json').exists())


class PackagingTests(unittest.TestCase):
    def prepare(self, variant=None):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        root=Path(temp.name);repo=root/'repo';source=repo/'chaincode/tokansh'
        source.mkdir(parents=True);release=root/'release';release.mkdir(mode=0o700)
        for name in ('go.mod','go.sum','main.go','contract/issuance.go'):
            path=source/name;path.parent.mkdir(exist_ok=True,parents=True);path.write_text('test-only-source')
        runner=u.Runner(root/'network',release)
        calls=[]
        def fake(args,env=None,cwd=None,timeout=30):
            args=[str(v) for v in args];calls.append((args,env,cwd))
            if args[:2]==['git','branch']:return 'feat/frontend-connected-mode'
            if args[:2]==['git','rev-parse']:return 'a'*40
            if args[:2]==['git','status']:return ' M dirty' if variant=='dirty' else ''
            if args[:2]==['git','ls-files']:return '\n'.join(str(p.relative_to(repo)) for p in source.rglob('*') if p.is_file())
            if args[:3]==['go','mod','vendor']:
                if variant=='module changed':(Path(cwd)/'go.mod').write_text('changed')
                return ''
            if args[0]=='go':return ''
            if 'calculatepackageid' in args:return 'tokansh_1.1:'+u.digest(Path(args[-1]))
            if 'package' in args:
                path=Path(args[4]);path.write_bytes(b'package'+(b'changed' if variant=='not reproducible' and path.name.startswith('reproducibility') else b''))
                return ''
            raise AssertionError('unreviewed packaging command')
        with patch.object(u,'REPO',repo),patch.object(runner,'run',side_effect=fake),patch.object(u.subprocess,'run',side_effect=AssertionError('no real subprocess')):
            if variant:
                with self.assertRaises(u.Stop):u.prepare_package(runner,'offline-package-001','a'*40)
            else:
                u.prepare_package(runner,'offline-package-001','a'*40)
                identity=u.checks.load(release/'package-identity.json')
                self.assertEqual(identity['package_sha256'],u.digest(release/'tokansh_1.1.tar.gz'))
                self.assertEqual(identity['source_revision'],'a'*40)
                with self.assertRaises(u.Stop):u.prepare_package(runner,'offline-package-001','a'*40)
        self.assertTrue(all('install' not in a and 'approveformyorg' not in a and 'commit' not in a for a,_,_ in calls))
        for args,env,cwd in calls:
            if args[0]=='go':
                self.assertEqual(env['GOPROXY'],'off');self.assertEqual(env['GOTOOLCHAIN'],'local')
                self.assertEqual(cwd,release/'staged-chaincode')
        return calls

    def test_offline_packaging_reproducibility_and_no_network_phase(self):
        calls=self.prepare()
        self.assertEqual(sum('package' in args for args,_,_ in calls),2)

    def test_dirty_source_changed_module_and_nonreproducible_archive_stop(self):
        for variant in ('dirty','module changed','not reproducible'):
            with self.subTest(variant=variant):self.prepare(variant)


class ShellBoundaryTests(unittest.TestCase):
    def test_shell_refuses_missing_wrong_or_chained_authorization(self):
        for args in [[],['install-org1','--authorize-install-org2'],['all','--authorize-all'],
                ['commit','--authorize-commit','verify','--authorize-verify']]:
            result=subprocess.run(['bash',str(HERE/'upgrade-proposed.sh')]+args,
                env={'PATH':os.environ['PATH'],'PYTHONDONTWRITEBYTECODE':'1'},capture_output=True,text=True,timeout=10)
            self.assertNotEqual(result.returncode,0)
            self.assertNotIn('Traceback',result.stderr)


if __name__=='__main__': unittest.main()
