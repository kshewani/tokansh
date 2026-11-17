"""ANSH issuance against a registered approved property (API_CONTRACTS 7.5, Rules 3.1-3.4).

Issued supply is recognised only after DRUNIX confirms the IssueANSH commit.
"""
from typing import Literal

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.audit import asset_event, audit
from app.core.config import Settings
from app.core.deps import correlation_id, current_user, get_db, get_ledger, get_settings, require_role
from app.core.errors import ApiError, forbidden
from app.core.idempotency import run_idempotent
from app.core.money import Amount, from_minor, to_minor
from app.core.serial import envelope, iso, paginate
from app.db import models as m
from app.db.enums import EventSource, IssuanceStatus, OperationType, PropertyStatus, UserRole
from app.db.types import utcnow
from app.ledger import executor
from app.ledger.port import LedgerPort
from app.ledger.projections import apply_deltas, delta
from app.modules.common import get_or_404, identity, user_brief

router = APIRouter(prefix="/api/v1/ansh/issuances", tags=["ANSH issuance"])


class IssuanceIn(BaseModel):
    property_id: str = Field(min_length=1, max_length=36)
    quantity: int = Field(gt=0, le=10**12)
    issue_price: Amount | None = None
    currency: Literal["INR"] = "INR"


def view(db: Session, iss: m.AnshIssuance) -> dict:
    prop = db.get(m.Property, iss.property_id)
    return {"id": iss.id, "property_id": iss.property_id, "property_name": prop.property_name,
            "approved_property_ref": iss.approved_property_ref, "ansh_asset_id": iss.ansh_asset_id,
            "issuer": user_brief(db.get(m.User, iss.issuer_id)), "approved_supply": iss.approved_supply,
            "requested_quantity": iss.requested_quantity, "issued_quantity": iss.issued_quantity,
            "remaining_supply": iss.approved_supply - iss.issued_quantity,
            "issue_price": from_minor(iss.issue_price_minor), "currency": iss.currency,
            "issuance_value": from_minor(iss.issue_price_minor * iss.requested_quantity),
            "status": iss.issuance_status.value, "ledger_transaction_id": iss.ledger_transaction_id,
            "confirmed_at": iso(iss.confirmed_at), "created_at": iso(iss.created_at),
            "operation": executor.operation_view(db.get(m.LedgerOperation, iss.ledger_operation_id)
                                                 if iss.ledger_operation_id else None)}


def _committed(db: Session, op: m.LedgerOperation) -> None:
    iss = db.get(m.AnshIssuance, op.entity_id)
    iss.ledger_operation_id = op.id
    previous = iss.issuance_status
    iss.issuance_status = IssuanceStatus.CONFIRMED
    iss.issued_quantity = iss.requested_quantity
    iss.ledger_transaction_id = op.transaction_id
    iss.confirmed_at = op.confirmed_at or utcnow()
    apply_deltas(db, op)
    asset_event(db, event_type="ANSH_ISSUED", source=EventSource.DRUNIX_LEDGER, property_id=iss.property_id,
                issuance_id=iss.id, reference_id=op.id, ledger_transaction_id=op.transaction_id,
                description=f"{iss.issued_quantity:,} ANSH issued as {iss.ansh_asset_id}.")
    audit(db, entity_type="issuance", entity_id=iss.id, operation_type="ANSH_ISSUANCE", actor_id=iss.issuer_id,
          previous_state=previous, new_state=iss.issuance_status, source=EventSource.DRUNIX_LEDGER,
          operation_id=op.id, ledger_transaction_id=op.transaction_id)


def _failed(db: Session, op: m.LedgerOperation) -> None:
    iss = db.get(m.AnshIssuance, op.entity_id)
    iss.ledger_operation_id = op.id
    previous = iss.issuance_status
    iss.issuance_status = IssuanceStatus.FAILED
    audit(db, entity_type="issuance", entity_id=iss.id, operation_type="ANSH_ISSUANCE", actor_id=iss.issuer_id,
          previous_state=previous, new_state=IssuanceStatus.FAILED, outcome="FAILED", operation_id=op.id,
          detail={"error_code": op.error_code, "error_message": op.error_message})


executor.register(OperationType.ANSH_ISSUANCE, committed=_committed, failed=_failed)


@router.get("")
def list_issuances(request: Request, property_id: str | None = None, page: int = 1, page_size: int = 20,
                   db: Session = Depends(get_db), user: m.User = Depends(current_user)):
    stmt = sa.select(m.AnshIssuance).order_by(m.AnshIssuance.created_at.desc())
    if property_id:
        stmt = stmt.where(m.AnshIssuance.property_id == property_id)
    return envelope(request, paginate(db, stmt, page, page_size, lambda i: view(db, i)))


