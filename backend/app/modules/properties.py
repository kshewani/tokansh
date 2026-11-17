"""Property registry: onboarding, review, approval and DRUNIX registration (API_CONTRACTS 7.4).

Approval is an application decision. Only the approved property reference and its
supply constraint are registered on DRUNIX (RegisterApprovedProperty) before issuance.
"""
from typing import Literal

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.audit import asset_event, audit
from app.core.config import Settings
from app.core.deps import correlation_id, current_user, get_db, get_ledger, get_settings, require_role
from app.core.errors import ApiError, forbidden, invalid_state
from app.core.idempotency import run_idempotent
from app.core.money import Amount, from_minor, to_minor
from app.core.serial import envelope, iso, paginate
from app.db import models as m
from app.db.enums import (DocumentType, EventSource, OperationStatus, OperationType, PropertyStatus, ReviewDecision,
                          UserRole, ValuationPurpose, VerificationStatus)
from app.db.types import utcnow
from app.ledger import executor
from app.ledger.port import LedgerPort
from app.modules.common import get_or_404, identity, property_ref, user_brief

router = APIRouter(prefix="/api/v1/properties", tags=["Property registry"])
REVIEWERS = (UserRole.ADMIN, UserRole.ISSUER)


class PropertyIn(BaseModel):
    name: str = Field(min_length=3, max_length=160)
    property_type: str = Field(min_length=2, max_length=60)
    address: str = Field(min_length=2, max_length=255)
    city: str = Field(min_length=2, max_length=80)
    country: str = Field(default="India", min_length=2, max_length=80)
    description: str | None = Field(default=None, max_length=2000)
    valuation: Amount
    proposed_supply: int = Field(gt=0, le=10**12)
    issue_price: Amount
    currency: Literal["INR"] = "INR"


class DocumentIn(BaseModel):
    document_type: DocumentType
    document_name: str = Field(min_length=2, max_length=200)
    document_reference: str = Field(min_length=2, max_length=500)
    content_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class ApproveIn(BaseModel):
    approved_supply: int | None = Field(default=None, gt=0, le=10**12)
    collateral_unit_value: Amount | None = None
    notes: str | None = Field(default=None, max_length=2000)


class RejectIn(BaseModel):
    reason: str = Field(min_length=3, max_length=2000)


# ---------------------------------------------------------------- views

def registration_op(db: Session, prop: m.Property) -> m.LedgerOperation | None:
    return db.scalar(sa.select(m.LedgerOperation)
                     .filter_by(entity_type="property", entity_id=prop.id,
                                operation_type=OperationType.APPROVED_PROPERTY_REGISTRATION)
                     .order_by(m.LedgerOperation.created_at.desc()).limit(1))


def view(db: Session, prop: m.Property, detail: bool = False) -> dict:
    op = registration_op(db, prop)
    issuance = db.scalar(sa.select(m.AnshIssuance).filter_by(property_id=prop.id))
    data = {
        "id": prop.id, "name": prop.property_name, "property_type": prop.property_type,
        "description": prop.description, "address": prop.address, "city": prop.city, "country": prop.country,
        "valuation": from_minor(prop.illustrative_valuation_minor), "currency": prop.valuation_currency,
        "proposed_supply": prop.proposed_supply, "issue_price": from_minor(prop.proposed_issue_price_minor),
        "approved_supply": prop.approved_supply, "approval_status": prop.approval_status.value,
        "verification_status": prop.verification_status.value, "issuer": user_brief(db.get(m.User, prop.issuer_id)),
        "is_synthetic": prop.is_synthetic, "created_at": iso(prop.created_at), "updated_at": iso(prop.updated_at),
        "ledger": {
            "approved_property_ref": prop.approved_property_ref,
            "registered": prop.approved_property_ref is not None,
            "registration_transaction_id": prop.drunix_registration_transaction_id,
            "registered_at": iso(prop.ledger_registered_at),
            "operation": executor.operation_view(op),
        },
        "issuance": None if issuance is None else {
            "id": issuance.id, "status": issuance.issuance_status.value, "issued_quantity": issuance.issued_quantity,
            "ansh_asset_id": issuance.ansh_asset_id},
    }
    if detail:
        data["documents"] = [{"id": d.id, "document_type": d.document_type.value, "document_name": d.document_name,
                              "document_reference": d.document_reference, "verification_status": d.verification_status.value,
                              "is_synthetic": d.is_synthetic, "uploaded_at": iso(d.uploaded_at)}
                             for d in db.scalars(sa.select(m.PropertyDocument).filter_by(property_id=prop.id))]
        data["valuations"] = [{"id": v.id, "purpose": v.purpose.value, "property_value": from_minor(v.property_value_minor),
                               "unit_value": from_minor(v.unit_value_minor), "currency": v.currency,
                               "source": v.valuation_source, "is_simulated": v.is_simulated, "observed_at": iso(v.observed_at)}
                              for v in db.scalars(sa.select(m.PropertyValuation).filter_by(property_id=prop.id)
                                                  .order_by(m.PropertyValuation.observed_at))]
        data["reviews"] = [{"id": r.id, "decision": r.decision.value, "approved_supply": r.approved_supply,
                            "notes": r.notes, "reviewer": user_brief(db.get(m.User, r.reviewer_id)),
                            "decided_at": iso(r.decided_at)}
                           for r in db.scalars(sa.select(m.PropertyReview).filter_by(property_id=prop.id))]
    return data


