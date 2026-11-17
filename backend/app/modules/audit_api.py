"""Audit trail, asset history and ledger operations (API_CONTRACTS 7.13, ADR-011)."""
import json

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.deps import current_user, get_db, get_ledger, get_settings, require_role
from app.core.errors import ApiError, not_found
from app.core.serial import envelope, iso, paginate
from app.db import models as m
from app.db.enums import EventSource, OperationStatus, UserRole
from app.ledger import executor
from app.ledger.port import LedgerPort, LedgerUnavailable
from app.modules.common import get_or_404, user_brief

router = APIRouter(prefix="/api/v1", tags=["Audit and ledger"])


def audit_view(db: Session, e: m.AuditEvent) -> dict:
    return {"id": e.id, "entity_type": e.entity_type, "entity_id": e.entity_id, "operation_type": e.operation_type,
            "actor": user_brief(db.get(m.User, e.actor_id)) if e.actor_id else None,
            "previous_state": e.previous_state, "new_state": e.new_state, "source": e.source_system.value,
            "simulated": e.simulation_flag, "outcome": e.outcome, "ledger_transaction_id": e.ledger_transaction_id,
            "operation_id": e.operation_id, "correlation_id": e.correlation_id,
            "detail": json.loads(e.detail_json) if e.detail_json else None, "occurred_at": iso(e.occurred_at)}


def asset_event_view(db: Session, e: m.AssetEvent) -> dict:
    return {"id": e.id, "property_id": e.property_id, "issuance_id": e.issuance_id, "event_type": e.event_type,
            "description": e.event_description, "source": e.event_source.value, "simulated": e.is_simulated,
            "reference_id": e.reference_id, "ledger_transaction_id": e.ledger_transaction_id,
            "actor": user_brief(db.get(m.User, e.actor_id)) if e.actor_id else None, "occurred_at": iso(e.occurred_at)}


@router.get("/audit/events")
def audit_events(request: Request, entity_type: str | None = None, entity_id: str | None = None,
                 source: EventSource | None = None, page: int = 1, page_size: int = 20,
                 db: Session = Depends(get_db), user: m.User = Depends(current_user)):
    stmt = sa.select(m.AuditEvent).order_by(m.AuditEvent.occurred_at.desc(), m.AuditEvent.id)
    if user.role == UserRole.INVESTOR:
        stmt = stmt.where(m.AuditEvent.actor_id == user.id)
    if entity_type:
        stmt = stmt.where(m.AuditEvent.entity_type == entity_type)
    if entity_id:
        stmt = stmt.where(m.AuditEvent.entity_id == entity_id)
    if source:
        stmt = stmt.where(m.AuditEvent.source_system == source)
    return envelope(request, paginate(db, stmt, page, page_size, lambda e: audit_view(db, e)))


@router.get("/assets/{property_id}/history")
def asset_history(property_id: str, request: Request, page: int = 1, page_size: int = 50,
                  db: Session = Depends(get_db), user: m.User = Depends(current_user)):
    get_or_404(db, m.Property, property_id, "Property")
    stmt = sa.select(m.AssetEvent).filter_by(property_id=property_id).order_by(m.AssetEvent.occurred_at.desc())
    return envelope(request, paginate(db, stmt, page, page_size, lambda e: asset_event_view(db, e)))


@router.get("/assets/events")
def all_asset_events(request: Request, page: int = 1, page_size: int = 50, db: Session = Depends(get_db),
                     user: m.User = Depends(current_user)):
    stmt = sa.select(m.AssetEvent).order_by(m.AssetEvent.occurred_at.desc())
    return envelope(request, paginate(db, stmt, page, page_size, lambda e: asset_event_view(db, e)))


@router.get("/ledger/operations")
def list_operations(request: Request, status: OperationStatus | None = None, page: int = 1, page_size: int = 20,
                    db: Session = Depends(get_db), user: m.User = Depends(current_user)):
    require_role(user, UserRole.ADMIN, UserRole.ISSUER, UserRole.LENDER)
    stmt = sa.select(m.LedgerOperation).order_by(m.LedgerOperation.created_at.desc())
    if status:
        stmt = stmt.where(m.LedgerOperation.status == status)
    return envelope(request, paginate(db, stmt, page, page_size, executor.operation_view))


@router.get("/ledger/operations/{operation_id}")
def get_operation(operation_id: str, request: Request, db: Session = Depends(get_db),
                  user: m.User = Depends(current_user)):
    return envelope(request, executor.operation_view(get_or_404(db, m.LedgerOperation, operation_id, "Ledger operation")))


@router.post("/ledger/operations/{operation_id}/reconcile")
def reconcile_operation(operation_id: str, request: Request, db: Session = Depends(get_db),
                        user: m.User = Depends(current_user), ledger: LedgerPort = Depends(get_ledger),
                        settings: Settings = Depends(get_settings)):
    require_role(user, UserRole.ADMIN, UserRole.ISSUER)
    op = get_or_404(db, m.LedgerOperation, operation_id, "Ledger operation")
    return envelope(request, executor.operation_view(executor.reconcile(db, ledger, settings, op, user.id)))


@router.get("/ledger/transactions/{transaction_id}")
def get_transaction(transaction_id: str, request: Request, db: Session = Depends(get_db),
                    user: m.User = Depends(current_user), ledger: LedgerPort = Depends(get_ledger)):
    op = db.scalar(sa.select(m.LedgerOperation).filter_by(transaction_id=transaction_id))
    if op is None:
        raise not_found("Ledger transaction", transaction_id)
    data = {"operation": executor.operation_view(op), "live_status": None}
    try:
        live = ledger.commit_status(transaction_id)
        data["live_status"] = {"state": live.state.value, "validation_code": live.validation_code,
                               "block_number": live.block_number, "source": "DRUNIX_LEDGER"}
    except LedgerUnavailable as exc:
        data["live_status"] = {"state": "UNAVAILABLE", "detail": exc.message}
    return envelope(request, data)


@router.get("/reconciliation/cases")
def reconciliation_cases(request: Request, db: Session = Depends(get_db), user: m.User = Depends(current_user)):
    require_role(user, UserRole.ADMIN, UserRole.ISSUER)
    cases = db.scalars(sa.select(m.ReconciliationCase).order_by(m.ReconciliationCase.opened_at.desc())).all()
    return envelope(request, {"items": [{"id": c.id, "ledger_operation_id": c.ledger_operation_id, "order_id": c.order_id,
                                         "reason": c.reason, "status": c.status.value, "resolution": c.resolution,
                                         "opened_at": iso(c.opened_at), "resolved_at": iso(c.resolved_at)}
                                        for c in cases]})
