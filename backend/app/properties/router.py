from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request

from app.dependencies import DemoActor, SessionDependency, demo_actor, property_writer
from app.properties.schemas import NewProperty, PropertyRead, PropertyPage
from app.schemas import Envelope
from app.properties.service import PropertyService
from app.errors import success

router = APIRouter(prefix="/properties", tags=["properties"])
IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")]


@router.post("", status_code=201, response_model=Envelope[PropertyRead])
def create_property(request: Request, command: NewProperty, session: SessionDependency,
                    actor: Annotated[DemoActor, Depends(property_writer)], idempotency_key: IdempotencyKey):
    return success(request, PropertyService(session).create(
        command, actor.user_id, idempotency_key, request.state.correlation_id))


@router.get("", response_model=Envelope[PropertyPage])
def list_properties(request: Request, session: SessionDependency,
                    actor: Annotated[DemoActor, Depends(demo_actor)],
                    page: Annotated[int, Query(ge=1)] = 1, page_size: Annotated[int, Query(ge=1, le=100)] = 20):
    return success(request, PropertyService(session).page(page, page_size))


@router.get("/{property_id}", response_model=Envelope[PropertyRead])
def property_details(property_id: UUID, request: Request, session: SessionDependency,
                     actor: Annotated[DemoActor, Depends(demo_actor)]):
    return success(request, PropertyService(session).get(str(property_id)))
