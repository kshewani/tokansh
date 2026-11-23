from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.errors import ApplicationError
from app.auth import AARAV_ID, DemoIdentity, ISSUER_ID, LENDER_ACTOR_ID, current_identity


@dataclass(frozen=True)
class DemoActor:
    user_id: str
    role: str
    username: str = ""
    organization_id: str | None = None


DEMO_ACTORS = {
    "ADMIN": DemoActor("00000000-0000-4000-8000-000000000001", "ADMIN", "Admin"),
    "ISSUER": DemoActor(ISSUER_ID, "ISSUER", "Meera"),
    "INVESTOR": DemoActor(AARAV_ID, "INVESTOR", "Aarav"),
    "LENDER": DemoActor(LENDER_ACTOR_ID, "LENDER", "Lender"),
}


def demo_actor(request: Request, identity: Annotated[DemoIdentity, Depends(current_identity)]) -> DemoActor:
    if not request.app.state.settings.demo_auth_enabled:
        raise ApplicationError(503, "AUTH_NOT_CONFIGURED", "Production authentication is not implemented in M2.")
    return DemoActor(identity.user_id, identity.role, identity.username, identity.organization_id)


def property_writer(actor: Annotated[DemoActor, Depends(demo_actor)]) -> DemoActor:
    # Issuer status is property-specific.  The authenticated investor becomes
    # the issuer for the new property; the legacy ISSUER actor remains valid
    # for existing issuer-managed inventory and records.
    if actor.role not in {"ADMIN", "ISSUER", "INVESTOR"}:
        raise ApplicationError(403, "INSUFFICIENT_PERMISSIONS", "Only an investor, issuer, or admin may onboard a property.")
    return actor


def get_session(request: Request):
    database = request.app.state.database
    if not database.ready():
        raise ApplicationError(503, "DATABASE_UNAVAILABLE", "The database is unavailable or migrations are not current.")
    with database.sessions() as session:
        yield session


SessionDependency = Annotated[Session, Depends(get_session)]
