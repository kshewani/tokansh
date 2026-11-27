"""Focused M4.2 upgrade tests; synthetic peers only, subprocesses forbidden."""
import copy
import importlib.util
import json
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

import test_upgrade_workflow as legacy

spec = importlib.util.spec_from_file_location('upgrade_v12', Path(__file__).with_name('upgrade-workflow.py'))
v = importlib.util.module_from_spec(spec); spec.loader.exec_module(v); v.configure_m42()


class FakeRunner(v.Runner):
    def __init__(self, fixture, baseline, package):
        super().__init__(fixture.network,fixture.release)
        self.package=package; self.captured=copy.deepcopy(baseline)
        self.calls=[]; self.installed_rows={org:[] for org in ('1','2')}
        self.approvals={org:legacy.approved(package,'1.2',3) for org in ('1','2')}
        self.installed_raw=None
        self.readiness={'approvals':{'Org1MSP':True,'Org2MSP':True}}

    def run(self,args,env=None,cwd=None,timeout=30):
        args=[str(a) for a in args]; env=env or self.env
        org='2' if env.get('CORE_PEER_ADDRESS','').endswith((':9051',':9061')) else '1'
        row=self.captured['organizations'][org]
        if 'queryapproved' in args:
            self.calls.append((args,env.copy()))
            seq=args[args.index('--sequence')+1]
            if seq=='2':return json.dumps(row['approval_previous'])
            assert seq=='3'
            value=self.approvals[org]
            if isinstance(value,Exception):raise value
            return json.dumps(value)
        if 'query' in args:
            call=json.loads(args[args.index('-c')+1])['Args']
            mapping={'GetIssuanceState':'issuance','GetBalance':'issuer_balance','GetIssuanceOperation':'issuance_operation'}
            if call[0] in mapping:
                self.calls.append((args,env.copy()))
                if call[0]=='GetBalance':assert call[1:]==[legacy.PID,v.ISSUER_ID]
                if call[0]=='GetIssuanceOperation':assert call[1:]==[v.ISSUANCE_ID]
                return json.dumps(row[mapping[call[0]]])
        if any(a in args for a in ('install','approveformyorg','commit')):
            self.calls.append((args,env.copy()))
            return 'test-only acknowledgement'
        return legacy.FakeRunner.run(self,args,env,cwd,timeout)

    def mutations(self):
        return legacy.FakeRunner.mutations(self)


