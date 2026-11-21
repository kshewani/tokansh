"""Shared lookups for the domain modules."""
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
    """Holder id on DRUNIX: the user's application UUID (platform-mediated custodial model).

    One pinned service identity signs every transaction; holder ids are data, not signers.
    """
    return user.id


def user_brief(user: m.User | None) -> dict | None:
    if user is None:
        return None
    return {"id": user.id, "name": user.full_name, "role": user.role.value}


def property_ref(prop: m.Property) -> str:
    """Approved-property reference on DRUNIX: the chaincode keys properties by their UUID."""
    return prop.id


def position(db: Session, user_id: str, issuance_id: str) -> m.OwnershipPosition | None:
    return db.scalar(sa.select(m.OwnershipPosition).filter_by(investor_id=user_id, issuance_id=issuance_id))
