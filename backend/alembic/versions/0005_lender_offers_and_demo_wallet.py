"""lender offers on loans; simulated demo cash wallet

* loans.offer_id: the lender catalogue offer a loan was taken under.
* demo_cash_accounts / demo_cash_entries: simulated INR cash. Disbursement credits,
  repayment debits, demo top-ups and withdrawals. Unique reference keys prevent a
  movement being applied twice. No real money.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-25
"""
from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

KINDS = ("DEMO_FUNDS", "WITHDRAWAL", "DISBURSEMENT", "REPAYMENT")


def upgrade() -> None:
    with op.batch_alter_table("loans") as batch:
        batch.add_column(sa.Column("offer_id", sa.String(40), nullable=True))
    op.create_table(
        "demo_cash_accounts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("balance_minor", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(3), nullable=False, server_default="INR"),
        sa.Column("simulation_flag", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", name="uq_demo_cash_accounts_user_id"),
        sa.CheckConstraint("length(currency) = 3 AND currency = upper(currency)", name="currency_iso"),
        sa.CheckConstraint("balance_minor >= 0", name="balance_non_negative"),
        sa.CheckConstraint("simulation_flag = 1", name="cash_is_simulated"),
    )
    op.create_table(
        "demo_cash_entries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("account_id", sa.String(36), sa.ForeignKey("demo_cash_accounts.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("kind", sa.Enum(*KINDS, name="wallet_entry_kind", native_enum=False, create_constraint=True, length=40),
                  nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("balance_after_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="INR"),
        sa.Column("loan_id", sa.String(36), sa.ForeignKey("loans.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("reference_key", sa.String(200), nullable=False),
        sa.Column("simulation_flag", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("reference_key", name="uq_demo_cash_entries_reference_key"),
        sa.CheckConstraint("length(currency) = 3 AND currency = upper(currency)", name="currency_iso"),
        sa.CheckConstraint("amount_minor > 0", name="amount_positive"),
        sa.CheckConstraint("balance_after_minor >= 0", name="balance_after_non_negative"),
        sa.CheckConstraint("simulation_flag = 1", name="entry_is_simulated"),
        sa.CheckConstraint("kind NOT IN ('DISBURSEMENT','REPAYMENT') OR loan_id IS NOT NULL",
                           name="loan_entries_need_loan"),
    )
    op.create_index("ix_demo_cash_entries_loan_id", "demo_cash_entries", ["loan_id"])
    op.create_index("ix_demo_cash_entries_account_time", "demo_cash_entries", ["account_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_demo_cash_entries_account_time", table_name="demo_cash_entries")
    op.drop_index("ix_demo_cash_entries_loan_id", table_name="demo_cash_entries")
    op.drop_table("demo_cash_entries")
    op.drop_table("demo_cash_accounts")
    with op.batch_alter_table("loans") as batch:
        batch.drop_column("offer_id")
