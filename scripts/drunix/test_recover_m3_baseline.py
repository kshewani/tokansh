"""Offline recovery tests: synthetic CLI observations; never real peer calls."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import test_upgrade_workflow as fixtures
u=fixtures.u

spec=importlib.util.spec_from_file_location('recovery',Path(__file__).with_name('recover-m3-baseline.py'))
r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)


class RecoveryTests(unittest.TestCase):
    setUp=fixtures.UpgradeTests.setUp

    def prepare(self):
        for org in self.runner.captured['organizations'].values():
            org['property']['registration_transaction_id']=r.TX
            org['operation']['original_transaction_id']=r.TX
            org['operation']['result']['transaction_id']=r.TX
        # Stand-in for private raw CLI output; all actual subprocesses are forbidden by setUp.
        if not (self.runner.evidence/'001.stdout').exists():
            u.save(self.runner.evidence/'001.stdout',{'test_only':True})
        p=r.capture(self.runner,self.b['deployment_id'],'a'*40)
        return p

    def accepted(self):
        p=self.prepare()
        a=r.accept(p,u.digest(p),'Independent Reviewer',r.ACK)
        return p,a

    def test_capture_is_not_acceptance_and_read_only_observations_are_independent(self):
        p=self.prepare()
        self.assertFalse((p.parent/'accepted-m3.json').exists())
        with self.assertRaises(SystemExit):r.validate_accepted(p,u.digest(p))
        self.assertEqual(self.runner.mutations(),[])
        for port in (':7061',':9061',':7051',':9051'):
            self.assertTrue(any(env.get('CORE_PEER_ADDRESS','').endswith(port) for _,env in self.runner.calls))
        with self.assertRaises(FileExistsError):u.save(p,{})

    def test_explicit_acceptance_provenance_hashes_and_no_overwrite(self):
        p,a=self.accepted()
        value=r.validate_accepted(a,u.digest(a))
        self.assertEqual(value['property_id'],r.PROPERTY)
        candidate=u.checks.load(p)
        self.assertEqual(candidate['kind'],r.KIND)
        self.assertEqual(candidate['source_revision'],'a'*40)
        self.assertIn('started_at',candidate)
        with self.assertRaises(FileExistsError):r.accept(p,u.digest(p),'Independent Reviewer',r.ACK)
        with self.assertRaises(r.u.Stop):r.accept(p,u.digest(p),'Independent Reviewer','yes')
        with self.assertRaises(r.u.Stop):r.accept(p,'0'*64,'Independent Reviewer',r.ACK)
        self.assertEqual(self.runner.mutations(),[])

    def test_changed_evidence_candidate_and_acceptance_fail_closed(self):
        p,a=self.accepted();saved=p.read_bytes()
        p.write_text('{}')
        with self.assertRaises(SystemExit):r.validate_accepted(a,u.digest(a))
        p.write_bytes(saved)
        (self.runner.evidence/'001.stdout').write_text('changed')
        with self.assertRaises(SystemExit):r.validate_accepted(a,u.digest(a))
        a.write_text('{}')
        with self.assertRaises(SystemExit):r.validate_accepted(a,u.digest(a))

    def test_mismatched_definitions_assets_property_receipt_or_channels_reject_candidate(self):
        original=copy.deepcopy(self.runner.captured)
        cases=[('definitions',lambda row:row['definitions']['tokansh'].update(version='1.1',sequence=2)),
               ('basic',lambda row:row['basic'][0].update(Owner='changed')),
               ('property',lambda row:row['property'].update(approved_supply=101)),
               ('operation',lambda row:row['operation'].update(request_digest='c'*64)),
               ('channel',lambda row:row['channel'].update(height=99))]
        for name,change in cases:
            self.runner.captured=copy.deepcopy(original)
            change(self.runner.captured['organizations']['2'])
            with self.subTest(name=name),self.assertRaises((u.Stop,r.u.Stop,SystemExit)):
                self.prepare()
            self.assertFalse((self.release/'candidate.json').exists())
        self.assertEqual(self.runner.mutations(),[])

    def test_channel_changes_during_capture_fail_closed(self):
        original=self.runner.height
        calls=[]
        def height(org):
            value=copy.deepcopy(original(org));calls.append(org)
            if len(calls)>2:value['height']+=1
            return value
        with patch.object(self.runner,'height',side_effect=height):
            with self.assertRaises(u.Stop):self.prepare()
        self.assertFalse((self.release/'candidate.json').exists())

    def test_failed_or_unknown_query_never_produces_candidate(self):
        self.runner.cli_error='UNKNOWN: synthetic query failure'
        with self.assertRaises(u.Stop):self.prepare()
        self.assertFalse((self.release/'candidate.json').exists())

    def test_malformed_provenance_missing_records_and_receipt_identity_rejected(self):
        p=self.prepare();original=u.checks.load(p)
        changes=[lambda v:v.update(started_at='unknown'),
                 lambda v:v.update(kind='HISTORICAL'),
                 lambda v:v.update(evidence_sha256={}),
                 lambda v:v['snapshot']['organizations']['1'].pop('operation'),
                 lambda v:v['snapshot']['organizations']['1']['property'].update(registration_transaction_id='wrong')]
        for change in changes:
            value=copy.deepcopy(original);change(value);p.write_text(json.dumps(value))
            with self.assertRaises((r.u.Stop,SystemExit,ValueError,KeyError)):
                r.accept(p,u.digest(p),'Independent Reviewer',r.ACK)
            self.assertFalse((p.parent/'accepted-m3.json').exists())

    def test_cli_requires_separate_authorization(self):
        with self.assertRaises(SystemExit):r.main(['capture'])
        with self.assertRaises(SystemExit):r.main(['accept'])
        self.assertEqual(self.runner.mutations(),[])

    def test_preflight_requires_acceptance_and_preserves_full_m3_records(self):
        p,a=self.accepted()
        target=self.root/'new-upgrade';target.mkdir(mode=0o700)
        args=['preflight','--authorize-preflight','--deployment-id','new-upgrade-001',
              '--network-root',str(self.network),'--release-directory',str(target),
              '--property-id',r.PROPERTY,'--operation-id',r.OPERATION]
        self.runner.release=target
        with patch.object(u,'Runner',return_value=self.runner):
            with self.assertRaises(SystemExit):u.main(args+['--preservation-baseline',str(p),'--preservation-sha256',u.digest(p)])
            self.assertFalse((target/'baseline.json').exists())
            self.runner.captured['organizations']['1']['property']['approved_supply']=101
            self.runner.captured['organizations']['2']['property']['approved_supply']=101
            with self.assertRaises(u.Stop):u.main(args+['--preservation-baseline',str(a),'--preservation-sha256',u.digest(a)])
            for row in self.runner.captured['organizations'].values():row['property']['approved_supply']=100
            u.main(args+['--preservation-baseline',str(a),'--preservation-sha256',u.digest(a)])
        self.assertTrue((target/'baseline.json').exists())
        self.assertEqual(u.checks.load(target/'baseline-provenance.json')['accepted_baseline_sha256'],u.digest(a))
        self.assertEqual(self.runner.mutations(),[])


if __name__=='__main__':unittest.main()
