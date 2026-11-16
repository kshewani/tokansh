import sqlalchemy as sa

from app.db.base import Base, created_at, enum_col, fk, integer, text, timestamp, updated_at, uuid_pk
from app.db.enums import OperationStatus, OperationType, ReconciliationStatus


class LedgerOperation(Base):
    """One operation sent to DRUNIX through the gateway adapter (DOMAIN_MODEL 2.10).

    The row is written BEFORE submission, so an unknown outcome can always be
    reconciled by transaction id instead of being blindly retried (ADR-011).
    """

    __tablename__ = "ledger_operations"
    __table_args__ = (
        sa.UniqueConstraint("idempotency_key"),
        sa.UniqueConstraint("transaction_id"),
        # A commit can be recorded only with the genuine DRUNIX evidence (AGENTS.md section 9).
        sa.CheckConstraint("status <> 'COMMITTED' OR (transaction_id IS NOT NULL AND confirmed_at IS NOT NULL)",
                           name="committed_needs_evidence"),
        sa.CheckConstraint("confirmed_at IS NULL OR status = 'COMMITTED'", name="confirmed_only_when_committed"),
        sa.CheckConstraint("block_number IS NULL OR block_number >= 0", name="block_non_negative"),
        sa.CheckConstraint("attempt_count >= 0", name="attempts_non_negative"),
        sa.Index("ix_ledger_operations_entity", "entity_type", "entity_id"),
    )

    id = uuid_pk()
    operation_type = enum_col(OperationType, index=True)
    entity_type = text(60)
    entity_id = text(36)
    idempotency_key = text(128)
    correlation_id = text(128, nullable=True)
    channel = text(64, nullable=True)
    chaincode = text(64, nullable=True)
    function_name = text(64, nullable=True)
    request_hash = text(64, nullable=True)  # SHA-256 of the arguments, for audit
    transaction_id = text(128, nullable=True)  # exactly as returned by DRUNIX; never generated here
    drunix_network_reference = text(128, nullable=True)
    status = enum_col(OperationStatus, default=OperationStatus.CREATED, index=True)
    validation_code = text(64, nullable=True)
    block_number = sa.orm.mapped_column(sa.BigInteger, nullable=True)
    error_code = text(64, nullable=True)
    error_message = text(500, nullable=True)
    attempt_count = integer(default=0)
    created_at = created_at()
    updated_at = updated_at()
    submitted_at = timestamp()
    observed_at = timestamp()
    confirmed_at = timestamp()


class LedgerEvent(Base):
    """Chaincode event consumed from DRUNIX. Duplicate delivery is normal, so rows are unique."""

    __tablename__ = "ledger_events"
    __table_args__ = (
        sa.UniqueConstraint("transaction_id", "event_name"),
        sa.CheckConstraint("block_number >= 0", name="block_non_negative"),
        sa.Index("ix_ledger_events_block", "block_number"),
    )

    id = uuid_pk()
    transaction_id = text(128)
    event_name = text(64)
    block_number = sa.orm.mapped_column(sa.BigInteger, nullable=False)
    chaincode = text(64)
    payload_json = sa.orm.mapped_column(sa.Text, nullable=False)
    ledger_timestamp = timestamp()
    received_at = created_at()
    applied_at = timestamp()  # when the read models were updated from this event


class LedgerEventCursor(Base):
    """Checkpoint so the event consumer resumes after a restart without losing or re-applying events."""

    __tablename__ = "ledger_event_cursors"
    __table_args__ = (sa.UniqueConstraint("channel", "chaincode"),)

    id = uuid_pk()
    channel = text(64)
    chaincode = text(64)
    last_block_number = integer(big=True, default=0)
    last_transaction_id = text(128, nullable=True)
    updated_at = updated_at()


class ReconciliationCase(Base):
    """Open question about a ledger outcome (Rules 6.3 and 6.4). Resolved explicitly, never silently."""

    __tablename__ = "reconciliation_cases"
    __table_args__ = (
        sa.CheckConstraint("status <> 'RESOLVED' OR (resolved_at IS NOT NULL AND resolution IS NOT NULL)",
                           name="resolved_needs_outcome"),
    )

    id = uuid_pk()
    ledger_operation_id = fk("ledger_operations.id")
    order_id = fk("purchase_orders.id", nullable=True)
    reason = text(300)
    status = enum_col(ReconciliationStatus, default=ReconciliationStatus.OPEN, index=True)
    resolution = text(500, nullable=True)
    resolved_by = fk("users.id", nullable=True, index=False)
    opened_at = created_at()
    resolved_at = timestamp()


class IdempotencyRecord(Base):
    """Idempotency-Key store (API_CONTRACTS 4.7). Same key + different request = conflict."""

    __tablename__ = "idempotency_records"
    __table_args__ = (sa.UniqueConstraint("idempotency_key", "scope"),)

    id = uuid_pk()
    idempotency_key = text(128)
    scope = text(120)  # e.g. "POST /api/v1/marketplace/orders"
    request_hash = text(64)
    response_status = sa.orm.mapped_column(sa.Integer, nullable=True)
    response_body = sa.orm.mapped_column(sa.Text, nullable=True)
    resource_id = text(36, nullable=True)
    created_at = created_at()
    completed_at = timestamp()
