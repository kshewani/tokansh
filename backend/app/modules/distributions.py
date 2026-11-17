"""Rental income distributions (API_CONTRACTS 7.11, 10.4; Rules 10.1-10.6; ADR-014).

Eligibility comes from record-date holdings reconstructed deterministically from
committed DRUNIX operations (EVENT_RECONSTRUCTION). Current holdings are never
substituted. Payouts are simulated.

Record-date cut-off: holdings committed up to the end of the record date (UTC).
Calculation is refused before the record date. If calculated ON the record date,
the cut-off is the calculation time, which is recorded on the snapshot.

Rounding: each entitlement is floored to the paisa; the residual paise are given
one each by largest remainder, ties broken by investor id (deterministic).
"""
import uuid
from datetime import date, datetime, time, timedelta, timezone
from typing import Literal

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import asset_event, audit
from app.core.deps import correlation_id, current_user, get_db, require_role
from app.core.errors import ApiError, forbidden, invalid_state
from app.core.idempotency import run_idempotent
from app.core.money import Amount, from_minor, to_minor
from app.core.serial import envelope, iso, paginate
from app.db import models as m
from app.db.enums import DistributionStatus, EntitlementStatus, EventSource, IssuanceStatus, SnapshotMethod, UserRole
from app.db.types import utcnow
from app.ledger.projections import holdings_as_of
from app.modules.common import get_or_404, user_brief

router = APIRouter(prefix="/api/v1/distributions", tags=["Distributions"])
ROUNDING = "Floor to paisa; residual paise allocated one each by largest remainder, ties by investor id."


class DistributionIn(BaseModel):
    issuance_id: str = Field(min_length=1, max_length=36)
    period_label: str = Field(min_length=2, max_length=60)
    total_amount: Amount
    currency: Literal["INR"] = "INR"
    record_date: date
    distribution_date: date


def allocate(total_minor: int, holdings: dict[str, int]) -> dict[str, tuple[int, int]]:
    """Return {investor_id: (amount_minor, residual_minor)} summing exactly to total_minor."""
    total_units = sum(holdings.values())
    base, remainders = {}, []
    for investor, units in holdings.items():
        q, r = divmod(total_minor * units, total_units)
        base[investor] = q
        remainders.append((-r, investor))
    residual = total_minor - sum(base.values())
    extra = {inv: 0 for inv in holdings}
    for _, inv in sorted(remainders)[:residual]:
        extra[inv] = 1
    return {inv: (base[inv] + extra[inv], extra[inv]) for inv in holdings}


def view(db: Session, d: m.Distribution, user: m.User | None = None) -> dict:
    iss = db.get(m.AnshIssuance, d.issuance_id)
    snap = db.get(m.OwnershipSnapshot, d.snapshot_id) if d.snapshot_id else None
    ents = db.scalars(sa.select(m.DistributionEntitlement).filter_by(distribution_id=d.id)).all()
    mine = next((e for e in ents if user and e.investor_id == user.id), None)
    return {"id": d.id, "property_id": d.property_id, "property_name": db.get(m.Property, d.property_id).property_name,
            "issuance_id": d.issuance_id, "ansh_asset_id": iss.ansh_asset_id, "period_label": d.period_label,
            "total_amount": from_minor(d.total_amount_minor), "currency": d.currency,
            "record_date": iso(d.record_date), "distribution_date": iso(d.distribution_date),
            "status": d.distribution_status.value, "declared_by": user_brief(db.get(m.User, d.declared_by)),
            "rounding_method": d.rounding_method, "created_at": iso(d.created_at),
            "snapshot": None if snap is None else {
                "id": snap.id, "method": snap.method.value, "ledger_reference": snap.ledger_reference,
                "as_of_block_number": snap.as_of_block_number, "total_eligible_quantity": snap.total_eligible_quantity,
                "is_verified": snap.is_verified, "captured_at": iso(snap.captured_at), "verified_at": iso(snap.verified_at)},
            "entitlement_count": len(ents),
            "entitlements_total": from_minor(sum(e.entitlement_amount_minor for e in ents)) if ents else None,
            "my_entitlement": None if mine is None else ent_view(db, mine),
            "payout_simulated": True}


def ent_view(db: Session, e: m.DistributionEntitlement) -> dict:
    return {"id": e.id, "investor": user_brief(db.get(m.User, e.investor_id)), "eligible_quantity": e.eligible_quantity,
            "total_eligible_quantity": e.total_eligible_quantity, "amount": from_minor(e.entitlement_amount_minor),
            "rounding_residual": from_minor(e.rounding_residual_minor), "currency": e.currency,
            "status": e.entitlement_status.value, "payment_reference": e.payment_reference,
            "paid_at": iso(e.paid_at), "simulated": True}


