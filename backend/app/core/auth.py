"""Demo login with bearer sessions (adopted from the connected-mode branch).

Not production authentication: any non-empty password is accepted for the seeded
demo usernames, and sessions live in process memory (a restart signs everyone out).
It replaces the spoofable X-Demo-User-Id header: the browser now holds an opaque,
server-issued token and the server decides who the caller is. Login is refused when
APP_ENV=production or DEMO_AUTH_ENABLED=false.
"""
import secrets
import threading

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.core.serial import envelope
from app.db import models as m
from app.db.enums import UserStatus


class SessionStore:
    def __init__(self):
        self._sessions: dict[str, str] = {}
        self._lock = threading.Lock()

    def create(self, user_id: str) -> str:
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._sessions[token] = user_id
        return token

    def resolve(self, token: str) -> str | None:
        with self._lock:
            return self._sessions.get(token)

    def revoke(self, token: str) -> None:
        with self._lock:
            self._sessions.pop(token, None)


def demo_auth_allowed(request: Request) -> bool:
    s = request.app.state.settings
    return s.demo_auth_enabled and s.app_env.lower() != "production"


def bearer_token(request: Request) -> str:
    if not demo_auth_allowed(request):
        raise ApiError(503, "AUTH_NOT_CONFIGURED", "Demo authentication is disabled in this environment.")
    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token or len(token) > 256:
        raise ApiError(401, "AUTHENTICATION_REQUIRED", "Sign in to continue.")
    return token


def user_for_login(db: Session, username: str) -> m.User | None:
    name = username.strip().lower()
    return db.scalar(sa.select(m.User).where(sa.func.lower(m.User.ledger_identity_ref) == name,
                                             m.User.status == UserStatus.ACTIVE))


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=256)


def user_view(u: m.User) -> dict:
    return {"id": u.id, "name": u.full_name, "username": u.ledger_identity_ref, "role": u.role.value}


def build_router(get_db, current_user):
    router = APIRouter(prefix="/api/v1/auth", tags=["Demo authentication"])

    @router.post("/login")
    def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
        if not demo_auth_allowed(request):
            raise ApiError(503, "AUTH_NOT_CONFIGURED", "Demo authentication is disabled in this environment.")
        user = user_for_login(db, body.username)
        if user is None:
            raise ApiError(401, "INVALID_CREDENTIALS", "Unknown demo username.")
        token = request.app.state.sessions.create(user.id)
        return envelope(request, {"access_token": token, "token_type": "bearer", "user": user_view(user),
                                  "notice": "Demonstration sign-in only; any non-empty password is accepted."})

    @router.get("/me")
    def me(request: Request, user: m.User = Depends(current_user)):
        return envelope(request, {"user": user_view(user)})

    @router.post("/logout")
    def logout(request: Request):
        try:
            request.app.state.sessions.revoke(bearer_token(request))
        except ApiError:
            pass
        return envelope(request, {"signed_out": True})

    return router
