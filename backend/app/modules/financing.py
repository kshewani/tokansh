"""Collateral pledges, simulated loans and collateral release (API_CONTRACTS 7.10, 10.2, 10.3).

The pledge and its release are DRUNIX operations. Everything about the loan
(assessment, approval, disbursement, repayment) is the lender SIMULATOR: no
real lending takes place (ADR-010, ADR-020).
"""
import uuid
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
from app.core.money import Amount, bps_to_percent, from_minor, ratio_bps, to_minor
from app.core.serial import envelope, iso, paginate
from app.db import models as m
from app.db.enums import (CreditDecision, EventSource, IssuanceStatus, LoanStatus, OperationType, PledgeStatus,
                          RepaymentStatus, UserRole, ValuationPurpose, WalletEntryKind)
from app.db.types import utcnow
from app.ledger import executor
from app.ledger.port import LedgerPort
from app.ledger.projections import apply_deltas, delta
from app.modules import lenders, wallet
from app.modules.common import get_or_404, identity, user_brief
from app.modules.ledger_reads import check_available, ledger_position

router = APIRouter(prefix="/api/v1", tags=["Collateral and financing"])
LENDER_SIM = EventSource.LENDER_SIMULATOR


class PledgeIn(BaseModel):
    issuance_id: str = Field(min_length=1, max_length=36)
    quantity: int = Field(gt=0, le=10**12)


class LoanIn(BaseModel):
    pledge_id: str = Field(min_length=1, max_length=36)
    principal: Amount
    lender_id: str | None = Field(default=None, max_length=36)
    offer_id: str | None = Field(default=None, max_length=40)
    currency: Literal["INR"] = "INR"
    # Simulated terms from the lender's offer; omitted values default to the offer's.
    interest_rate_bps: int | None = Field(default=None, ge=0, le=3000)
    term_months: int | None = Field(default=None, ge=1, le=36)


def interest_quote(principal_minor: int, rate_bps: int, term_months: int) -> int:
    """principal x rate_bps x months / 120000, rounded half up to the paisa. Integers only."""
    denominator = 120000
    return (principal_minor * rate_bps * term_months * 2 + denominator) // (denominator * 2)


class DecisionIn(BaseModel):
    notes: str | None = Field(default=None, max_length=500)


class RepaymentIn(BaseModel):
    amount: Amount
    currency: Literal["INR"] = "INR"


# ---------------------------------------------------------------- views

def pledge_view(db: Session, p: m.CollateralPledge) -> dict:
    iss = db.get(m.AnshIssuance, p.issuance_id)
    loan = db.scalar(sa.select(m.Loan).filter_by(pledge_id=p.id))
    val = db.get(m.PropertyValuation, p.valuation_id) if p.valuation_id else None
    return {"id": p.id, "investor": user_brief(db.get(m.User, p.investor_id)), "issuance_id": iss.id,
            "property_name": db.get(m.Property, iss.property_id).property_name, "ansh_asset_id": iss.ansh_asset_id,
            "quantity": p.quantity, "collateral_unit_value": from_minor(p.collateral_unit_value_minor),
            "collateral_value": from_minor(p.collateral_value_minor), "currency": p.currency,
            "valuation": None if val is None else {"id": val.id, "source": val.valuation_source,
                                                   "observed_at": iso(val.observed_at), "is_simulated": val.is_simulated},
            "status": p.pledge_status.value, "loan_id": loan.id if loan else None,
            "created_at": iso(p.created_at), "released_at": iso(p.released_at),
            "pledge_operation": executor.operation_view(db.get(m.LedgerOperation, p.pledge_operation_id)
                                                        if p.pledge_operation_id else None),
            "release_operation": executor.operation_view(db.get(m.LedgerOperation, p.release_operation_id)
                                                         if p.release_operation_id else None)}


