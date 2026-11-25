"""FastAPI dependencies: database session, settings, ledger adapter and demo identity."""
from collections.abc import Iterator

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import ApiError, forbidden
from app.db import models as m
from app.db.enums import UserRole, UserStatus
from app.ledger.port import LedgerPort



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
    """Caller from the demo bearer session (app/core/auth.py). Not production authentication.

    Role permissions are still enforced on every operation by the services.
    """
    from app.core.auth import bearer_token
    user_id = request.app.state.sessions.resolve(bearer_token(request))
    if user_id is None:
        raise ApiError(401, "INVALID_SESSION", "Your session has ended. Sign in again.")
    user = db.get(m.User, user_id)
    if user is None or user.status != UserStatus.ACTIVE:
        raise ApiError(401, "INVALID_SESSION", "Unknown or inactive demonstration user.")
    return user


def require_role(user: m.User, *roles: UserRole) -> None:
    if user.role not in roles:
        raise forbidden(f"This operation requires one of the roles: {', '.join(r.value for r in roles)}.")


def correlation_id(request: Request) -> str | None:
    return getattr(request.state, "correlation_id", None)
