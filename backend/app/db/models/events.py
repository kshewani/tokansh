import sqlalchemy as sa

from app.db.base import Base, created_at, enum_col, fk, flag, text, timestamp, uuid_pk
from app.db.enums import EventSource


class AssetEvent(Base):
    """Lifecycle event of a property or its ANSH (DOMAIN_MODEL 2.17). The source is always visible."""

    __tablename__ = "asset_events"
    __table_args__ = (
        sa.CheckConstraint("property_id IS NOT NULL OR issuance_id IS NOT NULL", name="has_subject"),
        # An event may claim the ledger as its source only with a genuine transaction id.
        sa.CheckConstraint("event_source <> 'DRUNIX_LEDGER' OR ledger_transaction_id IS NOT NULL",
                           name="ledger_source_needs_tx"),
        sa.CheckConstraint("event_source = 'DRUNIX_LEDGER' OR ledger_transaction_id IS NULL",
                           name="tx_only_for_ledger_source"),
        sa.CheckConstraint("event_source NOT IN ('PAYMENT_SIMULATOR','LENDER_SIMULATOR','EXTERNAL_SIMULATOR') "
                           "OR is_simulated = 1", name="simulator_events_are_flagged"),
        sa.CheckConstraint("event_source <> 'DRUNIX_LEDGER' OR is_simulated = 0", name="ledger_events_not_simulated"),
        sa.UniqueConstraint("ledger_transaction_id", "event_type"),
        sa.Index("ix_asset_events_timeline", "property_id", "occurred_at"),
    )

    id = uuid_pk()
    property_id = fk("properties.id", nullable=True, index=False)
    issuance_id = fk("ansh_issuances.id", nullable=True)
    event_type = text(60)
    event_description = text(500)
    event_source = enum_col(EventSource, index=True)
    is_simulated = flag(False)
    reference_id = text(64, nullable=True)
    ledger_transaction_id = text(128, nullable=True)
    actor_id = fk("users.id", nullable=True, index=False)
    occurred_at = timestamp(nullable=False)
    created_at = created_at()


class AuditEvent(Base):
    """Application audit record (BUSINESS_RULES section 12). Append-only; not a blockchain record."""

    __tablename__ = "audit_events"
    __table_args__ = (
        sa.Index("ix_audit_events_entity", "entity_type", "entity_id"),
        sa.Index("ix_audit_events_time", "occurred_at"),
    )

    id = uuid_pk()
    operation_id = text(64, nullable=True)
    entity_type = text(60)
    entity_id = text(36)
    actor_id = fk("users.id", nullable=True)
    operation_type = text(60)
    previous_state = text(40, nullable=True)
    new_state = text(40, nullable=True)
    source_system = enum_col(EventSource)
    simulation_flag = flag(False)
    ledger_transaction_id = text(128, nullable=True)
    outcome = text(40)
    detail_json = sa.orm.mapped_column(sa.Text, nullable=True)
    correlation_id = text(128, nullable=True)
    occurred_at = created_at()
