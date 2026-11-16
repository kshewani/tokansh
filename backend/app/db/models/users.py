import sqlalchemy as sa

from app.db.base import Base, created_at, enum_col, text, updated_at, uuid_pk
from app.db.enums import UserRole, UserStatus


class User(Base):
    """Demonstration participant (DOMAIN_MODEL 2.1). Not production authentication."""

    __tablename__ = "users"
    __table_args__ = (sa.UniqueConstraint("email"),)

    id = uuid_pk()
    full_name = text(160)
    email = text(255)
    role = enum_col(UserRole, index=True)
    status = enum_col(UserStatus, default=UserStatus.ACTIVE)
    # Identity reference used for this user on the ledger (custodial model); never key material.
    ledger_identity_ref = text(128, nullable=True)
    created_at = created_at()
    updated_at = updated_at()
