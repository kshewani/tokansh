"""Offline only: CLI_shape CLI fixtures and synthetic negative cases. No peer commands."""
import fixtures
import base64
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('checks',HERE/'deployment-checks.py')
checks=importlib.util.module_from_spec(spec)
spec.loader.exec_module(checks)


class AssertionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.baseline=fixtures.baseline()
        self.basic=copy.deepcopy(self.baseline['Org1_definitions']['observed']['chaincode_definitions'][0])
        self.definition={**self.basic,'name':'tokansh'}
        self.policy=fixtures.policy()

    def file(self,name,value,raw=False):
        p=Path(self.tmp.name)/name
        p.write_text(value if raw else json.dumps(value))
        return str(p)

    def definition_check(self,d=None,p=None):
        checks.check('definition',self.baseline,[self.file('definition.json',self.definition if d is None else d),self.file('policy.json',self.policy if p is None else p)])

    def basic_check(self,d):
        checks.check('basic',self.baseline,['1',self.file('basic.json',d),self.file('assets.json',self.baseline['Org1_basic']['observed'])])

    def test_positive_named_definitions_and_cli_shape_all_definitions(self):
        self.definition_check()
        self.basic_check(self.basic)
        self.basic_check(self.baseline['Org1_definitions']['observed'])
        self.definition_check({'chaincode_definitions':[self.basic,self.definition]})

    def test_missing_incorrect_and_nonstring_names(self):
        for kind in ['basic','tokansh']:
            for name in [None,'wrong','',7]:
                with self.subTest(kind=kind,name=name):
                    d=copy.deepcopy(self.basic if kind=='basic' else self.definition)
                    if name is None:del d['name']
                    else:d['name']=name
                    with self.assertRaisesRegex(SystemExit,'Validation failed:'):
                        self.basic_check(d) if kind=='basic' else self.definition_check(d)

    def test_missing_definition_fields(self):
        for kind in ['basic','tokansh']:
            for field in ['version','sequence','endorsement_plugin','validation_plugin','validation_parameter','collections']:
                with self.subTest(kind=kind,field=field):
                    d=copy.deepcopy(self.basic if kind=='basic' else self.definition);del d[field]
                    with self.assertRaisesRegex(SystemExit,'Validation failed:'):
                        self.basic_check(d) if kind=='basic' else self.definition_check(d)

    def test_encoded_principals_use_selected_local_translator(self):
        policy=copy.deepcopy(self.policy)
        for identity in policy['signature_policy']['identities']:
            identity['principal']=base64.b64encode(json.dumps(identity['principal']).encode()).decode()
        def decode(argv, **kwargs):
            self.assertEqual(argv[0], '/test-only/configtxlator')
            return SimpleNamespace(stdout=kwargs['input'])
        with patch.dict('os.environ', {'DRUNIX_CONFIGTXLATOR':'/test-only/configtxlator'}), patch.object(checks.subprocess,'run',side_effect=decode) as run:
            self.definition_check(p=policy)
            self.assertEqual(run.call_count,2)

    def test_missing_policy_fields(self):
        variants=[{}, {'signature_policy':None}, {'signature_policy':{}}, []]
        for field in ['version','identities','rule']:
            p=copy.deepcopy(self.policy);del p['signature_policy'][field];variants.append(p)
        for p in variants:
            with self.subTest(policy=p),self.assertRaisesRegex(SystemExit,'Validation failed:'):
                self.definition_check(p=p)

    def test_malformed_structures(self):
        for d in [[],None,{'chaincode_definitions':None},{'chaincode_definitions':[None]}, {'chaincode_definitions':[self.definition,self.definition]}]:
            with self.subTest(value=d),self.assertRaisesRegex(SystemExit,'Validation failed:'):
                checks.check('definition',self.baseline,[self.file('bad.json',d),self.file('policy.json',self.policy)])
        for mode,paths in [('definition',[]),('basic',[]),('readiness',[]),('info',[])]:
            with self.subTest(mode=mode),self.assertRaisesRegex(SystemExit,'Validation failed:'):
                checks.check(mode,self.baseline,paths)

    def test_channel_positive_and_malformed(self):
        good=self.baseline['Org1_channel']['observed']
        def channel_check(raw):
            p=self.file('channel.txt',raw,raw=True)
            checks.check('channels',self.baseline,[p,p])
        channel_check('Blockchain info: '+json.dumps(good))
        variants=['garbage','Blockchain info: {broken','Blockchain info: []','Blockchain info: null','Blockchain info: {}']
        for field in ['height','currentBlockHash','previousBlockHash']:
            d=copy.deepcopy(good);del d[field];variants.append('Blockchain info: '+json.dumps(d))
        for height in [True,'8',0,-1]:
            variants.append('Blockchain info: '+json.dumps({**good,'height':height}))
        for value in ['bad',None,7,base64.b64encode(b'short').decode()]:
            variants.append('Blockchain info: '+json.dumps({**good,'currentBlockHash':value}))
        for raw in variants:
            with self.subTest(raw=raw),self.assertRaisesRegex(SystemExit,'Validation failed:'):
                channel_check(raw)

    def test_load_rejects_malformed_and_duplicate_json(self):
        for value in ['{broken','{"name":"tokansh","name":"basic"}','{"height":NaN}']:
            with self.subTest(value=value),self.assertRaisesRegex(SystemExit,'Validation failed:'):
                checks.load(self.file('bad.json',value,raw=True))

    def test_no_name_is_invented_for_cli_shape_basic_definition(self):
        # The CLI-shaped all-definitions response provides the name. A named-query
        # response uses a different protobuf without Name (confirmed in CLI source).
        require_keys={'name','version','sequence','endorsement_plugin','validation_plugin','validation_parameter','collections'}
        self.assertTrue(require_keys <= self.basic.keys())
        unnamed=copy.deepcopy(self.basic);del unnamed['name']
        with self.assertRaisesRegex(SystemExit,'name'):self.basic_check(unnamed)
        with self.assertRaisesRegex(SystemExit,'name'):self.definition_check(unnamed)


if __name__=='__main__':unittest.main()
