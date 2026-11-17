"""Audit trail and asset lifecycle events (BUSINESS_RULES section 12, DOMAIN_MODEL 2.17).

Every record states its source system, so simulated, application and ledger
events are never confused (ADR-010, ADR-020).
"""
import json

from sqlalchemy.orm import Session

from app.db import models as m
from app.db.enums import EventSource
from app.db.types import utcnow

SIMULATORS = {EventSource.PAYMENT_SIMULATOR, EventSource.LENDER_SIMULATOR, EventSource.EXTERNAL_SIMULATOR}


def audit(db: Session, *, entity_type: str, entity_id: str, operation_type: str, actor_id: str | None,
          previous_state=None, new_state=None, source: EventSource = EventSource.APPLICATION,
          outcome: str = "SUCCESS", ledger_transaction_id: str | None = None, operation_id: str | None = None,
          correlation_id: str | None = None, detail: dict | None = None) -> m.AuditEvent:
    event = m.AuditEvent(
        entity_type=entity_type, entity_id=entity_id, operation_type=operation_type, actor_id=actor_id,
        previous_state=str(previous_state) if previous_state is not None else None,
        new_state=str(new_state) if new_state is not None else None,
        source_system=source, simulation_flag=source in SIMULATORS, outcome=outcome,
        ledger_transaction_id=ledger_transaction_id, operation_id=operation_id, correlation_id=correlation_id,
        detail_json=json.dumps(detail, default=str) if detail else None)
    db.add(event)
    return event


def asset_event(db: Session, *, event_type: str, description: str, source: EventSource,
                property_id: str | None = None, issuance_id: str | None = None, actor_id: str | None = None,
                reference_id: str | None = None, ledger_transaction_id: str | None = None) -> m.AssetEvent:
    event = m.AssetEvent(
        property_id=property_id, issuance_id=issuance_id, event_type=event_type, event_description=description,
        event_source=source, is_simulated=source in SIMULATORS, reference_id=reference_id,
        ledger_transaction_id=ledger_transaction_id if source == EventSource.DRUNIX_LEDGER else None,
        actor_id=actor_id, occurred_at=utcnow())
    db.add(event)
    return event
