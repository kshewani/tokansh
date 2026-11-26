"""Private operator-only orchestration. No browser route or demo-role authorization."""
import hashlib
import hmac
import json
import re
import time
from uuid import UUID

import httpx
from sqlalchemy import CheckConstraint, String, Text, select, update
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.errors import ApplicationError
from app.properties.models import Property

STATES = ('CREATED','PREPARED','SUBMISSION_PENDING','SUBMITTED','COMMITTED_VALID','COMMITTED_INVALID','UNKNOWN')
SIGNER = 'Org1MSP:54690b215edf0e4065332b7b3bd6387dad86f6a36de54b2c49b945309abac59c'
FIELDS = ('command_version','operation_id','property_id','issuer_id','approval_reference','approval_digest','approved_supply','issue_price_minor','currency')


def fail(code='RECONCILIATION_REQUIRED'):
    return ApplicationError(409, code, 'Registration requires operator review; no automatic resubmission is performed.')


def secret(value):
    return isinstance(value,str) and re.fullmatch(r'[0-9a-fA-F]{64}',value) is not None


def validate(command):
    if not isinstance(command,dict): raise fail('INVALID_REQUEST')
    if set(command)!=set(FIELDS) or type(command['command_version']) is not int or command['command_version']!=1:
        raise fail('INVALID_REQUEST')
    for field in ('operation_id','property_id','issuer_id','approval_reference'):
        try:
            u=UUID(command[field])
            if str(u)!=command[field] or u.version not in range(1,6): raise ValueError()
        except (ValueError,TypeError,AttributeError): raise fail('INVALID_REQUEST')
    if (type(command['approved_supply']) is not int or not 1<=command['approved_supply']<=9007199254740991
        or not isinstance(command['issue_price_minor'],str) or not re.fullmatch(r'[1-9][0-9]{0,15}',command['issue_price_minor'])
        or command['currency']!='INR' or not isinstance(command['approval_digest'],str) or not re.fullmatch(r'[0-9a-f]{64}',command['approval_digest'])):
        raise fail('INVALID_REQUEST')
    return {key:command[key] for key in FIELDS}


class LedgerOperation(Base):
    __tablename__='ledger_operations'
    __table_args__=(CheckConstraint("state IN ("+','.join(repr(x) for x in STATES)+")",name='ck_ledger_operation_state'),)
    operation_id: Mapped[str]=mapped_column(String(36),primary_key=True)
    property_id: Mapped[str]=mapped_column(String(36),unique=True)
    request_digest: Mapped[str]=mapped_column(String(64))
    command_json: Mapped[str]=mapped_column(Text)
    state: Mapped[str]=mapped_column(String(32))
    artifact_json: Mapped[str|None]=mapped_column(Text)
    transaction_id: Mapped[str|None]=mapped_column(String(128))
    signer: Mapped[str|None]=mapped_column(String(128))
    channel: Mapped[str]=mapped_column(String(32),default='mychannel')
    chaincode: Mapped[str]=mapped_column(String(32),default='tokansh')
    validation_code: Mapped[str|None]=mapped_column(String(32))
    block_number: Mapped[str|None]=mapped_column(String(32))


def exact_object(pairs):
    result={}
    for key,value in pairs:
        if key in result: raise ValueError('Duplicate JSON field')
        result[key]=value
    return result


class RegistrationClient:
    def __init__(self,url,backend_secret,operator_secret,client):
        self.url=url;self.backend_secret=backend_secret;self.operator_secret=operator_secret;self.client=client

    def request(self,path,payload):
        # Validate the raw destination before constructing any credentialed request.
        # Literal addresses avoid DNS and parser-normalization ambiguities.
        match = re.fullmatch(r'http://(?:127\.0\.0\.1|\[::1\]):([0-9]{1,5})/?', self.url) if isinstance(self.url,str) else None
        if (match is None or not 1 <= int(match[1]) <= 65535
                or self.client.trust_env or self.client.follow_redirects):
            raise fail('GATEWAY_CONFIGURATION_INVALID')
        origin = self.url.rstrip('/')
        if not self.url or not secret(self.backend_secret) or not secret(self.operator_secret) or self.backend_secret==self.operator_secret:
            raise fail('AUTH_NOT_CONFIGURED')
        try:
            with self.client.stream('POST',origin+'/v1/tokansh/'+path,json=payload,follow_redirects=False,headers={
                'Authorization':'Bearer '+self.backend_secret,'X-Operator-Capability':self.operator_secret}) as response:
                body=bytearray();deadline=time.monotonic()+7
                for chunk in response.iter_bytes():
                    if time.monotonic()>deadline: raise ValueError()
                    body.extend(chunk)
                    if len(body)>2<<20: raise ValueError()
                if response.status_code!=200 or response.headers.get('content-type','').split(';')[0]!='application/json': raise ValueError()
                data=json.loads(body,object_pairs_hook=exact_object)
                if set(data)!={'data'} or not isinstance(data['data'],dict): raise ValueError()
                return data['data']
        except (httpx.HTTPError,ValueError,TypeError):
            raise fail('GATEWAY_UNAVAILABLE') from None


