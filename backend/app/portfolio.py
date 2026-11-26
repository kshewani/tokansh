"""Authenticated, property-scoped investor portfolio observations."""
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select

from app.auth import DemoIdentity, current_identity
from app.errors import ApplicationError, success
from app.properties.models import Property
from app.registration import LedgerOperation
from app.reservations import financing_reserved_quantity, offering_committed_quantity


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _registered(property_row: Property, operation: LedgerOperation | None) -> bool:
    if operation is None or operation.state != "COMMITTED_VALID":
        return False
    try:
        import json
        command = json.loads(operation.command_json)
    except (TypeError, ValueError, json.JSONDecodeError):
        return False
    return (command.get("property_id") == property_row.id
            and command.get("issuer_id") == property_row.issuer_id
            and command.get("approved_supply") == property_row.proposed_supply
            and command.get("issue_price_minor") == str(property_row.issue_price_minor)
            and command.get("currency") == property_row.currency)


def _issuance(gateway, property_id: str, correlation_id: str) -> dict:
    state = gateway.call("GET", "issuance-state/" + property_id, correlation_id)
    if (set(state) != {"schema_version", "property_id", "issuer_id", "approved_supply",
                       "cumulative_issued_supply", "remaining_issuance_capacity"}
            or state["property_id"] != property_id
            or type(state["approved_supply"]) is not int
            or type(state["cumulative_issued_supply"]) is not int
            or type(state["remaining_issuance_capacity"]) is not int
            or state["approved_supply"] < 1
            or not 0 <= state["cumulative_issued_supply"] <= state["approved_supply"]
            or state["remaining_issuance_capacity"] != state["approved_supply"] - state["cumulative_issued_supply"]):
        raise ApplicationError(502, "GATEWAY_BAD_RESPONSE", "The Gateway returned an invalid issuance state.")
    return state


class PortfolioService:
    def __init__(self, database, gateway):
        self.database, self.gateway = database, gateway

    def read(self, investor: DemoIdentity, correlation_id: str) -> dict:
        if investor.role != "INVESTOR":
            raise ApplicationError(403, "INSUFFICIENT_PERMISSIONS", "Only an authenticated investor may read a portfolio.")
        with self.database.sessions() as session:
            rows = list(session.scalars(select(Property).order_by(Property.created_at, Property.id)).all())
            registrations = {row.property_id: row for row in session.scalars(
                select(LedgerOperation).where(LedgerOperation.property_id.in_([row.id for row in rows]))
            ).all()}
            # Portfolio discovery is limited to properties whose registration
            # is already committed; draft application records are not assets.
            rows = [row for row in rows if _registered(row, registrations.get(row.id))]
            reservations = {
                row.id: (financing_reserved_quantity(session, investor.user_id, row.id),
                         offering_committed_quantity(session, investor.user_id, row.id))
                for row in rows
            }

        items = []
        unavailable = 0
        for row in rows:
            registration = registrations.get(row.id)
            base = {
                "property_id": row.id,
                "ansh_id": "ANSH-" + row.id.lower(),
                "name": row.name,
                "category": row.category,
                "location": row.location,
                "issuer_id": row.issuer_id,
                "registration_status": "REGISTERED" if _registered(row, registration) else "NOT_REGISTERED",
                "issuance_status": "UNAVAILABLE",
                "approved_valuation_minor": str(row.valuation_minor),
                "initial_issue_price_minor": str(row.issue_price_minor),
                "currency": row.currency,
                "approved_supply": row.proposed_supply,
                "issued_supply": None,
                "owned_units": None,
                "pledged_units": reservations[row.id][0],
                "offering_committed_units": reservations[row.id][1],
                "transferable_units": None,
                "observation_status": "UNAVAILABLE",
                "source": "DRUNIX_EVALUATE",
                "observed_at": None,
                "error_code": None,
            }
            if not _registered(row, registration):
                base["error_code"] = "PROPERTY_NOT_REGISTERED"
                unavailable += 1
                items.append(base)
                continue
            try:
                state = _issuance(self.gateway, row.id, correlation_id)
                balance = self.gateway.balance(row.id, investor.user_id, correlation_id)
                issued = state["cumulative_issued_supply"]
                owned = balance["quantity"]
                reserved = base["pledged_units"] + base["offering_committed_units"]
                base.update({
                    "issuance_status": "ISSUED" if issued else "REGISTERED",
                    "issued_supply": issued,
                    "owned_units": owned,
                    "transferable_units": max(0, owned - reserved),
                    "observation_status": "AVAILABLE",
                    "observed_at": now(),
                })
            except ApplicationError as error:
                base["error_code"] = error.code
                unavailable += 1
            items.append(base)

        available_items = [item for item in items if item["observation_status"] == "AVAILABLE"]
        total_value = sum(
            item["owned_units"] * int(item["initial_issue_price_minor"])
            for item in available_items
            if item["issued_supply"] and item["owned_units"] is not None
        )
        observed_value_count = sum(
            1 for item in available_items if item["issued_supply"] and item["owned_units"] is not None
        )
        return {
            "investor_id": investor.user_id,
            "currency": "INR",
            "items": items,
            "aggregate": {
                "status": "UNAVAILABLE" if not observed_value_count and items else "PARTIAL" if unavailable else "COMPLETE",
                "observed_property_count": observed_value_count,
                "total_indicative_value_minor": str(total_value) if observed_value_count and not unavailable else None,
                "valuation_basis": "INITIAL_ISSUE_PRICE" if observed_value_count else None,
            },
            "source": "DRUNIX_EVALUATE",
        }


router = APIRouter(prefix="/portfolio", tags=["portfolio"])
Actor = Annotated[DemoIdentity, Depends(current_identity)]


@router.get("")
def portfolio(request: Request, actor: Actor):
    return success(request, PortfolioService(request.app.state.database, request.app.state.transfer_gateway).read(
        actor, request.state.correlation_id))