def loan_view(db: Session, loan: m.Loan) -> dict:
    assessments = db.scalars(sa.select(m.CreditAssessment).filter_by(loan_id=loan.id)
                             .order_by(m.CreditAssessment.assessed_at)).all()
    repayments = db.scalars(sa.select(m.LoanRepayment).filter_by(loan_id=loan.id)
                            .order_by(m.LoanRepayment.created_at)).all()
    return {"id": loan.id, "borrower": user_brief(db.get(m.User, loan.borrower_id)),
            "lender": user_brief(db.get(m.User, loan.lender_id)), "pledge_id": loan.pledge_id,
            "principal": from_minor(loan.principal_minor), "outstanding": from_minor(loan.outstanding_minor),
            "currency": loan.currency, "collateral_value": from_minor(loan.collateral_value_minor),
            "ltv_percent": bps_to_percent(loan.ltv_bps), "max_ltv_percent": bps_to_percent(loan.max_ltv_bps),
            "ltv_is_indicative": True, "interest_rate_percent": bps_to_percent(loan.interest_rate_bps),
            "term_months": loan.term_months, "offer_id": loan.offer_id,
            "interest_quote": from_minor(loan.interest_quote_minor),
            "interest_outstanding": from_minor(loan.interest_outstanding_minor),
            "total_due": from_minor(loan.principal_minor + loan.interest_quote_minor),
            "total_outstanding": from_minor(loan.outstanding_minor + loan.interest_outstanding_minor),
            "interest_method": "Fixed-term simple interest: principal x rate x months / 12, rounded half up to the paisa.",
            "status": loan.loan_status.value, "simulated": loan.simulation_flag, "source": "LENDER_SIMULATOR",
            "created_at": iso(loan.created_at), "disbursed_at": iso(loan.disbursed_at),
            "assessments": [{"id": a.id, "decision": a.decision.value, "assessed_ltv_percent": bps_to_percent(a.assessed_ltv_bps),
                             "max_ltv_percent": bps_to_percent(a.max_ltv_bps), "notes": a.notes,
                             "assessed_at": iso(a.assessed_at), "simulated": True} for a in assessments],
            "repayments": [{"id": r.id, "amount": from_minor(r.amount_minor), "reference": r.repayment_reference,
                            "outstanding_before": from_minor(r.outstanding_before_minor),
                            "outstanding_after": from_minor(r.outstanding_after_minor),
                            "status": r.repayment_status.value, "created_at": iso(r.created_at), "simulated": True}
                           for r in repayments]}


# ---------------------------------------------------------------- ledger effects

def _set_pledge(db: Session, p: m.CollateralPledge, status: PledgeStatus, op: m.LedgerOperation | None = None,
                **kw) -> None:
    previous = p.pledge_status
    p.pledge_status = status
    audit(db, entity_type="pledge", entity_id=p.id, operation_type="PLEDGE_STATUS", actor_id=p.investor_id,
          previous_state=previous, new_state=status, operation_id=op.id if op else None,
          ledger_transaction_id=op.transaction_id if op and op.transaction_id else None, **kw)


def _pledge_committed(db: Session, op: m.LedgerOperation) -> None:
    p = db.get(m.CollateralPledge, op.entity_id)
    p.pledge_operation_id = op.id
    apply_deltas(db, op)  # pledged += qty, owned unchanged (Rule 8.6)
    _set_pledge(db, p, PledgeStatus.ACTIVE, op, source=EventSource.DRUNIX_LEDGER)
    iss = db.get(m.AnshIssuance, p.issuance_id)
    asset_event(db, event_type="ANSH_PLEDGED", source=EventSource.DRUNIX_LEDGER, property_id=iss.property_id,
                issuance_id=iss.id, reference_id=p.id, ledger_transaction_id=op.transaction_id,
                description=f"{p.quantity:,} ANSH pledged as collateral; transfer-restricted.")


def _pledge_failed(db: Session, op: m.LedgerOperation) -> None:
    db.get(m.CollateralPledge, op.entity_id).pledge_operation_id = op.id
    _set_pledge(db, db.get(m.CollateralPledge, op.entity_id), PledgeStatus.FAILED, op, outcome="FAILED",
                detail={"error_code": op.error_code})