class UpgradeV12Tests(unittest.TestCase):
    def setUp(self):
        self.f=legacy.UpgradeTests('runTest'); self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.b=copy.deepcopy(self.f.b)
        for row in self.b['organizations'].values():
            row['definitions']['tokansh']=legacy.definition('1.1',2)
            row['info']['functions']=list(v.FUNCTIONS)
            row['approval_previous']=legacy.approved('tokansh_1.1:'+'d'*64,'1.1',2)
            del row['approval_v1']
            p=row['property']; p['issuer_id']=v.ISSUER_ID
            p['registration_transaction_id']='205f60daf6790d1d2a9cc2077026691e6bdef754810c1451c6791f0e892b984f'
            row['operation']['original_transaction_id']=p['registration_transaction_id']
            row['operation']['result']['transaction_id']=p['registration_transaction_id']
            row['issuance']=dict(schema_version=1,property_id=legacy.PID,issuer_id=v.ISSUER_ID,
                approved_supply=100,cumulative_issued_supply=10,remaining_issuance_capacity=90)
            row['issuer_balance']=dict(schema_version=1,property_id=legacy.PID,holder_id=v.ISSUER_ID,quantity=10)
            row['issuance_operation']=dict(schema_version=1,operation_id=v.ISSUANCE_ID,authorizing_msp='Org1MSP',
                authorizing_principal=p['registered_by_principal'],function='IssueANSH',request_digest='c'*64,
                property_id=legacy.PID,issuer_id=v.ISSUER_ID,quantity=10,original_transaction_id=v.ISSUANCE_TX,
                result=dict(property_id=legacy.PID,issuer_id=v.ISSUER_ID,operation_id=v.ISSUANCE_ID,
                    transaction_id=v.ISSUANCE_TX,quantity=10,cumulative_issued_supply=10,
                    remaining_issuance_capacity=90,issuer_balance=10))
        archive=self.f.release/'tokansh_1.2.tar.gz'; archive.write_bytes(b'new-test-only-v12-package'); archive.chmod(0o600)
        self.package='tokansh_1.2:'+v.digest(archive)
        self.m={**self.f.m,**v.PARAMS,'package_path':str(archive),'package_id':self.package,'package_sha256':v.digest(archive)}
        self.runner=FakeRunner(self.f,self.b,self.package)
        self.binding='a'*64

    def execute(self,phase,authorization=None):
        self.runner.evidence=Path(tempfile.mkdtemp(prefix='phase-',dir=self.f.release))
        v.execute(phase,self.runner,self.m,self.b,self.binding,authorization)

    def test_fixed_profile_and_exact_metadata(self):
        args=v.definition_args()
        self.assertEqual(args[args.index('--version')+1],'1.2')
        self.assertEqual(args[args.index('--sequence')+1],'3')
        self.assertEqual(args[args.index('--signature-policy')+1],v.POLICY)
        self.assertEqual(v.package_label(),'tokansh_1.2')
        self.assertIn('version 1.2 sequence-3',v.APPROVAL_ACK)
        v.snapshot(self.b,self.b['deployment_id'])
        self.assertEqual(v.FUNCTIONS,legacy.u.M4_FUNCTIONS)
        self.assertEqual(v.M4_FUNCTIONS,v.FUNCTIONS+['TransferANSH'])
        with self.assertRaises(v.Stop):v.info(self.b['organizations']['1']['info'],True)
        self.assertEqual(legacy.u.PARAMS['sequence'],2) # legacy default untouched

    def test_capture_reads_both_orgs_and_issuance_preserves(self):
        actual=self.runner.capture(self.b['deployment_id'],legacy.PID,legacy.OP)
        self.assertEqual(v.snapshot(actual,self.b['deployment_id']),self.b)
        v.preserve(self.b,actual,False)
        for org in ('1','2'):
            for field in v.ISSUANCE_FIELDS+('property','operation','basic'):
                bad=copy.deepcopy(actual); bad['organizations'][org][field]={}
                with self.subTest(org=org,field=field),self.assertRaises((v.Stop,KeyError)):
                    v.preserve(self.b,bad,False)
        self.assertEqual(self.runner.mutations(),[])

    def test_install_single_org_once_and_no_automatic_next_phase(self):
        self.execute('install-org1')
        self.assertEqual(len(self.runner.mutations()),1)
        with self.assertRaises(v.Stop):self.execute('install-org1')
        self.assertEqual(len(self.runner.mutations()),1)
        self.assertFalse((self.f.release/'attempt-install-org2.json').exists())
        self.runner.installed_rows['1']=[dict(package_id=self.package,label='tokansh_1.2')]
        self.execute('install-org1')
        self.assertEqual(len(self.runner.mutations()),1)

    def test_approval_inspection_is_sequence_three_and_never_submits(self):
        self.runner.installed_rows['1']=[dict(package_id=self.package,label='tokansh_1.2')]
        self.execute('approve-org1')
        self.assertEqual(self.runner.mutations(),[])
        self.runner.approvals['1']=legacy.approved(self.package,'1.1',2)
        with self.assertRaises(v.Stop):self.execute('approve-org1')
        self.assertEqual(self.runner.mutations(),[])

    def test_post_upgrade_requires_target_metadata_and_all_preserved_records(self):
        for org in ('1','2'):
            row=self.runner.captured['organizations'][org]
            row['definitions']['tokansh']=legacy.definition('1.2',3)
            row['info']['functions']=list(v.M4_FUNCTIONS)
            row['info']['supply_interpretation']=v.ONE_TIME_SUPPLY
            row['channel']['height']+=3
            self.runner.installed_rows[org]=[dict(package_id=self.package,label='tokansh_1.2')]
        self.execute('verify')
        self.runner.captured['organizations']['2']['issuer_balance']['quantity']=9
        with self.assertRaises(v.Stop):self.execute('verify')
        self.assertEqual(self.runner.mutations(),[])

    def test_new_context_requires_new_package_and_transfer_source(self):
        identity=v.checks.load(self.f.m['package_identity_path'])
        identity.update(package_id=self.package,package_sha256=self.m['package_sha256'],
                        package_size_bytes=Path(self.m['package_path']).stat().st_size,label='tokansh_1.2')
        identity['source_files']['contract/transfer.go']='d'*64
        Path(self.m['package_identity_path']).write_text(json.dumps(identity))
        self.f.baseline_path.write_text(json.dumps(self.b))
        self.m.update(package_identity_sha256=v.digest(self.m['package_identity_path']),baseline_sha256=v.digest(self.f.baseline_path))
        self.f.manifest.write_text(json.dumps(self.m))
        v.context(self.f.manifest,v.digest(self.f.manifest),self.m['deployment_id'])
        self.m['package_id']='tokansh_1.1:'+self.m['package_sha256']
        self.f.manifest.write_text(json.dumps(self.m))
        with self.assertRaises(v.Stop):v.context(self.f.manifest,v.digest(self.f.manifest),self.m['deployment_id'])

    def test_desired_approval_binds_sequence_three_and_one_attempt(self):
        self.runner.installed_rows['1']=[dict(package_id=self.package,label='tokansh_1.2')]
        self.runner.approvals['1']=v.CLIRejected(1,'',"query failed with status: 500 - failed to invoke backing implementation of 'QueryApprovedChaincodeDefinition': could not fetch approved chaincode definition (name: 'tokansh', sequence: '3') on channel 'mychannel'")
        with self.assertRaises(v.Stop):self.execute('approve-org1')
        self.assertEqual(self.runner.mutations(),[])
        auth=dict(schema_version=2,**v.approval_scope(self.m,self.binding,'1'),
                  acknowledgement=v.APPROVAL_ACK,maintenance_acknowledgement=v.MAINTENANCE_ACK)
        path=self.f.release/'approval-org1.json';v.save(path,auth)
        flags=dict(path=str(path),sha256=v.digest(path),acknowledgement=v.APPROVAL_ACK,
                   maintenance_acknowledgement=v.MAINTENANCE_ACK)
        self.execute('approve-org1',flags)
        args=self.runner.mutations()[0]
        self.assertIn('approveformyorg',args)
        self.assertEqual(args[args.index('--sequence')+1],'3')
        self.assertEqual(args[args.index('--version')+1],'1.2')
        self.assertEqual(args[args.index('--package-id')+1],self.package)
        self.assertEqual(v.checks.load(self.f.release/'attempt-approve-org1.json')['state'],'UNKNOWN')
        with self.assertRaises(v.Stop):self.execute('approve-org1',flags)
        self.assertEqual(len(self.runner.mutations()),1)
        self.assertFalse((self.f.release/'attempt-approve-org2.json').exists())
        self.assertFalse((self.f.release/'attempt-commit.json').exists())

    def test_old_context_and_wrong_sequence_rejected(self):
        with self.assertRaises(v.Stop):v.context(self.f.manifest,legacy.u.digest(self.f.manifest),self.f.m['deployment_id'])
        for version,seq in [('1.0',1),('1.2',2),('1.1',3)]:
            actual=copy.deepcopy(self.b)
            for row in actual['organizations'].values():row['definitions']['tokansh']=legacy.definition(version,seq)
            with self.subTest(version=version,sequence=seq),self.assertRaises(v.Stop):v.preserve(self.b,actual,False)


if __name__=='__main__':unittest.main()
