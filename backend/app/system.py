from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.errors import success
from app.schemas import Envelope, SystemStatus, Readiness, HealthStatus, SafeConfiguration

router = APIRouter(tags=["system"])


def system_status(request: Request) -> dict:
    db_ready = request.app.state.database.ready()
    return {"components": [
        {"name": "FastAPI", "status": "CONNECTED"},
        {"name": "Application database", "status": "CONNECTED" if db_ready else "UNAVAILABLE"},
        {"name": "Go gateway", "status": "UNAVAILABLE", "detail": "Gateway integration is not implemented in M2."},
        {"name": "DRUNIX peers", "status": "UNKNOWN"},
        {"name": "Ordering service", "status": "UNKNOWN"},
        {"name": "Validation service", "status": "UNKNOWN"},
        {"name": "DRUNIX state database", "status": "UNKNOWN"},
        {"name": "DRUNIX network connectivity", "status": "UNKNOWN"},
        {"name": "DRUNIX transaction capability", "status": "UNAVAILABLE"},
    ], "last_ledger_operation": None}


@router.get("/health", response_model=Envelope[HealthStatus])
def health(request: Request):
    return success(request, {"status": "UP"})


@router.get("/ready", responses={503: {"model": Envelope[Readiness]}})
def ready(request: Request):
    # Overall readiness includes mandatory DRUNIX transaction capability.
    return JSONResponse(status_code=503, content=success(request, {"ready": False, **system_status(request)}))


@router.get("/api/v1/system/status", response_model=Envelope[SystemStatus], response_model_exclude_unset=True)
def status(request: Request):
    return success(request, system_status(request))


@router.get("/api/v1/system/configuration", response_model=Envelope[SafeConfiguration])
def configuration(request: Request):
    settings = request.app.state.settings
    return success(request, {"app_env": settings.app_env, "demo_auth_enabled": settings.demo_auth_enabled,
                             "ledger_integration": "NOT_IMPLEMENTED"})
