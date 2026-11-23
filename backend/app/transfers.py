"""Local supervised transfers; SQLite tracks workflow, DRUNIX owns balances."""
import hashlib
import hmac
import json
import re
import time
from datetime import datetime, timezone
from typing import Annotated, Literal
from uuid import UUID, uuid4

import httpx
from fastapi import APIRouter, Depends, Header, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.dependencies import DemoActor, demo_actor, get_session
from app.errors import ApplicationError, success
from app.properties.models import ApplicationOperation
from app.registration import SIGNER, exact_object, secret

UUID_PATTERN = r'^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
Identifier = Annotated[str, Field(pattern=UUID_PATTERN)]
MAX_QUANTITY = 9007199254740991


class TransferRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    asset_id: Identifier  # Registered property UUID, not a separate token ID.
    from_user_id: Identifier
    to_user_id: Identifier
    quantity: Annotated[int, Field(ge=1, le=MAX_QUANTITY)]
    kind: Literal['ACQUISITION', 'TRANSFER'] = 'TRANSFER'
    payment_outcome: Literal['SUCCESS', 'FAILED'] = 'SUCCESS'


class TransferGateway:
    """Same private HTTP boundary as RegistrationClient; no redirects/proxies."""
    def __init__(self, settings, client):
        self.settings, self.client = settings, client

    def call(self, method, path, correlation_id, payload=None):
        cfg = self.settings
        match = re.fullmatch(r'http://(?:127\.0\.0\.1|\[::1\]):([0-9]{1,5})/?', cfg.drunix_gateway_url or '')
        if (match is None or not 1 <= int(match[1]) <= 65535 or self.client.trust_env or self.client.follow_redirects
                or not secret(cfg.tokansh_gateway_secret) or not secret(cfg.tokansh_operator_secret)
                or hmac.compare_digest(bytes.fromhex(cfg.tokansh_gateway_secret), bytes.fromhex(cfg.tokansh_operator_secret))):
            raise ApplicationError(503, 'GATEWAY_CONFIGURATION_INVALID', 'Configure the private loopback Gateway and distinct credentials.')
        headers = {'Authorization': 'Bearer '+cfg.tokansh_gateway_secret, 'X-Correlation-ID': correlation_id}
        if method == 'POST':
            headers['X-Operator-Capability'] = cfg.tokansh_operator_secret
        try:
            with self.client.stream(method, cfg.drunix_gateway_url.rstrip('/')+'/v1/tokansh/'+path,
                                    headers=headers, json=payload, follow_redirects=False) as response:
                body = bytearray(); deadline = time.monotonic()+cfg.drunix_gateway_timeout_seconds
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > 2 << 20 or time.monotonic() > deadline:
                        raise ValueError()
                if response.headers.get('content-type', '').split(';')[0] != 'application/json':
                    raise ValueError()
                frame = json.loads(body, object_pairs_hook=exact_object)
                if response.status_code != 200:
                    known = {
                        (409, 'INSUFFICIENT_BALANCE'): 'Sender has insufficient ANSH.',
                        (409, 'IDEMPOTENCY_CONFLICT'): 'The ledger operation conflicts with an existing operation.',
                        (404, 'PROPERTY_NOT_FOUND'): 'Registered property was not found.',
                        (504, 'LEDGER_TIMEOUT'): 'DRUNIX did not respond within its deadline.',
                        (503, 'LEDGER_UNAVAILABLE'): 'DRUNIX is unavailable.',
                    }
                    if (isinstance(frame, dict) and set(frame) == {'error'} and isinstance(frame['error'], dict)
                            and set(frame['error']) == {'code', 'message'} and isinstance(frame['error']['message'], str)):
                        key = (response.status_code, frame['error']['code'])
                        if key in known:
                            raise ApplicationError(key[0], key[1], known[key])
                    raise ValueError()
                if not isinstance(frame, dict) or set(frame) != {'data'} or not isinstance(frame['data'], dict):
                    raise ValueError()
                return frame['data']
        except httpx.TimeoutException:
            raise ApplicationError(504, 'GATEWAY_TIMEOUT', 'The Gateway timed out; do not resubmit a pending transaction.') from None
        except httpx.HTTPError:
            raise ApplicationError(503, 'GATEWAY_UNAVAILABLE', 'The private Gateway is unavailable.') from None
        except (ValueError, TypeError, KeyError):
            raise ApplicationError(502, 'GATEWAY_BAD_RESPONSE', 'The Gateway returned an unsupported response.') from None

    def balance(self, property_id, holder_id, correlation_id):
        data = self.call('GET', f'balances/{property_id}/{holder_id}', correlation_id)
        if (set(data) != {'schema_version', 'property_id', 'holder_id', 'quantity'}
                or type(data['schema_version']) is not int or data['schema_version'] != 1
                or data['property_id'] != property_id or data['holder_id'] != holder_id
                or type(data['quantity']) is not int or not 0 <= data['quantity'] <= MAX_QUANTITY):
            raise ApplicationError(502, 'GATEWAY_BAD_RESPONSE', 'The Gateway returned an invalid balance.')
        return dict(data, source='DRUNIX_EVALUATE')


