"""M5 financing simulation. GET-only ledger observations; never a blockchain pledge."""
import hashlib
import json
from datetime import datetime, timezone
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.dependencies import DemoActor, demo_actor, get_session
from app.errors import ApplicationError, success
from app.properties.models import ApplicationOperation
from app.transfers import Identifier
from app.lenders import LENDERS, DEFAULT_LENDER, terms
from app.wallet import MAX_CASH, change
from app.reservations import financing_reserved_quantity, offering_committed_quantity

RESERVED = {'APPROVED', 'DISBURSED', 'REPAID'}
TYPE = 'SIMULATED_FINANCING'


class FinancingRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    property_id: Identifier
    asset_class: Literal['ANSH'] = 'ANSH'
    lender_id: str = DEFAULT_LENDER
    offer_id: str = 'axim-standard'
    quantity: Annotated[int, Field(ge=1, le=9007199254740991)]
    unit_value_minor: Annotated[str, Field(pattern=r'^[1-9][0-9]{0,11}$')] = '1000000'
    ltv_percent: Annotated[int, Field(ge=20, le=75)] = 60
    annual_rate_bps: Annotated[int, Field(ge=1, le=3000)] = 1000
    term_months: Annotated[int, Field(ge=1, le=36)] = 12


def quote(command):
    collateral = command.quantity * int(command.unit_value_minor)
    principal = collateral * command.ltv_percent // 100  # Round down the advance.
    if principal < 1:
        raise ApplicationError(422, 'INVALID_REQUEST', 'The illustrative loan must be at least one paise.')
    # Simple fixed-term interest, half-up to one paise; no accrual or compounding.
    interest = (principal * command.annual_rate_bps * command.term_months + 60000) // 120000
    if principal + interest > MAX_CASH:
        raise ApplicationError(422, 'INVALID_AMOUNT', 'Loan repayment exceeds the demo cash limit.')
    return dict(collateral_value_minor=str(collateral), principal_minor=str(principal),
                interest_minor=str(interest), repayment_minor=str(principal + interest), currency='INR')


def now():
    return datetime.now(timezone.utc).isoformat()


def finance_actor(request: Request, actor: Annotated[DemoActor, Depends(demo_actor)]):
    if request.app.state.settings.app_env == 'production':
        raise ApplicationError(503, 'AUTH_NOT_CONFIGURED', 'Financing simulation is local-demo only.')
    if actor.role not in {'INVESTOR', 'LENDER'}:
        raise ApplicationError(403, 'INSUFFICIENT_PERMISSIONS', 'Select the investor or lender demo identity.')
    return actor


