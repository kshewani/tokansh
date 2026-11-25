"""Investor portfolio (API_CONTRACTS 7.9, Rules 11.1-11.3).

ANSH positions are a projection of committed DRUNIX state; ``?verify=true``
re-reads each balance from the ledger. REIT holdings are a separate, simulated
asset class (ADR-019) and are never mixed into ANSH figures.
"""
import sqlalchemy as sa
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.deps import current_user, get_db, get_ledger
from app.core.errors import ApiError, forbidden
from app.core.money import from_minor
from app.core.serial import envelope, iso
from app.db import models as m
from app.db.enums import PledgeStatus, UserRole, ValuationPurpose
from app.ledger import executor
from app.ledger.port import LedgerPort
from app.modules.common import get_or_404, user_brief
from app.modules.ledger_reads import ledger_position
from app.modules import wallet
from app.modules.marketplace import order_view

router = APIRouter(prefix="/api/v1/portfolios", tags=["Portfolio"])


def _owner(db: Session, user_id: str, viewer: m.User) -> m.User:
    owner = get_or_404(db, m.User, user_id, "User")
    if viewer.id != owner.id and viewer.role not in (UserRole.ADMIN, UserRole.ISSUER, UserRole.LENDER):
        raise forbidden("You can view only your own portfolio.")
    return owner


def _market_unit(db: Session, property_id: str) -> int | None:
    v = db.scalar(sa.select(m.PropertyValuation).filter_by(property_id=property_id,
                                                           purpose=ValuationPurpose.ILLUSTRATIVE_MARKET)
                  .order_by(m.PropertyValuation.observed_at.desc()).limit(1))
    return v.unit_value_minor if v else None


def ansh_holdings(db: Session, owner: m.User, ledger: LedgerPort | None = None) -> list[dict]:
    rows = []
    for pos in db.scalars(sa.select(m.OwnershipPosition).filter_by(investor_id=owner.id)):
        iss = db.get(m.AnshIssuance, pos.issuance_id)
        prop = db.get(m.Property, iss.property_id)
        unit = _market_unit(db, prop.id)
        row = {"issuance_id": iss.id, "ansh_asset_id": iss.ansh_asset_id, "property_id": prop.id,
               "property_name": prop.property_name, "owned_units": pos.owned_quantity,
               "pledged_units": pos.pledged_quantity, "available_units": pos.available_quantity,
               "acquisition_cost": from_minor(pos.acquisition_cost_minor),
               "illustrative_unit_value": from_minor(unit),
               "illustrative_value": from_minor(unit * pos.owned_quantity) if unit is not None else None,
               "currency": pos.currency, "source": "DRUNIX_PROJECTION", "ledger_reference": pos.ledger_reference,
               "as_of": iso(pos.observed_at), "reconciliation_status": pos.reconciliation_status.value,
               "valuation_is_simulated": True}
        if ledger is not None:
            try:
                bal = ledger_position(db, ledger, iss, owner)
                row["ledger_verification"] = {"status": "VERIFIED" if (bal["owned"], bal["pledged"]) ==
                                              (pos.owned_quantity, pos.pledged_quantity) else "MISMATCH", **bal}
            except ApiError as exc:
                row["ledger_verification"] = {"status": "UNAVAILABLE", "error_code": exc.code}
        rows.append(row)
    return rows


def reit_holdings(db: Session, owner: m.User) -> list[dict]:
    return [{"id": r.id, "reit_identifier": r.reit_identifier, "reit_name": r.reit_name, "quantity": r.quantity,
             "purchase_value": from_minor(r.purchase_value_minor),
             "illustrative_market_value": from_minor(r.illustrative_market_value_minor), "currency": r.currency,
             "data_source": r.data_source, "is_simulated": r.is_simulated, "observed_at": iso(r.observed_at),
             "asset_class": "REIT"}
            for r in db.scalars(sa.select(m.ReitHolding).filter_by(investor_id=owner.id))]


