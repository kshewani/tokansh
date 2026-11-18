import logging

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException

logger = logging.getLogger("tokansh")


class ApplicationError(Exception):
    def __init__(self, status: int, code: str, message: str, details: dict | None = None):
        self.status, self.code, self.message, self.details = status, code, message, details


def success(request: Request, data):
    return {"data": data, "meta": {"correlation_id": request.state.correlation_id}}


def error_response(request: Request, status: int, code: str, message: str, details=None):
    correlation_id = request.state.correlation_id
    logger.warning("application_error code=%s correlation_id=%s", code, correlation_id)
    return JSONResponse(status_code=status, headers={"X-Correlation-ID": correlation_id}, content={
        "error": {"code": code, "message": message, "details": details or {}},
        "meta": {"correlation_id": correlation_id},
    })


def register_handlers(app):
    @app.exception_handler(ApplicationError)
    async def application_error(request, exc):
        return error_response(request, exc.status, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        # Do not echo raw request bodies, input values or validator exception contexts.
        errors = [{"location": list(error["loc"]), "message": error["msg"], "type": error["type"]}
                  for error in exc.errors()]
        return error_response(request, 422, "INVALID_REQUEST", "Request validation failed.", {"errors": errors})

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        code = "RESOURCE_NOT_FOUND" if exc.status_code == 404 else "INVALID_REQUEST"
        return error_response(request, exc.status_code, code, str(exc.detail))

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request, exc):
        logger.error("database_error type=%s correlation_id=%s", type(exc).__name__, request.state.correlation_id)
        return error_response(request, 503, "DATABASE_UNAVAILABLE", "The application database is unavailable.")
