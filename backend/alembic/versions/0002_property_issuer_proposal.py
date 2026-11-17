"""property: issuer's proposed supply and issue price

The UI's new-property form (frontend/src/api/contracts.ts, NewProperty) sends
proposed_supply and issue_price. Until now only the reviewer's approved_supply
was stored. Both columns are optional while a property is a DRAFT and required
once it is submitted for review.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-17
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

CHECKS = [
    ("proposed_supply_positive", "proposed_supply IS NULL OR proposed_supply > 0"),
    ("proposed_price_positive", "proposed_issue_price_minor IS NULL OR proposed_issue_price_minor > 0"),
    ("submitted_needs_proposal",
     "approval_status = 'DRAFT' OR (proposed_supply IS NOT NULL AND proposed_issue_price_minor IS NOT NULL)"),
]


def upgrade() -> None:
    # Existing non-draft rows have no proposal to backfill; use the approved supply where there is one.
    with op.batch_alter_table("properties") as batch:
        batch.add_column(sa.Column("proposed_supply", sa.BigInteger(), nullable=True))
        batch.add_column(sa.Column("proposed_issue_price_minor", sa.BigInteger(), nullable=True))
    op.execute("UPDATE properties SET proposed_supply = approved_supply WHERE proposed_supply IS NULL")
    op.execute("UPDATE properties SET proposed_issue_price_minor = (SELECT MIN(i.issue_price_minor) FROM ansh_issuances i "
               "WHERE i.property_id = properties.id) WHERE proposed_issue_price_minor IS NULL")
    with op.batch_alter_table("properties") as batch:
        for name, sql in CHECKS:
            batch.create_check_constraint(op.f(f"ck_properties_{name}"), sql)


def downgrade() -> None:
    with op.batch_alter_table("properties") as batch:
        for name, _ in reversed(CHECKS):
            batch.drop_constraint(op.f(f"ck_properties_{name}"), type_="check")
        batch.drop_column("proposed_issue_price_minor")
        batch.drop_column("proposed_supply")
