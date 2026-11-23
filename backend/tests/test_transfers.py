"""Focused M4.2 HTTP tests; synthetic Gateway responses, temporary SQLite only."""
import hashlib
import json

import httpx
import pytest

from app.properties.models import ApplicationOperation
from app.registration import SIGNER
from app.transfers import TransferGateway

PID='f6169750-4676-4e99-887f-2bc5471bd518'
ISSUER='00000000-0000-4000-8000-000000000002'
INVESTOR='00000000-0000-4000-8000-000000000003'
RECIPIENT='00000000-0000-4000-8000-000000000005'
TX='a'*64  # Isolated test-only transaction identifier, never live evidence.


@pytest.fixture
def bridge(application):
    cfg=application.state.settings
    cfg.drunix_gateway_url='http://127.0.0.1:8001'
    cfg.tokansh_gateway_secret='01'*32;cfg.tokansh_operator_secret='02'*32
    state={'calls':[], 'prepare_error':False, 'submit_timeout':False}

    def handle(request):
        assert request.headers['Authorization']=='Bearer '+cfg.tokansh_gateway_secret
        path=request.url.path.removeprefix('/v1/tokansh/')
        state['calls'].append(path)
        if request.method=='POST':assert request.headers['X-Operator-Capability']==cfg.tokansh_operator_secret
        if path.startswith('properties/'):
            data={'property_id':PID,'issuer_id':ISSUER}
        elif path.startswith('balances/'):
            data=dict(schema_version=1,property_id=PID,holder_id=path.rsplit('/',1)[-1],quantity=10)
        elif path=='transfers/prepare':
            if state['prepare_error']:
                return httpx.Response(409,json={'error':{'code':'INSUFFICIENT_BALANCE','message':'raw test-only infrastructure detail'}})
            command=json.loads(request.content)
            data=dict(version=1,channel='mychannel',chaincode='tokansh',signer=SIGNER,function='TransferANSH',
                      command=command,request_digest=hashlib.sha256(json.dumps(command,separators=(',',':')).encode()).hexdigest(),
                      transaction_id=TX,transaction='test-only-bytes',creator='test-only-creator',mac='test-only-mac')
        elif path=='transfers/submit':
            artifact=json.loads(request.content)
            with application.state.database.sessions() as db:
                row=db.get(ApplicationOperation,artifact['command']['operation_id'])
                assert row.status=='SUBMISSION_PENDING'
                assert json.loads(row.response_json)['artifact']==artifact
            if state['submit_timeout']:raise httpx.ReadTimeout('test-only private detail')
            data=dict(state='SUBMITTED',transaction_id=TX)
        elif path=='transfers/commit-status':
            data=dict(transaction_id=TX,code=0,block_number=42,successful=True)
        else:raise AssertionError('Unreviewed Gateway route: '+path)
        return httpx.Response(200,json={'data':data})

    with httpx.Client(transport=httpx.MockTransport(handle),trust_env=False,follow_redirects=False) as http:
        application.state.transfer_gateway=TransferGateway(cfg,http)
        yield state


def headers(client,key='one-transfer',username='Aarav'):
    response=client.post('/api/v1/auth/login',json={'username':username,'password':'test-password'})
    assert response.status_code==200,response.text
    return {'Authorization':'Bearer '+response.json()['data']['access_token'],'Idempotency-Key':key}


def payload(kind='ACQUISITION'):
    return dict(asset_id=PID,from_user_id=ISSUER if kind=='ACQUISITION' else INVESTOR,
                to_user_id=INVESTOR if kind=='ACQUISITION' else RECIPIENT,quantity=4,kind=kind)


