"""Isolated demo finance tests: temporary SQLite, GET balance stub, no live network."""
import json
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import select
from app.wallet import DemoCashAccount, DemoCashEntry
from app.properties.models import ApplicationOperation
from app.dependencies import DEMO_ACTORS
from app.financing import FinancingService
from test_financing import balances, apply, action, eligible, INVESTOR, LENDER, BODY  # noqa: F401


def cash(client, kind, amount, key):
    return client.post('/api/v1/demo-wallet/'+kind, json={'amount_minor':str(amount)},
                       headers={**INVESTOR,'Idempotency-Key':key})


def balance(client):
    return client.get('/api/v1/demo-wallet',headers=INVESTOR).json()['data']['balance_minor']


def test_lender_catalogue_terms_and_authorization(client, balances):
    catalogue=client.get('/api/v1/financing/lenders',headers=INVESTOR).json()['data']
    assert [x['name'] for x in catalogue]==['Axim Bank','Real Finance','Horizon Credit']
    for change in [dict(lender_id='unknown'),dict(offer_id='real-flex'),dict(annual_rate_bps=1),dict(term_months=36),dict(ltv_percent=61)]:
        r=client.post('/api/v1/financing/applications',json={**BODY,**change},headers={**INVESTOR,'Idempotency-Key':'bad'})
        assert r.status_code==422,r.text
    loan=apply(client)
    for kind in ('assess','approve','reject','disburse'):
        assert client.post(f"/api/v1/financing/applications/{loan['id']}/{kind}",headers=INVESTOR).status_code==403
    path=f"/api/v1/financing/applications/{loan['id']}/assess"
    assert client.post(path,headers=LENDER,params={'lender_id':'real-finance'}).status_code==403
    assert client.post(path,headers=LENDER,params={'lender_id':'unknown'}).status_code==422
    assert client.get('/api/v1/financing/applications',headers=LENDER,params={'lender_id':'real-finance'}).json()['data']==[]
    loan=action(client,loan,'assess')
    assert loan['reviewer_context']['lender_id']=='axim-bank' and loan['terms_snapshot']['catalogue_version']==1
    assert action(client,loan,'reject')['state']=='REJECTED'


def test_cross_lender_reservation_race(client, balances):
    a=apply(client,'axim',quantity=2)
    b=apply(client,'real',quantity=2,lender_id='real-finance',offer_id='real-flex',annual_rate_bps=900,ltv_percent=55)
    action(client,a,'assess');action(client,b,'assess',lender_id='real-finance')
    with ThreadPoolExecutor(max_workers=2) as pool:
        tasks=[pool.submit(action,client,a,'approve'),pool.submit(action,client,b,'approve',None,'real-finance')]
        results=[t.result() for t in tasks]
    assert sorted(x['state'] for x in results)==['APPROVED','REJECTED']
    assert eligible(client)['reserved_simulated']==2


def test_duplicate_disbursement_and_atomic_repayment(client,application,balances):
    loan=apply(client);action(client,loan,'assess');action(client,loan,'approve')
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:action(client,loan,'disburse'),range(2)))
    assert results[0]==results[1] and balance(client)=='600000'
    loan=results[0]
    path=f"/api/v1/financing/applications/{loan['id']}/repay"
    assert client.post(path,headers=INVESTOR).status_code==409
    assert balance(client)=='600000'
    assert client.get('/api/v1/financing/applications',headers=INVESTOR).json()['data'][0]['state']=='DISBURSED'
    assert cash(client,'fund',60000,'interest').status_code==200
    loan=action(client,loan,'repay')
    assert action(client,loan,'repay')==loan and balance(client)=='0'
    with application.state.database.sessions() as session:
        entries=session.scalars(select(DemoCashEntry)).all()
        assert sorted(e.kind for e in entries)==['DEMO_FUNDS','DISBURSEMENT','REPAYMENT']
        assert session.get(ApplicationOperation,loan['id']).status=='FIN_REPAID'
    assert eligible(client)['reserved_simulated']==1
    action(client,loan,'release')
    assert eligible(client)['reserved_simulated']==0


def test_wallet_idempotency_and_concurrent_withdrawals(client, application):
    assert balance(client)=='0'
    assert cash(client,'fund',100,'topup').status_code==200
    assert cash(client,'fund',100,'topup').status_code==200 and balance(client)=='100'
    assert cash(client,'fund',101,'topup').status_code==409
    assert cash(client,'withdraw',100,'topup').status_code==409
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses=list(pool.map(lambda key:cash(client,'withdraw',80,key),['one','two']))
    assert sorted(r.status_code for r in responses)==[200,409] and balance(client)=='20'
    history=client.get('/api/v1/demo-wallet/activity',headers=INVESTOR).json()['data']
    assert len(history)==2 and all(e['simulated'] for e in history)
    assert client.post('/api/v1/demo-wallet/fund',headers={**LENDER,'Idempotency-Key':'bad'},json={'amount_minor':'100'}).status_code==403
    assert cash(client,'fund',9007199254740992,'overflow').status_code==422