@router.get("")
def list_distributions(request: Request, issuance_id: str | None = None, page: int = 1, page_size: int = 20,
                       db: Session = Depends(get_db), user: m.User = Depends(current_user)):
    stmt = sa.select(m.Distribution).order_by(m.Distribution.created_at.desc())
    if issuance_id:
        stmt = stmt.where(m.Distribution.issuance_id == issuance_id)
    return envelope(request, paginate(db, stmt, page, page_size, lambda d: view(db, d, user)))


@router.post("", status_code=201)
def declare(body: DistributionIn, request: Request, db: Session = Depends(get_db), user: m.User = Depends(current_user)):
    require_role(user, UserRole.ISSUER, UserRole.ADMIN)
    iss = get_or_404(db, m.AnshIssuance, body.issuance_id, "Issuance")
    if user.role == UserRole.ISSUER and iss.issuer_id != user.id:
        raise forbidden("Only the issuer can declare distributions for this asset.")
    if iss.issuance_status != IssuanceStatus.CONFIRMED:
        raise invalid_state("Distributions require a confirmed issuance.")
    if body.distribution_date < body.record_date:
        raise ApiError(422, "INVALID_REQUEST", "Distribution date must be on or after the record date.")
    d = m.Distribution(property_id=iss.property_id, issuance_id=iss.id, declared_by=user.id,
                       period_label=body.period_label.strip(), total_amount_minor=to_minor(body.total_amount, "total_amount"),
                       currency=body.currency, record_date=body.record_date, distribution_date=body.distribution_date,
                       distribution_status=DistributionStatus.DECLARED, rounding_method=ROUNDING)
    db.add(d)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise invalid_state("A distribution for this asset, record date and period already exists.")  # Rule 10.5
    audit(db, entity_type="distribution", entity_id=d.id, operation_type="DISTRIBUTION_DECLARED", actor_id=user.id,
          new_state=DistributionStatus.DECLARED, correlation_id=correlation_id(request),
          detail={"total_amount": body.total_amount, "record_date": body.record_date.isoformat()})
    asset_event(db, event_type="DISTRIBUTION_DECLARED", source=EventSource.APPLICATION, property_id=iss.property_id,
                issuance_id=iss.id, actor_id=user.id, reference_id=d.id,
                description=f"{body.period_label}: INR {body.total_amount} declared, record date {body.record_date}.")
    db.commit()
    return envelope(request, view(db, d, user))


@router.get("/{distribution_id}")
def get_distribution(distribution_id: str, request: Request, db: Session = Depends(get_db),
                     user: m.User = Depends(current_user)):
    return envelope(request, view(db, get_or_404(db, m.Distribution, distribution_id, "Distribution"), user))


