"""Authenticated, durable orchestration for the one-time property issuance."""
import hashlib
import json
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.dependencies import DemoActor, demo_actor, get_session
from app.errors import ApplicationError, success
from app.properties.models import ApplicationOperation, Property
from app.registration import LedgerOperation, SIGNER

MAX_INTEGER = 9_007_199_254_740_991
MAX_MINOR = 9_999_999_999_999_999
UUID_PATTERN = r'^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'


class IssuanceRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    property_id: Annotated[str, Field(pattern=UUID_PATTERN)]
    quantity: Annotated[int, Field(strict=True, ge=1, le=MAX_INTEGER)]
    issue_price_minor: Annotated[str, Field(pattern=r'^[1-9][0-9]{0,15}$')]
    currency: Literal['INR']


def minor(value: str) -> int:
    try:
        parsed = Decimal(value)
    except InvalidOperation:
        raise ApplicationError(422, 'INVALID_ISSUANCE_ECONOMICS', 'Issue price is not a valid integer minor-unit amount.') from None
    if parsed != parsed.to_integral_value() or not 0 < parsed <= MAX_MINOR:
        raise ApplicationError(422, 'INVALID_ISSUANCE_ECONOMICS', 'Issue price is outside the supported integer range.')
    return int(parsed)


def checked_economics(record: Property, quantity: int, price_minor: int):
    if record.valuation_minor <= 0 or record.proposed_supply <= 0 or price_minor <= 0:
        raise ApplicationError(422, 'INVALID_ISSUANCE_ECONOMICS', 'Approved issuance economics must be positive integers.')
    if record.proposed_supply > MAX_INTEGER or record.valuation_minor > MAX_MINOR * MAX_INTEGER:
        raise ApplicationError(422, 'INVALID_ISSUANCE_ECONOMICS', 'Approved issuance economics exceed supported bounds.')
    if quantity != record.proposed_supply or price_minor != record.issue_price_minor:
        raise ApplicationError(422, 'INCONSISTENT_ISSUANCE_ECONOMICS', 'Issuance must use the registered full supply and issue price.')
    if quantity * price_minor != record.valuation_minor:
        raise ApplicationError(422, 'INCONSISTENT_ISSUANCE_ECONOMICS', 'Supply multiplied by issue price must equal tokenized value.')


def view(row: ApplicationOperation, data: dict) -> dict:
    return dict(operation_id=row.id, state=row.status, transaction_id=data.get('transaction_id'),
                request=data['request'], commit=data.get('commit'), issuance=data.get('issuance'),
                error_code=data.get('error_code'), status_source='PERSISTED_WORKFLOW',
                ownership_confirmed=row.status == 'COMMITTED_VALID')


def actor_for_issuance(actor: Annotated[DemoActor, Depends(demo_actor)]) -> DemoActor:
    if actor.role != 'INVESTOR':
        raise ApplicationError(403, 'INSUFFICIENT_PERMISSIONS', 'Only an authenticated investor may issue a property.')
    return actor


def gateway(request: Request):
    return request.app.state.transfer_gateway


