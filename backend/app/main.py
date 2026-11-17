"""TokANSH FastAPI application: a modular monolith (ADR-001, ARCHITECTURE section 12).

Run:  uvicorn app.main:app --reload    (from backend/)
"""
import logging
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.orm import sessionmaker
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import Settings
from app.core.errors import ApiError
from app.db.session import make_engine
from app.ledger.gateway_client import GatewayLedgerClient
from app.ledger.port import LedgerPort
from app.modules import (audit_api, distributions, financing, issuance, marketplace, portfolio, properties, system,
                         transfers)

log = logging.getLogger("tokansh")


def _error(request: Request, status: int, code: str, message: str, details: dict | None = None) -> JSONResponse:
    return JSONResponse(status_code=status, content={
        "error": {"code": code, "message": message, "details": details or {}},
        "meta": {"correlation_id": getattr(request.state, "correlation_id", None)}})


def create_app(settings: Settings | None = None, ledger: LedgerPort | None = None) -> FastAPI:
    """``ledger`` is injectable ONLY so isolated tests can pass a test double.

    The running application always builds the real gateway client.
    """
    settings = settings or Settings.from_env()
    app = FastAPI(title="TokANSH API", version="0.1.0",
                  description="Unlocking Real Estate, One Ansh at a Time. Payments and lending are simulated; "
                              "ANSH ledger operations require DRUNIX.")
    engine = make_engine(settings.database_url)
    app.state.settings = settings
    app.state.engine = engine
    app.state.sessionmaker = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    app.state.ledger = ledger if ledger is not None else GatewayLedgerClient(settings)

    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins,
                       allow_origin_regex=settings.cors_origin_regex, allow_credentials=True,
                       allow_methods=["*"], allow_headers=["*"],
                       expose_headers=["X-Correlation-ID"])

    @app.middleware("http")
    async def correlation(request: Request, call_next):
        cid = request.headers.get("X-Correlation-ID") or str(uuid.uuid4())
        request.state.correlation_id = cid[:128]
        response = await call_next(request)
        response.headers["X-Correlation-ID"] = request.state.correlation_id
        return response

    @app.exception_handler(ApiError)
    async def api_error(request: Request, exc: ApiError):
        return _error(request, exc.status, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        errors = [{"field": ".".join(str(p) for p in e["loc"][1:]), "message": e["msg"]} for e in exc.errors()]
        return _error(request, 422, "INVALID_REQUEST", "Request validation failed.", {"errors": errors})

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        code = "RESOURCE_NOT_FOUND" if exc.status_code == 404 else "INVALID_REQUEST"
        return _error(request, exc.status_code, code, str(exc.detail))

    @app.exception_handler(Exception)
    async def unexpected(request: Request, exc: Exception):
        log.exception("unhandled error", extra={"correlation_id": getattr(request.state, "correlation_id", None)})
        return _error(request, 500, "INTERNAL_ERROR", "An unexpected error occurred.")

    for module in (system, properties, issuance, marketplace, transfers, portfolio, financing, distributions, audit_api):
        app.include_router(module.router)
    return app


app = create_app()
