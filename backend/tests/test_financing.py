"""Focused financing simulation tests. Temporary SQLite, mocked balance reads only."""
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.errors import ApplicationError
from app.financing import FinancingService, FinancingRequest, quote
from app.dependencies import DEMO_ACTORS

PID='f6169750-4676-4e99-887f-2bc5471bd518'
INVESTOR={'X-Demo-Role':'INVESTOR'}
LENDER={'X-Demo-Role':'LENDER'}
BODY=dict(property_id=PID,asset_class='ANSH',quantity=1,unit_value_minor='1000000',ltv_percent=60,annual_rate_bps=1000,term_months=12)


@pytest.fixture
def balances(application):
    class ReadOnlyBalances:
        owned=2
        unavailable=False
        calls=[]
        def balance(self,property_id,holder_id,correlation):
            self.calls.append((property_id,holder_id))
            if self.unavailable:raise ApplicationError(503,'LEDGER_UNAVAILABLE','Test-only unavailable balance')
            return dict(schema_version=1,property_id=property_id,holder_id=holder_id,quantity=self.owned,source='DRUNIX_EVALUATE')
        def call(self,*args,**kwargs):
            raise AssertionError('Financing must never invoke Gateway transaction operations')
    bridge=ReadOnlyBalances();application.state.transfer_gateway=bridge
    return bridge


def apply(client,key='finance-one',**changes):
    response=client.post('/api/v1/financing/applications',json={**BODY,**changes},headers={**INVESTOR,'Idempotency-Key':key})
    assert response.status_code==201,response.text
    return response.json()['data']


def action(client,loan,kind,headers=None, lender_id='axim-bank'):
    headers = headers or (INVESTOR if kind in {'repay', 'release'} else LENDER)
    response=client.post(f"/api/v1/financing/applications/{loan['id']}/{kind}",headers=headers,json={},params={'lender_id':lender_id})
    assert response.status_code==200,response.text
    return response.json()['data']


def eligible(client):
    response=client.get('/api/v1/financing/eligibility/'+PID,headers=INVESTOR)
    assert response.status_code==200,response.text
    return response.json()['data']


def test_full_simulated_lifecycle_persistence_and_unchanged_ownership(client,application,balances):
    loan=apply(client)
    assert loan['principal_minor']=='600000' and loan['interest_minor']=='60000' and loan['repayment_minor']=='660000'
    assert loan['simulated'] and loan['on_chain_lock'] is False
    assert apply(client)==loan
    client.post('/api/v1/demo-wallet/fund',json={'amount_minor':'60000'},headers={**INVESTOR,'Idempotency-Key':'interest'})
    for kind,state in [('assess','ASSESSED'),('approve','APPROVED'),('disburse','DISBURSED'),('repay','REPAID'),('release','RELEASED')]:
        loan=action(client,loan,kind)
        assert loan['state']==state
        observation=eligible(client)
        assert observation['owned']==2 and observation['on_chain_lock'] is False
        assert observation['reserved_simulated']==(1 if state in {'APPROVED','DISBURSED','REPAID'} else 0)
    assert loan['amount_due_minor']==loan['outstanding_principal_minor']=='0' and not loan['reservation_active']
    assert [v['state'] for v in loan['timeline']]==['APPLIED','ASSESSED','APPROVED','DISBURSED','REPAID','RELEASED']
    assert all(v['simulated'] and v['timestamp'] for v in loan['timeline'])
    assert action(client,loan,'release')==loan
    restarted=FinancingService(application.state.database,balances)
    assert restarted.list(DEMO_ACTORS['INVESTOR'])[0]==loan
    assert balances.owned==2


def test_concurrent_approvals_cannot_reserve_same_units_twice(client,balances):
    loans=[apply(client,key='first',quantity=2),apply(client,key='second',quantity=2)]
    for loan in loans:action(client,loan,'assess')
    with ThreadPoolExecutor(max_workers=2) as pool:
        decisions=list(pool.map(lambda loan:action(client,loan,'approve',LENDER),loans))
    assert sorted(v['state'] for v in decisions)==['APPROVED','REJECTED']
    observation=eligible(client)
    assert observation['reserved_simulated']==2 and observation['eligible_simulated']==0
    response=client.post('/api/v1/financing/applications',json=BODY,headers={**INVESTOR,'Idempotency-Key':'overlap'})
    assert response.status_code==409


def test_holdings_rechecked_at_approval_and_unavailable_reads_fail_closed(client,balances):
    loan=apply(client);loan=action(client,loan,'assess')
    count=len(balances.calls)
    balances.unavailable=True
    response=client.post(f"/api/v1/financing/applications/{loan['id']}/approve",headers=LENDER)
    assert response.status_code==503
    assert client.get('/api/v1/financing/applications',headers=INVESTOR).json()['data'][0]['state']=='ASSESSED'
    balances.unavailable=False;balances.owned=0
    loan=action(client,loan,'approve',LENDER)
    assert len(balances.calls)>count and loan['state']=='REJECTED' and not loan['reservation_active']
    assert eligible(client)['reserved_simulated']==0


def test_repayment_ordering_and_transferable_reservation_shortfall(client,balances):
    loan=apply(client);loan=action(client,loan,'assess');loan=action(client,loan,'approve')
    response=client.post(f"/api/v1/financing/applications/{loan['id']}/release",headers=INVESTOR)
    assert response.status_code==409 and eligible(client)['reserved_simulated']==1
    balances.owned=0  # Existing DRUNIX transfer controls do not enforce our reservation.
    observation=eligible(client)
    assert observation['reservation_shortfall'] and observation['eligible_simulated']==0
    response=client.post(f"/api/v1/financing/applications/{loan['id']}/disburse",headers=LENDER)
    assert response.status_code==409 and response.json()['error']['code']=='HOLDINGS_CHANGED'
    balances.owned=2;loan=action(client,loan,'disburse',LENDER)
    assert loan['amount_due_minor']=='660000'
    response=client.post(f"/api/v1/financing/applications/{loan['id']}/repay",headers=LENDER)
    assert response.status_code==403
    client.post('/api/v1/demo-wallet/fund',json={'amount_minor':'60000'},headers={**INVESTOR,'Idempotency-Key':'interest'})
    loan=action(client,loan,'repay')
    assert action(client,loan,'repay')==loan and eligible(client)['reserved_simulated']==1


def test_reits_invalid_quantities_and_conflicting_keys_are_rejected(client,balances):
    for change in [dict(asset_class='REIT'),dict(quantity=0),dict(quantity=3),dict(ltv_percent=76)]:
        response=client.post('/api/v1/financing/applications',json={**BODY,**change},headers={**INVESTOR,'Idempotency-Key':'invalid'})
        assert response.status_code in (409,422)
    loan=apply(client)
    response=client.post('/api/v1/financing/applications',json={**BODY,'quantity':2},headers={**INVESTOR,'Idempotency-Key':'finance-one'})
    assert response.status_code==409 and response.json()['error']['code']=='IDEMPOTENCY_CONFLICT'
    assert client.get('/api/v1/financing/applications',headers={'X-Demo-Role':'ISSUER'}).status_code==403
    assert loan['state']=='APPLIED'


def test_money_uses_integer_paise_and_half_up_interest():
    value=quote(FinancingRequest(**{**BODY,'unit_value_minor':'20','ltv_percent':50,'term_months':6}))
    assert value['principal_minor']=='10' and value['interest_minor']=='1' and value['repayment_minor']=='11'