def summary(db: Session, owner: m.User) -> dict:
    ansh = ansh_holdings(db, owner)
    reits = reit_holdings(db, owner)

    def sum_minor(rows: list[dict], key: str) -> int:
        return sum(_minor(r[key]) for r in rows if r[key] is not None)

    active_pledges = db.scalars(sa.select(m.CollateralPledge).filter_by(investor_id=owner.id,
                                                                        pledge_status=PledgeStatus.ACTIVE)).all()
    loans = db.scalars(sa.select(m.Loan).filter_by(borrower_id=owner.id)).all()
    return {"ansh": {"owned_units": sum(r["owned_units"] for r in ansh),
                     "pledged_units": sum(r["pledged_units"] for r in ansh),
                     "available_units": sum(r["available_units"] for r in ansh),
                     "acquisition_cost": from_minor(sum_minor(ansh, "acquisition_cost")),
                     "illustrative_value": from_minor(sum_minor(ansh, "illustrative_value")),
                     "source": "DRUNIX_PROJECTION"},
            "reit": {"holdings": len(reits), "purchase_value": from_minor(sum_minor(reits, "purchase_value")),
                     "illustrative_market_value": from_minor(sum_minor(reits, "illustrative_market_value")),
                     "is_simulated": True},
            "cash": {"balance": from_minor(wallet.balance(db, owner.id)), "simulated": True},
            "financing": {"active_pledges": len(active_pledges),
                          "outstanding_loans": from_minor(sum(l.outstanding_minor for l in loans)),
                          "is_simulated": True},
            "currency": "INR"}


def _minor(value: str) -> int:
    whole, _, frac = value.partition(".")
    sign = -1 if whole.startswith("-") else 1
    return sign * (abs(int(whole)) * 100 + int((frac or "0").ljust(2, "0")))


@router.get("/{user_id}")
def get_portfolio(user_id: str, request: Request, verify: bool = False, db: Session = Depends(get_db),
                  viewer: m.User = Depends(current_user), ledger: LedgerPort = Depends(get_ledger)):
    owner = _owner(db, user_id, viewer)
    return envelope(request, {"user": user_brief(owner), "ansh": ansh_holdings(db, owner, ledger if verify else None),
                              "reits": reit_holdings(db, owner), "summary": summary(db, owner)})


@router.get("/{user_id}/ansh")
def get_ansh(user_id: str, request: Request, verify: bool = False, db: Session = Depends(get_db),
             viewer: m.User = Depends(current_user), ledger: LedgerPort = Depends(get_ledger)):
    owner = _owner(db, user_id, viewer)
    return envelope(request, {"items": ansh_holdings(db, owner, ledger if verify else None)})


@router.get("/{user_id}/reits")
def get_reits(user_id: str, request: Request, db: Session = Depends(get_db), viewer: m.User = Depends(current_user)):
    return envelope(request, {"items": reit_holdings(db, _owner(db, user_id, viewer))})


@router.get("/{user_id}/summary")
def get_summary(user_id: str, request: Request, db: Session = Depends(get_db), viewer: m.User = Depends(current_user)):
    return envelope(request, summary(db, _owner(db, user_id, viewer)))


@router.get("/{user_id}/transactions")
def get_transactions(user_id: str, request: Request, db: Session = Depends(get_db),
                     viewer: m.User = Depends(current_user)):
    owner = _owner(db, user_id, viewer)
    orders = db.scalars(sa.select(m.PurchaseOrder).where(sa.or_(m.PurchaseOrder.buyer_id == owner.id,
                                                                m.PurchaseOrder.seller_id == owner.id))
                        .order_by(m.PurchaseOrder.created_at.desc())).all()
    ops = [op for op in db.scalars(sa.select(m.LedgerOperation).order_by(m.LedgerOperation.created_at.desc()))
           if owner.id in {d["user_id"] for d in executor.payload_of(op).get("deltas", [])}]
    return envelope(request, {"orders": [order_view(db, o) for o in orders],
                              "ledger_operations": [executor.operation_view(op) for op in ops]})
