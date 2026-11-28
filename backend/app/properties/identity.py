"""Stable, human-readable property symbols.

Symbols are presentation metadata only.  All ledger and API operations use
the immutable property UUID.
"""
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.properties.models import Property


KNOWN_SYMBOLS = (
    ("SILVER OAK", "OAK"), ("GREEN ACRES", "GREEN"), ("URBAN NEST", "NEST"),
    ("CORNERSTONE", "CORNER"), ("HILLCREST", "HILL"), ("METRO", "METRO"),
    ("PALM HAVEN", "PALM"), ("SUMMIT", "SUMMIT"), ("TECHPARK", "TECHPARK"),
)


def suggested_symbol(name: str) -> str:
    normalized = " ".join(re.findall(r"[A-Za-z0-9]+", name.upper()))
    for hint, symbol in KNOWN_SYMBOLS:
        if hint in normalized:
            return symbol
    words = normalized.split()
    return ("-".join(words[:2]) or "PROPERTY")[:24]


def allocate_symbol(session: Session, name: str, requested: str | None = None) -> str:
    base = (requested or suggested_symbol(name)).strip().upper()
    base = re.sub(r"[^A-Z0-9-]", "-", base).strip("-") or "PROPERTY"
    base = base[:24]
    used = set(session.scalars(select(Property.friendly_symbol).where(Property.friendly_symbol.is_not(None))).all())
    candidate = base
    suffix = 2
    while candidate in used:
        candidate = f"{base[:max(1, 31 - len(str(suffix)) - 1)]}-{suffix}"
        suffix += 1
    return candidate


def display_symbol(value: str | None, name: str) -> str:
    return "ANSH-" + ((value or suggested_symbol(name)).strip().upper())
