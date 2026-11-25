"""Simulated demo cash wallet (adopted from the connected-mode branch).

Loan disbursement credits the borrower, repayment debits them, and users can add
demo funds or withdraw. All cash is simulated INR in the application database:
no bank, no payment processor, no real money (ADR-010, ADR-020).
"""
import sqlalchemy as sa
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.audit import audit
from app.core.deps import correlation_id, current_user, get_db, require_role
from app.core.errors import ApiError
from app.core.idempotency import run_idempotent
from app.core.money import Amount, from_minor, to_minor
from app.core.serial import envelope, iso
from app.db import models as m
from app.db.enums import EventSource, UserRole, WalletEntryKind

MAX_TOP_UP_MINOR = 100_000_000_00  # Rs 10 crore per top-up keeps demo figures readable
CASH_ROLES = (UserRole.INVESTOR, UserRole.ISSUER)


def account(db: Session, user_id: str) -> m.DemoCashAccount:
    acct = db.scalar(sa.select(m.DemoCashAccount).filter_by(user_id=user_id))
    if acct is None:
        acct = m.DemoCashAccount(user_id=user_id, balance_minor=0)
        db.add(acct)
        db.flush()
    return acct


def balance(db: Session, user_id: str) -> int:
    acct = db.scalar(sa.select(m.DemoCashAccount).filter_by(user_id=user_id))
    return acct.balance_minor if acct else 0


def move(db: Session, user_id: str, kind: WalletEntryKind, amount_minor: int, reference_key: str,
         loan_id: str | None = None) -> m.DemoCashEntry:
    """Credit or debit inside the caller's transaction. A repeated reference_key returns the original entry."""
    existing = db.scalar(sa.select(m.DemoCashEntry).filter_by(reference_key=reference_key))
    if existing is not None:
        return existing
    acct = account(db, user_id)
    debit = kind in (WalletEntryKind.WITHDRAWAL, WalletEntryKind.REPAYMENT)
    if debit and acct.balance_minor < amount_minor:
        raise ApiError(409, "INSUFFICIENT_DEMO_CASH", "Not enough demo cash. Add demo funds first.",
                       {"balance": from_minor(acct.balance_minor), "required": from_minor(amount_minor)})
    acct.balance_minor += -amount_minor if debit else amount_minor
    entry = m.DemoCashEntry(account_id=acct.id, kind=kind, amount_minor=amount_minor,
                            balance_after_minor=acct.balance_minor, loan_id=loan_id, reference_key=reference_key)
    db.add(entry)
    audit(db, entity_type="demo_cash", entity_id=acct.id, operation_type=f"CASH_{kind.value}", actor_id=user_id,
          new_state=from_minor(acct.balance_minor), source=EventSource.PAYMENT_SIMULATOR,
          detail={"amount": from_minor(amount_minor), "loan_id": loan_id})
    return entry


def entry_view(e: m.DemoCashEntry) -> dict:
    return {"id": e.id, "kind": e.kind.value, "amount": from_minor(e.amount_minor),
            "balance_after": from_minor(e.balance_after_minor), "currency": e.currency, "loan_id": e.loan_id,
            "simulated": True, "created_at": iso(e.created_at)}


def wallet_view(db: Session, user: m.User) -> dict:
    acct = db.scalar(sa.select(m.DemoCashAccount).filter_by(user_id=user.id))
    entries = [] if acct is None else db.scalars(sa.select(m.DemoCashEntry).filter_by(account_id=acct.id)
                                                 .order_by(m.DemoCashEntry.created_at.desc()).limit(50)).all()
    return {"balance": from_minor(acct.balance_minor if acct else 0), "currency": "INR", "simulated": True,
            "source": "PAYMENT_SIMULATOR", "entries": [entry_view(e) for e in entries]}


class CashIn(BaseModel):
    amount: Amount


router = APIRouter(prefix="/api/v1/wallet", tags=["Demo wallet (simulated)"])


@router.get("")
def get_wallet(request: Request, db: Session = Depends(get_db), user: m.User = Depends(current_user)):
    require_role(user, *CASH_ROLES)
    return envelope(request, wallet_view(db, user))


def _cash(kind: WalletEntryKind, label: str):
    def endpoint(body: CashIn, request: Request, db: Session = Depends(get_db), user: m.User = Depends(current_user)):
        require_role(user, *CASH_ROLES)

        def op(key: str):
            amount = to_minor(body.amount, "amount")
            if amount > MAX_TOP_UP_MINOR:
                raise ApiError(422, "INVALID_REQUEST", "Amount exceeds the demo limit of Rs 10 crore per request.")
            move(db, user.id, kind, amount, f"{kind.value}:{user.id}:{key}")
            db.commit()
            return 200, wallet_view(db, user)

        return run_idempotent(request, db, f"POST /wallet/{label}", {"user": user.id, **body.model_dump()}, op)
    return endpoint


router.post("/fund")(_cash(WalletEntryKind.DEMO_FUNDS, "fund"))
router.post("/withdraw")(_cash(WalletEntryKind.WITHDRAWAL, "withdraw"))