def _release_committed(db: Session, op: m.LedgerOperation) -> None:
    p = db.get(m.CollateralPledge, op.entity_id)
    p.release_operation_id = op.id
    apply_deltas(db, op)  # pledged -= qty, owned unchanged (Rule 9.4)
    p.released_at = op.confirmed_at or utcnow()
    _set_pledge(db, p, PledgeStatus.RELEASED, op, source=EventSource.DRUNIX_LEDGER)
    iss = db.get(m.AnshIssuance, p.issuance_id)
    asset_event(db, event_type="ANSH_PLEDGE_RELEASED", source=EventSource.DRUNIX_LEDGER, property_id=iss.property_id,
                issuance_id=iss.id, reference_id=p.id, ledger_transaction_id=op.transaction_id,
                description=f"{p.quantity:,} ANSH released from collateral; transferable again.")


def _release_failed(db: Session, op: m.LedgerOperation) -> None:
    # The units stay pledged on the ledger; the pledge returns to ACTIVE.
    db.get(m.CollateralPledge, op.entity_id).release_operation_id = op.id
    _set_pledge(db, db.get(m.CollateralPledge, op.entity_id), PledgeStatus.ACTIVE, op, outcome="RELEASE_FAILED",
                detail={"error_code": op.error_code})


executor.register(OperationType.ANSH_PLEDGE, committed=_pledge_committed, failed=_pledge_failed)
executor.register(OperationType.ANSH_RELEASE, committed=_release_committed, failed=_release_failed)


# ---------------------------------------------------------------- pledges

@router.get("/collateral/pledges")
def list_pledges(request: Request, status: PledgeStatus | None = None, page: int = 1, page_size: int = 20,
                 db: Session = Depends(get_db), user: m.User = Depends(current_user)):
    stmt = sa.select(m.CollateralPledge).order_by(m.CollateralPledge.created_at.desc())
    if user.role == UserRole.INVESTOR:
        stmt = stmt.where(m.CollateralPledge.investor_id == user.id)
    if status:
        stmt = stmt.where(m.CollateralPledge.pledge_status == status)
    return envelope(request, paginate(db, stmt, page, page_size, lambda p: pledge_view(db, p)))


@router.post("/collateral/pledges", status_code=201)
def create_pledge(body: PledgeIn, request: Request, db: Session = Depends(get_db),
                  user: m.User = Depends(current_user), ledger: LedgerPort = Depends(get_ledger),
                  settings: Settings = Depends(get_settings)):
    require_role(user, UserRole.INVESTOR)

    def op(_key: str):
        iss = get_or_404(db, m.AnshIssuance, body.issuance_id, "Issuance")
        if iss.issuance_status != IssuanceStatus.CONFIRMED:
            raise invalid_state("ANSH has not been issued.")
        check_available(ledger_position(db, ledger, iss, user), body.quantity, allow_pledged_message=False)  # Rule 8.2
        val = db.scalar(sa.select(m.PropertyValuation).filter_by(property_id=iss.property_id,
                                                                 purpose=ValuationPurpose.COLLATERAL)
                        .order_by(m.PropertyValuation.observed_at.desc()).limit(1))
        if val is None:  # Rule 8.3: never fall back to the market value
            raise invalid_state("No approved collateral valuation exists for this property.")
        p = m.CollateralPledge(investor_id=user.id, issuance_id=iss.id, quantity=body.quantity,
                               collateral_unit_value_minor=val.unit_value_minor,
                               collateral_value_minor=body.quantity * val.unit_value_minor,
                               currency=val.currency, valuation_id=val.id)
        db.add(p)
        db.flush()
        audit(db, entity_type="pledge", entity_id=p.id, operation_type="PLEDGE_REQUESTED", actor_id=user.id,
              new_state=PledgeStatus.REQUESTED, correlation_id=correlation_id(request),
              detail={"quantity": body.quantity, "collateral_value": from_minor(p.collateral_value_minor)})
        _set_pledge(db, p, PledgeStatus.APPROVED, detail={"reason": "Backend validation passed"})
        _set_pledge(db, p, PledgeStatus.SUBMITTED)
        db.commit()
        ledger_op = executor.submit_operation(
            db, ledger, settings, op_type=OperationType.ANSH_PLEDGE, entity_type="pledge", entity_id=p.id,
            # Proposed PledgeANSH command; the deployed chaincode does not implement it yet.
            command=lambda op_id: {"command_version": 1, "operation_id": op_id, "property_id": iss.property_id,
                                   "holder_id": identity(user), "pledge_id": p.id, "quantity": body.quantity},
            context={"issuance_id": iss.id, "pledge_id": p.id, "deltas": [delta(user.id, pledged=body.quantity)]},
            correlation_id=correlation_id(request))
        p.pledge_operation_id = ledger_op.id
        db.commit()
        return executor.outcome(ledger_op, pledge_view(db, p), created=True)

    return run_idempotent(request, db, "POST /collateral/pledges", {"user": user.id, **body.model_dump()}, op)


