"""Isolated transaction lifecycle tests. Never call DRUNIX."""
import json
from concurrent.futures import ThreadPoolExecutor
import pytest
from app.registration import RegistrationService, LedgerOperation
SIGNER = 'Org1MSP:test-only-signer'
from app.errors import ApplicationError

CAP='02'*32
COMMAND=dict(command_version=1,operation_id='10000000-0000-4000-8000-000000000001',property_id='20000000-0000-4000-8000-000000000001',issuer_id='30000000-0000-4000-8000-000000000001',approval_reference='40000000-0000-4000-8000-000000000001',approval_digest='a'*64,approved_supply=100000,issue_price_minor='1000000',currency='INR')
class MockGateway:
    def __init__(self): self.calls=[];self.failure=None;self.valid=True;self.database=None
    def request(self,path,payload):
        self.calls.append(path)
        if path==self.failure: raise RuntimeError('test-only secret')
        if path.endswith('/prepare'):
            import hashlib
            return dict(version=1,channel='mychannel',chaincode='tokansh',signer=SIGNER,command=payload,request_digest=hashlib.sha256(json.dumps(payload,separators=(',',':')).encode()).hexdigest(),transaction_id='test-only-tx',transaction='test-only-bytes',creator='test-only-creator',mac='test-only-mac')
        if path.endswith('/submit'):
            with self.database.sessions() as s:
                row=s.get(LedgerOperation,COMMAND['operation_id'])
                assert row.state=='SUBMISSION_PENDING' and row.artifact_json and row.transaction_id
            return dict(state='SUBMITTED',transaction_id='test-only-tx')
        return dict(transaction_id='test-only-tx',code=0 if self.valid else 11,successful=self.valid,block_number=4)

def service(application):
    gateway=MockGateway();gateway.database=application.state.database
    return RegistrationService(gateway.database,gateway,CAP),gateway

def test_durable_restart_and_valid_commit(application):
    s,g=service(application);assert s.prepare(COMMAND,CAP)=='PREPARED'
    restarted=RegistrationService(g.database,g,CAP)
    assert restarted.submit(COMMAND['operation_id'],CAP)=='COMMITTED_VALID'
    assert restarted.reconcile(COMMAND['operation_id'],CAP)=='COMMITTED_VALID'
    assert g.calls.count('property-registrations/submit')==1
    with g.database.sessions() as db:
        row=db.get(LedgerOperation,COMMAND['operation_id']);assert row.validation_code=='0' and row.block_number=='4'

@pytest.mark.parametrize('where',['property-registrations/submit','commit-status'])
def test_ambiguous_failures_are_status_only_after_restart(application,where):
    s,g=service(application);s.prepare(COMMAND,CAP);g.failure=where
    with pytest.raises(ApplicationError):s.submit(COMMAND['operation_id'],CAP)
    with pytest.raises(ApplicationError):s.submit(COMMAND['operation_id'],CAP)
    g.failure=None
    assert RegistrationService(g.database,g,CAP).reconcile(COMMAND['operation_id'],CAP)=='COMMITTED_VALID'
    assert g.calls.count('property-registrations/submit')==1

def test_preparation_failure_persists_created_without_submission(application):
    s,g=service(application);g.failure='property-registrations/prepare'
    with pytest.raises(RuntimeError):s.prepare(COMMAND,CAP)
    with g.database.sessions() as db:assert db.get(LedgerOperation,COMMAND['operation_id']).state=='CREATED'
    g.failure=None;assert s.prepare_created(COMMAND['operation_id'],CAP)=='PREPARED'
    assert 'property-registrations/submit' not in g.calls

def test_idempotency_conflict_authorization_and_corruption(application):
    s,g=service(application)
    with pytest.raises(ApplicationError):s.prepare(COMMAND,'X-Demo-Role: ADMIN')
    assert not g.calls
    assert s.prepare(COMMAND,CAP)==s.prepare(COMMAND,CAP)=='PREPARED'
    with pytest.raises(ApplicationError):s.prepare({**COMMAND,'approved_supply':1},CAP)
    with g.database.sessions.begin() as db:db.get(LedgerOperation,COMMAND['operation_id']).artifact_json='{}'
    with pytest.raises(ApplicationError):s.submit(COMMAND['operation_id'],CAP)
    assert 'property-registrations/submit' not in g.calls

def test_invalid_commit_never_reports_success(application):
    s,g=service(application);s.prepare(COMMAND,CAP);g.valid=False
    assert s.submit(COMMAND['operation_id'],CAP)=='COMMITTED_INVALID'

