"""Idempotency-Key handling (API_CONTRACTS 4.7, Rule 5.5).

The first request with a key runs and its response is stored. A repeat with the
same key and the same request returns the stored response without running the
operation again. A repeat with different parameters is an IDEMPOTENCY_CONFLICT.
"""
import hashlib
import json
from collections.abc import Callable

from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import sqlalchemy as sa

from app.core.errors import ApiError
from app.core.serial import envelope
from app.db import models as m
from app.db.types import utcnow

HEADER = "Idempotency-Key"


def request_hash(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def require_key(request: Request) -> str:
    key = request.headers.get(HEADER, "").strip()
    if not key or len(key) > 128:
        raise ApiError(400, "INVALID_REQUEST", f"An {HEADER} header (1-128 characters) is required for this operation.")
    return key


def run_idempotent(request: Request, db: Session, scope: str, payload: dict,
                   operation: Callable[[str], tuple[int, object]]) -> JSONResponse:
    """Run ``operation(key)`` at most once per (key, scope).

    ``operation`` returns (http_status, data). Business errors (4xx) are stored too,
    so a retry reports the same outcome. Unexpected failures (5xx) release the key.
    """
    key = require_key(request)
    digest = request_hash(payload)
    existing = db.scalar(sa.select(m.IdempotencyRecord).filter_by(idempotency_key=key, scope=scope))
    if existing is not None:
        if existing.request_hash != digest:
            raise ApiError(409, "IDEMPOTENCY_CONFLICT", "This Idempotency-Key was already used with different parameters.")
        if existing.completed_at is None:
            raise ApiError(409, "INVALID_OPERATION_STATE", "A request with this Idempotency-Key is still being processed.")
        body = json.loads(existing.response_body)
        body.setdefault("meta", {})["idempotent_replay"] = True
        return JSONResponse(status_code=existing.response_status, content=body)

    record = m.IdempotencyRecord(idempotency_key=key, scope=scope, request_hash=digest)
    db.add(record)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise ApiError(409, "INVALID_OPERATION_STATE", "A request with this Idempotency-Key is still being processed.")

    try:
        status, data = operation(key)
        body = envelope(request, data)
    except ApiError as exc:
        db.rollback()
        if exc.status >= 500:
            _release(db, record.id)
            raise
        status = exc.status
        body = {"error": {"code": exc.code, "message": exc.message, "details": exc.details},
                "meta": {"correlation_id": getattr(request.state, "correlation_id", None)}}
    except Exception:
        db.rollback()
        _release(db, record.id)
        raise

    record = db.get(m.IdempotencyRecord, record.id)
    record.response_status = status
    record.response_body = json.dumps(body, default=str)
    record.completed_at = utcnow()
    db.commit()
    return JSONResponse(status_code=status, content=body)


def _release(db: Session, record_id: str) -> None:
    rec = db.get(m.IdempotencyRecord, record_id)
    if rec is not None:
        db.delete(rec)
        db.commit()
