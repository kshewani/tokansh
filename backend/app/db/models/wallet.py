import sqlalchemy as sa

from app.db.base import (Base, created_at, currency_check, currency_col, enum_col, fk, flag, money, text, updated_at,
                         uuid_pk)
from app.db.enums import WalletEntryKind


class DemoCashAccount(Base):
    """Simulated INR cash for one demo user. No bank, no real money (ADR-010)."""

    __tablename__ = "demo_cash_accounts"
    __table_args__ = (
        currency_check(),
        sa.UniqueConstraint("user_id"),
        sa.CheckConstraint("balance_minor >= 0", name="balance_non_negative"),
        sa.CheckConstraint("simulation_flag = 1", name="cash_is_simulated"),
    )

    id = uuid_pk()
    user_id = fk("users.id", index=False)
    balance_minor = money(default=0)
    currency = currency_col()
    simulation_flag = flag(True)
    created_at = created_at()
    updated_at = updated_at()


class DemoCashEntry(Base):
    """One simulated cash movement. ``reference_key`` is unique, so a disbursement,
    repayment or top-up can never be applied twice."""

    __tablename__ = "demo_cash_entries"
    __table_args__ = (
        currency_check(),
        sa.UniqueConstraint("reference_key"),
        sa.CheckConstraint("amount_minor > 0", name="amount_positive"),
        sa.CheckConstraint("balance_after_minor >= 0", name="balance_after_non_negative"),
        sa.CheckConstraint("simulation_flag = 1", name="entry_is_simulated"),
        sa.CheckConstraint("kind NOT IN ('DISBURSEMENT','REPAYMENT') OR loan_id IS NOT NULL", name="loan_entries_need_loan"),
        sa.Index("ix_demo_cash_entries_account_time", "account_id", "created_at"),
    )

    id = uuid_pk()
    account_id = fk("demo_cash_accounts.id", index=False)
    kind = enum_col(WalletEntryKind)
    amount_minor = money()
    balance_after_minor = money()
    currency = currency_col()
    loan_id = fk("loans.id", nullable=True)
    reference_key = text(200)
    simulation_flag = flag(True)
    created_at = created_at()
