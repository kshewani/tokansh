from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Integer, String, Text, UniqueConstraint
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
