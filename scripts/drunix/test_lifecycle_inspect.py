"""Actual parser and isolated shell tests; every CLI is a temporary test executable."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import fixtures
import test_deployment_context as ctx

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('inspect_lifecycle',HERE/'lifecycle-inspect.py')
parser=importlib.util.module_from_spec(spec);spec.loader.exec_module(parser)
PACKAGE='tokansh_1.0:'+'a'*64


def definition(name='tokansh'):
    return dict(name=name,version='1.0',sequence=1,endorsement_plugin='escc',
        validation_plugin='vscc',validation_parameter=parser.POLICY,collections={})


def approval(package=PACKAGE):
    d=definition();del d['name']
    d['source']={'Type':{'LocalPackage':{'package_id':package}}}
    return d


class ParserTests(unittest.TestCase):
    def run_parser(self, mode, value, raw=False):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'input.json';path.write_text(value if raw else json.dumps(value))
            return subprocess.run([sys.executable,'-B',str(HERE/'lifecycle-inspect.py'),mode,str(path),PACKAGE],capture_output=True,text=True,timeout=30)

    def test_expected_and_conflicting_outcomes(self):
        for mode,value,code in [
            ('installed',{'installed_chaincodes':[]},3),
            ('installed',{'installed_chaincodes':[dict(package_id=PACKAGE,label='tokansh_1.0')]},0),
            ('installed',{'installed_chaincodes':[dict(package_id='tokansh_1.0:'+'b'*64,label='tokansh_1.0')]},4),
            ('committed',{'chaincode_definitions':[definition('basic')]},3),
            ('committed',{'chaincode_definitions':[definition()]},0),
            ('committed',{'chaincode_definitions':[{**definition(),'sequence':2}]},4),
            ('approved',approval(),0),('approved',approval('tokansh_1.0:'+'b'*64),4)]:
            with self.subTest(mode=mode,value=value):self.assertEqual(self.run_parser(mode,value).returncode,code)
        for field,value in [('version','2.0'),('sequence',2),('validation_parameter','d3Jvbmc='),
                ('endorsement_plugin','other'),('validation_plugin','other'),('init_required',True),('collections',{'config':[]})]:
            d=approval();d[field]=value
            with self.subTest(field=field):self.assertEqual(self.run_parser('approved',d).returncode,4)

    def test_malformed_and_duplicate_json_never_absent(self):
        for mode in ('installed','committed','approved'):
            for raw in ['{bad','{}','[]','null','{"x":1,"x":2}']:
                with self.subTest(mode=mode,raw=raw):self.assertEqual(self.run_parser(mode,raw,True).returncode,1)
        for mode,key,row in [('installed','installed_chaincodes',dict(package_id=PACKAGE,label='tokansh_1.0')),
                ('committed','chaincode_definitions',definition())]:
            for value in [None,{},[None],[row,row]]:
                with self.subTest(mode=mode,value=value):self.assertEqual(self.run_parser(mode,{key:value}).returncode,1)
            raw=json.dumps({key:[]})[:-1]+','+json.dumps(key)+':[]}'
            self.assertEqual(self.run_parser(mode,raw,True).returncode,1)
            for field in row:
                for replacement in ('missing',None,[],True):
                    broken=copy.deepcopy(row)
                    if replacement=='missing':del broken[field]
                    else:broken[field]=replacement
                    with self.subTest(mode=mode,field=field,value=replacement):
                        self.assertEqual(self.run_parser(mode,{key:[broken]}).returncode,1)
        for field in approval():
            d=approval();del d[field]
            self.assertEqual(self.run_parser('approved',d).returncode,1)
        for source in [{},{'Type':None},{'Type':{'Unavailable':{}}},{'local_package':{'package_id':PACKAGE}}]:
            self.assertEqual(self.run_parser('approved',{**approval(),'source':source}).returncode,1)


FAKE_PEER = '''#!/usr/bin/python3
import json,os,sys
from pathlib import Path
args=sys.argv[1:];state=json.loads(Path(os.environ['TEST_STATE']).read_text());log=Path(os.environ['TEST_LOG'])
with log.open('a') as f:f.write(' '.join(args)+'\\n')
if 'calculatepackageid' in args:print(state['package_id'])
elif 'queryinstalled' in args:
    if state.get('query_failure'):sys.exit(9)
    previous=log.read_text()
    print(state['installed'] if 'chaincode install ' not in previous else state['installed_after'])
elif 'queryapproved' in args:
    if state.get('approval_failure'):
        print(state['approval_failure'],file=sys.stderr);sys.exit(1)
    print(state['approved'])
elif 'checkcommitreadiness' in args:print('{"approvals":{"Org1MSP":true,"Org2MSP":true}}')
elif 'getinfo' in args:print('Blockchain info: '+json.dumps(state['channel']))
elif 'querycommitted' in args:
    count=log.read_text().count('querycommitted')
    print(state.get('final_committed',state['committed']) if count>2 else state['committed'])
elif 'query' in args:print(state['assets'])
elif any(x in args for x in ('install','approveformyorg','commit')):sys.exit(state.get('mutation_exit',0))
else:sys.exit(99)
'''


class ShellTests(unittest.TestCase):
    def setUp(self):
        self.context=ctx.ContextTests('runTest');self.context.setUp();self.addCleanup(self.context.doCleanups)
        self.root=Path(self.context.tmp.name);m=self.context.m
        self.network=Path(m['network_root']);b=self.network/'build/bin';b.mkdir(parents=True)
        (b/'peer').write_text(FAKE_PEER);(b/'peer').chmod(0o700)
        (b/'configtxlator').write_text('#!/bin/sh\nexit 99\n');(b/'configtxlator').chmod(0o700)
        shim=self.root/'shim';shim.mkdir();(shim/'openssl').write_text('#!/bin/sh\nexit 0\n');(shim/'openssl').chmod(0o700)
        net=self.network/'drunix-network/test-network/organizations'
        for org in (1,2):
            (net/f'peerOrganizations/org{org}.example.com/users/Admin@org{org}.example.com/msp').mkdir(parents=True)
            ca=net/f'peerOrganizations/org{org}.example.com/peers/peer0.org{org}.example.com/tls/ca.crt'
            ca.parent.mkdir(parents=True);ca.write_text('test-only')
        ca=net/'ordererOrganizations/example.com/orderers/orderer.example.com/tls/ca.crt'
        ca.parent.mkdir(parents=True);ca.write_text('test-only')
        self.context.run_context()
        self.env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1','PATH':str(shim)+os.pathsep+os.environ['PATH'],
            'TOKANSH_DEPLOYMENT_MANIFEST':str(self.context.manifest),
            'TOKANSH_DEPLOYMENT_MANIFEST_SHA256':ctx.context.sha(self.context.manifest),
            'TOKANSH_DEPLOYMENT_ID':m['deployment_id'], 'TEST_STATE':str(self.root/'state.json'), 'TEST_LOG':str(self.root/'calls.txt')}
        row=dict(package_id=m['package_id'],label='tokansh_1.0')
        baseline=fixtures.baseline()
        self.state=dict(package_id=m['package_id'],installed=json.dumps({'installed_chaincodes':[row]}),
            installed_after=json.dumps({'installed_chaincodes':[row]}),approved=json.dumps(approval(m['package_id'])),
            committed=json.dumps(baseline['Org1_definitions']['observed']),
            channel=baseline['Org1_channel']['observed'],assets=json.dumps(baseline['Org1_basic']['observed']))

    def run_phase(self,phase,extra=None):
        Path(self.env['TEST_STATE']).write_text(json.dumps(self.state))
        log=Path(self.env['TEST_LOG']);log.unlink(missing_ok=True)
        args=['bash',str(HERE/'deployment-proposed.sh'),phase,'--authorize-'+phase]
        if phase in ('install','approve'):args+=['1']
        if extra:args+=extra
        result=subprocess.run(args,env=self.env,capture_output=True,text=True,timeout=45)
        calls=log.read_text().splitlines() if log.exists() else []
        mutations=[c for c in calls if any('chaincode '+x+' ' in c for x in ('install','approveformyorg','commit'))]
        return result,mutations,calls

    def test_install_present_absent_malformed_conflicting_and_failed_mutation(self):
        for value,expected,mutations in [(self.state['installed'],0,0),
                ('{"installed_chaincodes":[]}',0,1),('{}',1,0),('{bad',1,0),
                (json.dumps({'installed_chaincodes':[dict(package_id='tokansh_1.0:'+'c'*64,label='tokansh_1.0')]}),4,0)]:
            self.state['installed']=value
            r,m,_=self.run_phase('install')
            with self.subTest(value=value):self.assertEqual((r.returncode,len(m)),(expected,mutations))
        self.state.update(installed='{"installed_chaincodes":[]}',mutation_exit=9)
        r,m,_=self.run_phase('install');self.assertEqual((r.returncode,len(m)),(9,1))
        self.state['query_failure']=True
        r,m,_=self.run_phase('install');self.assertNotEqual(r.returncode,0);self.assertEqual(m,[])

    def test_approval_matching_conflicting_missing_and_ambiguous_stop(self):
        r,m,_=self.run_phase('approve');self.assertEqual((r.returncode,m),(0,[]))
        for value in ['{}','{bad',json.dumps(approval('tokansh_1.0:'+'c'*64))]:
            self.state['approved']=value;r,m,_=self.run_phase('approve')
            self.assertNotEqual(r.returncode,0);self.assertEqual(m,[])
        for error in ["query failed with status: 500 - failed to invoke backing implementation of 'QueryApprovedChaincodeDefinition': could not fetch approved chaincode definition (name: 'tokansh', sequence: '1') on channel 'mychannel'",'connection unavailable','deadline exceeded']:
            self.state['approval_failure']=error;r,m,_=self.run_phase('approve')
            self.assertNotEqual(r.returncode,0);self.assertEqual(m,[])

    def test_commit_absent_matching_conflicting_and_malformed(self):
        basic=fixtures.baseline()['Org1_definitions']['observed']['chaincode_definitions'][0]
        for rows,expected,count in [([basic],0,1),([basic,definition()],4,0),
                ([basic,{**definition(),'sequence':2}],4,0),([basic,definition(),definition()],1,0)]:
            self.state['committed']=json.dumps({'chaincode_definitions':rows})
            r,m,calls=self.run_phase('commit')
            with self.subTest(rows=rows):self.assertEqual((r.returncode,len(m)),(expected,count))
            self.assertFalse(any('queryapproved' in c or 'approveformyorg' in c for c in calls))
        for value in ['{}','{bad','{"chaincode_definitions":null}']:
            self.state['committed']=value;r,m,_=self.run_phase('commit')
            self.assertNotEqual(r.returncode,0);self.assertEqual(m,[])
        self.state.update(committed=json.dumps({'chaincode_definitions':[basic]}),mutation_exit=9)
        r,m,_=self.run_phase('commit');self.assertEqual((r.returncode,len(m)),(9,1))

    def test_final_commit_guard_rejects_malformed_after_preservation_passes(self):
        for value in ['{}','{bad','{"chaincode_definitions":[],"chaincode_definitions":[]}']:
            self.state['final_committed']=value
            r,m,calls=self.run_phase('commit')
            self.assertEqual(r.returncode,1);self.assertEqual(m,[])
            self.assertGreaterEqual(sum('querycommitted' in c for c in calls),3)

    def test_missing_authorization_never_contacts_peer(self):
        Path(self.env['TEST_STATE']).write_text(json.dumps(self.state))
        for args in [['install'],['commit','--authorize-approve'],['all','--authorize-all']]:
            log=Path(self.env['TEST_LOG']);log.unlink(missing_ok=True)
            r=subprocess.run(['bash',str(HERE/'deployment-proposed.sh')]+args,env=self.env,capture_output=True,text=True,timeout=30)
            self.assertNotEqual(r.returncode,0);self.assertFalse(log.exists())

    def test_extra_phase_arguments_never_contact_peer(self):
        r,m,calls=self.run_phase('install',['approve','--authorize-approve','1'])
        self.assertEqual((r.returncode,m,calls),(2,[],[]))


if __name__=='__main__':unittest.main()
