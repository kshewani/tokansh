"""SQLite-only demo money. Call change() inside the caller's BEGIN IMMEDIATE."""
import hashlib
import json
from datetime import datetime, timezone
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, String, UniqueConstraint, select
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.dependencies import DemoActor, demo_actor, get_session
from app.errors import ApplicationError, success

MAX_CASH = 9007199254740991


class DemoCashAccount(Base):
    __tablename__ = 'demo_cash_accounts'
    __table_args__ = (CheckConstraint(f'balance_minor >= 0 AND balance_minor <= {MAX_CASH}', name='ck_demo_cash_balance'),)
    investor_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    balance_minor: Mapped[int] = mapped_column(BigInteger)


class DemoCashEntry(Base):
    __tablename__ = 'demo_cash_entries'
    __table_args__ = (
        UniqueConstraint('investor_id', 'idempotency_key', name='uq_demo_cash_key'),
        UniqueConstraint('loan_id', 'kind', name='uq_demo_cash_loan_kind'),
        CheckConstraint(f'amount_minor > 0 AND amount_minor <= {MAX_CASH}', name='ck_demo_cash_amount'),
        CheckConstraint(f'balance_after_minor >= 0 AND balance_after_minor <= {MAX_CASH}', name='ck_demo_cash_after'),
        CheckConstraint("kind IN ('DEMO_FUNDS','WITHDRAWAL','DISBURSEMENT','REPAYMENT')", name='ck_demo_cash_kind'),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    investor_id: Mapped[str] = mapped_column(ForeignKey('demo_cash_accounts.investor_id'), index=True)
    loan_id: Mapped[str | None] = mapped_column(ForeignKey('application_operations.id'), nullable=True)
    kind: Mapped[str] = mapped_column(String(24))
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    balance_after_minor: Mapped[int] = mapped_column(BigInteger)
    idempotency_key: Mapped[str] = mapped_column(String(128))
    request_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[str] = mapped_column(String(40))


def entry_data(entry):
    return dict(id=entry.id, kind=entry.kind, amount_minor=str(entry.amount_minor),
                balance_after_minor=str(entry.balance_after_minor), loan_id=entry.loan_id,
                created_at=entry.created_at, currency='INR', simulated=True, status='SIMULATED_COMPLETED')


def change(session, investor_id, kind, amount, key, loan_id=None):
    if type(amount) is not int or not 0 < amount <= MAX_CASH:
        raise ApplicationError(422, 'INVALID_AMOUNT', 'Demo money amount exceeds the supported integer-paise range.')
    digest = hashlib.sha256(json.dumps([kind, amount, loan_id], separators=(',', ':')).encode()).hexdigest()
    existing = session.scalar(select(DemoCashEntry).where(
        DemoCashEntry.investor_id == investor_id, DemoCashEntry.idempotency_key == key))
    if existing:
        if existing.request_hash != digest:
            raise ApplicationError(409, 'IDEMPOTENCY_CONFLICT', 'Wallet request key was used with different parameters.')
        return entry_data(existing)
    account = session.get(DemoCashAccount, investor_id)
    if account is None:
        account = DemoCashAccount(investor_id=investor_id, balance_minor=0)
        session.add(account)
        session.flush()
    delta = amount if kind in {'DEMO_FUNDS', 'DISBURSEMENT'} else -amount
    new_balance = account.balance_minor + delta
    if new_balance < 0:
        raise ApplicationError(409, 'INSUFFICIENT_DEMO_FUNDS', 'Add demo funds before this simulated payment.')
    if new_balance > MAX_CASH:
        raise ApplicationError(409, 'WALLET_LIMIT', 'Demo wallet balance limit would be exceeded.')
    account.balance_minor = new_balance
    entry = DemoCashEntry(id=str(uuid4()), investor_id=investor_id, loan_id=loan_id, kind=kind,
        amount_minor=amount, balance_after_minor=new_balance, idempotency_key=key,
        request_hash=digest, created_at=datetime.now(timezone.utc).isoformat())
    session.add(entry)
    session.flush()
    return entry_data(entry)


class CashRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    amount_minor: Annotated[str, Field(pattern=r'^[1-9][0-9]{0,15}$')]


def investor(request: Request, actor: Annotated[DemoActor, Depends(demo_actor)]):
    if request.app.state.settings.app_env == 'production':
        raise ApplicationError(503, 'AUTH_NOT_CONFIGURED', 'Demo wallet is local-demo only.')
    if actor.role != 'INVESTOR':
        raise ApplicationError(403, 'INSUFFICIENT_PERMISSIONS', 'Only the investor may use the demo wallet.')
    return actor


router = APIRouter(prefix='/demo-wallet', tags=['simulated cash wallet'])
Actor = Annotated[DemoActor, Depends(investor)]
Ready = Depends(get_session)


@router.get('', dependencies=[Ready])
def balance(request: Request, actor: Actor):
    with request.app.state.database.sessions() as session:
        account = session.get(DemoCashAccount, actor.user_id)
        return success(request, dict(investor_id=actor.user_id, balance_minor=str(account.balance_minor if account else 0), currency='INR', simulated=True))


@router.get('/activity', dependencies=[Ready])
def activity(request: Request, actor: Actor):
    with request.app.state.database.sessions() as session:
        entries = session.scalars(select(DemoCashEntry).where(DemoCashEntry.investor_id == actor.user_id)
                                  .order_by(DemoCashEntry.created_at.desc(), DemoCashEntry.id)).all()
        return success(request, [entry_data(entry) for entry in entries])


@router.post('/{action}', dependencies=[Ready])
def cash_action(action: str, command: CashRequest, request: Request, actor: Actor,
    key: Annotated[str, Header(alias='Idempotency-Key', min_length=1, max_length=120, pattern=r'^[A-Za-z0-9._:-]+$')]):
    if action not in {'fund', 'withdraw'}:
        raise ApplicationError(404, 'RESOURCE_NOT_FOUND', 'Demo wallet action was not found.')
    with request.app.state.database.sessions() as session:
        session.connection().exec_driver_sql('BEGIN IMMEDIATE')
        result = change(session, actor.user_id, 'DEMO_FUNDS' if action == 'fund' else 'WITHDRAWAL',
                        int(command.amount_minor), 'user:' + key)
        session.commit()
        return success(request, result)
