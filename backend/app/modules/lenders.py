"""Fictional lender catalogue (adopted from the connected-mode branch). No real credit or banking.

Each demo lender institution is a LENDER user (login username = catalogue id) with
fixed offers. An application must match its offer's rate and a supported tenure.
The offer's maximum LTV applies, capped by the platform ceiling MAX_LTV_BPS (Rule 8.5).
"""
from dataclasses import dataclass

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.deps import current_user, get_db, get_settings
from app.core.errors import ApiError
from app.core.money import bps_to_percent
from app.core.serial import envelope
from app.db import models as m
from app.db.enums import UserRole, UserStatus


@dataclass(frozen=True)
class Offer:
    id: str
    name: str
    annual_rate_bps: int
    max_ltv_bps: int
    tenures_months: tuple[int, ...]


CATALOGUE: dict[str, tuple[Offer, ...]] = {
    "axim-bank": (Offer("axim-standard", "Standard", 1000, 6000, (6, 12)),),
    "real-finance": (Offer("real-flex", "Flex", 900, 5500, (6, 12, 24)),),
    "horizon-credit": (Offer("horizon-liquidity", "Liquidity", 1200, 7000, (3, 6, 12)),),
}
DEFAULT_LENDER = "axim-bank"


def effective_max_ltv(offer: Offer, settings: Settings) -> int:
    return min(offer.max_ltv_bps, settings.max_ltv_bps)


def offers_for(lender: m.User) -> tuple[Offer, ...]:
    return CATALOGUE.get((lender.ledger_identity_ref or "").lower(), ())


def resolve(db: Session, lender_id: str | None, offer_id: str | None) -> tuple[m.User, Offer]:
    if lender_id:
        lender = db.get(m.User, lender_id)
    else:
        lender = db.scalar(sa.select(m.User).where(sa.func.lower(m.User.ledger_identity_ref) == DEFAULT_LENDER))
    if lender is None or lender.role != UserRole.LENDER or not offers_for(lender):
        raise ApiError(422, "INVALID_LENDER", "Select a lender from the catalogue.")
    offers = offers_for(lender)
    offer = next((o for o in offers if o.id == offer_id), None) if offer_id else offers[0]
    if offer is None:
        raise ApiError(422, "INVALID_OFFER", "Select one of this lender's offers.")
    return lender, offer


def offer_view(o: Offer, settings: Settings) -> dict:
    return {"id": o.id, "name": o.name, "annual_rate_percent": bps_to_percent(o.annual_rate_bps),
            "annual_rate_bps": o.annual_rate_bps, "max_ltv_percent": bps_to_percent(o.max_ltv_bps),
            "effective_max_ltv_percent": bps_to_percent(effective_max_ltv(o, settings)),
            "tenures_months": list(o.tenures_months)}


router = APIRouter(prefix="/api/v1/financing", tags=["Collateral and financing"])


@router.get("/lenders")
def list_lenders(request: Request, db: Session = Depends(get_db), user: m.User = Depends(current_user),
                 settings: Settings = Depends(get_settings)):
    lenders = db.scalars(sa.select(m.User).where(m.User.role == UserRole.LENDER, m.User.status == UserStatus.ACTIVE)
                         .order_by(m.User.full_name)).all()
    return envelope(request, {"items": [{"id": u.id, "username": u.ledger_identity_ref, "name": u.full_name,
                                         "simulated": True, "offers": [offer_view(o, settings) for o in offers_for(u)]}
                                        for u in lenders if offers_for(u)]})
