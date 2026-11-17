"""FastAPI dependencies: database session, settings, ledger adapter and demo identity."""
from collections.abc import Iterator

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import ApiError, forbidden
from app.db import models as m
from app.db.enums import UserRole, UserStatus
from app.ledger.port import LedgerPort

DEMO_USER_HEADER = "X-Demo-User-Id"


def get_db(request: Request) -> Iterator[Session]:
    session = request.app.state.sessionmaker()
    try:
        yield session
    finally:
        session.close()


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_ledger(request: Request) -> LedgerPort:
    return request.app.state.ledger


def current_user(request: Request, db: Session = Depends(get_db)) -> m.User:
    """Demonstration identity (API_CONTRACTS section 6). Not production authentication.

    The demo user is selected by the X-Demo-User-Id header. Role permissions are
    still enforced on every operation by the services.
    """
    user_id = request.headers.get(DEMO_USER_HEADER)
    if not user_id:
        raise ApiError(401, "AUTHENTICATION_REQUIRED", f"Select a demonstration user ({DEMO_USER_HEADER} header).")
    user = db.get(m.User, user_id)
    if user is None or user.status != UserStatus.ACTIVE:
        raise ApiError(401, "AUTHENTICATION_REQUIRED", "Unknown or inactive demonstration user.")
    return user


def require_role(user: m.User, *roles: UserRole) -> None:
    if user.role not in roles:
        raise forbidden(f"This operation requires one of the roles: {', '.join(r.value for r in roles)}.")


def correlation_id(request: Request) -> str | None:
    return getattr(request.state, "correlation_id", None)