def test_concurrent_submit_only_one_effect(application):
    s,g=service(application);s.prepare(COMMAND,CAP)
    def attempt(_):
        try:return s.submit(COMMAND['operation_id'],CAP)
        except ApplicationError:return 'BLOCKED'
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(attempt,range(2)))
    assert results.count('COMMITTED_VALID')>=1
    assert g.calls.count('property-registrations/submit')==1

def test_pending_crash_reconciles_without_submit(application):
    s,g=service(application);s.prepare(COMMAND,CAP);s.transition(COMMAND['operation_id'],('PREPARED',),'SUBMISSION_PENDING')
    assert s.reconcile(COMMAND['operation_id'],CAP)=='COMMITTED_VALID'
    assert 'property-registrations/submit' not in g.calls

@pytest.mark.parametrize('kind',['connection','timeout','malformed','auth','duplicate'])
def test_private_http_client_sanitizes_failures(kind):
    import httpx
    from app.registration import RegistrationClient
    def upstream(request):
        assert request.headers['Authorization']=='Bearer '+'01'*32
        if kind=='connection':raise httpx.ConnectError('secret detail')
        if kind=='timeout':raise httpx.ReadTimeout('secret detail')
        if kind=='duplicate':return httpx.Response(200,text='{"data":{},"data":{}}',headers={'content-type':'application/json'})
        if kind=='auth':return httpx.Response(403,json={'error':'secret detail'})
        return httpx.Response(200,text='not-json',headers={'content-type':'application/json'})
    with httpx.Client(transport=httpx.MockTransport(upstream),trust_env=False,follow_redirects=False) as http:
        client=RegistrationClient('http://127.0.0.1:8001','01'*32,CAP,http)
        with pytest.raises(ApplicationError) as error:client.request('commit-status',{})
        assert 'secret detail' not in error.value.message


def test_no_public_write_route_or_demo_authorization(application):
    from fastapi.testclient import TestClient
    with TestClient(application) as http:
        assert http.post('/api/v1/registrations',headers={'X-Demo-Role':'ADMIN'},json=COMMAND).status_code==404
    s,g=service(application)
    with pytest.raises(ApplicationError):s.prepare(COMMAND,'ADMIN')
    assert not g.calls

@pytest.mark.parametrize('change',[{'successful':True,'code':11},{'transaction_id':'wrong'},{'block_number':-1},{'code':False}])
def test_inconsistent_commit_observation_never_reports_success(application,change):
    s,g=service(application);s.prepare(COMMAND,CAP);original=g.request
    def request(path,payload):
        result=original(path,payload)
        return {**result,**change} if path=='commit-status' else result
    g.request=request
    with pytest.raises(ApplicationError):s.submit(COMMAND['operation_id'],CAP)
    with g.database.sessions() as db:assert db.get(LedgerOperation,COMMAND['operation_id']).state=='UNKNOWN'


def test_recovery_uses_reopened_database(application):
    from app.database import Database
    s,g=service(application);s.prepare(COMMAND,CAP)
    url=str(application.state.database.engine.url)
    reopened=Database(url)
    try:
        g.database=reopened
        restarted=RegistrationService(reopened,g,CAP)
        assert restarted.submit(COMMAND['operation_id'],CAP)=='COMMITTED_VALID'
        assert restarted.submit(COMMAND['operation_id'],CAP)=='COMMITTED_VALID'
        assert g.calls.count('property-registrations/submit')==1
    finally:reopened.engine.dispose()


@pytest.mark.parametrize('url',[
    'http://example.com:8001','http://localhost:8001','http://192.168.1.1:8001',
    'http://127.0.0.1.evil:8001','http://127.1:8001','http://[::ffff:127.0.0.1]:8001',
    'https://127.0.0.1:8001','http://127.0.0.1','http://[::1]',
    'http://127.0.0.1:0','http://127.0.0.1:65536','http://127.0.0.1:bad',
    'http://user:password@127.0.0.1:8001','http://127.0.0.1:8001/prefix',
    'http://127.0.0.1:8001/?','http://127.0.0.1:8001/#',
    'http://127.0.0.1:8001?token=value','http://127.0.0.1:8001#fragment',
    ' http://127.0.0.1:8001','http://127.0.0.1:8001\n',
    'http://127.0.0.1:8001\\@example.com',None,
])
def test_registration_destination_rejected_before_transport(url):
    import httpx
    from app.registration import RegistrationClient
    calls=[]
    def transport(request):
        calls.append(request)
        raise AssertionError('Credentials must not reach transport')
    with httpx.Client(transport=httpx.MockTransport(transport),trust_env=False) as http:
        client=RegistrationClient(url,'01'*32,CAP,http)
        with pytest.raises(ApplicationError) as error:client.request('commit-status',{})
    assert error.value.code=='GATEWAY_CONFIGURATION_INVALID'
    assert 'password' not in error.value.message and 'value' not in error.value.message
    assert not calls


