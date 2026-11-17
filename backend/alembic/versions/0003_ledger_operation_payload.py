"""ledger_operations: keep the exact request payload

The backend needs the arguments it sent and the balance changes it expects
(``deltas``) in order to apply projections only after a confirmed commit, to
reconcile an ambiguous outcome, and to reconstruct record-date holdings for
distributions from committed operations (BUSINESS_RULES 10.6).

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-17
"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("ledger_operations") as batch:
        batch.add_column(sa.Column("request_payload", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("ledger_operations") as batch:
        batch.drop_column("request_payload")
