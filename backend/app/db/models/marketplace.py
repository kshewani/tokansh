import sqlalchemy as sa

from app.db.base import (Base, created_at, currency_check, currency_col, enum_col, fk, flag, money, quantity as qty,
                         text, timestamp, updated_at, uuid_pk)
from app.db.enums import ListingStatus, OrderStatus, PaymentKind, PaymentStatus


class MarketplaceListing(Base):
    """Offer to sell ANSH (DOMAIN_MODEL 2.7). Application-owned."""

    __tablename__ = "marketplace_listings"
    __table_args__ = (
        currency_check(),
        sa.CheckConstraint("quantity > 0", name="quantity_positive"),
        sa.CheckConstraint("remaining_quantity >= 0 AND remaining_quantity <= quantity", name="remaining_in_range"),
        sa.CheckConstraint("unit_price_minor > 0", name="price_positive"),
        sa.CheckConstraint("listing_status <> 'FILLED' OR remaining_quantity = 0", name="filled_means_empty"),
        sa.Index("ix_marketplace_listings_open", "issuance_id", "listing_status"),
    )

    id = uuid_pk()
    seller_id = fk("users.id")
    issuance_id = fk("ansh_issuances.id", index=False)
    quantity = qty()
    remaining_quantity = qty()  # reduced only after a confirmed transfer (Rule 5.4)
    unit_price_minor = money()
    currency = currency_col()
    listing_status = enum_col(ListingStatus, default=ListingStatus.DRAFT)
    created_at = created_at()
    updated_at = updated_at()
    expires_at = timestamp()


class PurchaseOrder(Base):
    """Investor's purchase intent (DOMAIN_MODEL 2.8)."""

    __tablename__ = "purchase_orders"
    __table_args__ = (
        currency_check(),
        sa.UniqueConstraint("idempotency_key"),
        sa.CheckConstraint("quantity > 0", name="quantity_positive"),
        sa.CheckConstraint("unit_price_minor > 0", name="price_positive"),
        sa.CheckConstraint("total_amount_minor = quantity * unit_price_minor", name="total_is_qty_times_price"),
        sa.CheckConstraint("buyer_id <> seller_id", name="buyer_is_not_seller"),
        # A completed order must point at the ledger operation that moved the units.
        sa.CheckConstraint("order_status <> 'COMPLETED' OR transfer_operation_id IS NOT NULL",
                           name="completed_needs_transfer"),
    )

    id = uuid_pk()
    buyer_id = fk("users.id")
    seller_id = fk("users.id")
    listing_id = fk("marketplace_listings.id")
    issuance_id = fk("ansh_issuances.id")
    quantity = qty()
    unit_price_minor = money()
    total_amount_minor = money()  # computed by the backend (Rule 5.3)
    currency = currency_col()
    order_status = enum_col(OrderStatus, default=OrderStatus.CREATED, index=True)
    failure_reason = text(300, nullable=True)
    idempotency_key = text(128)
    transfer_operation_id = fk("ledger_operations.id", nullable=True)
    created_at = created_at()
    updated_at = updated_at()


class PaymentRecord(Base):
    """Simulated payment attempt (DOMAIN_MODEL 2.9). Never proof of ownership."""

    __tablename__ = "payment_records"
    __table_args__ = (
        currency_check(),
        sa.UniqueConstraint("payment_reference"),
        sa.CheckConstraint("amount_minor > 0", name="amount_positive"),
        sa.CheckConstraint("simulation_flag = 1", name="mvp_payments_are_simulated"),
        sa.CheckConstraint("payment_kind <> 'REFUND' OR refund_of_payment_id IS NOT NULL", name="refund_needs_original"),
    )

    id = uuid_pk()
    order_id = fk("purchase_orders.id")
    payment_kind = enum_col(PaymentKind, default=PaymentKind.PURCHASE)
    refund_of_payment_id = fk("payment_records.id", nullable=True)
    payment_reference = text(128)
    amount_minor = money()
    currency = currency_col()
    payment_status = enum_col(PaymentStatus, default=PaymentStatus.INITIATED)
    failure_reason = text(300, nullable=True)
    simulation_flag = flag(True)
    created_at = created_at()
    completed_at = timestamp()
