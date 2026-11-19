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
PID = 'f6169750-4676-4e99-887f-2bc5471bd518'
OP = 'edaeabd1-78e9-4e9d-a808-92affc2a81af'


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
        self.approval_after = None

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
        if any(v in args for v in ('install','approveformyorg','commit')):
            if self.mutation_error: raise u.Stop('UNKNOWN: simulated timeout')
            if 'approveformyorg' in args:
                self.approvals[org] = self.approval_after if self.approval_after is not None else approved(self.package,'1.1',2)
                for peer in self.captured['organizations'].values():
                    peer['channel']['height'] += 1
                    peer['channel']['previousBlockHash'] = peer['channel']['currentBlockHash']
                    peer['channel']['currentBlockHash'] = base64.b64encode(b'x'*32).decode()
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

    def execute(self, phase, authorization=None):
        # A CLI invocation owns a fresh evidence directory; keep durable attempt markers.
        self.runner.evidence = Path(tempfile.mkdtemp(prefix='phase-', dir=self.release))
        self.runner.count = 0
        u.execute(phase,self.runner,self.m,self.b,u.digest(self.manifest),authorization)

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
        self.execute('verify-approval-org1');self.execute('verify-approval-org2')
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
        self.runner.installed_all();self.execute('verify-approval-org1');self.execute('verify-approval-org2');self.execute('commit')
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
        self.execute('verify-approval-org1');self.execute('verify-approval-org2')
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
            with self.assertRaisesRegex(u.CommandTimeout,'UNKNOWN'):u.Runner.run(self.runner,['offline-peer'],timeout=1)
            self.assertEqual(run.call_count,1)
        with patch.object(u.subprocess,'run',side_effect=OSError('private launch detail')) as run:
            with self.assertRaisesRegex(u.Stop,'command unavailable') as failure:u.Runner.run(self.runner,['offline-peer'])
            self.assertNotIsInstance(failure.exception,u.CommandTimeout)
            self.assertNotIn('private launch detail',str(failure.exception))
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