# ---------------------------------------------------------------- ledger effects

def _registered(db: Session, op: m.LedgerOperation) -> None:
    prop = db.get(m.Property, op.entity_id)
    prop.approved_property_ref = executor.payload_of(op)["approved_property_ref"]
    prop.drunix_registration_transaction_id = op.transaction_id
    prop.ledger_registered_at = op.confirmed_at
    asset_event(db, event_type="PROPERTY_REGISTERED", source=EventSource.DRUNIX_LEDGER, property_id=prop.id,
                description=f"Approved property reference {prop.approved_property_ref} registered on DRUNIX.",
                reference_id=op.id, ledger_transaction_id=op.transaction_id)
    audit(db, entity_type="property", entity_id=prop.id, operation_type="PROPERTY_LEDGER_REGISTRATION",
          actor_id=None, new_state="REGISTERED", source=EventSource.DRUNIX_LEDGER, operation_id=op.id,
          ledger_transaction_id=op.transaction_id)


def _registration_failed(db: Session, op: m.LedgerOperation) -> None:
    audit(db, entity_type="property", entity_id=op.entity_id, operation_type="PROPERTY_LEDGER_REGISTRATION",
          actor_id=None, new_state="NOT_REGISTERED", outcome="FAILED", operation_id=op.id,
          detail={"error_code": op.error_code, "error_message": op.error_message})


executor.register(OperationType.APPROVED_PROPERTY_REGISTRATION, committed=_registered, failed=_registration_failed)


def _register_on_ledger(db: Session, ledger: LedgerPort, settings: Settings, prop: m.Property,
                        corr: str | None) -> m.LedgerOperation:
    issuer = db.get(m.User, prop.issuer_id)
    ref = property_ref(prop)
    args = [ref, identity(issuer), str(prop.approved_supply)]
    return executor.submit_operation(
        db, ledger, settings, op_type=OperationType.APPROVED_PROPERTY_REGISTRATION, entity_type="property",
        entity_id=prop.id, function="RegisterApprovedProperty", args=args,
        context={"approved_property_ref": ref, "property_id": prop.id}, correlation_id=corr)


# ---------------------------------------------------------------- routes

@router.get("")
def list_properties(request: Request, status: PropertyStatus | None = None, page: int = 1, page_size: int = 20,
                    db: Session = Depends(get_db), user: m.User = Depends(current_user)):
    stmt = sa.select(m.Property).order_by(m.Property.created_at.desc())
    if status:
        stmt = stmt.where(m.Property.approval_status == status)
    return envelope(request, paginate(db, stmt, page, page_size, lambda p: view(db, p)))


@router.post("", status_code=201)
def create_property(body: PropertyIn, request: Request, db: Session = Depends(get_db),
                    user: m.User = Depends(current_user)):
    require_role(user, UserRole.ISSUER)
    valuation, price = to_minor(body.valuation, "valuation"), to_minor(body.issue_price, "issue_price")
    prop = m.Property(property_name=body.name.strip(), property_type=body.property_type.strip(),
                      description=body.description, address=body.address.strip(), city=body.city.strip(),
                      country=body.country.strip(), illustrative_valuation_minor=valuation,
                      valuation_currency=body.currency, proposed_supply=body.proposed_supply,
                      proposed_issue_price_minor=price, issuer_id=user.id, is_synthetic=True)
    db.add(prop)
    db.flush()
    db.add(m.PropertyValuation(property_id=prop.id, purpose=ValuationPurpose.ILLUSTRATIVE_MARKET,
                               property_value_minor=valuation, unit_value_minor=price, currency=body.currency,
                               valuation_source="Issuer-declared illustrative valuation (synthetic)",
                               is_simulated=True, observed_at=utcnow()))
    audit(db, entity_type="property", entity_id=prop.id, operation_type="PROPERTY_CREATED", actor_id=user.id,
          new_state=PropertyStatus.DRAFT, correlation_id=correlation_id(request))
    asset_event(db, event_type="PROPERTY_ONBOARDED", source=EventSource.APPLICATION, property_id=prop.id,
                actor_id=user.id, description=f"{prop.property_name} onboarded as a draft.")
    db.commit()
    return envelope(request, view(db, prop, detail=True))