def test_legacy_loans_not_credited_or_reassigned(client,application,balances):
    loan=apply(client);action(client,loan,'assess');action(client,loan,'approve');action(client,loan,'disburse')
    with application.state.database.sessions() as session:
        row=session.get(ApplicationOperation,loan['id'])
        legacy=json.loads(row.response_json)
        for key in ('lender_id','offer_id','terms_snapshot','reviewer_context','wallet_disbursement_entry_id'):
            legacy.pop(key,None)
        row.response_json=json.dumps(legacy)
        # Fixture emulates the previous M5 version: loan exists, cash tables empty.
        for entry in session.scalars(select(DemoCashEntry)):session.delete(entry)
        session.flush()
        session.delete(session.get(DemoCashAccount,DEMO_ACTORS['INVESTOR'].user_id));session.commit()
    assert balance(client)=='0'
    assert client.get('/api/v1/financing/applications',headers=INVESTOR).json()['data'][0]==legacy
    assert client.get('/api/v1/financing/applications',headers=LENDER).json()['data']==[]
    assert client.post(f"/api/v1/financing/applications/{loan['id']}/disburse",headers=LENDER).status_code==403
    assert balance(client)=='0' and eligible(client)['reserved_simulated']==1
    assert cash(client,'fund',660000,'legacy-repayment').status_code==200
    action(client,loan,'repay');action(client,loan,'release')
    assert balance(client)=='0'
    restarted=FinancingService(application.state.database,balances)
    assert restarted.list(DEMO_ACTORS['INVESTOR'])[0]['state']=='RELEASED'


def test_repayment_rolls_back_cash_entry_if_loan_update_fails(client,application,balances):
    from sqlalchemy import event
    loan=apply(client);action(client,loan,'assess');action(client,loan,'approve');action(client,loan,'disburse')
    cash(client,'fund',60000,'interest')
    engine=application.state.database.engine
    def fail_update(connection,cursor,statement,parameters,context,executemany):
        if statement.startswith('UPDATE application_operations'):
            raise RuntimeError('Test-only loan write failure')
    event.listen(engine,'before_cursor_execute',fail_update)
    try:
        response=client.post(f"/api/v1/financing/applications/{loan['id']}/repay",headers=INVESTOR)
        assert response.status_code==500
    finally:
        event.remove(engine,'before_cursor_execute',fail_update)
    assert balance(client)=='660000'
    with application.state.database.sessions() as session:
        assert session.get(ApplicationOperation,loan['id']).status=='FIN_DISBURSED'
        assert session.scalar(select(DemoCashEntry).where(DemoCashEntry.kind=='REPAYMENT')) is None
    action(client,loan,'repay')
    assert balance(client)=='0'


def test_additive_migration_preserves_legacy_record_and_does_not_credit(tmp_path):
    from alembic import command
    from conftest import migration_config
    from app.database import Database
    url=f"sqlite:///{tmp_path / 'legacy.db'}"
    config=migration_config(url)
    command.upgrade(config,'0002_registration')
    db=Database(url)
    legacy=dict(type='SIMULATED_FINANCING',id='legacy',state='DISBURSED',principal_minor='600000')
    with db.sessions() as session:
        session.add(ApplicationOperation(id='legacy',actor_id=DEMO_ACTORS['INVESTOR'].user_id,
            idempotency_key='legacy',request_hash='0'*64,status='FIN_DISBURSED',response_json=json.dumps(legacy),
            response_status=201,correlation_id='test',created_at='2026-01-01'))
        session.commit()
    command.upgrade(config,'head')
    assert db.ready()
    with db.sessions() as session:
        assert json.loads(session.get(ApplicationOperation,'legacy').response_json)==legacy
        assert session.scalar(select(DemoCashAccount)) is None
        assert session.scalar(select(DemoCashEntry)) is None
    db.engine.dispose()


def test_legacy_application_idempotency_is_preserved(client,application,balances):
    import hashlib
    loan=apply(client)
    with application.state.database.sessions() as session:
        row=session.get(ApplicationOperation,loan['id'])
        legacy=json.loads(row.response_json)
        for key in ('lender_id','offer_id','terms_snapshot','reviewer_context'):legacy.pop(key,None)
        row.response_json=json.dumps(legacy)
        row.request_hash=hashlib.sha256(('POST /api/v1/financing/applications\n'+json.dumps(BODY,sort_keys=True,separators=(',',':'))).encode()).hexdigest()
        session.commit()
    assert apply(client)==legacy
    response=client.post('/api/v1/financing/applications',headers={**INVESTOR,'Idempotency-Key':'finance-one'},
                         json={**BODY,'lender_id':'axim-bank','offer_id':'axim-standard'})
    assert response.status_code==409
