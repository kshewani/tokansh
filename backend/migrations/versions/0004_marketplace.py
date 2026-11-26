"""Add durable issuer offerings and purchase reservations."""
from alembic import op
import sqlalchemy as sa

revision = "0004_marketplace"
down_revision = "0003_demo_cash"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "sale_offerings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("property_id", sa.String(36), sa.ForeignKey("properties.id"), nullable=False),
        sa.Column("issuer_id", sa.String(36), nullable=False),
        sa.Column("offered_quantity", sa.BigInteger(), nullable=False),
        sa.Column("sold_quantity", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("reserved_quantity", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("price_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="ACTIVE"),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("updated_at", sa.String(40), nullable=False),
        sa.CheckConstraint("offered_quantity > 0", name="ck_sale_offering_offered_positive"),
        sa.CheckConstraint("sold_quantity >= 0", name="ck_sale_offering_sold_nonnegative"),
        sa.CheckConstraint("reserved_quantity >= 0", name="ck_sale_offering_reserved_nonnegative"),
        sa.CheckConstraint("sold_quantity + reserved_quantity <= offered_quantity", name="ck_sale_offering_conservation"),
        sa.CheckConstraint("price_minor > 0", name="ck_sale_offering_price_positive"),
        sa.CheckConstraint("currency = 'INR'", name="ck_sale_offering_currency"),
        sa.CheckConstraint("status IN ('ACTIVE','SOLD_OUT','CLOSED')", name="ck_sale_offering_status"),
    )
    op.create_index("ix_sale_offerings_property_id", "sale_offerings", ["property_id"])
    op.create_index("ix_sale_offerings_issuer_id", "sale_offerings", ["issuer_id"])
    op.create_index("ix_sale_offerings_status", "sale_offerings", ["status"])
    # SQLite has no portable partial UNIQUE constraint in CREATE TABLE; this
    # index enforces one active offering while preserving historical records.
    op.create_index("uq_sale_offerings_active_property", "sale_offerings", ["property_id"],
                    unique=True, sqlite_where=sa.text("status = 'ACTIVE'"))

    op.create_table(
        "purchase_operations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("offering_id", sa.String(36), sa.ForeignKey("sale_offerings.id"), nullable=False),
        sa.Column("property_id", sa.String(36), sa.ForeignKey("properties.id"), nullable=False),
        sa.Column("buyer_id", sa.String(36), nullable=False),
        sa.Column("seller_id", sa.String(36), nullable=False),
        sa.Column("quantity", sa.BigInteger(), nullable=False),
        sa.Column("price_minor", sa.BigInteger(), nullable=False),
        sa.Column("total_amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("transfer_operation_id", sa.String(36), nullable=True),
        sa.Column("transaction_id", sa.String(128), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("updated_at", sa.String(40), nullable=False),
        sa.UniqueConstraint("buyer_id", "idempotency_key", name="uq_purchase_buyer_key"),
        sa.CheckConstraint("quantity > 0", name="ck_purchase_quantity_positive"),
        sa.CheckConstraint("price_minor > 0", name="ck_purchase_price_positive"),
        sa.CheckConstraint("total_amount_minor > 0", name="ck_purchase_total_positive"),
        sa.CheckConstraint("currency = 'INR'", name="ck_purchase_currency"),
        sa.CheckConstraint("state IN ('RESERVED','PREPARING','PREPARED','SUBMISSION_PENDING','SUBMITTED','UNKNOWN','COMMITTED_PENDING_SETTLEMENT','SETTLED','FAILED','COMMITTED_INVALID','RECONCILIATION_REQUIRED')", name="ck_purchase_state"),
    )
    op.create_index("ix_purchase_operations_offering_id", "purchase_operations", ["offering_id"])
    op.create_index("ix_purchase_operations_property_id", "purchase_operations", ["property_id"])
    op.create_index("ix_purchase_operations_buyer_id", "purchase_operations", ["buyer_id"])
    op.create_index("ix_purchase_operations_seller_id", "purchase_operations", ["seller_id"])
    op.create_index("ix_purchase_operations_state", "purchase_operations", ["state"])

    # Add explicit, auditable purchase cash entries while preserving all old
    # wallet rows. SQLite requires table recreation to change a CHECK clause.
    with op.batch_alter_table("demo_cash_entries", recreate="always") as batch:
        batch.add_column(sa.Column("purchase_id", sa.String(36), nullable=True))
        batch.create_foreign_key("fk_demo_cash_purchase", "purchase_operations", ["purchase_id"], ["id"])
        batch.drop_constraint("ck_demo_cash_kind", type_="check")
        batch.create_check_constraint("ck_demo_cash_kind", "kind IN ('DEMO_FUNDS','WITHDRAWAL','DISBURSEMENT','REPAYMENT','PURCHASE_DEBIT','SALE_PROCEEDS')")
        batch.create_unique_constraint("uq_demo_cash_purchase_kind", ["purchase_id", "kind"])


def downgrade():
    with op.batch_alter_table("demo_cash_entries", recreate="always") as batch:
        batch.drop_constraint("fk_demo_cash_purchase", type_="foreignkey")
        batch.drop_constraint("uq_demo_cash_purchase_kind", type_="unique")
        batch.drop_constraint("ck_demo_cash_kind", type_="check")
        batch.create_check_constraint("ck_demo_cash_kind", "kind IN ('DEMO_FUNDS','WITHDRAWAL','DISBURSEMENT','REPAYMENT')")
        batch.drop_column("purchase_id")
    op.drop_index("ix_purchase_operations_state", table_name="purchase_operations")
    op.drop_index("ix_purchase_operations_seller_id", table_name="purchase_operations")
    op.drop_index("ix_purchase_operations_buyer_id", table_name="purchase_operations")
    op.drop_index("ix_purchase_operations_property_id", table_name="purchase_operations")
    op.drop_index("ix_purchase_operations_offering_id", table_name="purchase_operations")
    op.drop_table("purchase_operations")
    op.drop_index("uq_sale_offerings_active_property", table_name="sale_offerings")
    op.drop_index("ix_sale_offerings_status", table_name="sale_offerings")
    op.drop_index("ix_sale_offerings_issuer_id", table_name="sale_offerings")
    op.drop_index("ix_sale_offerings_property_id", table_name="sale_offerings")
    op.drop_table("sale_offerings")