class DesiredApprovalTests(unittest.TestCase):
    setUp = UpgradeTests.setUp
    execute = UpgradeTests.execute
    assert_stops = UpgradeTests.assert_stops
    # Reuse fixture construction without duplicating all original inherited tests.
    def authorization(self, org='1'):
        path = self.release/('approval-org'+org+'.json')
        value = dict(schema_version=2,organization='Org'+org+'MSP',channel='mychannel',chaincode='tokansh',
            version='1.1',sequence=2,package_id=self.m['package_id'],context_sha256=u.digest(self.manifest),
            deployment_id=self.m['deployment_id'],acknowledgement=u.APPROVAL_ACK,maintenance_acknowledgement=u.MAINTENANCE_ACK)
        path.write_text(json.dumps(value));path.chmod(0o600)
        return dict(path=str(path),sha256=u.digest(path),acknowledgement=u.APPROVAL_ACK,maintenance_acknowledgement=u.MAINTENANCE_ACK)

    def ambiguous(self, org='1'):
        message = ("Error: query failed with status: 500 - failed to invoke backing implementation of "
            "'QueryApprovedChaincodeDefinition': could not fetch approved chaincode definition "
            "(name: 'tokansh', sequence: '2') on channel 'mychannel'")
        self.runner.approvals[org] = u.CLIRejected(1,'',message)

    def test_desired_approval_uses_native_cli_one_org_and_bound_durable_intent(self):
        self.runner.installed_all();self.ambiguous()
        flags = self.authorization()
        before = copy.deepcopy(self.b)
        self.execute('approve-org1',flags)
        mutations=self.runner.mutations()
        self.assertEqual(len(mutations),1)
        self.assertIn('approveformyorg',mutations[0])
        self.assertIn(self.m['package_id'],mutations[0])
        self.assertIn('localhost:7061',mutations[0])
        self.assertIn('--waitForEvent',mutations[0])
        args,env=next((a,e) for a,e in self.runner.calls if 'approveformyorg' in a)
        self.assertEqual(env['CORE_PEER_LOCALMSPID'],'Org1MSP')
        self.assertIn('Admin@org1.example.com/msp',env['CORE_PEER_MSPCONFIGPATH'])
        self.assertEqual(env['CORE_PEER_TLS_SERVERHOSTOVERRIDE'],'peer1.org1.example.com')
        self.assertIn('--tls',args);self.assertIn('orderer.example.com',args)
        intent=u.checks.load(self.release/'attempt-approve-org1.json')
        self.assertEqual(intent['state'],'UNKNOWN')
        self.assertEqual(intent['desired_state_authorization']['binding']['organization'],'Org1MSP')
        self.assertEqual(intent['desired_state_authorization']['authorization_sha256'],flags['sha256'])
        self.assertFalse((self.release/'attempt-approve-org2.json').exists())
        self.assertFalse((self.release/'attempt-commit.json').exists())
        for org in ('1','2'):
            for field in ('property','operation','basic','definitions','approval_v1'):
                self.assertEqual(self.runner.captured['organizations'][org][field],before['organizations'][org][field])
        self.assertGreater(self.runner.captured['organizations']['1']['channel']['height'],before['organizations']['1']['channel']['height'])
        self.assertFalse((self.runner.evidence/'desired-approval-observed.json').exists())
        self.assertIn('approveformyorg',self.runner.calls[-1][0])
        self.assertEqual(u.checks.load(self.runner.evidence/'prior-approval.json')['state'],'UNKNOWN')

    def test_org2_authorization_is_independent(self):
        self.runner.installed_all();self.ambiguous('2')
        self.execute('approve-org2',self.authorization('2'))
        args,env=next((a,e) for a,e in self.runner.calls if 'approveformyorg' in a)
        self.assertIn('localhost:9061',args)
        self.assertIn('Admin@org2.example.com/msp',env['CORE_PEER_MSPCONFIGPATH'])
        self.assertEqual(env['CORE_PEER_LOCALMSPID'],'Org2MSP')
        self.assertFalse((self.release/'attempt-approve-org1.json').exists())

    def test_known_conflict_replaced_only_with_explicit_authorization(self):
        self.runner.installed_all()
        self.runner.approvals['1']=approved('tokansh_1.1:'+'f'*64,'2.0',2)
        self.assert_stops('approve-org1')
        self.assertEqual(self.runner.mutations(),[])
        self.execute('approve-org1',self.authorization())
        self.assertEqual(len(self.runner.mutations()),1)
        self.assertEqual(u.checks.load(self.runner.evidence/'prior-approval.json')['state'],'CONFLICT')

    def test_matching_approval_is_read_only_even_with_desired_acknowledgement(self):
        self.runner.installed_all()
        self.execute('approve-org1',self.authorization())
        self.assertEqual(self.runner.mutations(),[])
        self.assertFalse((self.release/'attempt-approve-org1.json').exists())

    def test_authorization_mismatch_fields_types_hash_and_ack_fail_before_queries(self):
        flags=self.authorization();path=Path(flags['path']);original=json.loads(path.read_text())
        for key,value in [('organization','Org2MSP'),('channel','other'),('chaincode','basic'),('version','1.0'),
                ('sequence',1),('sequence',True),('package_id','tokansh_1.1:'+'0'*64),('context_sha256','0'*64),
                ('deployment_id','other-release'),('schema_version',True),('acknowledgement','yes')]:
            changed=dict(original);changed[key]=value;path.write_text(json.dumps(changed))
            with self.subTest(key=key),self.assertRaises(u.Stop):
                self.execute('approve-org1',dict(flags,sha256=u.digest(path)))
        path.write_text(json.dumps(original))
        for changed in (dict(flags,sha256='0'*64),dict(flags,acknowledgement='yes')):
            with self.assertRaises(u.Stop):self.execute('approve-org1',changed)
        for key in original:
            changed=dict(original);del changed[key];path.write_text(json.dumps(changed))
            with self.subTest(missing=key),self.assertRaises(u.Stop):
                self.execute('approve-org1',dict(flags,sha256=u.digest(path)))
        self.assertEqual(self.runner.calls,[])
        self.assertEqual(self.runner.mutations(),[])

    def test_authorization_duplicate_keys_unknown_fields_permissions_and_wrong_phase(self):
        flags=self.authorization();path=Path(flags['path']);original=path.read_text()
        for body in (original[:-1]+',"sequence":2}',original[:-1]+',"extra":true}','{broken','null'):
            path.write_text(body)
            with self.assertRaises((u.Stop,SystemExit,ValueError)):
                self.execute('approve-org1',dict(flags,sha256=u.digest(path)))
        path.write_text(original);path.chmod(0o644)
        with self.assertRaises(u.Stop):self.execute('approve-org1',flags)
        path.chmod(0o600)
        with self.assertRaises(u.Stop):self.execute('commit',flags)
        self.assertEqual(self.runner.calls,[])

    def test_malformed_approval_or_unrelated_cli_failure_never_authorizes_write(self):
        self.runner.installed_all();flags=self.authorization()
        for value in ({},None,approved(self.m['package_id'],'1.1',1),
                u.CLIRejected(1,'','connection unavailable'),u.CLIRejected(1,'','access denied'),
                u.CLIRejected(1,'','TLS verification failed'),u.Stop('UNKNOWN: timeout')):
            self.runner.approvals['1']=value
            with self.subTest(value=str(type(value))),self.assertRaises((u.Stop,SystemExit)):
                self.execute('approve-org1',flags)
        self.assertEqual(self.runner.mutations(),[])

    def test_timeout_or_failed_postcheck_never_causes_resubmission(self):
        self.runner.installed_all();self.ambiguous();flags=self.authorization()
        self.runner.mutation_error=True
        with self.assertRaises(u.Stop):self.execute('approve-org1',flags)
        self.assertEqual(len(self.runner.mutations()),1)
        self.runner.mutation_error=False
        with self.assertRaises(u.Stop):self.execute('approve-org1',flags)
        self.assertEqual(len(self.runner.mutations()),1)
        self.assertTrue((self.release/'attempt-approve-org1.json').exists())
        # Late read reconciliation may observe the desired state without another
        # submission or claiming the original command's transaction committed.
        self.runner.approvals['1']=approved(self.m['package_id'],'1.1',2)
        self.execute('approve-org1',flags)
        self.assertEqual(len(self.runner.mutations()),1)
        self.assertFalse((self.runner.evidence/'desired-approval-observed.json').exists())

    def test_acknowledged_approval_with_wrong_poststate_stays_unresolved(self):
        self.runner.installed_all();self.ambiguous();flags=self.authorization()
        self.runner.approval_after=approved('tokansh_1.1:'+'f'*64,'1.1',2)
        self.execute('approve-org1',flags)
        with self.assertRaises(u.Stop):self.execute('verify-approval-org1')
        self.assertEqual(len(self.runner.mutations()),1)
        self.assertTrue((self.release/'acknowledged-approve-org1.json').exists())
        self.assertFalse((self.runner.evidence/'desired-approval-observed.json').exists())
        with self.assertRaises(u.Stop):self.execute('approve-org1',flags)
        self.assertEqual(len(self.runner.mutations()),1)

    def test_preservation_peers_package_or_tls_failure_blocks_desired_approval(self):
        self.runner.installed_all();flags=self.authorization();self.ambiguous()
        original=copy.deepcopy(self.runner.captured)
        for field in ('property','operation','basic','channel','definitions'):
            self.runner.captured=copy.deepcopy(original)
            self.runner.captured['organizations']['2'][field]={} if field!='basic' else []
            with self.assertRaises((u.Stop,SystemExit,KeyError,TypeError)):
                self.execute('approve-org1',flags)
        self.runner.captured=original
        self.runner.installed_rows['1']=[]
        with self.assertRaises(u.Stop):self.execute('approve-org1',flags)
        self.runner.installed_all()
        with patch.object(self.runner,'tls_commit',side_effect=u.Stop('TLS mismatch')):
            with self.assertRaises(u.Stop):self.execute('approve-org1',flags)
        self.assertEqual(self.runner.mutations(),[])

    def test_cli_partial_duplicate_or_wrong_org_acknowledgements_stop(self):
        flags=self.authorization()
        common=['approve-org1','--authorize-approve-org1','--context',str(self.manifest),
            '--context-sha256',u.digest(self.manifest),'--deployment-id',self.m['deployment_id']]
        with patch.object(u,'Runner',return_value=self.runner):
            for extra in (['--desired-state-authorization',flags['path']],
                    ['--context',str(self.manifest)],['--authorization-sha256',flags['sha256']],
                    ['--acknowledge-replacement-and-repair','yes']):
                with self.assertRaises(u.Stop):u.main(common+extra)
        self.assertEqual(self.runner.calls,[])

    def test_org2_approval_requires_org2_authorization_and_org2_admin_only(self):
        self.runner.installed_all();self.ambiguous('2')
        flags1=self.authorization('1');flags2=self.authorization('2')
        with self.assertRaises(u.Stop):self.execute('approve-org2',flags1)
        self.assertEqual(self.runner.calls,[])
        self.execute('approve-org2',flags2)
        native=[(a,e) for a,e in self.runner.calls if 'approveformyorg' in a]
        self.assertEqual(len(native),1)
        args,env=native[0]
        self.assertIn('localhost:9061',args);self.assertNotIn('localhost:7061',args)
        self.assertEqual(env['CORE_PEER_LOCALMSPID'],'Org2MSP')
        self.assertIn('Admin@org2.example.com/msp',env['CORE_PEER_MSPCONFIGPATH'])
        self.assertEqual(env['CORE_PEER_TLS_SERVERHOSTOVERRIDE'],'peer1.org2.example.com')
        self.assertFalse((self.release/'attempt-approve-org1.json').exists())
        self.assertTrue((self.release/'attempt-approve-org2.json').exists())

    def test_durable_bound_intent_exists_before_native_execution_and_crash_blocks_repeat(self):
        self.runner.installed_all();self.ambiguous();flags=self.authorization()
        original=self.runner.run
        launches=[]
        def crash(args,*a,**kw):
            if 'approveformyorg' in args:
                intent=u.checks.load(self.release/'attempt-approve-org1.json')
                auth=intent['desired_state_authorization']
                self.assertEqual(auth['authorization_sha256'],flags['sha256'])
                self.assertEqual(auth['binding']['package_id'],self.m['package_id'])
                self.assertEqual(auth['binding']['context_sha256'],u.digest(self.manifest))
                launches.append(list(args))
                raise KeyboardInterrupt('test-only process crash')
            return original(args,*a,**kw)
        with patch.object(self.runner,'run',side_effect=crash):
            with self.assertRaises(KeyboardInterrupt):self.execute('approve-org1',flags)
        self.assertEqual(len(launches),1)
        with self.assertRaises(u.Stop):self.execute('approve-org1',flags)
        self.assertEqual(self.runner.mutations(),[])
        self.assertFalse((self.release/'acknowledged-approve-org1.json').exists())

    def test_conflicting_and_unavailable_sources_require_explicit_replacement(self):
        self.runner.installed_all()
        self.runner.approvals['1']=approved('tokansh_1.1:'+'f'*64,'2.0',2)
        with self.assertRaises(u.Stop):self.execute('approve-org1')
        self.assertEqual(self.runner.mutations(),[])
        self.execute('approve-org1',self.authorization())
        self.assertEqual(len(self.runner.mutations()),1)
        # Independent Org2 approval can repair the native valid unavailable source.
        value=approved(self.m['package_id'],'1.1',2)
        value['source']={'Type':{'Unavailable':{}}}
        self.runner.approvals['2']=value
        self.execute('verify-approval-org1')
        self.execute('approve-org2',self.authorization('2'))
        self.assertEqual(len(self.runner.mutations()),2)

    def test_known_error_with_extra_content_wrong_scope_or_rc_is_not_repair_authorization(self):
        self.runner.installed_all();self.ambiguous();flags=self.authorization()
        error=self.runner.approvals['1']
        for candidate in (u.CLIRejected(9,'',error.stderr),u.CLIRejected(1,'unexpected stdout',error.stderr),
                u.CLIRejected(1,'',error.stderr+' extra'),
                u.CLIRejected(1,'',error.stderr.replace("sequence: '2'","sequence: '1'")),
                u.CLIRejected(1,'',error.stderr.replace('mychannel','otherchannel'))):
            self.runner.approvals['1']=candidate
            with self.assertRaises(u.Stop):self.execute('approve-org1',flags)
        self.assertEqual(self.runner.mutations(),[])
        self.assertNotIn('secret-test-value',str(u.CLIRejected(1,'secret-test-value','secret-test-value')))

    def test_changed_package_or_authorization_is_rejected_again_before_intent(self):
        self.runner.installed_all();self.ambiguous();flags=self.authorization()
        original=self.runner.tls_approval
        def change_package(org):
            original(org)
            Path(self.m['package_path']).write_bytes(b'changed-in-test')
        with patch.object(self.runner,'tls_approval',side_effect=change_package):
            with self.assertRaises(u.Stop):self.execute('approve-org1',flags)
        self.assertEqual(self.runner.mutations(),[])
        self.assertFalse((self.release/'attempt-approve-org1.json').exists())
        Path(self.m['package_path']).write_bytes(b'offline-test-only-package')
        def change_authorization(org):
            original(org)
            value=json.loads(Path(flags['path']).read_text());value['organization']='Org2MSP'
            Path(flags['path']).write_text(json.dumps(value))
        with patch.object(self.runner,'tls_approval',side_effect=change_authorization):
            with self.assertRaises(u.Stop):self.execute('approve-org1',flags)
        self.assertEqual(self.runner.mutations(),[])
        self.assertFalse((self.release/'attempt-approve-org1.json').exists())

    def test_malformed_duplicate_unknown_or_case_variant_authorization_fails_closed(self):
        flags=self.authorization();path=Path(flags['path']);original=path.read_text()
        for body in ('{}','null','[]','{broken',original[:-1]+',"sequence":2}',
                original[:-1]+',"extra":true}',original.replace('"organization"','"Organization"',1)):
            path.write_text(body)
            with self.assertRaises((u.Stop,SystemExit,ValueError)):
                self.execute('approve-org1',dict(flags,sha256=u.digest(path)))
        self.assertEqual(self.runner.calls,[])
        self.assertFalse((self.release/'attempt-approve-org1.json').exists())

    def test_post_approval_preservation_failure_retains_unknown_and_stops(self):
        self.runner.installed_all();self.ambiguous();flags=self.authorization()
        original=self.runner.run
        def alter_receipt(args,*a,**kw):
            result=original(args,*a,**kw)
            if 'approveformyorg' in args:
                for org in ('1','2'):
                    self.runner.captured['organizations'][org]['operation']['request_digest']='c'*64
            return result
        with patch.object(self.runner,'run',side_effect=alter_receipt):
            self.execute('approve-org1',flags)
        with self.assertRaises(u.Stop):self.execute('verify-approval-org1')
        self.assertEqual(len(self.runner.mutations()),1)
        self.assertTrue((self.release/'attempt-approve-org1.json').exists())
        self.assertTrue((self.release/'acknowledged-approve-org1.json').exists())
        self.assertFalse((self.runner.evidence/'desired-approval-observed.json').exists())
        with self.assertRaises(u.Stop):self.execute('approve-org1',flags)
        self.assertEqual(len(self.runner.mutations()),1)

    def test_already_committed_sequence2_cannot_reassociate_package(self):
        self.runner.installed_all();flags=self.authorization()
        for org in ('1','2'):
            row=self.runner.captured['organizations'][org]
            row['definitions']['tokansh']=definition('1.1',2)
            row['info']['functions']=u.M4_FUNCTIONS
            row['channel']['height']+=1
            row['channel']['currentBlockHash']=base64.b64encode(b'y'*32).decode()
        with self.assertRaises(u.Stop):self.execute('approve-org1',flags)
        self.assertEqual(self.runner.mutations(),[])
        self.assertFalse((self.release/'attempt-approve-org1.json').exists())

    def test_main_dispatches_exact_one_desired_approval(self):
        self.runner.installed_all();self.ambiguous();flags=self.authorization()
        with patch.object(u,'Runner',return_value=self.runner):
            u.main(['approve-org1','--authorize-approve-org1','--context',str(self.manifest),
                '--context-sha256',u.digest(self.manifest),'--deployment-id',self.m['deployment_id'],
                '--desired-state-authorization',flags['path'],'--authorization-sha256',flags['sha256'],
                '--acknowledge-replacement-and-repair',u.APPROVAL_ACK,'--acknowledge-maintenance-window',u.MAINTENANCE_ACK])
        self.assertEqual(len(self.runner.mutations()),1)
        self.assertIn('approveformyorg',self.runner.mutations()[0])