@router.post("", status_code=201)
def create_issuance(body: IssuanceIn, request: Request, db: Session = Depends(get_db),
                    user: m.User = Depends(current_user), ledger: LedgerPort = Depends(get_ledger),
                    settings: Settings = Depends(get_settings)):
    require_role(user, UserRole.ISSUER, UserRole.ADMIN)

    def op(_key: str):
        prop = get_or_404(db, m.Property, body.property_id, "Property")
        if user.role == UserRole.ISSUER and prop.issuer_id != user.id:
            raise forbidden("Only the property's issuer can issue its ANSH.")
        if prop.approval_status != PropertyStatus.APPROVED:
            raise ApiError(409, "PROPERTY_NOT_APPROVED", "ANSH can be issued only against an approved property.")
        if not prop.approved_property_ref:
            raise ApiError(409, "PROPERTY_NOT_APPROVED",
                           "The approved property is not yet registered on DRUNIX; registration must commit first.")
        if body.quantity > prop.approved_supply:
            raise ApiError(409, "ISSUANCE_LIMIT_EXCEEDED", "Requested issuance exceeds the approved supply.",
                           {"requested_quantity": body.quantity, "approved_supply": prop.approved_supply})
        price = to_minor(body.issue_price, "issue_price") if body.issue_price else prop.proposed_issue_price_minor
        iss = db.scalar(sa.select(m.AnshIssuance).filter_by(property_id=prop.id))
        if iss is not None:
            if iss.issuance_status == IssuanceStatus.CONFIRMED:
                raise ApiError(409, "ISSUANCE_LIMIT_EXCEEDED",
                               "This property's ANSH has already been issued (one issuance per property in the MVP).",
                               {"issued_quantity": iss.issued_quantity})
            if iss.issuance_status != IssuanceStatus.FAILED:
                raise ApiError(409, "RECONCILIATION_REQUIRED",
                               "A previous issuance outcome is unresolved. Reconcile it instead of resubmitting.",
                               {"issuance_id": iss.id, "operation_id": iss.ledger_operation_id})
            iss.requested_quantity, iss.issue_price_minor = body.quantity, price
        else:
            iss = m.AnshIssuance(property_id=prop.id, approved_property_ref=prop.approved_property_ref,
                                 ansh_asset_id=f"ANSH-{prop.approved_property_ref}", issuer_id=prop.issuer_id,
                                 approved_supply=prop.approved_supply, requested_quantity=body.quantity,
                                 issue_price_minor=price, currency=body.currency)
            db.add(iss)
        iss.issuance_status = IssuanceStatus.SUBMITTED
        db.flush()
        audit(db, entity_type="issuance", entity_id=iss.id, operation_type="ANSH_ISSUANCE_REQUESTED", actor_id=user.id,
              new_state=IssuanceStatus.SUBMITTED, correlation_id=correlation_id(request),
              detail={"quantity": body.quantity, "issue_price": from_minor(price)})
        issuer = db.get(m.User, prop.issuer_id)
        ledger_op = executor.submit_operation(
            db, ledger, settings, op_type=OperationType.ANSH_ISSUANCE, entity_type="issuance", entity_id=iss.id,
            function="IssueANSH",
            args=[iss.ansh_asset_id, prop.approved_property_ref, str(body.quantity), identity(issuer)],
            context={"issuance_id": iss.id, "deltas": [delta(issuer.id, owned=body.quantity)]},
            correlation_id=correlation_id(request))
        iss.ledger_operation_id = ledger_op.id
        db.commit()
        return executor.outcome(ledger_op, view(db, iss), created=True)

    return run_idempotent(request, db, "POST /ansh/issuances", {"user": user.id, **body.model_dump()}, op)


@router.get("/{issuance_id}")
def get_issuance(issuance_id: str, request: Request, db: Session = Depends(get_db),
                 user: m.User = Depends(current_user)):
    return envelope(request, view(db, get_or_404(db, m.AnshIssuance, issuance_id, "Issuance")))


@router.get("/{issuance_id}/status")
def issuance_status(issuance_id: str, request: Request, db: Session = Depends(get_db),
                    user: m.User = Depends(current_user)):
    iss = get_or_404(db, m.AnshIssuance, issuance_id, "Issuance")
    op = db.get(m.LedgerOperation, iss.ledger_operation_id) if iss.ledger_operation_id else None
    return envelope(request, {"issuance_id": iss.id, "status": iss.issuance_status.value,
                              "operation": executor.operation_view(op)})
