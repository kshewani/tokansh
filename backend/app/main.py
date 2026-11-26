import logging
import httpx
import re
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.transfers import TransferGateway, router as transfers_router
from app.financing import router as financing_router
from app.wallet import router as wallet_router
from app.config import Settings, get_settings
from app.database import Database
from app.errors import error_response, register_handlers
from app.properties.router import router as properties_router
from app.system import router as system_router
from app.schemas import ErrorEnvelope
from app.drunix import GatewayAdapter, router as diagnostic_router
from app.auth import SessionStore, router as auth_router
from app.issuance import router as issuance_router
from app.marketplace import router as marketplace_router
from app.portfolio import router as portfolio_router

logger = logging.getLogger("tokansh")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    database = Database(settings.database_url)
    gateway_client = httpx.Client(timeout=httpx.Timeout(settings.drunix_gateway_timeout_seconds, connect=1),
                                 trust_env=False, follow_redirects=False)
    logger.setLevel(settings.log_level)

    @asynccontextmanager
    async def lifespan(app):
        # Schema changes are exclusively Alembic-managed; no create_all fallback.
        try:
            yield
        finally:
            gateway_client.close()
            database.engine.dispose()

    app = FastAPI(title="TokANSH Backend", version="0.2.0", lifespan=lifespan,
                  responses={status: {"model": ErrorEnvelope} for status in [400, 401, 403, 404, 409, 422, 500, 503]})
    app.state.settings, app.state.database = settings, database
    app.state.sessions = SessionStore()
    app.state.gateway = GatewayAdapter(settings.drunix_gateway_url, gateway_client)
    app.state.transfer_gateway = TransferGateway(settings, gateway_client)
    register_handlers(app)

    @app.middleware("http")
    async def correlate_request(request: Request, call_next):
        supplied_id = request.headers.get("X-Correlation-ID")
        request.state.correlation_id = str(uuid4())
        if supplied_id is not None:
            if not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", supplied_id):
                return error_response(request, 400, "INVALID_REQUEST", "Invalid X-Correlation-ID header.")
            request.state.correlation_id = supplied_id
        try:
            response = await call_next(request)
        except Exception as exc:
            # Log classification and correlation, never request bodies or SQL/secret values.
            logger.error("unhandled_error type=%s correlation_id=%s", type(exc).__name__, request.state.correlation_id)
            response = error_response(request, 500, "INTERNAL_ERROR", "The request could not be completed.")
        response.headers["X-Correlation-ID"] = request.state.correlation_id
        return response

    app.add_middleware(CORSMiddleware, allow_origins=settings.allowed_origins, allow_credentials=True,
                       allow_methods=["GET", "POST", "OPTIONS"],
                       allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Correlation-ID"],
                       expose_headers=["X-Correlation-ID"])
    api = APIRouter(prefix="/api/v1")
    api.include_router(auth_router)
    api.include_router(properties_router)
    api.include_router(transfers_router)
    api.include_router(financing_router)
    api.include_router(wallet_router)
    api.include_router(issuance_router)
    api.include_router(marketplace_router)
    api.include_router(portfolio_router)
    app.include_router(api)
    app.include_router(system_router)
    app.include_router(diagnostic_router)
    return app