def _pledge_for(db: Session, pledge_id: str, user: m.User) -> m.CollateralPledge:
    p = get_or_404(db, m.CollateralPledge, pledge_id, "Pledge")
    if user.role == UserRole.INVESTOR and p.investor_id != user.id:
        raise forbidden()
    return p


@router.get("/collateral/pledges/{pledge_id}")
def get_pledge(pledge_id: str, request: Request, db: Session = Depends(get_db), user: m.User = Depends(current_user)):
    return envelope(request, pledge_view(db, _pledge_for(db, pledge_id, user)))


@router.get("/collateral/pledges/{pledge_id}/status")
def pledge_status(pledge_id: str, request: Request, db: Session = Depends(get_db), user: m.User = Depends(current_user)):
    v = pledge_view(db, _pledge_for(db, pledge_id, user))
    return envelope(request, {k: v[k] for k in ("id", "status", "pledge_operation", "release_operation")})


@router.post("/collateral/pledges/{pledge_id}/release")
def release_pledge(pledge_id: str, request: Request, db: Session = Depends(get_db),
                   user: m.User = Depends(current_user), ledger: LedgerPort = Depends(get_ledger),
                   settings: Settings = Depends(get_settings)):
    require_role(user, UserRole.INVESTOR, UserRole.LENDER)

    def op(_key: str):
        p = _pledge_for(db, pledge_id, user)
        if p.pledge_status != PledgeStatus.ACTIVE:
            raise invalid_state("Only an active pledge can be released.", status=p.pledge_status.value)
        loan = db.scalar(sa.select(m.Loan).filter_by(pledge_id=p.id))
        if user.role == UserRole.LENDER and (loan is None or loan.lender_id != user.id):
            raise forbidden("Only the loan's lender or the investor can release this pledge.")
        # Rules 9.3-9.5: release requires full repayment (partial release is not supported).
        if loan is not None and loan.loan_status not in (LoanStatus.REPAID, LoanStatus.REJECTED):
            raise invalid_state("The loan secured by this pledge must be fully repaid before release.",
                                loan_status=loan.loan_status.value, outstanding=from_minor(loan.outstanding_minor))
        iss = db.get(m.AnshIssuance, p.issuance_id)
        investor = db.get(m.User, p.investor_id)
        _set_pledge(db, p, PledgeStatus.RELEASE_PENDING, correlation_id=correlation_id(request))
        db.commit()
        ledger_op = executor.submit_operation(
            db, ledger, settings, op_type=OperationType.ANSH_RELEASE, entity_type="pledge", entity_id=p.id,
            command=lambda op_id: {"command_version": 1, "operation_id": op_id, "property_id": iss.property_id,
                                   "holder_id": identity(investor), "pledge_id": p.id},
            context={"issuance_id": iss.id, "pledge_id": p.id, "deltas": [delta(investor.id, pledged=-p.quantity)]},
            correlation_id=correlation_id(request))
        p.release_operation_id = ledger_op.id
        db.commit()
        return executor.outcome(ledger_op, pledge_view(db, p))

    return run_idempotent(request, db, f"POST /collateral/pledges/{pledge_id}/release", {"user": user.id}, op)


