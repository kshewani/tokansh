"""Structured API errors (API_CONTRACTS sections 5.2 and 11)."""
from typing import Any


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details or {}


def not_found(entity: str, entity_id: str) -> ApiError:
    return ApiError(404, "RESOURCE_NOT_FOUND", f"{entity} not found.", {"id": entity_id})


def invalid_state(message: str, **details) -> ApiError:
    return ApiError(409, "INVALID_OPERATION_STATE", message, details)


def forbidden(message: str = "You do not have permission for this operation.") -> ApiError:
    return ApiError(403, "INSUFFICIENT_PERMISSIONS", message)


def invalid(message: str, **details) -> ApiError:
    return ApiError(400, "INVALID_REQUEST", message, details)
