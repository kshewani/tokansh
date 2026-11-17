"""Health, system status, demo users and dashboard (API_CONTRACTS 7.1-7.3)."""
import sqlalchemy as sa
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.deps import current_user, get_db, get_ledger, get_settings
from app.core.errors import ApiError
from app.core.money import bps_to_percent, from_minor
from app.core.serial import envelope, iso
from app.db import models as m
from app.db.enums import (IssuanceStatus, LoanStatus, OperationStatus, PledgeStatus, PropertyStatus, UserRole,
                          UserStatus)
from app.ledger import executor
from app.ledger.port import LedgerPort
from app.modules.common import get_or_404

router = APIRouter(tags=["System"])

ROLE_INFO = {
    UserRole.ADMIN: "Platform administration, property review and reconciliation.",
    UserRole.ISSUER: "Property onboarding, approval, ANSH issuance and distributions.",
    UserRole.INVESTOR: "Marketplace purchases, portfolio, pledges and simulated loans.",
    UserRole.LENDER: "Simulated credit assessment, approval, disbursement and release.",
}


def _db_ok(db: Session) -> bool:
    try:
        db.execute(sa.text("SELECT 1"))
        return True
    except Exception:
        return False


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/ready")
def ready(db: Session = Depends(get_db), ledger: LedgerPort = Depends(get_ledger)):
    db_ok, ledger_health = _db_ok(db), ledger.health()
    ok = db_ok and ledger_health["status"] == "CONNECTED"
    return JSONResponse(status_code=200 if ok else 503,
                        content={"status": "ready" if ok else "not_ready",
                                 "database": "CONNECTED" if db_ok else "UNAVAILABLE",
                                 "drunix_gateway": ledger_health["status"]})


@router.get("/api/v1/system/status")
def system_status(request: Request, db: Session = Depends(get_db), ledger: LedgerPort = Depends(get_ledger)):
    lh = ledger.health()
    last = db.scalar(sa.select(m.LedgerOperation).order_by(m.LedgerOperation.created_at.desc()).limit(1))
    pending = db.scalar(sa.select(sa.func.count()).select_from(m.LedgerOperation)
                        .where(m.LedgerOperation.status.in_([OperationStatus.RECONCILIATION_REQUIRED,
                                                             OperationStatus.UNKNOWN, OperationStatus.SUBMITTED])))
    components = [
        {"name": "Python API", "status": "CONNECTED", "detail": "FastAPI application responding."},
        {"name": "Application database", "status": "CONNECTED" if _db_ok(db) else "UNAVAILABLE",
         "detail": "SQLite application database (not the ledger)."},
        {"name": "DRUNIX gateway adapter", "status": lh["status"], "detail": lh.get("detail")},
        {"name": "Payment simulator", "status": "CONNECTED", "detail": "SIMULATED: no real payments."},
        {"name": "Lender simulator", "status": "CONNECTED", "detail": "SIMULATED: no real lending."},
    ]
    return envelope(request, {"components": components,
                              "last_ledger_operation": executor.operation_view(last),
                              "unresolved_ledger_operations": pending})


@router.get("/api/v1/system/configuration")
def configuration(request: Request, settings: Settings = Depends(get_settings), ledger: LedgerPort = Depends(get_ledger)):
    return envelope(request, {"app_env": settings.app_env, "drunix_channel": settings.drunix_channel,
                              "drunix_chaincode": settings.drunix_chaincode,
                              "drunix_gateway_configured": bool(settings.drunix_gateway_url),
                              "max_ltv_percent": bps_to_percent(settings.max_ltv_bps), "currency": "INR",
                              "ledger_simulator_available": False})


def user_view(u: m.User) -> dict:
    return {"id": u.id, "name": u.full_name, "email": u.email, "role": u.role.value, "status": u.status.value}