class FinancingService:
    def __init__(self, database, gateway):
        self.database, self.gateway = database, gateway

    @staticmethod
    def rows(session, borrower=None):
        query = select(ApplicationOperation).where(ApplicationOperation.status.like('FIN_%'))
        if borrower is not None:
            query = query.where(ApplicationOperation.actor_id == borrower)
        return session.scalars(query).all()

    @staticmethod
    def data(row):
        data = json.loads(row.response_json)
        if data.get('type') != TYPE:
            raise ApplicationError(404, 'RESOURCE_NOT_FOUND', 'Financing application was not found.')
        return data

    def reserved(self, session, borrower, property_id):
        return sum(data['quantity'] for row in self.rows(session, borrower)
                   if (data := self.data(row))['property_id'] == property_id and data['state'] in RESERVED)

    def total_reserved(self, session, borrower, property_id):
        return self.reserved(session, borrower, property_id) + offering_committed_quantity(session, borrower, property_id)

    def eligibility(self, property_id, actor, correlation):
        # Balance is always a fresh authenticated read, never a local projection.
        balance = self.gateway.balance(property_id, actor.user_id, correlation)
        with self.database.sessions() as session:
            reserved = self.total_reserved(session, actor.user_id, property_id)
        return dict(property_id=property_id, holder_id=actor.user_id, owned=balance['quantity'],
                    ownership_source='DRUNIX_EVALUATE', observed_at=now(), reserved_simulated=reserved,
                    eligible_simulated=max(0, balance['quantity'] - reserved),
                    reservation_shortfall=reserved > balance['quantity'], on_chain_lock=False)

    def list(self, actor, lender_id=DEFAULT_LENDER):
        if actor.role == 'LENDER':
            if actor.organization_id is None:
                raise ApplicationError(403, 'INSUFFICIENT_PERMISSIONS', 'The lender session has no organization.')
            # The query parameter is retained for staged-client compatibility,
            # but the authenticated session is authoritative.
            lender_id = actor.organization_id
        with self.database.sessions() as session:
            rows = self.rows(session, None if actor.role == 'LENDER' else actor.user_id)
            return [data for row in sorted(rows, key=lambda r: r.created_at, reverse=True)
                    if (data := self.data(row)) and (actor.role != 'LENDER' or data.get('lender_id') == lender_id)]

    def get(self, session, loan_id, actor, lender_id=DEFAULT_LENDER):
        row = session.get(ApplicationOperation, loan_id)
        if row is None or not row.status.startswith('FIN_'):
            raise ApplicationError(404, 'RESOURCE_NOT_FOUND', 'Financing application was not found.')
        if row.actor_id != actor.user_id and actor.role != 'LENDER':
            raise ApplicationError(404, 'RESOURCE_NOT_FOUND', 'Financing application was not found.')
        data = self.data(row)
        if actor.role == 'LENDER':
            if actor.organization_id is None:
                raise ApplicationError(403, 'INSUFFICIENT_PERMISSIONS', 'The lender session has no organization.')
            lender_id = actor.organization_id
            if data.get('lender_id') != lender_id:
                raise ApplicationError(403, 'WRONG_LENDER', 'Application is not assigned to this demo lender workspace.')
        return row, data

    @staticmethod
    def event(data, state, actor):
        data['state'] = state
        data['updated_at'] = now()
        data['timeline'].append(dict(state=state, timestamp=data['updated_at'], actor_role=actor.role, simulated=True))

    def apply(self, command, actor, key, correlation):
        if actor.role != 'INVESTOR':
            raise ApplicationError(403, 'INSUFFICIENT_PERMISSIONS', 'Only the investor may apply for financing.')
        encoded = json.dumps(command.model_dump(), sort_keys=True, separators=(',', ':'))
        digest = hashlib.sha256(('POST /api/v1/financing/applications\n' + encoded).encode()).hexdigest()
        # Network I/O precedes the short database write lock.
        balance = self.gateway.balance(command.property_id, actor.user_id, correlation)
        with self.database.sessions() as session:
            session.connection().exec_driver_sql('BEGIN IMMEDIATE')
            existing = session.scalar(select(ApplicationOperation).where(
                ApplicationOperation.actor_id == actor.user_id, ApplicationOperation.idempotency_key == key))
            if existing:
                # Old clients must be able to replay an unchanged pre-catalogue request.
                legacy_body = command.model_dump(exclude={'lender_id', 'offer_id'})
                legacy_digest = hashlib.sha256(('POST /api/v1/financing/applications\n' +
                    json.dumps(legacy_body, sort_keys=True, separators=(',', ':'))).encode()).hexdigest()
                legacy_replay = (not {'lender_id', 'offer_id'} & command.model_fields_set
                    and existing.status.startswith('FIN_') and 'lender_id' not in self.data(existing) and existing.request_hash == legacy_digest)
                if existing.request_hash != digest and not legacy_replay:
                    raise ApplicationError(409, 'IDEMPOTENCY_CONFLICT', 'This request key was used with different parameters.')
                return self.data(existing)
            snapshot = terms(command)
            valuation = quote(command)
            if command.quantity > balance['quantity'] - self.total_reserved(session, actor.user_id, command.property_id):
                raise ApplicationError(409, 'INSUFFICIENT_COLLATERAL', 'Requested units exceed currently eligible simulated collateral.')
            loan_id = str(uuid4())
            data = dict(type=TYPE, id=loan_id, borrower_id=actor.user_id, **command.model_dump(), **valuation,
                        simulated=True, on_chain_lock=False, reservation_active=False,
                        terms_snapshot=snapshot, reviewer_context=None,
                        assessment=None, outstanding_principal_minor='0', amount_due_minor='0',
                        created_at=now(), timeline=[])
            self.event(data, 'APPLIED', actor)
            session.add(ApplicationOperation(id=loan_id, actor_id=actor.user_id, idempotency_key=key,
                request_hash=digest, status='FIN_APPLIED', response_json=json.dumps(data),
                response_status=201, correlation_id=correlation, created_at=data['created_at']))
            session.commit()
            return data

    def action(self, loan_id, action, actor, correlation, lender_id=DEFAULT_LENDER):
        if action not in {'assess', 'approve', 'reject', 'disburse', 'repay', 'release'}:
            raise ApplicationError(404, 'RESOURCE_NOT_FOUND', 'Financing action was not found.')
        required_role = 'INVESTOR' if action in {'repay', 'release'} else 'LENDER'
        if actor.role != required_role:
            raise ApplicationError(403, 'INSUFFICIENT_PERMISSIONS', 'Investor repayment/release and lender decisions require their respective demo roles.')
        with self.database.sessions() as session:
            _, initial = self.get(session, loan_id, actor, lender_id)
        # A new approval MUST recheck holdings, even following an earlier assessment.
        balance = None
        if action in {'assess', 'approve', 'disburse'}:
            balance = self.gateway.balance(initial['property_id'], initial['borrower_id'], correlation)
        with self.database.sessions() as session:
            session.connection().exec_driver_sql('BEGIN IMMEDIATE')
            row, data = self.get(session, loan_id, actor, lender_id)
            target = dict(assess='ASSESSED', approve='APPROVED', reject='REJECTED', disburse='DISBURSED', repay='REPAID', release='RELEASED')[action]
            if data['state'] == target:
                return data  # Same action has no additional effect or timeline entry.
            previous = dict(assess='APPLIED', approve='ASSESSED', reject=data['state'] if data['state'] in {'APPLIED', 'ASSESSED'} else None, disburse='APPROVED', repay='DISBURSED', release='REPAID')[action]
            if data['state'] != previous:
                raise ApplicationError(409, 'INVALID_FINANCING_STATE', 'This action does not follow the current financing stage.')
            if action in {'repay', 'release'} and actor.user_id != data['borrower_id']:
                raise ApplicationError(403, 'INSUFFICIENT_PERMISSIONS', 'The investor must confirm simulated repayment and release.')
            if balance is not None:
                reserved = self.total_reserved(session, data['borrower_id'], data['property_id'])
                other = reserved - (data['quantity'] if data['state'] in RESERVED else 0)
                enough = data['quantity'] <= balance['quantity'] - other
                data['assessment'] = dict(simulated=True, eligible=enough, observed_owned=balance['quantity'],
                    ownership_source='DRUNIX_EVALUATE', observed_at=now(),
                    risk_band='MODERATE' if data['ltv_percent'] <= 60 else 'ELEVATED',
                    reason='Illustrative policy met; no credit bureau or legal pledge verification.' if enough else 'Current holdings or existing simulated reservations do not support this request.')
                if not enough:
                    if data['reservation_active']:
                        raise ApplicationError(409, 'HOLDINGS_CHANGED', 'Current holdings no longer cover this simulated reservation; operator review is required.')
                    target = 'REJECTED'
            if actor.role == 'LENDER':
                data['reviewer_context'] = dict(actor_id=actor.user_id, actor_role=actor.role,
                    lender_id=actor.organization_id, reviewed_at=now(), demo_identity=True)
            if target == 'APPROVED':
                data['reservation_active'] = True
            if target == 'DISBURSED':
                # New transitions only. Legacy already-DISBURSED records return above without credit.
                entry = change(session, data['borrower_id'], 'DISBURSEMENT', int(data['principal_minor']),
                               'loan:disburse:' + loan_id, loan_id)
                data['wallet_disbursement_entry_id'] = entry['id']
                data['outstanding_principal_minor'] = data['principal_minor']
                data['amount_due_minor'] = data['repayment_minor']
                data['disbursed_at'] = now()
            if target == 'REPAID':
                entry = change(session, data['borrower_id'], 'REPAYMENT', int(data['amount_due_minor']),
                               'loan:repay:' + loan_id, loan_id)
                data['wallet_repayment_entry_id'] = entry['id']
                data['outstanding_principal_minor'] = '0'
                data['amount_due_minor'] = '0'
            if target == 'RELEASED':
                data['reservation_active'] = False
            self.event(data, target, actor)
            row.status = 'FIN_' + target
            row.response_json = json.dumps(data)
            session.commit()
            return data