@router.get("/{property_id}")
def get_property(property_id: str, request: Request, db: Session = Depends(get_db),
                 user: m.User = Depends(current_user)):
    return envelope(request, view(db, get_or_404(db, m.Property, property_id, "Property"), detail=True))


@router.put("/{property_id}")
def update_property(property_id: str, body: PropertyIn, request: Request, db: Session = Depends(get_db),
                    user: m.User = Depends(current_user)):
    prop = get_or_404(db, m.Property, property_id, "Property")
    if prop.issuer_id != user.id:
        raise forbidden("Only the issuer can edit this property.")
    if prop.approval_status != PropertyStatus.DRAFT:
        raise invalid_state("Only draft properties can be edited.", status=prop.approval_status.value)
    prop.property_name, prop.property_type = body.name.strip(), body.property_type.strip()
    prop.address, prop.city, prop.country = body.address.strip(), body.city.strip(), body.country.strip()
    prop.description = body.description
    prop.illustrative_valuation_minor = to_minor(body.valuation, "valuation")
    prop.proposed_supply, prop.proposed_issue_price_minor = body.proposed_supply, to_minor(body.issue_price, "issue_price")
    audit(db, entity_type="property", entity_id=prop.id, operation_type="PROPERTY_UPDATED", actor_id=user.id,
          previous_state=prop.approval_status, new_state=prop.approval_status, correlation_id=correlation_id(request))
    db.commit()
    return envelope(request, view(db, prop, detail=True))


@router.post("/{property_id}/documents", status_code=201)
def add_document(property_id: str, body: DocumentIn, request: Request, db: Session = Depends(get_db),
                 user: m.User = Depends(current_user)):
    prop = get_or_404(db, m.Property, property_id, "Property")
    if prop.issuer_id != user.id:
        raise forbidden("Only the issuer can attach documents.")
    if prop.approval_status not in (PropertyStatus.DRAFT, PropertyStatus.SUBMITTED):
        raise invalid_state("Documents can be attached only before review.")
    doc = m.PropertyDocument(property_id=prop.id, document_type=body.document_type, document_name=body.document_name,
                             document_reference=body.document_reference, content_sha256=body.content_sha256)
    db.add(doc)
    audit(db, entity_type="property", entity_id=prop.id, operation_type="DOCUMENT_ATTACHED", actor_id=user.id,
          detail={"document_type": body.document_type.value, "name": body.document_name})
    db.commit()
    return envelope(request, view(db, prop, detail=True))


@router.post("/{property_id}/submit")
def submit_property(property_id: str, request: Request, db: Session = Depends(get_db),
                    user: m.User = Depends(current_user)):
    prop = get_or_404(db, m.Property, property_id, "Property")
    if prop.issuer_id != user.id:
        raise forbidden("Only the issuer can submit this property.")
    if prop.approval_status != PropertyStatus.DRAFT:
        raise invalid_state("Only draft properties can be submitted.", status=prop.approval_status.value)
    prop.approval_status = PropertyStatus.SUBMITTED
    audit(db, entity_type="property", entity_id=prop.id, operation_type="PROPERTY_SUBMITTED", actor_id=user.id,
          previous_state=PropertyStatus.DRAFT, new_state=PropertyStatus.SUBMITTED, correlation_id=correlation_id(request))
    asset_event(db, event_type="PROPERTY_SUBMITTED", source=EventSource.APPLICATION, property_id=prop.id,
                actor_id=user.id, description="Submitted for approval.")
    db.commit()
    return envelope(request, view(db, prop, detail=True))