# ---------------------------------------------------------------- simulated loans

def _set_loan(db: Session, loan: m.Loan, status: LoanStatus, actor_id: str, **kw) -> None:
    previous = loan.loan_status
    loan.loan_status = status
    audit(db, entity_type="loan", entity_id=loan.id, operation_type="LOAN_STATUS", actor_id=actor_id,
          previous_state=previous, new_state=status, source=LENDER_SIM, **kw)


def _ltv(principal: int, collateral: int) -> int:
    return ratio_bps(principal, collateral)  # Rule 8.4: outstanding / collateral * 100


@router.post("/loans/applications", status_code=201)
def apply_loan(body: LoanIn, request: Request, db: Session = Depends(get_db), user: m.User = Depends(current_user),
               settings: Settings = Depends(get_settings)):
    require_role(user, UserRole.INVESTOR)
    p = _pledge_for(db, body.pledge_id, user)
    if p.pledge_status != PledgeStatus.ACTIVE:  # API_CONTRACTS 10.2 step 7
        raise invalid_state("A loan requires a pledge confirmed on DRUNIX.", pledge_status=p.pledge_status.value)
    if db.scalar(sa.select(m.Loan).filter_by(pledge_id=p.id)) is not None:
        raise invalid_state("This pledge already secures a loan.")
    principal = to_minor(body.principal, "principal")
    lender, offer = lenders.resolve(db, body.lender_id, body.offer_id)
    rate = offer.annual_rate_bps if body.interest_rate_bps is None else body.interest_rate_bps
    term = (12 if 12 in offer.tenures_months else offer.tenures_months[0]) if body.term_months is None else body.term_months
    if rate != offer.annual_rate_bps or term not in offer.tenures_months:
        raise ApiError(422, "INVALID_OFFER", "Rate and tenure must match the selected lender offer.",
                       {"offer": lenders.offer_view(offer, settings)})
    max_ltv = lenders.effective_max_ltv(offer, settings)
    if principal * 10000 > max_ltv * p.collateral_value_minor:  # exact integer comparison
        raise ApiError(409, "LTV_LIMIT_EXCEEDED", "The requested loan exceeds the maximum loan-to-value ratio.",
                       {"requested_ltv_percent": bps_to_percent(_ltv(principal, p.collateral_value_minor)),
                        "max_ltv_percent": bps_to_percent(max_ltv),
                        "max_principal": from_minor(max_ltv * p.collateral_value_minor // 10000)})
    loan = m.Loan(borrower_id=user.id, lender_id=lender.id, pledge_id=p.id, principal_minor=principal,
                  outstanding_minor=principal, currency=body.currency, collateral_value_minor=p.collateral_value_minor,
                  ltv_bps=_ltv(principal, p.collateral_value_minor), max_ltv_bps=max_ltv,
                  interest_rate_bps=rate, term_months=term, offer_id=offer.id)
    loan.interest_quote_minor = interest_quote(principal, rate, term)
    loan.interest_outstanding_minor = loan.interest_quote_minor
    db.add(loan)
    db.flush()
    audit(db, entity_type="loan", entity_id=loan.id, operation_type="LOAN_REQUESTED", actor_id=user.id,
          new_state=LoanStatus.REQUESTED, source=LENDER_SIM, correlation_id=correlation_id(request),
          detail={"principal": body.principal, "ltv_percent": bps_to_percent(loan.ltv_bps)})
    db.commit()
    return envelope(request, loan_view(db, loan))


@router.get("/loans")
def list_loans(request: Request, page: int = 1, page_size: int = 20, db: Session = Depends(get_db),
               user: m.User = Depends(current_user)):
    stmt = sa.select(m.Loan).order_by(m.Loan.created_at.desc())
    if user.role == UserRole.INVESTOR:
        stmt = stmt.where(m.Loan.borrower_id == user.id)
    elif user.role == UserRole.LENDER:
        stmt = stmt.where(m.Loan.lender_id == user.id)
    return envelope(request, paginate(db, stmt, page, page_size, lambda x: loan_view(db, x)))


def _loan_for(db: Session, loan_id: str, user: m.User) -> m.Loan:
    loan = get_or_404(db, m.Loan, loan_id, "Loan")
    if user.id not in (loan.borrower_id, loan.lender_id) and user.role != UserRole.ADMIN:
        raise forbidden()
    return loan


def _lender_loan(db: Session, loan_id: str, user: m.User) -> m.Loan:
    require_role(user, UserRole.LENDER)
    loan = _loan_for(db, loan_id, user)
    if loan.lender_id != user.id:
        raise forbidden("Only the assigned lender can act on this loan.")
    return loan


@router.get("/loans/{loan_id}")
def get_loan(loan_id: str, request: Request, db: Session = Depends(get_db), user: m.User = Depends(current_user)):
    return envelope(request, loan_view(db, _loan_for(db, loan_id, user)))


@router.post("/loans/{loan_id}/assess")
def assess_loan(loan_id: str, body: DecisionIn, request: Request, db: Session = Depends(get_db),
                user: m.User = Depends(current_user)):
    loan = _lender_loan(db, loan_id, user)
    if loan.loan_status not in (LoanStatus.REQUESTED, LoanStatus.UNDER_REVIEW):
        raise invalid_state("Loan is not awaiting assessment.", status=loan.loan_status.value)
    pledge = db.get(m.CollateralPledge, loan.pledge_id)
    if pledge.pledge_status != PledgeStatus.ACTIVE:
        raise invalid_state("Collateral pledge is not active.")
    decision = CreditDecision.ELIGIBLE if loan.ltv_bps <= loan.max_ltv_bps else CreditDecision.INELIGIBLE
    db.add(m.CreditAssessment(loan_id=loan.id, decision=decision, assessed_ltv_bps=loan.ltv_bps,
                              max_ltv_bps=loan.max_ltv_bps, notes=body.notes, assessed_by=user.id))
    if loan.loan_status == LoanStatus.REQUESTED:
        _set_loan(db, loan, LoanStatus.UNDER_REVIEW, user.id, detail={"decision": decision.value})
    db.commit()
    return envelope(request, loan_view(db, loan))


@router.post("/loans/{loan_id}/approve")
def approve_loan(loan_id: str, body: DecisionIn, request: Request, db: Session = Depends(get_db),
                 user: m.User = Depends(current_user)):
    loan = _lender_loan(db, loan_id, user)
    if loan.loan_status != LoanStatus.UNDER_REVIEW:
        raise invalid_state("Loan must be assessed before approval.", status=loan.loan_status.value)
    last = db.scalar(sa.select(m.CreditAssessment).filter_by(loan_id=loan.id)
                     .order_by(m.CreditAssessment.assessed_at.desc()).limit(1))
    if last is None or last.decision != CreditDecision.ELIGIBLE or loan.ltv_bps > loan.max_ltv_bps:
        raise ApiError(409, "LTV_LIMIT_EXCEEDED", "The latest simulated assessment does not permit approval.")
    _set_loan(db, loan, LoanStatus.APPROVED, user.id, detail={"notes": body.notes})
    db.commit()
    return envelope(request, loan_view(db, loan))


@router.post("/loans/{loan_id}/reject")
def reject_loan(loan_id: str, body: DecisionIn, request: Request, db: Session = Depends(get_db),
                user: m.User = Depends(current_user)):
    loan = _lender_loan(db, loan_id, user)
    if loan.loan_status not in (LoanStatus.REQUESTED, LoanStatus.UNDER_REVIEW, LoanStatus.APPROVED):
        raise invalid_state("Loan can no longer be rejected.", status=loan.loan_status.value)
    _set_loan(db, loan, LoanStatus.REJECTED, user.id, detail={"notes": body.notes})
    db.commit()
    return envelope(request, loan_view(db, loan))


@router.post("/loans/{loan_id}/disburse")
def disburse_loan(loan_id: str, request: Request, db: Session = Depends(get_db), user: m.User = Depends(current_user)):
    loan = _lender_loan(db, loan_id, user)
    if loan.loan_status != LoanStatus.APPROVED:
        raise invalid_state("Only an approved loan can be disbursed.", status=loan.loan_status.value)
    _set_loan(db, loan, LoanStatus.DISBURSED, user.id, detail={"amount": from_minor(loan.principal_minor)})
    loan.disbursed_at = utcnow()
    # Simulated: the principal lands in the borrower's demo wallet, once.
    wallet.move(db, loan.borrower_id, WalletEntryKind.DISBURSEMENT, loan.principal_minor,
                f"DISBURSEMENT:{loan.id}", loan_id=loan.id)
    _set_loan(db, loan, LoanStatus.ACTIVE, user.id)
    db.commit()
    return envelope(request, loan_view(db, loan))


@router.post("/loans/{loan_id}/repayments")
def repay_loan(loan_id: str, body: RepaymentIn, request: Request, db: Session = Depends(get_db),
               user: m.User = Depends(current_user)):
    def op(key: str):
        loan = _loan_for(db, loan_id, user)
        if loan.borrower_id != user.id:
            raise forbidden("Only the borrower can repay this loan.")
        if loan.loan_status not in (LoanStatus.ACTIVE, LoanStatus.PARTIALLY_REPAID):
            raise invalid_state("Loan is not in repayment.", status=loan.loan_status.value)
        amount = to_minor(body.amount, "amount")
        before = loan.outstanding_minor + loan.interest_outstanding_minor
        if amount > before:  # Rule 9.1
            raise ApiError(409, "REPAYMENT_EXCEEDS_OUTSTANDING", "Repayment cannot exceed the outstanding amount.",
                           {"outstanding": from_minor(before), "amount": body.amount})
        rep_key = f"repay:{loan.id}:{key}"[:128]
        # Simulated: debit the borrower's demo wallet (fails cleanly when the balance is short).
        wallet.move(db, user.id, WalletEntryKind.REPAYMENT, amount, f"REPAYMENT:{rep_key}", loan_id=loan.id)
        to_interest = min(amount, loan.interest_outstanding_minor)  # interest first, then principal
        loan.interest_outstanding_minor -= to_interest
        loan.outstanding_minor -= amount - to_interest  # Rule 9.2
        loan.ltv_bps = _ltv(loan.outstanding_minor, loan.collateral_value_minor)
        after = loan.outstanding_minor + loan.interest_outstanding_minor
        rep = m.LoanRepayment(loan_id=loan.id, amount_minor=amount, currency=body.currency,
                              outstanding_before_minor=before, outstanding_after_minor=after,
                              repayment_reference=f"SIM-REPAY-{uuid.uuid4().hex[:12].upper()}",
                              idempotency_key=rep_key, repayment_status=RepaymentStatus.SUCCESS)
        db.add(rep)
        _set_loan(db, loan, LoanStatus.REPAID if after == 0 else LoanStatus.PARTIALLY_REPAID,
                  user.id, correlation_id=correlation_id(request),
                  detail={"amount": body.amount, "to_interest": from_minor(to_interest), "outstanding_after": from_minor(after)})
        db.commit()
        return 200, loan_view(db, loan)

    return run_idempotent(request, db, f"POST /loans/{loan_id}/repayments", {"user": user.id, **body.model_dump()}, op)