class IssuanceService:
    def __init__(self, database, bridge):
        self.database, self.bridge = database, bridge

    def row(self, session, operation_id: str, actor_id: str):
        row = session.get(ApplicationOperation, operation_id)
        if row is None or row.actor_id != actor_id:
            raise ApplicationError(404, 'RESOURCE_NOT_FOUND', 'Issuance was not found.')
        data = json.loads(row.response_json or '{}')
        if data.get('type') != 'ANSH_ISSUANCE':
            raise ApplicationError(404, 'RESOURCE_NOT_FOUND', 'Issuance was not found.')
        return row, data

    def read(self, operation_id: str, actor_id: str):
        with self.database.sessions() as session:
            return view(*self.row(session, operation_id, actor_id))

    def claim(self, command: IssuanceRequest, actor: DemoActor, key: str, correlation_id: str):
        request = command.model_dump()
        fingerprint = hashlib.sha256(('POST /api/v1/ansh/issuances\n' + json.dumps(request, sort_keys=True)).encode()).hexdigest()
        with self.database.sessions() as session:
            existing = session.scalar(select(ApplicationOperation).where(
                ApplicationOperation.actor_id == actor.user_id, ApplicationOperation.idempotency_key == key))
            if existing:
                if existing.request_hash != fingerprint:
                    raise ApplicationError(409, 'IDEMPOTENCY_CONFLICT', 'This key was used with different parameters.')
                return self.read(existing.id, actor.user_id)
            operation_id = str(uuid4())
            data = dict(type='ANSH_ISSUANCE', request=request, artifact=None, transaction_id=None, commit=None)
            session.add(ApplicationOperation(id=operation_id, actor_id=actor.user_id, idempotency_key=key,
                request_hash=fingerprint, status='PREPARING', response_json=json.dumps(data),
                correlation_id=correlation_id, created_at=datetime.now(timezone.utc).isoformat()))
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                existing = session.scalar(select(ApplicationOperation).where(
                    ApplicationOperation.actor_id == actor.user_id, ApplicationOperation.idempotency_key == key))
                if existing is None or existing.request_hash != fingerprint:
                    raise ApplicationError(409, 'IDEMPOTENCY_CONFLICT', 'Conflicting operation identifier.') from None
                return self.read(existing.id, actor.user_id)
        return self.initiate(operation_id, command, actor, correlation_id)

    def initiate(self, operation_id: str, command: IssuanceRequest, actor: DemoActor, correlation_id: str):
        data = None
        try:
            with self.database.sessions() as session:
                record = session.get(Property, command.property_id)
                registration = session.scalar(select(LedgerOperation).where(LedgerOperation.property_id == command.property_id))
                if record is None:
                    raise ApplicationError(404, 'RESOURCE_NOT_FOUND', 'Property not found.')
                if record.issuer_id != actor.user_id:
                    raise ApplicationError(403, 'INSUFFICIENT_PERMISSIONS', 'The session is not the registered property issuer.')
                if record.status != 'DRAFT' or registration is None or registration.state != 'COMMITTED_VALID':
                    raise ApplicationError(409, 'PROPERTY_NOT_APPROVED', 'Property approval and committed ledger registration are required.')
                registered = json.loads(registration.command_json)
                price_minor = minor(command.issue_price_minor)
                checked_economics(record, command.quantity, price_minor)
                if (registered.get('property_id') != record.id or registered.get('issuer_id') != actor.user_id
                        or registered.get('approved_supply') != record.proposed_supply
                        or registered.get('issue_price_minor') != command.issue_price_minor or registered.get('currency') != 'INR'):
                    raise ApplicationError(409, 'REGISTRATION_MISMATCH', 'The committed registration does not match the property approval.')
            contract = self.bridge.call('GET', 'contract-info', correlation_id)
            if contract.get('supply_interpretation') != 'ONE_TIME_FULL_SUPPLY_ISSUANCE':
                raise ApplicationError(503, 'ISSUANCE_POLICY_UNSUPPORTED', 'The deployed contract does not prove the required issuance policy.')
            registered = self.bridge.call('GET', 'properties/' + command.property_id, correlation_id)
            if (registered.get('property_id') != command.property_id or registered.get('issuer_id') != actor.user_id
                    or registered.get('approved_supply') != command.quantity or registered.get('issue_price_minor') != command.issue_price_minor):
                raise ApplicationError(409, 'REGISTRATION_MISMATCH', 'The authoritative registration does not match the approved property.')
            state = self.bridge.call('GET', 'issuance-state/' + command.property_id, correlation_id)
            if state.get('cumulative_issued_supply') != 0 or state.get('remaining_issuance_capacity') != command.quantity:
                raise ApplicationError(409, 'ISSUANCE_ALREADY_COMPLETED', 'This property has already completed issuance.')
            frozen = dict(command_version=1, operation_id=operation_id, property_id=command.property_id, quantity=command.quantity)
            artifact = self.bridge.call('POST', 'issuances/prepare', correlation_id, frozen)
            expected = hashlib.sha256(json.dumps(frozen, separators=(',', ':')).encode()).hexdigest()
            if (artifact.get('version') != 1 or artifact.get('function') != 'IssueANSH' or artifact.get('command') != frozen
                    or artifact.get('request_digest') != expected or artifact.get('signer') != SIGNER
                    or artifact.get('channel') != 'mychannel' or artifact.get('chaincode') != 'tokansh'
                    or not isinstance(artifact.get('transaction_id'), str) or not artifact['transaction_id']
                    or not all(isinstance(artifact.get(k), str) and artifact[k] for k in ('transaction', 'creator', 'mac'))):
                raise ApplicationError(502, 'INVALID_ARTIFACT', 'The prepared issuance does not match the request.')
            data = dict(type='ANSH_ISSUANCE', request=command.model_dump(), artifact=artifact,
                        transaction_id=artifact['transaction_id'], commit=None)
            self.update(operation_id, 'PREPARED', data)
        except ApplicationError as error:
            if data is None:
                with self.database.sessions() as session:
                    row, data = self.row(session, operation_id, actor.user_id)
            data['error_code'] = error.code
            self.update(operation_id, 'FAILED', data)
            raise ApplicationError(error.status, error.code, error.message, {'operation_id': operation_id}) from None
        with self.database.sessions.begin() as session:
            changed = session.execute(update(ApplicationOperation).where(
                ApplicationOperation.id == operation_id, ApplicationOperation.status == 'PREPARED').values(status='SUBMISSION_PENDING')).rowcount
            if changed != 1:
                raise ApplicationError(409, 'RECONCILIATION_REQUIRED', 'Submission is already claimed; do not retry.')
        try:
            result = self.bridge.call('POST', 'issuances/submit', correlation_id, data['artifact'])
            if result != {'state': 'SUBMITTED', 'transaction_id': data['transaction_id']}:
                raise ValueError()
        except (ApplicationError, ValueError):
            self.update(operation_id, 'UNKNOWN', data, ('SUBMISSION_PENDING', 'SUBMITTED', 'UNKNOWN'))
            return self.read(operation_id, actor.user_id)
        self.update(operation_id, 'SUBMITTED', data, ('SUBMISSION_PENDING',))
        return self.reconcile(operation_id, actor.user_id, correlation_id)

    def update(self, operation_id, state, data, allowed=None):
        with self.database.sessions.begin() as session:
            statement = update(ApplicationOperation).where(ApplicationOperation.id == operation_id)
            if allowed is not None:
                statement = statement.where(ApplicationOperation.status.in_(allowed))
            session.execute(statement.values(status=state, response_json=json.dumps(data)))

    def reconcile(self, operation_id: str, actor_id: str, correlation_id: str):
        with self.database.sessions() as session:
            row, data = self.row(session, operation_id, actor_id)
            if row.status not in {'SUBMISSION_PENDING', 'SUBMITTED', 'UNKNOWN'}:
                return view(row, data)
        try:
            result = self.bridge.call('POST', 'issuances/commit-status', correlation_id, data['artifact'])
            if (set(result) != {'transaction_id', 'code', 'block_number', 'successful'}
                    or result['transaction_id'] != data['transaction_id'] or type(result['code']) is not int or result['code'] < 0
                    or type(result['block_number']) is not int or result['block_number'] < 0
                    or type(result['successful']) is not bool or result['successful'] != (result['code'] == 0)):
                raise ValueError()
            if result['successful']:
                receipt = self.bridge.call('GET', 'issuance-operations/' + operation_id, correlation_id)
                if receipt.get('property_id') != data['request']['property_id'] or receipt.get('issuer_id') != actor_id \
                        or receipt.get('quantity') != data['request']['quantity']:
                    raise ValueError()
                data['issuance'] = receipt
        except (ApplicationError, ValueError, TypeError, KeyError):
            self.update(operation_id, 'UNKNOWN', data, ('SUBMISSION_PENDING', 'SUBMITTED', 'UNKNOWN'))
            return self.read(operation_id, actor_id)
        data['commit'] = result
        self.update(operation_id, 'COMMITTED_VALID' if result['successful'] else 'COMMITTED_INVALID', data,
                    ('SUBMISSION_PENDING', 'SUBMITTED', 'UNKNOWN'))
        return self.read(operation_id, actor_id)


