"""Human-readable ANSH symbols (adopted from main). Presentation metadata only:
the ledger, the API and every operation keep using the immutable property UUID."""
import re

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.db import models as m

KNOWN = (("SILVER OAK", "OAK"), ("GREEN ACRES", "GREEN"), ("URBAN NEST", "NEST"), ("CORNERSTONE", "CORNER"),
         ("HILLCREST", "HILL"), ("METRO", "METRO"), ("PALM HAVEN", "PALM"), ("SUMMIT", "SUMMIT"),
         ("TECHPARK", "TECHPARK"))


def suggested(name: str) -> str:
    normalized = " ".join(re.findall(r"[A-Za-z0-9]+", name.upper()))
    for hint, symbol in KNOWN:
        if hint in normalized:
            return symbol
    return ("-".join(normalized.split()[:2]) or "PROPERTY")[:24]


def allocate(db: Session, name: str) -> str:
    base = re.sub(r"[^A-Z0-9-]", "-", suggested(name)).strip("-")[:24] or "PROPERTY"
    used = set(db.scalars(sa.select(m.Property.friendly_symbol).where(m.Property.friendly_symbol.is_not(None))))
    candidate, n = base, 2
    while candidate in used:
        candidate, n = f"{base}-{n}", n + 1
    return candidate


def display(prop: m.Property) -> str:
    return "ANSH-" + (prop.friendly_symbol or suggested(prop.property_name))
