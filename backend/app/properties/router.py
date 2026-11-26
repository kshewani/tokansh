from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request

from app.dependencies import DemoActor, SessionDependency, demo_actor, property_writer
from app.properties.schemas import NewProperty, PropertyRead, PropertyPage
from app.schemas import Envelope
from app.properties.service import PropertyService
from app.errors import ApplicationError, success

router = APIRouter(prefix="/properties", tags=["properties"])
IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")]


@router.post("", status_code=201, response_model=Envelope[PropertyRead])
def create_property(request: Request, command: NewProperty, session: SessionDependency,
                    actor: Annotated[DemoActor, Depends(property_writer)], idempotency_key: IdempotencyKey):
    return success(request, PropertyService(session, request.app.state.settings.initial_issue_price_minor).create(
        command, actor.user_id, idempotency_key, request.state.correlation_id))


@router.get("", response_model=Envelope[PropertyPage])
def list_properties(request: Request, session: SessionDependency,
                    actor: Annotated[DemoActor, Depends(demo_actor)],
                    page: Annotated[int, Query(ge=1)] = 1, page_size: Annotated[int, Query(ge=1, le=100)] = 20):
    return success(request, PropertyService(session, request.app.state.settings.initial_issue_price_minor).page(page, page_size))


@router.get("/{property_id}", response_model=Envelope[PropertyRead])
def property_details(property_id: UUID, request: Request, session: SessionDependency,
                     actor: Annotated[DemoActor, Depends(demo_actor)]):
    return success(request, PropertyService(session, request.app.state.settings.initial_issue_price_minor).get(str(property_id)))


@router.get("/{property_id}/issuance-state")
def property_issuance_state(property_id: UUID, request: Request, session: SessionDependency,
                            actor: Annotated[DemoActor, Depends(demo_actor)]):
    property_data = PropertyService(session, request.app.state.settings.initial_issue_price_minor).get(str(property_id))
    if actor.role != "INVESTOR" or property_data["issuer_id"] != actor.user_id:
        raise ApplicationError(403, "INSUFFICIENT_PERMISSIONS", "Only the authenticated property issuer may read issuance state.")
    if property_data["ledger_registration_status"] != "REGISTERED":
        raise ApplicationError(409, "PROPERTY_NOT_REGISTERED", "The property is not registered on DRUNIX.")
    state = request.app.state.transfer_gateway.call(
        "GET", "issuance-state/" + str(property_id), request.state.correlation_id)
    if not isinstance(state, dict) or state.get("property_id") != str(property_id):
        raise ApplicationError(502, "INVALID_LEDGER_RESPONSE", "DRUNIX returned an invalid issuance state.")
    return success(request, {
        "property_id": str(property_id),
        "approved_supply": property_data["approved_supply"],
        "issued_supply": state.get("cumulative_issued_supply", state.get("issued_supply")),
        "remaining_supply": state.get("remaining_issuance_capacity", state.get("remaining_supply")),
        "state": state.get("state", "UNKNOWN"),
        "source": "DRUNIX",
    })
