"""Synthetic offline CLI shapes only; never a deployment baseline."""
import base64
import copy

def baseline():
    definition = dict(name='basic', version='1.0', sequence=1,
        endorsement_plugin='escc', validation_plugin='vscc',
        validation_parameter=base64.b64encode(b'test-only-policy').decode(), collections={})
    result = {}
    for org in (1, 2):
        result[f'Org{org}_channel'] = {'observed': dict(height=8,
            currentBlockHash=base64.b64encode(b'a'*32).decode(),
            previousBlockHash=base64.b64encode(b'b'*32).decode())}
        result[f'Org{org}_definitions'] = {'observed': {'chaincode_definitions': [copy.deepcopy(definition)]}}
        result[f'Org{org}_basic'] = {'observed': [dict(ID=f'asset{i}', Owner='test-only',
            Color='blue', Size=i, AppraisedValue=i*100) for i in range(1,7)]}
    return result

def policy():
    return {'signature_policy': dict(version=0, identities=[
        dict(principal_classification='ROLE', principal=dict(role='PEER', msp_identifier=msp))
        for msp in ('Org1MSP','Org2MSP')],
        rule={'n_out_of': dict(n=2, rules=[{'signed_by':0},{'signed_by':1}])})}
