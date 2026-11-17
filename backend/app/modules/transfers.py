"""Direct ANSH transfers (API_CONTRACTS 7.8, Rules 7.1-7.5)."""
import sqlalchemy as sa
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.audit import audit
from app.core.config import Settings
from app.core.deps import correlation_id, current_user, get_db, get_ledger, get_settings
from app.core.errors import forbidden, invalid_state
from app.core.idempotency import run_idempotent
from app.core.serial import envelope
from app.db import models as m
from app.db.enums import IssuanceStatus, OperationType, UserRole
from app.ledger import executor
from app.ledger.port import LedgerPort
from app.modules.common import get_or_404
from app.modules.ledger_reads import check_available, ledger_position
from app.modules.marketplace import submit_transfer

router = APIRouter(prefix="/api/v1/ansh/transfers", tags=["ANSH transfers"])


class TransferIn(BaseModel):
    issuance_id: str = Field(min_length=1, max_length=36)
    to_user_id: str = Field(min_length=1, max_length=36)
    quantity: int = Field(gt=0, le=10**12)


def view(db: Session, op: m.LedgerOperation) -> dict:
    p = executor.payload_of(op)
    return {"transfer_id": op.entity_id, "issuance_id": p.get("issuance_id"), "quantity": p.get("quantity"),
            "from_user_id": p.get("from_user_id"), "to_user_id": p.get("to_user_id"),
            "from_name": p.get("from_name"), "to_name": p.get("to_name"), "order_id": p.get("order_id"),
            "status": op.status.value, "operation": executor.operation_view(op)}


def _op_for(db: Session, transfer_id: str, user: m.User) -> m.LedgerOperation:
    op = db.scalar(sa.select(m.LedgerOperation).where(m.LedgerOperation.operation_type == OperationType.ANSH_TRANSFER,
                                                      m.LedgerOperation.entity_id == transfer_id))
    if op is None:
        from app.core.errors import not_found
        raise not_found("Transfer", transfer_id)
    p = executor.payload_of(op)
    if user.id not in (p.get("from_user_id"), p.get("to_user_id")) and user.role not in (UserRole.ADMIN, UserRole.ISSUER):
        raise forbidden()
    return op


@router.post("", status_code=201)
def create_transfer(body: TransferIn, request: Request, db: Session = Depends(get_db),
                    user: m.User = Depends(current_user), ledger: LedgerPort = Depends(get_ledger),
                    settings: Settings = Depends(get_settings)):
    def op(_key: str):
        iss = get_or_404(db, m.AnshIssuance, body.issuance_id, "Issuance")
        if iss.issuance_status != IssuanceStatus.CONFIRMED:
            raise invalid_state("ANSH has not been issued.")
        recipient = get_or_404(db, m.User, body.to_user_id, "Recipient")
        if recipient.id == user.id:
            raise invalid_state("Sender and recipient must differ.")
        try:
            # Rules 7.1, 7.2: pledged units are never transferable; checked against the ledger.
            check_available(ledger_position(db, ledger, iss, user), body.quantity)
        except Exception as exc:
            from app.core.errors import ApiError
            if isinstance(exc, ApiError) and exc.status == 409:
                audit(db, entity_type="ansh_transfer", entity_id=iss.id, operation_type="ANSH_TRANSFER_REJECTED",
                      actor_id=user.id, outcome="REJECTED", correlation_id=correlation_id(request),
                      detail={"code": exc.code, **exc.details, "to_user_id": recipient.id})
                db.commit()
            raise
        ledger_op = submit_transfer(db, ledger, settings, issuance=iss, sender=user, recipient=recipient,
                                    quantity=body.quantity, corr=correlation_id(request))
        return executor.outcome(ledger_op, view(db, ledger_op), created=True)

    return run_idempotent(request, db, "POST /ansh/transfers", {"user": user.id, **body.model_dump()}, op)


@router.get("/{transfer_id}")
def get_transfer(transfer_id: str, request: Request, db: Session = Depends(get_db), user: m.User = Depends(current_user)):
    return envelope(request, view(db, _op_for(db, transfer_id, user)))


@router.get("/{transfer_id}/status")
def transfer_status(transfer_id: str, request: Request, db: Session = Depends(get_db), user: m.User = Depends(current_user)):
    op = _op_for(db, transfer_id, user)
    return envelope(request, {"transfer_id": transfer_id, "status": op.status.value,
                              "operation": executor.operation_view(op)})
