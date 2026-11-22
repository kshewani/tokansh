from fastapi import APIRouter, Request, Depends
from typing import Annotated
from app.drunix import GatewayAdapter, get_gateway
from fastapi.responses import JSONResponse

from app.errors import success
from app.schemas import Envelope, SystemStatus, Readiness, HealthStatus, SafeConfiguration

router = APIRouter(tags=["system"])


def system_status(request: Request, gateway: GatewayAdapter) -> dict:
    db_ready = request.app.state.database.ready()
    gateway_status, connectivity_status = gateway.connectivity(request.state.correlation_id)
    return {"components": [
        {"name": "FastAPI", "status": "CONNECTED"},
        {"name": "Application database", "status": "CONNECTED" if db_ready else "UNAVAILABLE"},
        {"name": "Go gateway", "status": gateway_status},
        {"name": "DRUNIX peers", "status": "UNKNOWN"},
        {"name": "Ordering service", "status": "UNKNOWN"},
        {"name": "Validation service", "status": "UNKNOWN"},
        {"name": "DRUNIX state database", "status": "UNKNOWN"},
        {"name": "DRUNIX network connectivity", "status": connectivity_status},
        {"name": "DRUNIX transaction capability", "status": "CONNECTED" if gateway_status == "CONNECTED" else "UNAVAILABLE"},
    ], "last_ledger_operation": None}


@router.get("/health", response_model=Envelope[HealthStatus])
def health(request: Request):
    return success(request, {"status": "UP"})


@router.get("/ready", responses={503: {"model": Envelope[Readiness]}})
def ready(request: Request, gateway: Annotated[GatewayAdapter, Depends(get_gateway)]):
    # Overall readiness includes mandatory DRUNIX transaction capability.
    return JSONResponse(status_code=503, content=success(request, {"ready": False, **system_status(request, gateway)}))


@router.get("/api/v1/system/status", response_model=Envelope[SystemStatus], response_model_exclude_unset=True)
def status(request: Request, gateway: Annotated[GatewayAdapter, Depends(get_gateway)]):
    return success(request, system_status(request, gateway))


@router.get("/api/v1/system/configuration", response_model=Envelope[SafeConfiguration])
def configuration(request: Request):
    settings = request.app.state.settings
    return success(request, {"app_env": settings.app_env, "demo_auth_enabled": settings.demo_auth_enabled,
                             "ledger_integration": "NOT_IMPLEMENTED"})
