"""Authoritative balance reads from DRUNIX (Rules 4.4, 5.2, 7.4, 8.2).

Pre-checks use the ledger, not the application projection. The chaincode still
re-validates at execution time (Rule 7.5); these checks give clear early errors.
"""
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.db import models as m
from app.db.enums import PositionStatus
from app.ledger.port import LedgerPort, LedgerUnavailable
from app.modules.common import position


def ledger_position(db: Session, ledger: LedgerPort, issuance: m.AnshIssuance, user: m.User) -> dict:
    try:
        result = ledger.get_position(issuance.property_id, user.id)  # GetBalance on DRUNIX
    except LedgerUnavailable as exc:
        raise ApiError(503, "LEDGER_UNAVAILABLE",
                       "DRUNIX is unavailable, so ledger balances cannot be verified. No operation was performed.",
                       {"reason": exc.message})
    owned, pledged = int(result.get("owned", 0)), int(result.get("pledged", 0))
    pos = position(db, user.id, issuance.id)
    if pos is not None and (pos.owned_quantity, pos.pledged_quantity) != (owned, pledged):
        # The projection disagrees with the ledger: flag it, never overwrite silently.
        pos.reconciliation_status = PositionStatus.RECONCILIATION_REQUIRED
        db.commit()
    return {"owned": owned, "pledged": pledged, "available": owned - pledged}


def check_available(balance: dict, quantity: int, *, allow_pledged_message: bool = True) -> None:
    if quantity <= balance["available"]:
        return
    details = {"requested_quantity": quantity, "available_quantity": balance["available"],
               "owned_quantity": balance["owned"], "pledged_quantity": balance["pledged"]}
    if allow_pledged_message and quantity <= balance["owned"]:
        raise ApiError(409, "PLEDGED_UNITS_RESTRICTED",
                       "The requested quantity includes pledged units, which cannot be transferred.", details)
    raise ApiError(409, "INSUFFICIENT_AVAILABLE_ANSH", "The requested quantity exceeds available ANSH.", details)