@router.get("/api/v1/users")
def list_users(request: Request, db: Session = Depends(get_db)):
    """Public list so the demo sign-in screen can choose an account. Not authentication."""
    users = db.scalars(sa.select(m.User).where(m.User.status == UserStatus.ACTIVE).order_by(m.User.full_name)).all()
    return envelope(request, {"items": [user_view(u) for u in users]})


@router.get("/api/v1/users/{user_id}")
def get_user(user_id: str, request: Request, db: Session = Depends(get_db)):
    return envelope(request, user_view(get_or_404(db, m.User, user_id, "User")))


@router.get("/api/v1/roles")
def roles(request: Request):
    return envelope(request, {"items": [{"role": r.value, "description": d} for r, d in ROLE_INFO.items()]})


class ActiveRoleIn(BaseModel):
    role: UserRole


@router.post("/api/v1/demo/active-role")
def active_role(body: ActiveRoleIn, request: Request, db: Session = Depends(get_db)):
    """Return the demonstration user for a role; the client sends its id as X-Demo-User-Id."""
    u = db.scalar(sa.select(m.User).filter_by(role=body.role, status=UserStatus.ACTIVE).order_by(m.User.created_at).limit(1))
    if u is None:
        raise ApiError(404, "RESOURCE_NOT_FOUND", f"No demonstration user has the role {body.role.value}.")
    return envelope(request, {"user": user_view(u), "header": "X-Demo-User-Id",
                              "notice": "Demonstration identity only; not production authentication."})


@router.get("/api/v1/dashboard/summary")
def dashboard(request: Request, db: Session = Depends(get_db), user: m.User = Depends(current_user)):
    count = lambda model, *where: db.scalar(sa.select(sa.func.count()).select_from(model).where(*where))  # noqa: E731
    issued = db.scalar(sa.select(sa.func.coalesce(sa.func.sum(m.AnshIssuance.issued_quantity), 0))
                       .where(m.AnshIssuance.issuance_status == IssuanceStatus.CONFIRMED))
    approved = db.scalar(sa.select(sa.func.coalesce(sa.func.sum(m.Property.approved_supply), 0))
                         .where(m.Property.approval_status == PropertyStatus.APPROVED))
    valuation = db.scalar(sa.select(sa.func.coalesce(sa.func.sum(m.Property.illustrative_valuation_minor), 0))
                          .where(m.Property.approval_status == PropertyStatus.APPROVED))
    outstanding = db.scalar(sa.select(sa.func.coalesce(sa.func.sum(m.Loan.outstanding_minor), 0))
                            .where(m.Loan.loan_status.in_([LoanStatus.ACTIVE, LoanStatus.PARTIALLY_REPAID])))
    pledged = db.scalar(sa.select(sa.func.coalesce(sa.func.sum(m.CollateralPledge.quantity), 0))
                        .where(m.CollateralPledge.pledge_status == PledgeStatus.ACTIVE))
    return envelope(request, {
        "properties": {"total": count(m.Property), "approved": count(m.Property, m.Property.approval_status == PropertyStatus.APPROVED),
                       "pending_review": count(m.Property, m.Property.approval_status.in_([PropertyStatus.SUBMITTED, PropertyStatus.UNDER_REVIEW])),
                       "illustrative_approved_valuation": from_minor(valuation)},
        "ansh": {"approved_supply": approved, "issued": issued, "pledged": pledged, "source": "DRUNIX_PROJECTION"},
        "financing": {"outstanding": from_minor(outstanding), "simulated": True},
        "ledger": {"committed": count(m.LedgerOperation, m.LedgerOperation.status == OperationStatus.COMMITTED),
                   "failed": count(m.LedgerOperation, m.LedgerOperation.status == OperationStatus.FAILED),
                   "unresolved": count(m.LedgerOperation, m.LedgerOperation.status.in_(
                       [OperationStatus.RECONCILIATION_REQUIRED, OperationStatus.UNKNOWN, OperationStatus.SUBMITTED]))},
        "currency": "INR"})
