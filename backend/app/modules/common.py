"""Shared lookups for the domain modules."""
import re

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.core.errors import not_found
from app.db import models as m


def get_or_404(db: Session, model, entity_id: str, label: str):
    obj = db.get(model, entity_id)
    if obj is None:
        raise not_found(label, entity_id)
    return obj


def identity(user: m.User) -> str:
    """Ledger identity reference for a user (custodial demo model). Never key material."""
    return user.ledger_identity_ref or user.id


def user_brief(user: m.User | None) -> dict | None:
    if user is None:
        return None
    return {"id": user.id, "name": user.full_name, "role": user.role.value}


def property_ref(prop: m.Property) -> str:
    """Stable approved-property reference registered on DRUNIX."""
    slug = re.sub(r"[^A-Z0-9]+", "-", prop.property_name.upper()).strip("-")[:40] or "PROPERTY"
    return f"{slug}-{prop.id[:8].upper()}"


def position(db: Session, user_id: str, issuance_id: str) -> m.OwnershipPosition | None:
    return db.scalar(sa.select(m.OwnershipPosition).filter_by(investor_id=user_id, issuance_id=issuance_id))
