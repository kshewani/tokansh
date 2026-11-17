"""Response helpers: envelope, timestamps and pagination (API_CONTRACTS 4.5, 4.6, 5.1)."""
import math
from datetime import date, datetime, timezone

import sqlalchemy as sa
from fastapi import Request
from sqlalchemy.orm import Session

from app.core.errors import ApiError


def iso(value: datetime | date | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return value.isoformat()


def envelope(request: Request, data) -> dict:
    return {"data": data, "meta": {"correlation_id": getattr(request.state, "correlation_id", None)}}


def page_params(page: int = 1, page_size: int = 20) -> tuple[int, int]:
    if page < 1 or page_size < 1 or page_size > 100:
        raise ApiError(422, "INVALID_REQUEST", "page must be >= 1 and page_size between 1 and 100.")
    return page, page_size


def paginate(db: Session, stmt, page: int, page_size: int, render) -> dict:
    page, page_size = page_params(page, page_size)
    total = db.scalar(sa.select(sa.func.count()).select_from(stmt.order_by(None).subquery()))
    rows = db.scalars(stmt.limit(page_size).offset((page - 1) * page_size)).all()
    return {"items": [render(r) for r in rows], "page": page, "page_size": page_size,
            "total_items": total, "total_pages": math.ceil(total / page_size) if total else 0}
