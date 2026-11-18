from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, Request
from sqlalchemy.orm import Session

from app.errors import ApplicationError


@dataclass(frozen=True)
class DemoActor:
    user_id: str
    role: str


DEMO_ACTORS = {
    "ADMIN": DemoActor("00000000-0000-4000-8000-000000000001", "ADMIN"),
    "ISSUER": DemoActor("00000000-0000-4000-8000-000000000002", "ISSUER"),
    "INVESTOR": DemoActor("00000000-0000-4000-8000-000000000003", "INVESTOR"),
    "LENDER": DemoActor("00000000-0000-4000-8000-000000000004", "LENDER"),
}


def demo_actor(request: Request, role: Annotated[str | None, Header(alias="X-Demo-Role")] = None) -> DemoActor:
    if not request.app.state.settings.demo_auth_enabled:
        raise ApplicationError(503, "AUTH_NOT_CONFIGURED", "Production authentication is not implemented in M2.")
    if role is None:
        raise ApplicationError(401, "AUTHENTICATION_REQUIRED", "Select a local demo identity using X-Demo-Role.")
    if role not in DEMO_ACTORS:
        raise ApplicationError(403, "INSUFFICIENT_PERMISSIONS", "The requested demo role is not supported.")
    return DEMO_ACTORS[role]


def property_writer(actor: Annotated[DemoActor, Depends(demo_actor)]) -> DemoActor:
    if actor.role not in {"ADMIN", "ISSUER"}:
        raise ApplicationError(403, "INSUFFICIENT_PERMISSIONS", "Only an admin or issuer may onboard a property.")
    return actor


def get_session(request: Request):
    database = request.app.state.database
    if not database.ready():
        raise ApplicationError(503, "DATABASE_UNAVAILABLE", "The database is unavailable or migrations are not current.")
    with database.sessions() as session:
        yield session


SessionDependency = Annotated[Session, Depends(get_session)]
