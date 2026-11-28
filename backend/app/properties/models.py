from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Property(Base):
    __tablename__ = "properties"
    __table_args__ = (
        CheckConstraint("valuation_minor > 0", name="ck_property_valuation_positive"),
        CheckConstraint("issue_price_minor > 0", name="ck_property_price_positive"),
        CheckConstraint("proposed_supply > 0", name="ck_property_supply_positive"),
        CheckConstraint("status = 'DRAFT'", name="ck_m2_property_draft_only"),
        CheckConstraint("currency = 'INR'", name="ck_property_currency"),
        Index("uq_properties_friendly_symbol", "friendly_symbol", unique=True),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    location: Mapped[str] = mapped_column(String(300))
    category: Mapped[str] = mapped_column(String(100))
    valuation_minor: Mapped[int] = mapped_column(BigInteger)
    proposed_supply: Mapped[int] = mapped_column(BigInteger)
    issue_price_minor: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3))
    issuer_id: Mapped[str] = mapped_column(String(36))
    friendly_symbol: Mapped[str | None] = mapped_column(String(32), nullable=True)
    size_description: Mapped[str | None] = mapped_column(String(120), nullable=True)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    risk_profile: Mapped[str | None] = mapped_column(String(240), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="DRAFT")
    created_at: Mapped[str] = mapped_column(String(32), index=True)


class ApplicationOperation(Base):
    __tablename__ = "application_operations"
    __table_args__ = (UniqueConstraint("actor_id", "idempotency_key", name="uq_operation_actor_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    actor_id: Mapped[str] = mapped_column(String(36))
    idempotency_key: Mapped[str] = mapped_column(String(128))
    request_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32))
    response_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    response_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    correlation_id: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[str] = mapped_column(String(32))


class PropertyEvent(Base):
    __tablename__ = "property_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    property_id: Mapped[str] = mapped_column(ForeignKey("properties.id"), index=True)
    operation_id: Mapped[str] = mapped_column(ForeignKey("application_operations.id"), unique=True)
    actor_id: Mapped[str] = mapped_column(String(36))
    event_type: Mapped[str] = mapped_column(String(40))
    event_source: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[str] = mapped_column(String(32))


class SaleOffering(Base):
    __tablename__ = "sale_offerings"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    property_id: Mapped[str] = mapped_column(ForeignKey("properties.id"), index=True)
    issuer_id: Mapped[str] = mapped_column(String(36), index=True)
    offered_quantity: Mapped[int] = mapped_column(BigInteger)
    sold_quantity: Mapped[int] = mapped_column(BigInteger, default=0)
    reserved_quantity: Mapped[int] = mapped_column(BigInteger, default=0)
    price_minor: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3))
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE", index=True)
    created_at: Mapped[str] = mapped_column(String(40))
    updated_at: Mapped[str] = mapped_column(String(40))

    __table_args__ = (
        CheckConstraint("offered_quantity > 0", name="ck_sale_offering_offered_positive"),
        CheckConstraint("sold_quantity >= 0", name="ck_sale_offering_sold_nonnegative"),
        CheckConstraint("reserved_quantity >= 0", name="ck_sale_offering_reserved_nonnegative"),
        CheckConstraint("sold_quantity + reserved_quantity <= offered_quantity", name="ck_sale_offering_conservation"),
        CheckConstraint("price_minor > 0", name="ck_sale_offering_price_positive"),
        CheckConstraint("currency = 'INR'", name="ck_sale_offering_currency"),
        CheckConstraint("status IN ('ACTIVE','SOLD_OUT','CLOSED')", name="ck_sale_offering_status"),
        Index("uq_sale_offerings_active_property", "property_id", unique=True,
              sqlite_where=text("status = 'ACTIVE'")),
    )


class PurchaseOperation(Base):
    __tablename__ = "purchase_operations"
    __table_args__ = (
        UniqueConstraint("buyer_id", "idempotency_key", name="uq_purchase_buyer_key"),
        CheckConstraint("quantity > 0", name="ck_purchase_quantity_positive"),
        CheckConstraint("price_minor > 0", name="ck_purchase_price_positive"),
        CheckConstraint("total_amount_minor > 0", name="ck_purchase_total_positive"),
        CheckConstraint("currency = 'INR'", name="ck_purchase_currency"),
        CheckConstraint("state IN ('RESERVED','PREPARING','PREPARED','SUBMISSION_PENDING','SUBMITTED','UNKNOWN','COMMITTED_PENDING_SETTLEMENT','SETTLED','FAILED','COMMITTED_INVALID','RECONCILIATION_REQUIRED')", name="ck_purchase_state"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    offering_id: Mapped[str] = mapped_column(ForeignKey("sale_offerings.id"), index=True)
    property_id: Mapped[str] = mapped_column(ForeignKey("properties.id"), index=True)
    buyer_id: Mapped[str] = mapped_column(String(36), index=True)
    seller_id: Mapped[str] = mapped_column(String(36), index=True)
    quantity: Mapped[int] = mapped_column(BigInteger)
    price_minor: Mapped[int] = mapped_column(BigInteger)
    total_amount_minor: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3))
    idempotency_key: Mapped[str] = mapped_column(String(128))
    request_hash: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(32), index=True)
    transfer_operation_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    transaction_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[str] = mapped_column(String(40))
    updated_at: Mapped[str] = mapped_column(String(40))
