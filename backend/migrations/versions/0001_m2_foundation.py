"""Persistent off-chain property onboarding and idempotent application operations."""
from alembic import op
import sqlalchemy as sa

revision = "0001_m2"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("properties",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("location", sa.String(300), nullable=False),
        sa.Column("category", sa.String(100), nullable=False),
        sa.Column("valuation_minor", sa.BigInteger(), nullable=False),
        sa.Column("proposed_supply", sa.BigInteger(), nullable=False),
        sa.Column("issue_price_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("issuer_id", sa.String(36), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.CheckConstraint("valuation_minor > 0", name="ck_property_valuation_positive"),
        sa.CheckConstraint("issue_price_minor > 0", name="ck_property_price_positive"),
        sa.CheckConstraint("proposed_supply > 0", name="ck_property_supply_positive"),
        sa.CheckConstraint("status = 'DRAFT'", name="ck_m2_property_draft_only"),
        sa.CheckConstraint("currency = 'INR'", name="ck_property_currency"),
    )
    op.create_index("ix_properties_created_at", "properties", ["created_at"])
    op.create_table("application_operations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("actor_id", sa.String(36), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("response_json", sa.Text(), nullable=True),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column("correlation_id", sa.String(128), nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.UniqueConstraint("actor_id", "idempotency_key", name="uq_operation_actor_key"),
    )
    op.create_table("property_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("property_id", sa.String(36), sa.ForeignKey("properties.id"), nullable=False),
        sa.Column("operation_id", sa.String(36), sa.ForeignKey("application_operations.id"), nullable=False, unique=True),
        sa.Column("actor_id", sa.String(36), nullable=False),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("event_source", sa.String(32), nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
    )
    op.create_index("ix_property_events_property_id", "property_events", ["property_id"])


def downgrade():
    op.drop_table("property_events")
    op.drop_table("application_operations")
    op.drop_table("properties")
