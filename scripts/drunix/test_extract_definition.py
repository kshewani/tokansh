"""Only offline synthetic/synthetic data. No deployment or peer invocation."""
import fixtures
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('extract_definition',HERE/'extract-definition.py')
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ExtractionTests(unittest.TestCase):
    def setUp(self):
        self.synthetic=fixtures.baseline()['Org1_definitions']['observed']
        self.basic=self.synthetic['chaincode_definitions'][0]
        self.tokansh={**self.basic,'name':'tokansh'}  # Synthetic addition, not a deployed definition.

    def test_synthetic_shape_and_exact_selection(self):
        for rows in [[self.basic,self.tokansh],[self.tokansh,self.basic]]:
            result=module.extract({'chaincode_definitions':rows})
            self.assertEqual(result,self.tokansh)
            self.assertEqual(result['name'],'tokansh')
        with self.assertRaisesRegex(SystemExit,'Missing tokansh'):
            module.extract(self.synthetic)

    def test_missing_duplicate_or_malformed_definitions(self):
        unnamed={k:v for k,v in self.tokansh.items() if k!='name'}
        cases=[None,[],{}, {'chaincode_definitions':None},{'chaincode_definitions':{}},
               {'chaincode_definitions':[]}, self.tokansh,
               {'chaincode_definitions':[self.tokansh,self.tokansh]},
               {'chaincode_definitions':[unnamed]},
               {'chaincode_definitions':[self.tokansh,None]},
               {'chaincode_definitions':[{'name':'tokansh'}]},
               {'chaincode_definitions':[{**self.tokansh,'name':'TOKANSH'}]},
               {'chaincode_definitions':[self.tokansh,{'name':'broken'}]}]
        for value in cases:
            with self.subTest(value=value),self.assertRaisesRegex(SystemExit,'Validation failed:'):
                module.extract(value)
        for key in ['validation_parameter','endorsement_plugin','version','sequence']:
            value=copy.deepcopy(self.tokansh);del value[key]
            with self.subTest(missing=key),self.assertRaisesRegex(SystemExit,'Validation failed:'):
                module.extract({'chaincode_definitions':[value]})

    def test_offline_file_pipeline_and_strict_policy_checks(self):
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'all.json';target=Path(directory)/'selected.json'
            source.write_text(json.dumps({'chaincode_definitions':[self.basic,self.tokansh]}))
            result=subprocess.run([sys.executable,'-B',str(HERE/'extract-definition.py'),str(source),str(target)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(json.loads(target.read_text()),self.tokansh)
            baseline=fixtures.baseline()
            policy=Path(directory)/'policy.json';policy.write_text(json.dumps(fixtures.policy()))
            module.checks.check('definition',baseline,[str(target),str(policy)])
            source.write_text('{"chaincode_definitions":[],"chaincode_definitions":[]}')
            target.unlink()
            result=subprocess.run([sys.executable,'-B',str(HERE/'extract-definition.py'),str(source),str(target)],capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0)
            self.assertIn('Validation failed:',result.stderr)
            self.assertFalse(target.exists())


if __name__=='__main__':unittest.main()