@pytest.mark.parametrize('url',['http://127.0.0.1:8001','http://127.0.0.1:8001/','http://[::1]:8001','http://[::1]:8001/'])
def test_literal_loopback_destination_allowed(url,monkeypatch):
    import httpx
    from app.registration import RegistrationClient
    monkeypatch.setenv('HTTP_PROXY','http://untrusted-proxy.invalid:9999')
    monkeypatch.setenv('ALL_PROXY','http://untrusted-proxy.invalid:9999')
    calls=[]
    def transport(request):
        calls.append(request)
        assert request.headers['Authorization']=='Bearer '+'01'*32
        assert request.headers['X-Operator-Capability']==CAP
        return httpx.Response(200,json={'data':{'state':'test-only'}})
    with httpx.Client(transport=httpx.MockTransport(transport),trust_env=False,follow_redirects=False) as http:
        assert RegistrationClient(url,'01'*32,CAP,http).request('commit-status',{})=={'state':'test-only'}
    assert len(calls)==1 and calls[0].url.host in ('127.0.0.1','::1')
    assert calls[0].url.path=='/v1/tokansh/commit-status'


@pytest.mark.parametrize('trust_env,redirects',[(True,False),(False,True)])
def test_unsafe_injected_client_fails_before_transport(trust_env,redirects):
    import httpx
    from app.registration import RegistrationClient
    calls=[]
    with httpx.Client(transport=httpx.MockTransport(lambda r:calls.append(r)),trust_env=trust_env,follow_redirects=redirects) as http:
        with pytest.raises(ApplicationError):RegistrationClient('http://127.0.0.1:8001','01'*32,CAP,http).request('commit-status',{})
    assert not calls


def test_redirect_response_is_not_followed():
    import httpx
    from app.registration import RegistrationClient
    calls=[]
    def transport(request):
        calls.append(request)
        return httpx.Response(307,headers={'Location':'http://remote.invalid:8001'})
    with httpx.Client(transport=httpx.MockTransport(transport),trust_env=False,follow_redirects=False) as http:
        with pytest.raises(ApplicationError):RegistrationClient('http://127.0.0.1:8001','01'*32,CAP,http).request('commit-status',{})
    assert len(calls)==1


def test_concurrent_preparation_serializes_remote_call(application):
    from threading import Event
    entered=Event();release=Event();second=Event()
    s,g=service(application);original=g.request
    def request(path,payload):
        if path.endswith('/prepare'):
            entered.set()
            assert release.wait(5)
        return original(path,payload)
    g.request=request
    def competing():
        second.set()
        return s.prepare_created(COMMAND['operation_id'],CAP)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first=pool.submit(s.prepare,COMMAND,CAP)
        try:
            assert entered.wait(5)
            following=pool.submit(competing)
            assert second.wait(5)
        finally:release.set()
        assert first.result(timeout=10)==following.result(timeout=10)=='PREPARED'
    assert g.calls==['property-registrations/prepare']


def test_process_exit_during_preparation_preserves_created(application):
    import subprocess
    import sys
    s,g=service(application);g.failure='property-registrations/prepare'
    with pytest.raises(RuntimeError):s.prepare(COMMAND,CAP)
    script='''
import os,sys
from app.database import Database
from app.registration import RegistrationService
class ExitDuringPrepare:
    def request(self,path,payload):
        assert path=='property-registrations/prepare'
        os._exit(23)
database=Database(sys.argv[1])
RegistrationService(database,ExitDuringPrepare(),'02'*32).prepare_created(sys.argv[2],'02'*32)
'''
    result=subprocess.run([sys.executable,'-c',script,str(g.database.engine.url),COMMAND['operation_id']],capture_output=True,timeout=15)
    assert result.returncode==23
    with g.database.sessions() as db:
        row=db.get(LedgerOperation,COMMAND['operation_id'])
        assert row.state=='CREATED' and row.artifact_json is None and row.transaction_id is None
    with pytest.raises(ApplicationError):s.submit(COMMAND['operation_id'],CAP)
    g.failure=None
    assert s.prepare_created(COMMAND['operation_id'],CAP)=='PREPARED'
    assert 'property-registrations/submit' not in g.calls