class IndependentApprovalVerificationTests(unittest.TestCase):
    setUp = UpgradeTests.setUp
    execute = UpgradeTests.execute
    assert_stops = UpgradeTests.assert_stops
    authorization = DesiredApprovalTests.authorization
    ambiguous = DesiredApprovalTests.ambiguous

    def latest(self,org='1'):
        return u.checks.load(u.verification_files(self.release,org)[-1])

    def test_no_automatic_verification_and_readiness_requires_both_independent_matches(self):
        self.runner.installed_all();self.ambiguous()
        self.execute('approve-org1',self.authorization())
        self.assertIn('approveformyorg',self.runner.calls[-1][0])
        self.assertEqual(u.verification_files(self.release,'1'),[])
        with self.assertRaises(u.Stop):self.execute('readiness')
        self.execute('verify-approval-org1')
        result=self.latest()
        self.assertEqual(result['observation']['state'],'MATCH')
        self.assertTrue(result['original_attempt']['native_acknowledgement_present'])
        self.assertEqual(result['original_attempt']['transaction_validation'],'UNKNOWN')
        with self.assertRaises(u.Stop):self.execute('readiness')
        self.execute('verify-approval-org2')
        self.execute('readiness')
        self.assertEqual(len(self.runner.mutations()),1)
        self.assertFalse((self.release/'attempt-commit.json').exists())

    def test_timeout_recovery_is_independent_read_only_and_never_claims_original_validity(self):
        self.runner.installed_all();self.ambiguous();flags=self.authorization()
        self.runner.mutation_error=True
        with self.assertRaises(u.Stop):self.execute('approve-org1',flags)
        self.runner.mutation_error=False
        with self.assertRaises(u.Stop):self.execute('verify-approval-org1')
        self.assertEqual(self.latest()['observation']['state'],'UNKNOWN')
        self.runner.approvals['1']=approved(self.m['package_id'],'1.1',2)
        self.execute('approve-org1',flags)  # inspection only
        self.assertEqual(len(u.verification_files(self.release,'1')),1)
        self.execute('verify-approval-org1')
        result=self.latest()
        self.assertEqual(result['observation']['state'],'MATCH')
        self.assertFalse(result['original_attempt']['native_acknowledgement_present'])
        self.assertEqual(result['original_attempt']['transaction_validation'],'UNKNOWN')
        self.assertEqual(len(self.runner.mutations()),1)
        self.assertTrue((self.release/'attempt-approve-org1.json').exists())

    def test_independent_conflict_incomplete_unknown_and_newest_record_block_progress(self):
        self.runner.installed_all();self.execute('verify-approval-org1');self.execute('verify-approval-org2')
        self.execute('readiness')
        cases=[('CONFLICT',approved('tokansh_1.1:'+'f'*64,'1.1',2)),
               ('INCOMPLETE',dict(approved(self.m['package_id'],'1.1',2),source={'Type':{'Unavailable':{}}})),
               ('UNKNOWN',u.Stop('UNKNOWN: timed out'))]
        for state,value in cases:
            self.runner.approvals['1']=value
            with self.assertRaises(u.Stop):self.execute('verify-approval-org1')
            self.assertEqual(self.latest()['observation']['state'],state)
            self.runner.approvals['1']=approved(self.m['package_id'],'1.1',2)
            with self.assertRaises(u.Stop):self.execute('readiness')
        self.assertEqual(len(u.verification_files(self.release,'1')),4)
        self.execute('verify-approval-org1');self.execute('readiness')
        self.assertEqual(self.runner.mutations(),[])

    def test_verification_failure_does_not_leave_older_match_usable(self):
        self.runner.installed_all();self.execute('verify-approval-org1');self.execute('verify-approval-org2')
        original=copy.deepcopy(self.runner.captured)
        self.runner.captured['organizations']['1']['property']['approved_supply']=101
        with self.assertRaises(u.Stop):self.execute('verify-approval-org1')
        self.assertEqual(self.latest()['observation']['state'],'UNKNOWN')
        self.assertFalse(self.latest()['preservation_verified'])
        self.runner.captured=original
        with self.assertRaises(u.Stop):self.execute('readiness')
        self.assertEqual(self.runner.mutations(),[])

    def test_forged_scope_or_changed_approval_cannot_reuse_verification(self):
        self.runner.installed_all();self.execute('verify-approval-org1');self.execute('verify-approval-org2')
        path=u.verification_files(self.release,'1')[-1]
        original=self.latest()
        for field,value in [('context_sha256','0'*64),('organization','Org2MSP'),('package_id','wrong'),('sequence',True)]:
            changed=copy.deepcopy(original);changed['scope'][field]=value
            path.write_text(json.dumps(changed))
            with self.assertRaises(u.Stop):self.execute('readiness')
        path.write_text(json.dumps(original))
        self.runner.approvals['1']=approved('tokansh_1.1:'+'f'*64,'1.1',2)
        with self.assertRaises(u.Stop):self.execute('readiness')
        self.assertEqual(self.runner.mutations(),[])

    def test_omitted_false_init_requirement_is_canonical_across_independent_reads(self):
        self.runner.installed_all()
        for org in ('1','2'):self.runner.approvals[org].pop('init_required')
        self.execute('verify-approval-org1');self.execute('verify-approval-org2')
        self.assertIs(self.latest()['observation']['observed']['init_required'],False)
        self.execute('readiness')
        self.assertEqual(self.runner.mutations(),[])

    def test_maintenance_acknowledgement_and_schema_are_mandatory(self):
        flags=self.authorization();self.runner.installed_all();self.ambiguous()
        for text in ('', 'yes', 'No competing operators'):
            changed=dict(flags,maintenance_acknowledgement=text)
            with self.assertRaises(u.Stop):self.execute('approve-org1',changed)
        path=Path(flags['path']);value=json.loads(path.read_text());value['schema_version']=1
        path.write_text(json.dumps(value));flags['sha256']=u.digest(path)
        with self.assertRaises(u.Stop):self.execute('approve-org1',flags)
        self.assertEqual(self.runner.calls,[])

    def test_wrong_admin_or_known_commit_attempt_prevents_approval(self):
        self.runner.installed_all();self.ambiguous();flags=self.authorization()
        original=self.runner.env_for
        def wrong_admin(org,lite=False,application=False):
            env=original(org,lite,application)
            if org=='1' and not lite and not application:env['CORE_PEER_LOCALMSPID']='Org2MSP'
            return env
        with patch.object(self.runner,'env_for',side_effect=wrong_admin):
            with self.assertRaises(u.Stop):self.execute('approve-org1',flags)
        self.assertEqual(self.runner.mutations(),[])
        u.save(self.release/'attempt-commit.json',dict(state='UNKNOWN'))
        with self.assertRaises(u.Stop):self.execute('approve-org1',flags)
        self.assertEqual(self.runner.mutations(),[])

    def test_other_org_unverified_attempt_blocks_competing_approval(self):
        self.runner.installed_all();self.ambiguous('1');self.ambiguous('2')
        self.execute('approve-org1',self.authorization('1'))
        with self.assertRaises(u.Stop):self.execute('approve-org2',self.authorization('2'))
        self.assertEqual(len(self.runner.mutations()),1)
        self.execute('verify-approval-org1')
        self.execute('approve-org2',self.authorization('2'))
        self.assertEqual(len(self.runner.mutations()),2)


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
            runner.count += 1
            args=[str(v) for v in args];calls.append((args,env,cwd))
            if args[:2]==['git','branch']:return 'feat/frontend-connected-mode'
            if args[:2]==['git','rev-parse']:return 'a'*40
            if args[:2]==['git','status']:return ' M dirty' if variant=='dirty' else ''
            if args[:2]==['git','ls-files']:return '\n'.join(str(p.relative_to(repo)) for p in source.rglob('*') if p.is_file())
            if args[:3]==['go','mod','vendor']:
                if variant=='module changed':(Path(cwd)/'go.mod').write_text('changed')
                return ''
            if args[0]=='go':
                self.assertEqual(timeout,600 if '-race' in args else 180)
                if 'test' in args:self.assertIn('-timeout=60s',args)
                if '-race' in args:
                    self.assertEqual(len(calls),7)  # Evidence command 007.
                    if variant=='race timeout':raise u.CommandTimeout('private infrastructure detail')
                    if variant=='race unavailable':raise u.Stop('private infrastructure detail')
                return ''
            if 'calculatepackageid' in args:return 'tokansh_1.1:'+u.digest(Path(args[-1]))
            if 'package' in args:
                path=Path(args[4]);path.write_bytes(b'package'+(b'changed' if variant=='not reproducible' and path.name.startswith('reproducibility') else b''))
                return ''
            raise AssertionError('unreviewed packaging command')
        with patch.object(u,'REPO',repo),patch.object(runner,'run',side_effect=fake),patch.object(u.subprocess,'run',side_effect=AssertionError('no real subprocess')):
            if variant:
                with self.assertRaises(u.Stop) as failure:u.prepare_package(runner,'offline-package-001','a'*40)
                if variant.startswith('race '):
                    message=str(failure.exception)
                    self.assertIn('Go race tests',message)
                    self.assertIn('deadline=600s',message)
                    self.assertIn('command=007',message)
                    self.assertIn(str(runner.evidence),message)
                    self.assertNotIn('private infrastructure detail',message)
                    self.assertIn('timed out' if variant=='race timeout' else 'failed or unavailable',message)
                    self.assertFalse((runner.release/'package-identity.json').exists())
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

    def test_race_timeout_or_launch_failure_stops_once_with_sanitized_diagnostics(self):
        for variant in ('race timeout','race unavailable'):
            with self.subTest(variant=variant):
                calls=self.prepare(variant)
                self.assertEqual(len(calls),7)
                self.assertIn('-race',calls[-1][0])


class ShellBoundaryTests(unittest.TestCase):
    def test_shell_refuses_missing_wrong_or_chained_authorization(self):
        for args in [[],['install-org1','--authorize-install-org2'],['all','--authorize-all'],
                ['commit','--authorize-commit','verify','--authorize-verify']]:
            result=subprocess.run(['bash',str(HERE/'upgrade-proposed.sh')]+args,
                env={'PATH':os.environ['PATH'],'PYTHONDONTWRITEBYTECODE':'1'},capture_output=True,text=True,timeout=10)
            self.assertNotEqual(result.returncode,0)
            self.assertNotIn('Traceback',result.stderr)


if __name__=='__main__': unittest.main()