router = APIRouter(prefix='/financing', tags=['simulated financing'])
Actor = Annotated[DemoActor, Depends(finance_actor)]
Ready = Depends(get_session)


def service(request):
    return FinancingService(request.app.state.database, request.app.state.transfer_gateway)


@router.get('/lenders', response_model=None)
def lender_catalogue(request: Request, actor: Actor) -> dict:
    return success(request, [item.model_dump(mode='json') for item in LENDERS])


@router.get('/applications', dependencies=[Ready])
def list_financing(request: Request, actor: Actor, lender_id: str = DEFAULT_LENDER):
    return success(request, service(request).list(actor, lender_id))


@router.get('/eligibility/{property_id}', dependencies=[Ready])
def financing_eligibility(property_id: UUID, request: Request, actor: Actor):
    if actor.role != 'INVESTOR':
        raise ApplicationError(403, 'INSUFFICIENT_PERMISSIONS', 'Select the investor to inspect financing eligibility.')
    return success(request, service(request).eligibility(str(property_id), actor, request.state.correlation_id))


@router.post('/applications', dependencies=[Ready], status_code=201)
def apply_financing(command: FinancingRequest, request: Request, actor: Actor,
                    key: Annotated[str, Header(alias='Idempotency-Key', min_length=1, max_length=128, pattern=r'^[A-Za-z0-9._:-]+$')]):
    return success(request, service(request).apply(command, actor, key, request.state.correlation_id))


@router.post('/applications/{loan_id}/{action}', dependencies=[Ready])
def financing_action(loan_id: UUID, action: str, request: Request, actor: Actor, lender_id: str = DEFAULT_LENDER):
    return success(request, service(request).action(str(loan_id), action, actor, request.state.correlation_id, lender_id))
