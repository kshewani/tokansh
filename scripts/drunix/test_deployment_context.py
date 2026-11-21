"""Offline context validation and shell guard regression tests; no phase execution."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest
import fixtures

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('context', HERE/'deployment-context.py')
context = importlib.util.module_from_spec(spec)
spec.loader.exec_module(context)


class ContextTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.manifest = root/'manifest.json'
        package = root/'package.tar.gz'; package.write_bytes(b'test-only-package')
        baseline = root/'baseline.json'; baseline.write_text(json.dumps(fixtures.baseline()))
        network = root/'network'; evidence = root/'evidence'; evidence.mkdir()
        # Synthetic PEM transport shape; no identity or private material.
        for org in (1, 2):
            cert = network/f'drunix-network/test-network/organizations/peerOrganizations/org{org}.example.com/peers/peer1.org{org}.example.com/tls/server.crt'
            cert.parent.mkdir(parents=True)
            cert.write_text('-----BEGIN CERTIFICATE-----\ndGVzdC1vbmx5\n-----END CERTIFICATE-----\n')
        self.m = dict(schema_version=1, deployment_id='test-environment-001', network_root=str(network),
            package_path=str(package), package_sha256=context.sha(package),
            package_id='tokansh_1.0:'+context.sha(package), baseline_path=str(baseline),
            baseline_sha256=context.sha(baseline), evidence_directory=str(evidence),
            cp_certificate_sha256={key:hashlib.sha256(b'test-only').hexdigest() for key in ('Org1MSP','Org2MSP')},
            channel='mychannel', chaincode='tokansh', version='1.0', sequence=1,
            policy="AND('Org1MSP.peer','Org2MSP.peer')", init_required=False)

    def run_context(self, m=None, deployment_id=None, sha=None):
        self.manifest.write_text(json.dumps(self.m if m is None else m))
        return context.validate(self.manifest, sha or context.sha(self.manifest), deployment_id or self.m['deployment_id'])

    def test_positive_and_explicit_new_package_identity(self):
        self.assertEqual(self.run_context()[4], self.m['package_id'])
        p=Path(self.m['package_path']);p.write_bytes(b'new-reviewed-package')
        self.m.update(package_sha256=context.sha(p),package_id='tokansh_1.0:'+context.sha(p))
        self.assertEqual(self.run_context()[4],self.m['package_id'])

    def test_fail_closed_context_and_parameter_mismatch(self):
        for key,value in [('channel','other'),('sequence',2),('sequence',True),('version','2.0'),
            ('policy',"OR('Org1MSP.peer','Org2MSP.peer')"),('init_required',True),
            ('package_sha256','0'*64),('package_id','wrong'),('baseline_sha256','0'*64),
            ('cp_certificate_sha256',{}),('evidence_directory',str(HERE)),('baseline_path','relative.json')]:
            m=copy.deepcopy(self.m);m[key]=value
            with self.subTest(key=key,value=value),self.assertRaises(SystemExit):self.run_context(m)
        with self.assertRaises(SystemExit):self.run_context(deployment_id='another-environment')
        with self.assertRaises(SystemExit):self.run_context(sha='0'*64)
        for key in self.m:
            m=copy.deepcopy(self.m);del m[key]
            with self.subTest(missing=key),self.assertRaises(SystemExit):self.run_context(m)

    def test_baseline_and_environment_reuse_rejected(self):
        p=Path(self.m['baseline_path']); b=fixtures.baseline();b['Org2_channel']['observed']['height']=9
        p.write_text(json.dumps(b));self.m['baseline_sha256']=context.sha(p)
        with self.assertRaises(SystemExit):self.run_context()
        p.write_text(json.dumps(fixtures.baseline()));self.m['baseline_sha256']=context.sha(p)
        self.m['cp_certificate_sha256']['Org2MSP']='0'*64
        with self.assertRaises(SystemExit):self.run_context()

    def test_tampering_after_review_and_malformed_cli_fail_closed(self):
        self.run_context()
        reviewed = context.sha(self.manifest)
        Path(self.m['package_path']).write_bytes(b'changed-after-review')
        with self.assertRaises(SystemExit):
            context.validate(self.manifest, reviewed, self.m['deployment_id'])
        for raw in ['{broken', '[]', '{"schema_version":1,"schema_version":1}']:
            self.manifest.write_text(raw)
            result = subprocess.run([sys.executable, '-B', str(HERE/'deployment-context.py'),
                str(self.manifest), context.sha(self.manifest), self.m['deployment_id']],
                capture_output=True, text=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Validation failed:', result.stderr)
            self.assertNotIn('Traceback', result.stderr)
            self.assertEqual(result.stdout, '')

    def test_shell_structure_without_executing_phases(self):
        script=(HERE/'deployment-proposed.sh').read_text()
        self.assertNotIn('/tmp/',script)
        self.assertNotIn('/home/kshewani/',script)
        self.assertIn('TOKANSH_DEPLOYMENT_MANIFEST_SHA256',script)
        self.assertIn('unset CORE_PEER_TLS_SERVERHOSTOVERRIDE',script)
        self.assertIn('preservation before',script)
        self.assertIn('preservation after',script)
        self.assertNotIn('network.sh',script)
        self.assertNotIn('chaincode invoke',script)
        self.assertIn('"--authorize-$PHASE"',script)


if __name__=='__main__':unittest.main()