class RegistrationService:
    def __init__(self,database,client,operator_secret):
        self.database=database;self.client=client;self.operator_secret=operator_secret

    def authorize(self,capability):
        if not secret(self.operator_secret) or not secret(capability) or not hmac.compare_digest(bytes.fromhex(capability),bytes.fromhex(self.operator_secret)):
            raise ApplicationError(403,'INSUFFICIENT_PERMISSIONS','Independent operator authorization is required.')

    def prepare(self,command,capability):
        self.authorize(capability);command=validate(command);encoded=json.dumps(command,separators=(',',':'));digest=hashlib.sha256(encoded.encode()).hexdigest()
        with self.database.sessions() as session:
            record = session.get(Property, command['property_id'])
            if record is not None:
                try:
                    exact_value = record.proposed_supply * int(command['issue_price_minor'])
                except (TypeError, ValueError):
                    raise fail('INVALID_REQUEST') from None
                if (record.issuer_id != command['issuer_id'] or record.proposed_supply != command['approved_supply']
                        or record.issue_price_minor != int(command['issue_price_minor']) or record.valuation_minor != exact_value):
                    raise fail('INVALID_REQUEST')
        # Serialize preparations, never submissions, under a bounded SQLite write lock.
        with self.database.sessions() as session:
            session.connection().exec_driver_sql('BEGIN IMMEDIATE')
            existing=session.get(LedgerOperation,command['operation_id'])
            if existing:
                if existing.request_digest!=digest: raise fail('IDEMPOTENCY_CONFLICT')
                return existing.state
            if session.scalar(select(LedgerOperation).where(LedgerOperation.property_id==command['property_id'])): raise fail('PROPERTY_ALREADY_REGISTERED')
            session.add(LedgerOperation(operation_id=command['operation_id'],property_id=command['property_id'],request_digest=digest,command_json=encoded,state='CREATED'))
            session.commit()
        # CREATED survives preparation failure; preparation itself cannot change ledger state.
        return self.prepare_created(command['operation_id'],capability)

    def prepare_created(self,operation_id,capability):
        self.authorize(capability)
        with self.database.sessions() as session:
            session.connection().exec_driver_sql('BEGIN IMMEDIATE');row=session.get(LedgerOperation,operation_id)
            if row is None: raise fail('RESOURCE_NOT_FOUND')
            if row.state!='CREATED': return row.state
            command=json.loads(row.command_json);artifact=self.client.request('property-registrations/prepare',command)
            if (artifact.get('version')!=1 or artifact.get('command')!=command or artifact.get('request_digest')!=row.request_digest
                or artifact.get('signer')!=SIGNER or artifact.get('channel')!='mychannel' or artifact.get('chaincode')!='tokansh'
                or not isinstance(artifact.get('transaction_id'),str) or not artifact['transaction_id']
                or not all(isinstance(artifact.get(k),str) and artifact[k] for k in ('transaction','creator','mac'))): raise fail('INVALID_ARTIFACT')
            row.artifact_json=json.dumps(artifact,separators=(',',':'));row.transaction_id=artifact['transaction_id'];row.signer=SIGNER;row.state='PREPARED';session.commit()
            return row.state

    def submit(self,operation_id,capability):
        self.authorize(capability)
        with self.database.sessions() as session:
            row=session.get(LedgerOperation,operation_id)
            if row is None: raise fail('RESOURCE_NOT_FOUND')
            if row.state in ('COMMITTED_VALID','COMMITTED_INVALID'): return row.state
            artifact=self.artifact(row)
            changed=session.execute(update(LedgerOperation).where(LedgerOperation.operation_id==operation_id,LedgerOperation.state=='PREPARED').values(state='SUBMISSION_PENDING')).rowcount
            if changed!=1: raise fail()
            session.commit()  # Must complete BEFORE any submission side effect.
        try:
            result=self.client.request('property-registrations/submit',artifact)
            if result!={'state':'SUBMITTED','transaction_id':artifact['transaction_id']}: raise fail('INVALID_RESPONSE')
        except Exception:
            self.transition(operation_id,('SUBMISSION_PENDING',),'UNKNOWN');raise fail() from None
        self.transition(operation_id,('SUBMISSION_PENDING',),'SUBMITTED')
        return self.reconcile(operation_id,capability)

    def artifact(self,row):
        try:
            a=json.loads(row.artifact_json)
            if (a['transaction_id']!=row.transaction_id or a['request_digest']!=row.request_digest or a['signer']!=row.signer
                or a['channel']!=row.channel or a['chaincode']!=row.chaincode or a['command']!=json.loads(row.command_json)):
                raise ValueError()
            return a
        except (ValueError,TypeError,KeyError): raise fail('INVALID_ARTIFACT') from None

    def transition(self,operation_id,allowed,state,code=None,block=None):
        with self.database.sessions.begin() as session:
            session.execute(update(LedgerOperation).where(LedgerOperation.operation_id==operation_id,LedgerOperation.state.in_(allowed)).values(state=state,validation_code=code,block_number=block))

    def reconcile(self,operation_id,capability):
        self.authorize(capability)
        with self.database.sessions() as session:
            row=session.get(LedgerOperation,operation_id)
            if row is None: raise fail('RESOURCE_NOT_FOUND')
            if row.state in ('COMMITTED_VALID','COMMITTED_INVALID'): return row.state
            if row.state not in ('SUBMISSION_PENDING','SUBMITTED','UNKNOWN'): raise fail()
            artifact=self.artifact(row)
        try:
            result=self.client.request('commit-status',artifact)
            if (set(result)!={'transaction_id','code','block_number','successful'} or result['transaction_id']!=artifact['transaction_id']
                or type(result['code']) is not int or result['code']<0 or type(result['block_number']) is not int or result['block_number']<0
                or type(result['successful']) is not bool or result['successful']!=(result['code']==0)): raise fail('INVALID_RESPONSE')
        except Exception:
            self.transition(operation_id,('SUBMISSION_PENDING','SUBMITTED','UNKNOWN'),'UNKNOWN');raise fail() from None
        state='COMMITTED_VALID' if result['successful'] else 'COMMITTED_INVALID'
        self.transition(operation_id,('SUBMISSION_PENDING','SUBMITTED','UNKNOWN'),state,str(result['code']),str(result['block_number']))
        return state
