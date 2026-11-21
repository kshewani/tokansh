"""Offline JSON assertions for the phase-gated deployment script; no network calls."""
import os
import base64
import subprocess
import json
import sys
from pathlib import Path


def require(ok, message):
    if not ok:
        raise SystemExit('Validation failed: '+message)


def exact_object(pairs):
    result={}
    for key,value in pairs:
        require(key not in result, 'Duplicate JSON field: '+key)
        result[key]=value
    return result


def parse_json(value):
    return json.loads(value,object_pairs_hook=exact_object,
                      parse_constant=lambda _: require(False, 'Non-finite JSON number'))


def load(path):
    try:
        return parse_json(Path(path).read_text())
    except (OSError,ValueError,TypeError,UnicodeError):
        raise SystemExit('Validation failed: unreadable or malformed JSON input') from None


def channel(value):
    require(isinstance(value,dict) and set(value)=={'height','currentBlockHash','previousBlockHash'}, 'Incomplete channel data')
    require(type(value['height']) is int and value['height']>0, 'Invalid channel height')
    for key in ('currentBlockHash','previousBlockHash'):
        require(isinstance(value[key],str) and len(base64.b64decode(value[key],validate=True))==32, 'Invalid channel block hash')
    return value


def named_definition(value,name):
    require(isinstance(value,dict), 'Expected definition object')
    if 'chaincode_definitions' in value:
        definitions=value['chaincode_definitions']
        require(isinstance(definitions,list), 'Expected definitions list')
        require(all(isinstance(d,dict) and isinstance(d.get('name'),str) and d['name'] for d in definitions), 'Every definition requires an explicit name')
        matches=[d for d in definitions if d['name']==name]
        require(len(matches)==1, 'Expected exactly one named '+name+' definition')
        value=matches[0]
    require(value.get('name')==name, 'Missing or incorrect '+name+' chaincode name')
    required={'name','version','sequence','endorsement_plugin','validation_plugin','validation_parameter','collections'}
    require(required<=value.keys(), 'Incomplete '+name+' definition')
    require(isinstance(value['version'],str) and bool(value['version']) and type(value['sequence']) is int and value['sequence']>0, 'Invalid definition version/sequence')
    require(all(isinstance(value[k],str) and value[k] for k in ('endorsement_plugin','validation_plugin','validation_parameter')), 'Missing endorsement/validation fields')
    require(bool(base64.b64decode(value['validation_parameter'],validate=True)), 'Empty validation parameter')
    require(isinstance(value['collections'],dict), 'Invalid collections')
    if 'init_required' in value: require(type(value['init_required']) is bool,'Invalid init requirement')
    return value


def _check(mode, baseline, paths):
    require(isinstance(baseline,dict), "Expected baseline object")
    if mode == 'channels':
        values=[channel(parse_json(Path(p).read_text().split('Blockchain info: ',1)[1])) for p in paths]
        require(len(values)==2 and values[0]==values[1], 'Committing peers disagree on channel state')
        initial=channel(baseline['Org1_channel']['observed'])
        require(values[0]['height']>=initial['height'], 'Channel height regressed')
        if values[0]['height']==initial['height']:
            require(values[0]==initial, 'Channel hashes changed at the baseline height')
        print('Channel agreement verified; height:',values[0]['height'])
    elif mode == 'basic':
        org,path,assets=paths
        require(org in ('1','2'), 'Invalid organization')
        expected=named_definition(baseline['Org'+org+'_definitions']['observed'],'basic')
        actual=named_definition(load(path),'basic')
        for key,value in expected.items():
            require(actual.get(key)==value, 'basic definition mismatch: '+key)
        require(actual.get('init_required',False) is False, 'basic init requirement changed')
        found=load(assets);original=baseline['Org'+org+'_basic']['observed']
        require(isinstance(found,list) and len(found)==6, 'Expected six basic assets')
        require(sorted(found,key=lambda a:a['ID'])==sorted(original,key=lambda a:a['ID']), 'basic asset payload changed')
    elif mode == 'readiness':
        approvals=load(paths[0])['approvals']
        require(approvals.get('Org1MSP') is True and approvals.get('Org2MSP') is True, 'Both organizations must approve')
    elif mode == 'definition':
        definition,policy=map(load,paths)
        definition=named_definition(definition,'tokansh')
        require(isinstance(policy,dict) and isinstance(policy.get('signature_policy'),dict),'Missing signature policy')
        require(definition['version']=='1.0' and definition['sequence']==1, 'tokansh version/sequence mismatch')
        require(definition.get('init_required',False) is False, 'tokansh unexpectedly requires init')
        require(definition['endorsement_plugin']=='escc' and definition['validation_plugin']=='vscc', 'Plugin mismatch')
        require(not definition.get('collections'), 'Unexpected private-data collections')
        signature=policy.get('signature_policy',{})
        require(type(signature.get('version')) is int and signature['version']==0, 'Signature policy version mismatch')
        identities=signature.get('identities',[])
        require(isinstance(identities,list) and len(identities)==2, 'Expected exactly two endorsement principals')
        principals=[]
        for identity in identities:
            require(identity['principal_classification']=='ROLE','Expected MSP role')
            principal=identity['principal']
            if isinstance(principal,str):
                decoded=subprocess.run([os.environ['DRUNIX_CONFIGTXLATOR'],'proto_decode','--type','common.MSPRole','--input','/dev/stdin','--output','/dev/stdout'],input=base64.b64decode(principal,validate=True),capture_output=True,check=True)
                principal=json.loads(decoded.stdout)
            require(isinstance(principal,dict) and principal['role']=='PEER','Expected peer role')
            principals.append(principal['msp_identifier'])
        require(set(principals)=={'Org1MSP','Org2MSP'}, 'Wrong endorsement organizations')
        rule=signature.get('rule',{}).get('n_out_of',{})
        require(type(rule.get('n')) is int and rule['n']==2 and isinstance(rule.get('rules'),list) and len(rule['rules'])==2,'Expected AND endorsement rule')
        require(all(isinstance(r,dict) and type(r.get('signed_by')) is int for r in rule['rules']) and sorted(r['signed_by'] for r in rule['rules'])==[0,1], 'Expected both distinct signatures')
    elif mode == 'info':
        info=load(paths[0])
        require(info['contract']=='tokansh' and type(info['schema_version']) is int and info['schema_version']==1,'Contract info mismatch')
        require(info['functions']==['GetContractInfo','GetRegisteredProperty','GetOperation','RegisterApprovedProperty'],'Function list mismatch')
        require(info['supply_interpretation']=='LIFETIME_CUMULATIVE_ISSUANCE_CEILING','Supply interpretation mismatch')
    else:
        raise SystemExit('Unknown validation mode')


def check(mode, baseline, paths):
    try:
        _check(mode,baseline,paths)
    except (KeyError,TypeError,ValueError,IndexError,AttributeError,StopIteration,OSError,subprocess.SubprocessError):
        raise SystemExit('Validation failed: malformed or incomplete '+str(mode)+' input') from None


if __name__=='__main__':
    require(len(sys.argv)>=3, 'Usage: MODE BASELINE INPUT...')
    check(sys.argv[1],load(sys.argv[2]),sys.argv[3:])
