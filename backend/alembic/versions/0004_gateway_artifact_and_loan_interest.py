"""ledger artifact for the private gateway; fixed-term interest on simulated loans

* ledger_operations.artifact_json: the signed, endorsed transaction returned by the
  TokANSH Go gateway's prepare step. Required to submit exactly once and to query
  commit status after a restart (gateway/TRANSACTIONS.md).
* loans.term_months, interest_quote_minor, interest_outstanding_minor: simple
  fixed-term interest modelled separately from principal (BUSINESS_RULES 9.2).

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-21
"""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("ledger_operations") as batch:
        batch.add_column(sa.Column("artifact_json", sa.Text(), nullable=True))
    with op.batch_alter_table("loans") as batch:
        batch.add_column(sa.Column("term_months", sa.Integer(), nullable=False, server_default="12"))
        batch.add_column(sa.Column("interest_quote_minor", sa.BigInteger(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("interest_outstanding_minor", sa.BigInteger(), nullable=False, server_default="0"))
        batch.create_check_constraint("term_in_range", "term_months >= 1 AND term_months <= 36")
        batch.create_check_constraint("interest_quote_non_negative", "interest_quote_minor >= 0")
        batch.create_check_constraint("interest_outstanding_in_range",
                                      "interest_outstanding_minor >= 0 AND interest_outstanding_minor <= interest_quote_minor")


def downgrade() -> None:
    with op.batch_alter_table("loans") as batch:
        batch.drop_constraint("interest_outstanding_in_range", type_="check")
        batch.drop_constraint("interest_quote_non_negative", type_="check")
        batch.drop_constraint("term_in_range", type_="check")
        batch.drop_column("interest_outstanding_minor")
        batch.drop_column("interest_quote_minor")
        batch.drop_column("term_months")
    with op.batch_alter_table("ledger_operations") as batch:
        batch.drop_column("artifact_json")
