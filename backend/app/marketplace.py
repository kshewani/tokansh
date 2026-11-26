"""Durable issuer offerings and simulated-cash purchase settlement."""
import hashlib
import json
from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.dependencies import DemoActor, demo_actor, get_session
from app.errors import ApplicationError, success
from app.properties.models import ApplicationOperation, Property, PurchaseOperation, SaleOffering
from app.registration import LedgerOperation
from app.properties.service import PropertyService
from app.reservations import (financing_reserved_quantity,
                              offering_committed_quantity, purchase_reserved_cash,
                              transfer_reserved_quantity)
from app.transfers import MAX_QUANTITY, TransferRequest, TransferService
from app.wallet import DemoCashAccount, change

MAX_MINOR = 9007199254740991
ACTIVE_PURCHASE_STATES = {
    "RESERVED", "PREPARING", "PREPARED", "SUBMISSION_PENDING", "SUBMITTED",
    "UNKNOWN", "COMMITTED_PENDING_SETTLEMENT", "RECONCILIATION_REQUIRED",
}


class OfferingCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    property_id: Annotated[str, Field(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")]
    quantity: Annotated[int, Field(ge=1, le=MAX_QUANTITY)]


class PurchaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    offering_id: Annotated[str, Field(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")]
    quantity: Annotated[int, Field(ge=1, le=MAX_QUANTITY)]


def now():
    return datetime.now(timezone.utc).isoformat()


def available(offering: SaleOffering) -> int:
    return offering.offered_quantity - offering.sold_quantity - offering.reserved_quantity


def offering_view(row: SaleOffering) -> dict:
    return {
        "id": row.id, "property_id": row.property_id, "issuer_id": row.issuer_id,
        "offered_quantity": row.offered_quantity, "sold_quantity": row.sold_quantity,
        "reserved_quantity": row.reserved_quantity, "available_quantity": available(row),
        "price_minor": str(row.price_minor), "currency": row.currency,
        "status": row.status, "created_at": row.created_at, "updated_at": row.updated_at,
    }


def purchase_view(row: PurchaseOperation) -> dict:
    return {
        "operation_id": row.id, "offering_id": row.offering_id, "property_id": row.property_id,
        "buyer_id": row.buyer_id, "seller_id": row.seller_id, "quantity": row.quantity,
        "price_minor": str(row.price_minor), "total_amount_minor": str(row.total_amount_minor),
        "currency": row.currency, "state": row.state, "transfer_operation_id": row.transfer_operation_id,
        "transaction_id": row.transaction_id, "error_code": row.error_code,
        "created_at": row.created_at, "updated_at": row.updated_at,
    }


def investor_actor(actor: DemoActor):
    if actor.role != "INVESTOR":
        raise ApplicationError(403, "INSUFFICIENT_PERMISSIONS", "Only an authenticated investor may use issuer offerings or purchases.")
    return actor


class MarketplaceService:
    def __init__(self, database, gateway, settings):
        self.database, self.gateway, self.settings = database, gateway, settings

    def _property(self, session, property_id: str):
        record = session.get(Property, property_id)
        if record is None:
            raise ApplicationError(404, "RESOURCE_NOT_FOUND", "Property not found.")
        return record

    def _issuance(self, property_id: str, correlation_id: str):
        state = self.gateway.call("GET", "issuance-state/" + property_id, correlation_id)
        if (set(state) != {"schema_version", "property_id", "issuer_id", "approved_supply",
                           "cumulative_issued_supply", "remaining_issuance_capacity"}
                or state["property_id"] != property_id or type(state["cumulative_issued_supply"]) is not int
                or state["cumulative_issued_supply"] <= 0):
            raise ApplicationError(502, "GATEWAY_BAD_RESPONSE", "The Gateway returned an invalid issuance state.")
        return state

    def create_offering(self, command: OfferingCreate, actor: DemoActor, correlation_id: str):
        with self.database.sessions() as session:
            record = self._property(session, command.property_id)
            if record.issuer_id != actor.user_id:
                raise ApplicationError(403, "INSUFFICIENT_PERMISSIONS", "Only the registered property issuer may create an offering.")
            if record.status != "DRAFT":
                raise ApplicationError(409, "INVALID_PROPERTY_STATE", "The property is not in a supported application state.")
            price_minor = record.issue_price_minor
            registered = session.scalar(select(LedgerOperation).where(
                LedgerOperation.property_id == record.id,
                LedgerOperation.state == "COMMITTED_VALID"))
            if registered is None:
                raise ApplicationError(409, "PROPERTY_NOT_REGISTERED", "The property registration is not committed.")
        self._issuance(command.property_id, correlation_id)
        with self.database.sessions() as session:
            session.connection().exec_driver_sql("BEGIN IMMEDIATE")
            record = self._property(session, command.property_id)
            active = session.scalar(select(SaleOffering).where(
                SaleOffering.property_id == command.property_id, SaleOffering.status == "ACTIVE"))
            if active is not None:
                raise ApplicationError(409, "ACTIVE_OFFERING_EXISTS", "The property already has an active offering.")
            # Re-read after taking the local write lock.  The pre-lock
            # balance used by earlier versions could become stale while a
            # trusted direct transfer was committing its own reservation.
            balance = self.gateway.balance(command.property_id, actor.user_id, correlation_id)
            reserved = (financing_reserved_quantity(session, actor.user_id, command.property_id)
                        + offering_committed_quantity(session, actor.user_id, command.property_id)
                        + transfer_reserved_quantity(session, actor.user_id, command.property_id))
            if command.quantity > balance["quantity"] - reserved:
                raise ApplicationError(409, "INSUFFICIENT_TRANSFERABLE_BALANCE", "The offering exceeds transferable issuer holdings.")
            timestamp = now()
            row = SaleOffering(id=str(uuid4()), property_id=record.id, issuer_id=record.issuer_id,
                               offered_quantity=command.quantity, sold_quantity=0, reserved_quantity=0,
                               price_minor=price_minor, currency="INR", status="ACTIVE",
                               created_at=timestamp, updated_at=timestamp)
            session.add(row)
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                raise ApplicationError(409, "ACTIVE_OFFERING_EXISTS", "The property already has an active offering.") from None
            return offering_view(row)

    def get_offering(self, offering_id: str):
        with self.database.sessions() as session:
            row = session.get(SaleOffering, offering_id)
            if row is None:
                raise ApplicationError(404, "RESOURCE_NOT_FOUND", "Sale offering was not found.")
            return offering_view(row)

    def list_offerings(self, issuer_id: str | None = None, active_only=True):
        with self.database.sessions() as session:
            query = select(SaleOffering)
            if active_only:
                query = query.where(SaleOffering.status == "ACTIVE")
            if issuer_id is not None:
                query = query.where(SaleOffering.issuer_id == issuer_id)
            return [offering_view(row) for row in session.scalars(query.order_by(SaleOffering.created_at.desc())).all()]

    def close_offering(self, offering_id: str, actor: DemoActor):
        with self.database.sessions() as session:
            session.connection().exec_driver_sql("BEGIN IMMEDIATE")
            row = session.get(SaleOffering, offering_id)
            if row is None:
                raise ApplicationError(404, "RESOURCE_NOT_FOUND", "Sale offering was not found.")
            if row.issuer_id != actor.user_id:
                raise ApplicationError(403, "INSUFFICIENT_PERMISSIONS", "Only the offering issuer may close it.")
            if row.status != "ACTIVE":
                return offering_view(row)
            unresolved = session.scalar(select(PurchaseOperation.id).where(
                PurchaseOperation.offering_id == row.id,
                PurchaseOperation.state.in_(ACTIVE_PURCHASE_STATES)).limit(1))
            if unresolved is not None:
                raise ApplicationError(409, "PURCHASE_RESERVATION_PENDING", "The offering has an unresolved purchase reservation.")
            row.status = "CLOSED"
            row.updated_at = now()
            session.commit()
            return offering_view(row)

    def _purchase_reservation(self, command: PurchaseRequest, actor: DemoActor, key: str, correlation_id: str):
        digest = hashlib.sha256(("POST /api/v1/marketplace/purchases\n" + json.dumps(
            command.model_dump(), sort_keys=True, separators=(",", ":"))).encode()).hexdigest()
        with self.database.sessions() as session:
            session.connection().exec_driver_sql("BEGIN IMMEDIATE")
            existing = session.scalar(select(PurchaseOperation).where(
                PurchaseOperation.buyer_id == actor.user_id, PurchaseOperation.idempotency_key == key))
            if existing:
                if existing.request_hash != digest:
                    raise ApplicationError(409, "IDEMPOTENCY_CONFLICT", "This key was used with different purchase parameters.")
                return existing, False
            offering = session.get(SaleOffering, command.offering_id)
            if offering is None or offering.status != "ACTIVE":
                raise ApplicationError(409, "OFFERING_NOT_ACTIVE", "The sale offering is not active.")
            if offering.issuer_id == actor.user_id:
                raise ApplicationError(422, "SELF_PURCHASE_NOT_ALLOWED", "The issuer cannot purchase from its own offering.")
            if command.quantity > available(offering):
                raise ApplicationError(409, "INSUFFICIENT_OFFERING_INVENTORY", "The requested quantity exceeds offering availability.")
            if command.quantity * offering.price_minor > MAX_MINOR:
                raise ApplicationError(422, "INVALID_AMOUNT", "Purchase amount exceeds the supported integer-paise range.")
            cash = session.get(DemoCashAccount, actor.user_id)
            total_cash = cash.balance_minor if cash is not None else 0
            total = command.quantity * offering.price_minor
            if total_cash - purchase_reserved_cash(session, actor.user_id) < total:
                raise ApplicationError(409, "INSUFFICIENT_AVAILABLE_CASH", "Available simulated cash is insufficient.")
            purchase_id = str(uuid4())
            timestamp = now()
            purchase = PurchaseOperation(id=purchase_id, offering_id=offering.id, property_id=offering.property_id,
                buyer_id=actor.user_id, seller_id=offering.issuer_id, quantity=command.quantity,
                price_minor=offering.price_minor, total_amount_minor=total, currency="INR",
                idempotency_key=key, request_hash=digest, state="RESERVED",
                transfer_operation_id=purchase_id,
                created_at=timestamp, updated_at=timestamp)
            offering.reserved_quantity += command.quantity
            offering.updated_at = timestamp
            session.add(purchase)
            session.commit()
            return purchase, True

    def _settle(self, purchase_id: str, result: dict):
        with self.database.sessions() as session:
            session.connection().exec_driver_sql("BEGIN IMMEDIATE")
            purchase = session.get(PurchaseOperation, purchase_id)
            if purchase is None:
                raise ApplicationError(404, "RESOURCE_NOT_FOUND", "Purchase was not found.")
            if purchase.state == "SETTLED":
                return purchase_view(purchase)
            if purchase.state != "COMMITTED_PENDING_SETTLEMENT":
                raise ApplicationError(409, "INVALID_PURCHASE_STATE", "Purchase is not ready for settlement.")
            offering = session.get(SaleOffering, purchase.offering_id)
            if offering is None:
                raise ApplicationError(500, "PURCHASE_DATA_CORRUPT", "The purchase offering could not be loaded.")
            if offering.reserved_quantity < purchase.quantity:
                raise ApplicationError(500, "PURCHASE_DATA_CORRUPT", "The purchase inventory reservation is inconsistent.")
            buyer_entry = change(session, purchase.buyer_id, "PURCHASE_DEBIT", purchase.total_amount_minor,
                                 "purchase:debit:" + purchase.id, purchase_id=purchase.id)
            seller_entry = change(session, purchase.seller_id, "SALE_PROCEEDS", purchase.total_amount_minor,
                                  "purchase:proceeds:" + purchase.id, purchase_id=purchase.id)
            offering.reserved_quantity -= purchase.quantity
            offering.sold_quantity += purchase.quantity
            offering.status = "SOLD_OUT" if available(offering) == 0 else "ACTIVE"
            offering.updated_at = now()
            purchase.state = "SETTLED"
            purchase.updated_at = now()
            purchase.transaction_id = result.get("transaction_id")
            session.commit()
            return purchase_view(purchase)

    def _release(self, purchase_id: str, state: str, error_code: str | None = None):
        with self.database.sessions() as session:
            session.connection().exec_driver_sql("BEGIN IMMEDIATE")
            purchase = session.get(PurchaseOperation, purchase_id)
            if purchase is None:
                raise ApplicationError(404, "RESOURCE_NOT_FOUND", "Purchase was not found.")
            if purchase.state in {"FAILED", "COMMITTED_INVALID"}:
                return purchase_view(purchase)
            if purchase.state == "SETTLED":
                return purchase_view(purchase)
            offering = session.get(SaleOffering, purchase.offering_id)
            if offering is not None and purchase.state in ACTIVE_PURCHASE_STATES:
                if offering.reserved_quantity < purchase.quantity:
                    raise ApplicationError(500, "PURCHASE_DATA_CORRUPT", "The purchase inventory reservation is inconsistent.")
                offering.reserved_quantity -= purchase.quantity
                offering.updated_at = now()
            purchase.state = state
            purchase.error_code = error_code
            purchase.updated_at = now()
            session.commit()
            return purchase_view(purchase)

    def _transfer(self, purchase: PurchaseOperation, actor: DemoActor, correlation_id: str):
        command = TransferRequest(asset_id=purchase.property_id, from_user_id=purchase.seller_id,
            to_user_id=purchase.buyer_id, quantity=purchase.quantity, kind="ACQUISITION", payment_outcome="SUCCESS")
        result = TransferService(self.database, self.gateway).initiate(
            command, actor, "purchase-transfer:" + purchase.id, correlation_id,
            purchase_offering_id=purchase.offering_id, operation_id=purchase.id)
        with self.database.sessions() as session:
            current = session.get(PurchaseOperation, purchase.id)
            current.updated_at = now()
            if result["state"] == "COMMITTED_VALID":
                current.state = "COMMITTED_PENDING_SETTLEMENT"
                current.transaction_id = result.get("transaction_id")
            elif result["state"] == "COMMITTED_INVALID":
                current.error_code = result.get("error_code")
            elif result["state"] in {"UNKNOWN", "SUBMITTED", "SUBMISSION_PENDING", "PREPARING", "PREPARED"}:
                current.state = "UNKNOWN" if result["state"] == "UNKNOWN" else result["state"]
            else:
                current.error_code = result.get("error_code")
            session.commit()
        return result

    def _transfer_error(self, purchase_id: str, error: ApplicationError):
        """Release only when the durable transfer operation is definitively failed.

        A transfer exception after a durable claim is not, by itself, evidence
        that DRUNIX did not commit.  Preserve the purchase reservation until
        the persisted transfer workflow can be reconciled.
        """
        with self.database.sessions() as session:
            purchase = session.get(PurchaseOperation, purchase_id)
            operation = session.get(ApplicationOperation, purchase_id)
            if purchase is None:
                raise ApplicationError(404, "RESOURCE_NOT_FOUND", "Purchase was not found.")
            if operation is not None and operation.status == "FAILED":
                definitive = True
            else:
                definitive = False
                purchase.state = ("UNKNOWN" if operation is not None and operation.status in {
                    "SUBMISSION_PENDING", "SUBMITTED", "UNKNOWN"
                } else "RECONCILIATION_REQUIRED")
                purchase.error_code = error.code
                purchase.updated_at = now()
                session.commit()
        if definitive:
            return self._release(purchase_id, "FAILED", error.code)
        return purchase_view(purchase)

    def purchase(self, command: PurchaseRequest, actor: DemoActor, key: str, correlation_id: str):
        purchase, created = self._purchase_reservation(command, actor, key, correlation_id)
        if not created:
            return purchase_view(purchase)
        try:
            result = self._transfer(purchase, actor, correlation_id)
        except ApplicationError as error:
            return self._transfer_error(purchase.id, error)
        if result["state"] == "COMMITTED_VALID":
            return self._settle(purchase.id, result)
        if result["state"] == "COMMITTED_INVALID":
            return self._release(purchase.id, "COMMITTED_INVALID", result.get("error_code"))
        if result["state"] in {"FAILED", "PAYMENT_FAILED"}:
            return self._release(purchase.id, "FAILED", result.get("error_code"))
        return self.get_purchase(purchase.id, actor.user_id)

    def get_purchase(self, purchase_id: str, buyer_id: str):
        with self.database.sessions() as session:
            row = session.get(PurchaseOperation, purchase_id)
            if row is None or row.buyer_id != buyer_id:
                raise ApplicationError(404, "RESOURCE_NOT_FOUND", "Purchase was not found.")
            return purchase_view(row)

    def reconcile(self, purchase_id: str, actor: DemoActor, correlation_id: str):
        with self.database.sessions() as session:
            purchase = session.get(PurchaseOperation, purchase_id)
            if purchase is None or purchase.buyer_id != actor.user_id:
                raise ApplicationError(404, "RESOURCE_NOT_FOUND", "Purchase was not found.")
            state = purchase.state
            transfer_operation = session.get(ApplicationOperation, purchase_id)
        if state in {"SETTLED", "FAILED", "COMMITTED_INVALID"}:
            return self.get_purchase(purchase_id, actor.user_id)
        if transfer_operation is None:
            if state != "RESERVED":
                return self.get_purchase(purchase_id, actor.user_id)
            try:
                transfer = self._transfer(purchase, actor, correlation_id)
            except ApplicationError as error:
                return self._transfer_error(purchase_id, error)
        elif transfer_operation.status in {"SUBMISSION_PENDING", "SUBMITTED", "UNKNOWN"}:
            transfer = TransferService(self.database, self.gateway).reconcile(purchase_id, actor.user_id, correlation_id)
        else:
            transfer = TransferService(self.database, self.gateway).read(purchase_id, actor.user_id)
        with self.database.sessions() as session:
            purchase = session.get(PurchaseOperation, purchase_id)
            purchase.transfer_operation_id = purchase_id
            purchase.updated_at = now()
            if transfer["state"] == "COMMITTED_VALID":
                purchase.state = "COMMITTED_PENDING_SETTLEMENT"
                purchase.transaction_id = transfer.get("transaction_id")
            elif transfer["state"] == "COMMITTED_INVALID":
                purchase.error_code = transfer.get("error_code")
            elif transfer["state"] == "UNKNOWN":
                purchase.state = "UNKNOWN"
            session.commit()
        if transfer["state"] == "COMMITTED_VALID":
            return self._settle(purchase_id, transfer)
        if transfer["state"] == "COMMITTED_INVALID":
            return self._release(purchase_id, "COMMITTED_INVALID", transfer.get("error_code"))
        if transfer["state"] in {"FAILED", "PAYMENT_FAILED"}:
            return self._release(purchase_id, "FAILED", transfer.get("error_code"))
        return self.get_purchase(purchase_id, actor.user_id)


router = APIRouter(prefix="/marketplace", tags=["marketplace"])
Actor = Annotated[DemoActor, Depends(demo_actor)]
Ready = Depends(get_session)
Key = Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")]


def service(request: Request):
    return MarketplaceService(request.app.state.database, request.app.state.transfer_gateway, request.app.state.settings)


@router.post("/offerings", dependencies=[Ready], status_code=201)
def create_offering(command: OfferingCreate, request: Request, actor: Actor):
    return success(request, service(request).create_offering(command, investor_actor(actor), request.state.correlation_id))


@router.get("/offerings", dependencies=[Ready])
def list_offerings(request: Request, actor: Actor, mine: bool = False, active_only: bool = True):
    actor = investor_actor(actor)
    return success(request, service(request).list_offerings(actor.user_id if mine else None, active_only=active_only))


@router.get("/offerings/{offering_id}", dependencies=[Ready])
def get_offering(offering_id: UUID, request: Request, actor: Actor):
    investor_actor(actor)
    return success(request, service(request).get_offering(str(offering_id)))


@router.post("/offerings/{offering_id}/close", dependencies=[Ready])
def close_offering(offering_id: UUID, request: Request, actor: Actor):
    return success(request, service(request).close_offering(str(offering_id), investor_actor(actor)))


@router.post("/purchases", dependencies=[Ready])
def create_purchase(command: PurchaseRequest, request: Request, response: Response, actor: Actor, key: Key):
    result = service(request).purchase(command, investor_actor(actor), key, request.state.correlation_id)
    response.status_code = 202 if result["state"] in ACTIVE_PURCHASE_STATES | {"COMMITTED_PENDING_SETTLEMENT"} else 200
    return success(request, result)


@router.get("/purchases/{purchase_id}", dependencies=[Ready])
def get_purchase(purchase_id: UUID, request: Request, actor: Actor):
    return success(request, service(request).get_purchase(str(purchase_id), investor_actor(actor).user_id))


@router.post("/purchases/{purchase_id}/reconcile", dependencies=[Ready])
def reconcile_purchase(purchase_id: UUID, request: Request, actor: Actor):
    return success(request, service(request).reconcile(str(purchase_id), investor_actor(actor), request.state.correlation_id))