@pytest.mark.parametrize('kind',['ACQUISITION','TRANSFER'])
def test_successful_transfer_durable_commit_and_replay(client,application,bridge,kind):
    response=client.post('/api/v1/ansh/transfers',json=payload(kind),headers=headers(client))
    assert response.status_code==200,response.text
    data=response.json()['data']
    assert data['state']=='COMMITTED_VALID' and data['transaction_id']==TX and data['ownership_confirmed']
    assert data['payment']=={'simulated':True,'status':'SUCCESS'} and data['commit']['block_number']==42
    assert 'artifact' not in data and 'test-only-bytes' not in response.text
    assert '01'*32 not in response.text and '02'*32 not in response.text
    assert bridge['calls'].count('transfers/submit')==1
    calls=list(bridge['calls'])
    assert client.post('/api/v1/ansh/transfers',json=payload(kind),headers=headers(client)).json()['data']==data
    assert bridge['calls']==calls
    changed=payload(kind);changed['quantity']=5
    assert client.post('/api/v1/ansh/transfers',json=changed,headers=headers(client)).status_code==409
    assert bridge['calls']==calls
    assert client.get('/api/v1/ansh/transfers/'+data['operation_id']+'/status',headers=headers(client)).json()['data']==data
    balance=client.get(f'/api/v1/ansh/balances/{PID}/{INVESTOR}',headers=headers(client))
    assert balance.status_code==200 and balance.json()['data']['source']=='DRUNIX_EVALUATE'


def test_insufficient_balance_never_submits(client,bridge):
    bridge['prepare_error']=True  # Balance changed after the initial evaluation.
    response=client.post('/api/v1/ansh/transfers',json=payload(),headers=headers(client))
    assert response.status_code==409 and response.json()['error']['code']=='INSUFFICIENT_BALANCE'
    assert 'infrastructure' not in response.text
    assert 'transfers/submit' not in bridge['calls']
    op=response.json()['error']['details']['operation_id']
    assert client.get('/api/v1/ansh/transfers/'+op,headers=headers(client)).json()['data']['state']=='FAILED'


def test_demo_identity_required_and_failed_payment_cannot_transfer(client,application,bridge):
    aarav_headers=headers(client)
    response=client.post('/api/v1/ansh/transfers',json=payload(),headers={'Idempotency-Key':'unauthorized'})
    assert response.status_code==401 and bridge['calls']==[]
    for role in ('ADMIN','LENDER'):
        response=client.post('/api/v1/ansh/transfers',json=payload(),headers={'X-Demo-Role':role,'Idempotency-Key':'role-only'})
        assert response.status_code==401 and bridge['calls']==[]
    application.state.settings.demo_auth_enabled=False
    assert client.post('/api/v1/ansh/transfers',json=payload(),headers=aarav_headers).status_code==503
    assert bridge['calls']==[]
    application.state.settings.demo_auth_enabled=True
    command=payload();command['payment_outcome']='FAILED'
    response=client.post('/api/v1/ansh/transfers',json=command,headers=aarav_headers)
    assert response.status_code==200 and response.json()['data']['state']=='PAYMENT_FAILED'
    assert response.json()['data']['ownership_confirmed'] is False
    assert not any(path.startswith('transfers/') for path in bridge['calls'])


def test_uncertain_submission_only_reconciles_never_resubmits(client,bridge):
    bridge['submit_timeout']=True
    response=client.post('/api/v1/ansh/transfers',json=payload(),headers=headers(client))
    assert response.status_code==202 and response.json()['data']['state']=='UNKNOWN'
    op=response.json()['data']['operation_id']
    assert response.json()['data']['transaction_id']==TX
    assert client.post('/api/v1/ansh/transfers',json=payload(),headers=headers(client)).json()['data']['state']=='UNKNOWN'
    result=client.post('/api/v1/ansh/transfers/'+op+'/reconcile',headers=headers(client))
    assert result.json()['data']['state']=='COMMITTED_VALID'
    assert bridge['calls'].count('transfers/prepare')==1 and bridge['calls'].count('transfers/submit')==1


def test_actor_ownership_checks_remain_enforced(client,bridge):
    for command in (dict(payload(),to_user_id=RECIPIENT),dict(payload('TRANSFER'),from_user_id=ISSUER)):
        response=client.post('/api/v1/ansh/transfers',json=command,headers=headers(client))
        assert response.status_code==403 and bridge['calls']==[]
    created=client.post('/api/v1/ansh/transfers',json=payload(),headers=headers(client)).json()['data']
    calls=list(bridge['calls'])
    other=headers(client,username='Meera')
    assert client.get('/api/v1/ansh/transfers/'+created['operation_id']+'/status',headers=other).status_code==404
    assert client.post('/api/v1/ansh/transfers/'+created['operation_id']+'/reconcile',headers=other).status_code==404
    assert bridge['calls']==calls
