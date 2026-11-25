import sqlalchemy as sa

from app.db.base import (Base, bps, created_at, integer, currency_check, currency_col, enum_col, fk, flag, money,
                         quantity as qty, text, timestamp, updated_at, uuid_pk)
from app.db.enums import CreditDecision, LoanStatus, PledgeStatus, RepaymentStatus


class CollateralPledge(Base):
    """ANSH restricted as collateral (DOMAIN_MODEL 2.11). The lock itself lives on DRUNIX."""

    __tablename__ = "collateral_pledges"
    __table_args__ = (
        currency_check(),
        sa.CheckConstraint("quantity > 0", name="quantity_positive"),
        sa.CheckConstraint("collateral_unit_value_minor > 0", name="unit_value_positive"),
        sa.CheckConstraint("collateral_value_minor = quantity * collateral_unit_value_minor",
                           name="value_is_qty_times_unit_value"),  # Rule 8.3
        sa.CheckConstraint("pledge_status NOT IN ('ACTIVE','RELEASE_PENDING','RELEASED') "
                           "OR pledge_operation_id IS NOT NULL", name="active_needs_ledger_pledge"),
        sa.CheckConstraint("pledge_status <> 'RELEASED' OR (release_operation_id IS NOT NULL "
                           "AND released_at IS NOT NULL)", name="released_needs_ledger_release"),
    )

    id = uuid_pk()
    investor_id = fk("users.id")
    issuance_id = fk("ansh_issuances.id")
    quantity = qty()
    collateral_unit_value_minor = money()
    collateral_value_minor = money()
    currency = currency_col()
    valuation_id = fk("property_valuations.id", nullable=True)  # which valuation was used, and when
    pledge_status = enum_col(PledgeStatus, default=PledgeStatus.REQUESTED, index=True)
    pledge_operation_id = fk("ledger_operations.id", nullable=True)
    release_operation_id = fk("ledger_operations.id", nullable=True)
    created_at = created_at()
    updated_at = updated_at()
    released_at = timestamp()


class Loan(Base):
    """Simulated financing backed by a pledge (DOMAIN_MODEL 2.12). Principal-only in the MVP (Rule 9.2)."""

    __tablename__ = "loans"
    __table_args__ = (
        currency_check(),
        sa.UniqueConstraint("pledge_id"),
        sa.CheckConstraint("principal_minor > 0", name="principal_positive"),
        sa.CheckConstraint("outstanding_minor >= 0 AND outstanding_minor <= principal_minor",
                           name="outstanding_in_range"),  # Rule 9.1: balance never negative
        sa.CheckConstraint("collateral_value_minor > 0", name="collateral_positive"),
        sa.CheckConstraint("ltv_bps >= 0", name="ltv_non_negative"),
        sa.CheckConstraint("max_ltv_bps > 0 AND max_ltv_bps <= 10000", name="max_ltv_in_range"),
        sa.CheckConstraint("interest_rate_bps >= 0", name="interest_non_negative"),
        sa.CheckConstraint("loan_status <> 'REPAID' OR outstanding_minor = 0", name="repaid_means_zero"),
        sa.CheckConstraint("simulation_flag = 1", name="mvp_loans_are_simulated"),
        sa.CheckConstraint("term_months >= 1 AND term_months <= 36", name="term_in_range"),
        sa.CheckConstraint("interest_quote_minor >= 0", name="interest_quote_non_negative"),
        sa.CheckConstraint("interest_outstanding_minor >= 0 AND interest_outstanding_minor <= interest_quote_minor",
                           name="interest_outstanding_in_range"),
    )

    id = uuid_pk()
    borrower_id = fk("users.id")
    lender_id = fk("users.id")
    pledge_id = fk("collateral_pledges.id", index=False)
    principal_minor = money()
    outstanding_minor = money()
    interest_rate_bps = bps(default=0)
    # Fixed-term simple interest, modelled separately from principal (Rule 9.2):
    # quote = principal x rate_bps x term_months / 120000, rounded half up to the paisa.
    term_months = integer(default=12)
    interest_quote_minor = money(default=0)
    interest_outstanding_minor = money(default=0)
    offer_id = text(40, nullable=True)  # lender catalogue offer (app/modules/lenders.py)
    currency = currency_col()
    collateral_value_minor = money()
    ltv_bps = bps()       # Outstanding / Collateral, in basis points (Rule 8.4)
    max_ltv_bps = bps()   # configured threshold applied at approval (Rule 8.5)
    loan_status = enum_col(LoanStatus, default=LoanStatus.REQUESTED, index=True)
    simulation_flag = flag(True)
    created_at = created_at()
    updated_at = updated_at()
    disbursed_at = timestamp()
    maturity_date = sa.orm.mapped_column(sa.Date, nullable=True)


class CreditAssessment(Base):
    """Outcome of the simulated lender assessment, kept with its inputs for audit."""

    __tablename__ = "credit_assessments"
    __table_args__ = (sa.CheckConstraint("simulation_flag = 1", name="mvp_assessments_are_simulated"),)

    id = uuid_pk()
    loan_id = fk("loans.id")
    decision = enum_col(CreditDecision)
    assessed_ltv_bps = bps()
    max_ltv_bps = bps()
    notes = text(500, nullable=True)
    assessed_by = fk("users.id", nullable=True, index=False)
    simulation_flag = flag(True)
    assessed_at = created_at()


class LoanRepayment(Base):
    """Simulated repayment (DOMAIN_MODEL 2.13)."""

    __tablename__ = "loan_repayments"
    __table_args__ = (
        currency_check(),
        sa.UniqueConstraint("repayment_reference"),
        sa.UniqueConstraint("idempotency_key"),
        sa.CheckConstraint("amount_minor > 0", name="amount_positive"),
        sa.CheckConstraint("outstanding_after_minor IS NULL OR outstanding_after_minor >= 0",
                           name="outstanding_after_non_negative"),
        sa.CheckConstraint("simulation_flag = 1", name="mvp_repayments_are_simulated"),
    )

    id = uuid_pk()
    loan_id = fk("loans.id")
    amount_minor = money()
    currency = currency_col()
    outstanding_before_minor = money(nullable=True)
    outstanding_after_minor = money(nullable=True)
    repayment_reference = text(128)
    idempotency_key = text(128)
    repayment_status = enum_col(RepaymentStatus, default=RepaymentStatus.INITIATED)
    simulation_flag = flag(True)
    created_at = created_at()
