"""Durable application reservations used by marketplace and finance workflows."""
import json

from sqlalchemy import select

from app.properties.models import ApplicationOperation, PurchaseOperation, SaleOffering

PURCHASE_RESERVATION_STATES = {
    "RESERVED", "PREPARING", "PREPARED", "SUBMISSION_PENDING", "SUBMITTED",
    "UNKNOWN", "COMMITTED_PENDING_SETTLEMENT", "RECONCILIATION_REQUIRED",
}
FINANCING_RESERVATION_STATES = {"APPROVED", "DISBURSED"}


def purchase_reserved_cash(session, buyer_id: str, exclude_purchase_id: str | None = None) -> int:
    query = select(PurchaseOperation).where(
        PurchaseOperation.buyer_id == buyer_id,
        PurchaseOperation.state.in_(PURCHASE_RESERVATION_STATES),
    )
    if exclude_purchase_id is not None:
        query = query.where(PurchaseOperation.id != exclude_purchase_id)
    return sum(row.total_amount_minor for row in session.scalars(query).all())


def offering_committed_quantity(session, issuer_id: str, property_id: str,
                                exclude_offering_id: str | None = None) -> int:
    query = select(SaleOffering).where(
        SaleOffering.issuer_id == issuer_id,
        SaleOffering.property_id == property_id,
        SaleOffering.status == "ACTIVE",
    )
    if exclude_offering_id is not None:
        query = query.where(SaleOffering.id != exclude_offering_id)
    return sum(row.offered_quantity - row.sold_quantity for row in session.scalars(query).all())


def financing_reserved_quantity(session, investor_id: str, property_id: str) -> int:
    rows = session.scalars(select(ApplicationOperation).where(
        ApplicationOperation.actor_id == investor_id,
        ApplicationOperation.status.like("FIN_%"),
    )).all()
    total = 0
    for row in rows:
        try:
            data = json.loads(row.response_json or "{}")
        except json.JSONDecodeError:
            continue
        if (data.get("type") == "SIMULATED_FINANCING" and data.get("property_id") == property_id
                and data.get("state") in FINANCING_RESERVATION_STATES):
            total += int(data.get("quantity", 0))
    return total


def transfer_reserved_quantity(session, sender_id: str, property_id: str,
                               exclude_operation_id: str | None = None) -> int:
    query = select(ApplicationOperation).where(
        ApplicationOperation.actor_id == sender_id,
        ApplicationOperation.status.in_({"PREPARING", "PREPARED", "SUBMISSION_PENDING", "SUBMITTED", "UNKNOWN"}),
    )
    if exclude_operation_id is not None:
        query = query.where(ApplicationOperation.id != exclude_operation_id)
    total = 0
    for row in session.scalars(query).all():
        try:
            data = json.loads(row.response_json or "{}")
            request = data.get("request", {})
            if (data.get("type") == "ANSH_TRANSFER" and request.get("asset_id") == property_id
                    and request.get("from_user_id") == sender_id):
                total += int(request.get("quantity", 0))
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
    return total