def transfer_actor(request: Request, actor: Annotated[DemoActor, Depends(demo_actor)]):
    # Controlled local demo: the backend, not the browser, holds Gateway credentials.
    if request.app.state.settings.app_env == 'production':
        raise ApplicationError(503, 'AUTH_NOT_CONFIGURED', 'Demo transfers are local-only.')
    if actor.role not in {'ISSUER', 'INVESTOR'}:
        raise ApplicationError(403, 'INSUFFICIENT_PERMISSIONS', 'Select an issuer or investor demo identity.')
    return actor


def gateway(request: Request):
    return request.app.state.transfer_gateway


class TransferService:
    def __init__(self, database, gateway):
        self.database, self.gateway = database, gateway

    def row(self, session, operation_id, actor_id):
        row = session.get(ApplicationOperation, operation_id)
        if row is None or row.actor_id != actor_id:
            raise ApplicationError(404, 'RESOURCE_NOT_FOUND', 'Transfer was not found.')
        data = json.loads(row.response_json or '{}')
        if data.get('type') != 'ANSH_TRANSFER':
            raise ApplicationError(404, 'RESOURCE_NOT_FOUND', 'Transfer was not found.')
        return row, data

    @staticmethod
    def view(row, data):
        # Never expose the recovery artifact, signatures or private credentials.
        return dict(operation_id=row.id, state=row.status, transaction_id=data.get('transaction_id'),
                    request=data['request'], payment=data['payment'], commit=data.get('commit'),
                    error_code=data.get('error_code'), status_source='PERSISTED_WORKFLOW',
                    ownership_confirmed=row.status == 'COMMITTED_VALID')

    def read(self, operation_id, actor_id):
        with self.database.sessions() as session:
            row, data = self.row(session, operation_id, actor_id)
            return self.view(row, data)

    def initiate(self, command, actor, key, correlation_id):
        if command.from_user_id == command.to_user_id:
            raise ApplicationError(422, 'INVALID_REQUEST', 'Sender and recipient must differ.')
        if ((command.kind == 'ACQUISITION' and (actor.role != 'INVESTOR' or command.to_user_id != actor.user_id))
                or (command.kind == 'TRANSFER' and command.from_user_id != actor.user_id)):
            raise ApplicationError(403, 'INSUFFICIENT_PERMISSIONS', 'The selected demo identity does not match this transfer.')
        request = command.model_dump()
        fingerprint = hashlib.sha256(('POST /api/v1/ansh/transfers\n'+json.dumps(request, sort_keys=True)).encode()).hexdigest()
        with self.database.sessions() as session:
            existing = session.scalar(select(ApplicationOperation).where(
                ApplicationOperation.actor_id == actor.user_id, ApplicationOperation.idempotency_key == key))
            if existing:
                if existing.request_hash != fingerprint:
                    raise ApplicationError(409, 'IDEMPOTENCY_CONFLICT', 'This key was used with different parameters.')
                return self.read(existing.id, actor.user_id)
            operation_id = str(uuid4())
            data = dict(type='ANSH_TRANSFER', request=request, payment={'simulated': True, 'status': 'NOT_EXECUTED'},
                        artifact=None, transaction_id=None, commit=None)
            session.add(ApplicationOperation(id=operation_id, actor_id=actor.user_id, idempotency_key=key,
                request_hash=fingerprint, status='PREPARING', response_json=json.dumps(data),
                correlation_id=correlation_id, created_at=datetime.now(timezone.utc).isoformat()))
            try:
                session.commit()  # Durable unique claim before any Gateway call.
            except IntegrityError:
                session.rollback()
                # Inspect the winning request; never execute a second preparation.
                existing = session.scalar(select(ApplicationOperation).where(
                    ApplicationOperation.actor_id == actor.user_id, ApplicationOperation.idempotency_key == key))
                if existing is None or existing.request_hash != fingerprint:
                    raise ApplicationError(409, 'IDEMPOTENCY_CONFLICT', 'Conflicting operation identifier.') from None
                return self.read(existing.id, actor.user_id)
        try:
            if command.kind == 'ACQUISITION':
                prop = self.gateway.call('GET', 'properties/'+command.asset_id, correlation_id)
                if prop.get('property_id') != command.asset_id or prop.get('issuer_id') != command.from_user_id:
                    raise ApplicationError(409, 'INVALID_SELLER', 'Acquisition must use the registered issuer inventory.')
            balance = self.gateway.balance(command.asset_id, command.from_user_id, correlation_id)
            if balance['quantity'] < command.quantity:
                raise ApplicationError(409, 'INSUFFICIENT_BALANCE', 'Sender has insufficient ANSH.')
            data['payment'] = dict(simulated=True, status=command.payment_outcome)
            if command.payment_outcome == 'FAILED':
                self.update(operation_id, 'PAYMENT_FAILED', data)
                return self.read(operation_id, actor.user_id)
            frozen = dict(command_version=1, operation_id=operation_id, property_id=command.asset_id,
                          from_holder_id=command.from_user_id, to_holder_id=command.to_user_id, quantity=command.quantity)
            artifact = self.gateway.call('POST', 'transfers/prepare', correlation_id, frozen)
            expected_digest = hashlib.sha256(json.dumps(frozen, separators=(',', ':')).encode()).hexdigest()
            if (type(artifact.get('version')) is not int or artifact['version'] != 1 or artifact.get('function') != 'TransferANSH'
                    or json.dumps(artifact.get('command'), sort_keys=True) != json.dumps(frozen, sort_keys=True) or artifact.get('request_digest') != expected_digest
                    or artifact.get('signer') != SIGNER or artifact.get('channel') != 'mychannel' or artifact.get('chaincode') != 'tokansh'
                    or not isinstance(artifact.get('transaction_id'), str)
                    or not re.fullmatch(r'[0-9a-f]{64}', artifact['transaction_id'])
                    or not all(isinstance(artifact.get(k), str) and artifact[k] for k in ('transaction', 'creator', 'mac'))):
                raise ApplicationError(502, 'INVALID_ARTIFACT', 'The prepared transfer does not match the request.')
            data.update(artifact=artifact, transaction_id=artifact['transaction_id'])
            self.update(operation_id, 'PREPARED', data)  # Must be durable before claiming submission.
        except ApplicationError as error:
            data['error_code'] = error.code
            self.update(operation_id, 'FAILED', data)
            raise ApplicationError(error.status, error.code, error.message, {'operation_id': operation_id}) from None
        with self.database.sessions.begin() as session:
            changed = session.execute(update(ApplicationOperation).where(
                ApplicationOperation.id == operation_id, ApplicationOperation.status == 'PREPARED'
            ).values(status='SUBMISSION_PENDING')).rowcount
            if changed != 1:
                raise ApplicationError(409, 'RECONCILIATION_REQUIRED', 'Submission is already claimed; do not retry.')
        try:
            result = self.gateway.call('POST', 'transfers/submit', correlation_id, data['artifact'])
            if result != {'state': 'SUBMITTED', 'transaction_id': data['transaction_id']}:
                raise ValueError()
        except (ApplicationError, ValueError):
            self.update(operation_id, 'UNKNOWN', data, ('SUBMISSION_PENDING','SUBMITTED','UNKNOWN'))
            return self.read(operation_id, actor.user_id)
        self.update(operation_id, 'SUBMITTED', data, ('SUBMISSION_PENDING',))
        return self.reconcile(operation_id, actor.user_id, correlation_id)

    def update(self, operation_id, state, data, allowed=None):
        with self.database.sessions.begin() as session:
            statement = update(ApplicationOperation).where(ApplicationOperation.id == operation_id)
            if allowed is not None:
                statement = statement.where(ApplicationOperation.status.in_(allowed))
            session.execute(statement.values(status=state, response_json=json.dumps(data)))

    def reconcile(self, operation_id, actor_id, correlation_id):
        with self.database.sessions() as session:
            row, data = self.row(session, operation_id, actor_id)
            if row.status not in {'SUBMISSION_PENDING', 'SUBMITTED', 'UNKNOWN'}:
                return self.view(row, data)
        try:
            result = self.gateway.call('POST', 'transfers/commit-status', correlation_id, data['artifact'])
            if (set(result) != {'transaction_id', 'code', 'block_number', 'successful'}
                    or result['transaction_id'] != data['transaction_id'] or type(result['code']) is not int or result['code'] < 0
                    or type(result['block_number']) is not int or result['block_number'] < 0
                    or type(result['successful']) is not bool or result['successful'] != (result['code'] == 0)):
                raise ValueError()
        except (ApplicationError, ValueError, TypeError):
            self.update(operation_id, 'UNKNOWN', data, ('SUBMISSION_PENDING','SUBMITTED','UNKNOWN'))
            return self.read(operation_id, actor_id)
        data['commit'] = result
        self.update(operation_id, 'COMMITTED_VALID' if result['successful'] else 'COMMITTED_INVALID', data,
                    ('SUBMISSION_PENDING','SUBMITTED','UNKNOWN'))
        return self.read(operation_id, actor_id)