@router.post("/{distribution_id}/calculate")
def calculate(distribution_id: str, request: Request, db: Session = Depends(get_db), user: m.User = Depends(current_user)):
    require_role(user, UserRole.ISSUER, UserRole.ADMIN)
    d = get_or_404(db, m.Distribution, distribution_id, "Distribution")
    if d.distribution_status != DistributionStatus.DECLARED:
        raise invalid_state("Entitlements were already calculated.", status=d.distribution_status.value)
    now = utcnow()
    if d.record_date > now.date():
        raise invalid_state("The record date has not been reached; record-date holdings do not exist yet.",
                            record_date=d.record_date.isoformat())
    end_of_day = datetime.combine(d.record_date + timedelta(days=1), time.min, tzinfo=timezone.utc)
    cutoff = min(end_of_day, now)
    balances, last_tx, last_block = holdings_as_of(db, d.issuance_id, cutoff)
    iss = db.get(m.AnshIssuance, d.issuance_id)
    total = sum(b["owned"] for b in balances.values())
    # Verification: the reconstruction must account for exactly the confirmed issued supply.
    if total != iss.issued_quantity or last_tx is None:
        raise ApiError(409, "RECONCILIATION_REQUIRED",
                       "Record-date holdings could not be verified against the confirmed issued supply. "
                       "The calculation stays pending.", {"reconstructed_total": total,
                                                          "issued_quantity": iss.issued_quantity})
    snap = m.OwnershipSnapshot(issuance_id=d.issuance_id, record_date=d.record_date,
                               method=SnapshotMethod.EVENT_RECONSTRUCTION, ledger_reference=last_tx,
                               as_of_block_number=last_block, total_eligible_quantity=total,
                               is_verified=True, verified_at=now)
    db.add(snap)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise invalid_state("A snapshot for this record date already exists.")
    for investor, b in balances.items():
        if b["owned"] > 0:
            db.add(m.OwnershipSnapshotLine(snapshot_id=snap.id, investor_id=investor, owned_quantity=b["owned"],
                                           pledged_quantity=b["pledged"], eligible_quantity=b["owned"]))  # Rule 10.4
    eligible = {inv: b["owned"] for inv, b in balances.items() if b["owned"] > 0}
    for investor, (amount, residual) in allocate(d.total_amount_minor, eligible).items():
        db.add(m.DistributionEntitlement(distribution_id=d.id, investor_id=investor, snapshot_id=snap.id,
                                         eligible_quantity=eligible[investor], total_eligible_quantity=total,
                                         entitlement_amount_minor=amount, rounding_residual_minor=residual,
                                         currency=d.currency))
    d.snapshot_id = snap.id
    d.distribution_status = DistributionStatus.PROCESSING
    audit(db, entity_type="distribution", entity_id=d.id, operation_type="ENTITLEMENTS_CALCULATED", actor_id=user.id,
          previous_state=DistributionStatus.DECLARED, new_state=DistributionStatus.PROCESSING,
          correlation_id=correlation_id(request),
          detail={"cutoff": cutoff.isoformat(), "snapshot_method": "EVENT_RECONSTRUCTION",
                  "ledger_reference": last_tx, "total_eligible": total, "investors": len(eligible)})
    db.commit()
    return envelope(request, view(db, d, user))


@router.get("/{distribution_id}/entitlements")
def entitlements(distribution_id: str, request: Request, db: Session = Depends(get_db),
                 user: m.User = Depends(current_user)):
    d = get_or_404(db, m.Distribution, distribution_id, "Distribution")
    stmt = sa.select(m.DistributionEntitlement).filter_by(distribution_id=d.id)
    if user.role == UserRole.INVESTOR:
        stmt = stmt.where(m.DistributionEntitlement.investor_id == user.id)
    rows = db.scalars(stmt.order_by(m.DistributionEntitlement.entitlement_amount_minor.desc())).all()
    return envelope(request, {"items": [ent_view(db, e) for e in rows]})


@router.post("/{distribution_id}/simulate-payment")
def simulate_payment(distribution_id: str, request: Request, db: Session = Depends(get_db),
                     user: m.User = Depends(current_user)):
    require_role(user, UserRole.ISSUER, UserRole.ADMIN)

    def op(_key: str):
        d = get_or_404(db, m.Distribution, distribution_id, "Distribution")
        if d.distribution_status != DistributionStatus.PROCESSING:
            raise invalid_state("Entitlements must be calculated before payment.", status=d.distribution_status.value)
        ents = db.scalars(sa.select(m.DistributionEntitlement).filter_by(distribution_id=d.id)).all()
        if sum(e.entitlement_amount_minor for e in ents) != d.total_amount_minor:  # Rule 10.5
            raise ApiError(409, "RECONCILIATION_REQUIRED", "Entitlements do not reconcile with the declared amount.")
        for e in ents:
            if e.entitlement_status == EntitlementStatus.CALCULATED:
                e.entitlement_status = EntitlementStatus.PAID
                e.payment_reference = f"SIM-DIST-{uuid.uuid4().hex[:12].upper()}"
                e.paid_at = utcnow()
        d.distribution_status = DistributionStatus.COMPLETED
        audit(db, entity_type="distribution", entity_id=d.id, operation_type="DISTRIBUTION_PAID", actor_id=user.id,
              previous_state=DistributionStatus.PROCESSING, new_state=DistributionStatus.COMPLETED,
              source=EventSource.PAYMENT_SIMULATOR, detail={"payouts": len(ents)})
        asset_event(db, event_type="DISTRIBUTION_PAID", source=EventSource.PAYMENT_SIMULATOR, property_id=d.property_id,
                    issuance_id=d.issuance_id, actor_id=user.id, reference_id=d.id,
                    description=f"{d.period_label}: simulated payout to {len(ents)} holders.")
        db.commit()
        return 200, view(db, d, user)

    return run_idempotent(request, db, f"POST /distributions/{distribution_id}/simulate-payment", {"user": user.id}, op)