@router.post("/{property_id}/approve")
def approve_property(property_id: str, body: ApproveIn, request: Request, db: Session = Depends(get_db),
                     user: m.User = Depends(current_user), ledger: LedgerPort = Depends(get_ledger),
                     settings: Settings = Depends(get_settings)):
    require_role(user, *REVIEWERS)

    def op(_key: str):
        prop = get_or_404(db, m.Property, property_id, "Property")
        if prop.approval_status not in (PropertyStatus.SUBMITTED, PropertyStatus.UNDER_REVIEW):
            raise invalid_state("Only submitted properties can be approved.", status=prop.approval_status.value)
        supply = body.approved_supply or prop.proposed_supply
        unit = to_minor(body.collateral_unit_value, "collateral_unit_value") if body.collateral_unit_value \
            else prop.proposed_issue_price_minor
        previous = prop.approval_status
        prop.approval_status = PropertyStatus.UNDER_REVIEW
        db.flush()
        db.add(m.PropertyReview(property_id=prop.id, reviewer_id=user.id, decision=ReviewDecision.APPROVED,
                                approved_supply=supply, notes=body.notes))
        prop.approval_status = PropertyStatus.APPROVED
        prop.verification_status = VerificationStatus.VERIFIED
        prop.approved_supply = supply
        db.add(m.PropertyValuation(property_id=prop.id, purpose=ValuationPurpose.COLLATERAL,
                                   property_value_minor=unit * supply, unit_value_minor=unit,
                                   currency=prop.valuation_currency, approved_by=user.id, is_simulated=True,
                                   valuation_source="Approved collateral value (synthetic, set at approval)",
                                   observed_at=utcnow()))
        audit(db, entity_type="property", entity_id=prop.id, operation_type="PROPERTY_APPROVED", actor_id=user.id,
              previous_state=previous, new_state=PropertyStatus.APPROVED, correlation_id=correlation_id(request),
              detail={"approved_supply": supply, "notes": body.notes})
        asset_event(db, event_type="PROPERTY_APPROVED", source=EventSource.APPLICATION, property_id=prop.id,
                    actor_id=user.id, description=f"Approved off-chain with a supply constraint of {supply:,} ANSH.")
        db.commit()
        reg = _register_on_ledger(db, ledger, settings, prop, correlation_id(request))
        data = view(db, prop, detail=True)
        # Approval itself succeeded; registration may still be pending or failed and can be retried.
        return (200 if reg.status == OperationStatus.COMMITTED else 202), data

    return run_idempotent(request, db, f"POST /properties/{property_id}/approve",
                          {"user": user.id, **body.model_dump()}, op)


@router.post("/{property_id}/register")
def register_property(property_id: str, request: Request, db: Session = Depends(get_db),
                      user: m.User = Depends(current_user), ledger: LedgerPort = Depends(get_ledger),
                      settings: Settings = Depends(get_settings)):
    """Retry RegisterApprovedProperty after a definitive failure (never after an unknown outcome)."""
    require_role(user, *REVIEWERS)

    def op(_key: str):
        prop = get_or_404(db, m.Property, property_id, "Property")
        if prop.approval_status != PropertyStatus.APPROVED:
            raise ApiError(409, "PROPERTY_NOT_APPROVED", "Property must be approved before ledger registration.")
        if prop.approved_property_ref:
            raise invalid_state("Property is already registered on DRUNIX.")
        last = registration_op(db, prop)
        if last is not None and last.status in executor.PENDING:
            raise ApiError(409, "RECONCILIATION_REQUIRED",
                           "The previous registration outcome is unresolved. Reconcile it instead of resubmitting.",
                           {"operation_id": last.id})
        reg = _register_on_ledger(db, ledger, settings, prop, correlation_id(request))
        return executor.outcome(reg, view(db, prop, detail=True))

    return run_idempotent(request, db, f"POST /properties/{property_id}/register", {"user": user.id}, op)


@router.post("/{property_id}/reject")
def reject_property(property_id: str, body: RejectIn, request: Request, db: Session = Depends(get_db),
                    user: m.User = Depends(current_user)):
    require_role(user, *REVIEWERS)
    prop = get_or_404(db, m.Property, property_id, "Property")
    if prop.approval_status not in (PropertyStatus.SUBMITTED, PropertyStatus.UNDER_REVIEW):
        raise invalid_state("Only submitted properties can be rejected.", status=prop.approval_status.value)
    previous = prop.approval_status
    db.add(m.PropertyReview(property_id=prop.id, reviewer_id=user.id, decision=ReviewDecision.REJECTED, notes=body.reason))
    prop.approval_status = PropertyStatus.REJECTED
    prop.verification_status = VerificationStatus.REJECTED
    audit(db, entity_type="property", entity_id=prop.id, operation_type="PROPERTY_REJECTED", actor_id=user.id,
          previous_state=previous, new_state=PropertyStatus.REJECTED, detail={"reason": body.reason})
    asset_event(db, event_type="PROPERTY_REJECTED", source=EventSource.APPLICATION, property_id=prop.id,
                actor_id=user.id, description=f"Rejected: {body.reason}"[:500])
    db.commit()
    return envelope(request, view(db, prop, detail=True))


@router.get("/{property_id}/history")
def property_history(property_id: str, request: Request, db: Session = Depends(get_db),
                     user: m.User = Depends(current_user)):
    from app.modules.audit_api import asset_event_view
    get_or_404(db, m.Property, property_id, "Property")
    events = db.scalars(sa.select(m.AssetEvent).filter_by(property_id=property_id)
                        .order_by(m.AssetEvent.occurred_at.desc())).all()
    return envelope(request, {"items": [asset_event_view(db, e) for e in events]})