router = APIRouter(prefix='/ansh', tags=['ANSH transfers'])
Actor = Annotated[DemoActor, Depends(transfer_actor)]
Gateway = Annotated[TransferGateway, Depends(gateway)]
Ready = Depends(get_session)


@router.post('/transfers', dependencies=[Ready])
def create_transfer(command: TransferRequest, request: Request, response: Response, actor: Actor, bridge: Gateway,
                    key: Annotated[str, Header(alias='Idempotency-Key', min_length=1, max_length=128, pattern=r'^[A-Za-z0-9._:-]+$')]):
    result = TransferService(request.app.state.database, bridge).initiate(command, actor, key, request.state.correlation_id)
    response.status_code = 202 if result['state'] in {'PREPARING', 'PREPARED', 'SUBMISSION_PENDING', 'SUBMITTED', 'UNKNOWN'} else 200
    return success(request, result)


@router.get('/transfers/{operation_id}', dependencies=[Ready])
@router.get('/transfers/{operation_id}/status', dependencies=[Ready])
def transfer_status(operation_id: UUID, request: Request, actor: Actor, bridge: Gateway):
    return success(request, TransferService(request.app.state.database, bridge).read(str(operation_id), actor.user_id))


@router.post('/transfers/{operation_id}/reconcile', dependencies=[Ready])
def reconcile_transfer(operation_id: UUID, request: Request, actor: Actor, bridge: Gateway):
    return success(request, TransferService(request.app.state.database, bridge).reconcile(
        str(operation_id), actor.user_id, request.state.correlation_id))


@router.get('/balances/{property_id}/{holder_id}')
def holder_balance(property_id: UUID, holder_id: UUID, request: Request,
                   actor: Annotated[DemoActor, Depends(demo_actor)], bridge: Gateway):
    if actor.role in {'INVESTOR', 'LENDER'} and str(holder_id) != actor.user_id:
        raise ApplicationError(403, 'INSUFFICIENT_PERMISSIONS', 'The session cannot read another holder balance.')
    if actor.role == 'ISSUER' and str(holder_id) != actor.user_id:
        raise ApplicationError(403, 'INSUFFICIENT_PERMISSIONS', 'The issuer session cannot read another holder balance.')
    return success(request, bridge.balance(str(property_id), str(holder_id), request.state.correlation_id))