router = APIRouter(prefix='/ansh', tags=['ANSH issuance'])
Actor = Annotated[DemoActor, Depends(actor_for_issuance)]
Ready = Depends(get_session)
Bridge = Annotated[object, Depends(gateway)]
Key = Annotated[str, Header(alias='Idempotency-Key', min_length=1, max_length=128, pattern=r'^[A-Za-z0-9._:-]+$')]


@router.post('/issuances', dependencies=[Ready])
def create_issuance(command: IssuanceRequest, request: Request, response: Response, actor: Actor, bridge: Bridge, key: Key):
    result = IssuanceService(request.app.state.database, bridge).claim(command, actor, key, request.state.correlation_id)
    response.status_code = 202 if result['state'] in {'PREPARING', 'PREPARED', 'SUBMISSION_PENDING', 'SUBMITTED', 'UNKNOWN'} else 200
    return success(request, result)


@router.get('/issuances/{operation_id}', dependencies=[Ready])
@router.get('/issuances/{operation_id}/status', dependencies=[Ready])
def issuance_status(operation_id: UUID, request: Request, actor: Actor, bridge: Bridge):
    return success(request, IssuanceService(request.app.state.database, bridge).read(str(operation_id), actor.user_id))


@router.post('/issuances/{operation_id}/reconcile', dependencies=[Ready])
def reconcile_issuance(operation_id: UUID, request: Request, actor: Actor, bridge: Bridge):
    return success(request, IssuanceService(request.app.state.database, bridge).reconcile(
        str(operation_id), actor.user_id, request.state.correlation_id))
