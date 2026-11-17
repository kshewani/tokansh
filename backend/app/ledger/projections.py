"""Ownership read model, updated only from committed ledger operations (ADR-007, Rule 4.4).

Each ledger operation records the balance changes it is expected to make
("deltas"). They are applied to the projection only after DRUNIX confirms the
commit, and they also let record-date holdings be reconstructed deterministically
from committed operations (Rule 10.6).
"""
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.db import models as m
from app.db.enums import OperationStatus, PositionStatus
from app.db.types import utcnow
from app.ledger.executor import payload_of


def delta(user_id: str, owned: int = 0, pledged: int = 0, cost_minor: int = 0) -> dict:
    return {"user_id": user_id, "owned": owned, "pledged": pledged, "cost_minor": cost_minor}


def apply_deltas(db: Session, op: m.LedgerOperation) -> None:
    payload = payload_of(op)
    issuance_id = payload["issuance_id"]
    for d in payload.get("deltas", []):
        pos = db.scalar(sa.select(m.OwnershipPosition).filter_by(investor_id=d["user_id"], issuance_id=issuance_id))
        if pos is None:
            pos = m.OwnershipPosition(investor_id=d["user_id"], issuance_id=issuance_id, owned_quantity=0,
                                      pledged_quantity=0, acquisition_cost_minor=0,
                                      ledger_reference=op.transaction_id, observed_at=utcnow())
            db.add(pos)
        pos.owned_quantity += d.get("owned", 0)
        pos.pledged_quantity += d.get("pledged", 0)
        pos.acquisition_cost_minor += d.get("cost_minor", 0)
        pos.ledger_reference = op.transaction_id
        pos.observed_at = utcnow()
        pos.reconciliation_status = PositionStatus.ACTIVE
    db.flush()


def holdings_as_of(db: Session, issuance_id: str, cutoff: datetime) -> tuple[dict[str, dict], str | None, int | None]:
    """Owned/pledged per user from committed operations confirmed at or before ``cutoff``."""
    ops = db.scalars(sa.select(m.LedgerOperation)
                     .where(m.LedgerOperation.status == OperationStatus.COMMITTED,
                            m.LedgerOperation.confirmed_at <= cutoff)
                     .order_by(m.LedgerOperation.confirmed_at, m.LedgerOperation.block_number)).all()
    balances: dict[str, dict] = {}
    last_tx, last_block = None, None
    for op in ops:
        payload = payload_of(op)
        if payload.get("issuance_id") != issuance_id:
            continue
        for d in payload.get("deltas", []):
            b = balances.setdefault(d["user_id"], {"owned": 0, "pledged": 0})
            b["owned"] += d.get("owned", 0)
            b["pledged"] += d.get("pledged", 0)
        last_tx, last_block = op.transaction_id, op.block_number
    return balances, last_tx, last_block
