"""Money conversion between API decimal strings and integer paise (ADR-015).

The API carries amounts as decimal strings ("5000000.00"); the database stores
integer minor units. Binary floating point is never used.
"""
from decimal import Decimal, InvalidOperation
from typing import Annotated

from pydantic import StringConstraints

from app.core.errors import ApiError

# At most two decimal places, no sign, no exponent.
Amount = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^\d{1,15}(\.\d{1,2})?$")]


def to_minor(value: str, field: str = "amount", allow_zero: bool = False) -> int:
    try:
        d = Decimal(value)
    except InvalidOperation:
        raise ApiError(422, "INVALID_REQUEST", f"{field} is not a valid decimal amount.", {"field": field})
    minor = d * 100
    if minor != minor.to_integral_value():
        raise ApiError(422, "INVALID_REQUEST", f"{field} has more than two decimal places.", {"field": field})
    minor = int(minor)
    if minor < 0 or (minor == 0 and not allow_zero):
        raise ApiError(422, "INVALID_REQUEST", f"{field} must be greater than zero.", {"field": field})
    return minor


def from_minor(minor: int | None) -> str | None:
    if minor is None:
        return None
    sign = "-" if minor < 0 else ""
    minor = abs(minor)
    return f"{sign}{minor // 100}.{minor % 100:02d}"


def bps_to_percent(bps: int | None) -> str | None:
    if bps is None:
        return None
    return f"{bps // 100}.{bps % 100:02d}"


def ratio_bps(numerator: int, denominator: int) -> int:
    """numerator / denominator in basis points, rounded half up, integers only."""
    if denominator <= 0:
        raise ValueError("denominator must be positive")
    return (numerator * 10000 * 2 + denominator) // (denominator * 2)
