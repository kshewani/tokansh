"""Local demo authentication and in-memory session management.

This is intentionally a small, process-local mechanism for the hackathon
demo. Tokens are opaque, random bearer values and are discarded when the
FastAPI process is recreated.
"""
import secrets
from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel, ConfigDict, Field

from app.errors import ApplicationError, success
from app.lenders import lender


AARAV_ID = "00000000-0000-4000-8000-000000000003"
MEERA_ID = "00000000-0000-4000-8000-000000000006"
ISSUER_ID = "00000000-0000-4000-8000-000000000002"
LENDER_ACTOR_ID = "00000000-0000-4000-8000-000000000004"
SHOWCASE_INVESTORS = {
    "rohan": ("Rohan", "00000000-0000-4000-8000-000000000007"),
    "priya": ("Priya", "00000000-0000-4000-8000-000000000008"),
    "vikram": ("Vikram", "00000000-0000-4000-8000-000000000009"),
    "ananya": ("Ananya", "00000000-0000-4000-8000-000000000010"),
    "neha": ("Neha", "00000000-0000-4000-8000-000000000011"),
    "arjun": ("Arjun", "00000000-0000-4000-8000-000000000012"),
}


@dataclass(frozen=True)
class DemoIdentity:
    username: str
    display_name: str
    role: str
    user_id: str
    organization_id: str | None = None


INVESTOR_IDENTITIES = {
    "aarav": DemoIdentity("Aarav", "Aarav", "INVESTOR",
                           AARAV_ID),
    "meera": DemoIdentity("Meera", "Meera", "INVESTOR", MEERA_ID),
}
INVESTOR_IDENTITIES.update({
    key: DemoIdentity(name, name, "INVESTOR", user_id)
    for key, (name, user_id) in SHOWCASE_INVESTORS.items()
})


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    username: Annotated[str, Field(min_length=1, max_length=80)]
    password: Annotated[str, Field(min_length=1, max_length=256)]


class SessionStore:
    def __init__(self):
        self._sessions: dict[str, DemoIdentity] = {}

    def create(self, identity: DemoIdentity) -> str:
        token = secrets.token_urlsafe(32)
        self._sessions[token] = identity
        return token

    def resolve(self, token: str) -> DemoIdentity | None:
        return self._sessions.get(token)

    def revoke(self, token: str) -> None:
        self._sessions.pop(token, None)


def identity_for_login(username: str) -> DemoIdentity:
    normalized = username.strip().casefold()
    investor = INVESTOR_IDENTITIES.get(normalized)
    if investor is not None:
        return investor
    try:
        organization = lender(normalized)
    except ApplicationError:
        raise ApplicationError(401, "INVALID_CREDENTIALS", "The demo identity or password is invalid.") from None
    return DemoIdentity(organization.id, organization.name, "LENDER", LENDER_ACTOR_ID, organization.id)


router = APIRouter(prefix="/auth", tags=["demo authentication"])


@router.post("/login")
def login(command: LoginRequest, request: Request):
    if not request.app.state.settings.demo_auth_enabled:
        raise ApplicationError(503, "AUTH_NOT_CONFIGURED", "Demo authentication is disabled in this environment.")
    identity = identity_for_login(command.username)
    token = request.app.state.sessions.create(identity)
    return success(request, {
        "access_token": token,
        "token_type": "bearer",
        "username": identity.username,
        "display_name": identity.display_name,
        "role": identity.role,
        "user_id": identity.user_id,
        "organization_id": identity.organization_id,
    })


def bearer_token(request: Request, authorization: Annotated[str | None, Header(alias="Authorization")] = None) -> str:
    if not request.app.state.settings.demo_auth_enabled:
        raise ApplicationError(503, "AUTH_NOT_CONFIGURED", "Demo authentication is disabled in this environment.")
    if authorization is None:
        raise ApplicationError(401, "AUTHENTICATION_REQUIRED", "A valid demo session is required.")
    scheme, separator, token = authorization.partition(" ")
    if scheme.casefold() != "bearer" or not separator or not token or len(token) > 256:
        raise ApplicationError(401, "AUTHENTICATION_REQUIRED", "A valid demo session is required.")
    return token


def current_identity(request: Request, token: Annotated[str, Depends(bearer_token)]) -> DemoIdentity:
    if not request.app.state.settings.demo_auth_enabled:
        raise ApplicationError(503, "AUTH_NOT_CONFIGURED", "Demo authentication is disabled in this environment.")
    identity = request.app.state.sessions.resolve(token)
    if identity is None:
        raise ApplicationError(401, "INVALID_SESSION", "The demo session is invalid or expired.")
    return identity


@router.get("/me")
def session_identity(request: Request, identity: Annotated[DemoIdentity, Depends(current_identity)]):
    return success(request, {
        "username": identity.username,
        "display_name": identity.display_name,
        "role": identity.role,
        "user_id": identity.user_id,
        "organization_id": identity.organization_id,
    })


@router.post("/logout")
def logout(request: Request, token: Annotated[str, Depends(bearer_token)]):
    request.app.state.sessions.revoke(token)
    return success(request, {"logged_out": True})
