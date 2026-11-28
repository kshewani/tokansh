"""Marketplace listings, purchase orders and the simulated payment (API_CONTRACTS 7.6, 7.7, 10.1).

Sequence (Rule 6.1): validate -> simulated payment -> TransferANSH on DRUNIX ->
confirmed commit -> projections and order COMPLETED. A failed payment never
submits a transfer (Rule 6.2). Payment success followed by a definitive ledger
failure records a simulated refund (Rule 6.3). An unknown outcome is reconciled.
"""
import uuid
from typing import Literal

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.audit import asset_event, audit
from app.core.config import Settings
from app.core.deps import correlation_id, current_user, get_db, get_ledger, get_settings, require_role
from app.core.errors import ApiError, forbidden, invalid_state
from app.core.idempotency import run_idempotent
from app.core.money import Amount, from_minor, to_minor
from app.core.serial import envelope, iso, paginate
from app.db import models as m
from app.db.enums import (EventSource, WalletEntryKind, IssuanceStatus, ListingStatus, OperationType, OrderStatus, PaymentKind,
                          PaymentStatus, UserRole)
from app.db.types import utcnow
from app.ledger import executor
from app.ledger.port import LedgerPort
from app.ledger.projections import apply_deltas, delta
from app.modules import symbols, wallet
from app.modules.common import get_or_404, identity, user_brief
from app.modules.ledger_reads import check_available, ledger_position

router = APIRouter(prefix="/api/v1", tags=["Marketplace and payments"])
OPEN_LISTING = (ListingStatus.ACTIVE, ListingStatus.PARTIALLY_FILLED)


class ListingIn(BaseModel):
    issuance_id: str = Field(min_length=1, max_length=36)
    quantity: int = Field(gt=0, le=10**12)
    unit_price: Amount | None = None
    currency: Literal["INR"] = "INR"


class OrderIn(BaseModel):
    listing_id: str = Field(min_length=1, max_length=36)
    quantity: int = Field(gt=0, le=10**12)
    currency: Literal["INR"] = "INR"


class PaymentIn(BaseModel):
    order_id: str = Field(min_length=1, max_length=36)
    # The payment simulator's outcome is chosen explicitly so the demo can show a failure.
    simulated_outcome: Literal["SUCCESS", "FAILED"] = "SUCCESS"
    failure_reason: str | None = Field(default=None, max_length=300)


# ---------------------------------------------------------------- views

def listing_view(db: Session, lst: m.MarketplaceListing) -> dict:
    iss = db.get(m.AnshIssuance, lst.issuance_id)
    prop = db.get(m.Property, iss.property_id)
    return {"id": lst.id, "issuance_id": lst.issuance_id, "ansh_asset_id": iss.ansh_asset_id,
            "ansh_symbol": symbols.display(prop),
            "property": {"id": prop.id, "name": prop.property_name, "city": prop.city, "property_type": prop.property_type,
                         "valuation": from_minor(prop.illustrative_valuation_minor), "is_synthetic": prop.is_synthetic},
            "seller": user_brief(db.get(m.User, lst.seller_id)), "quantity": lst.quantity,
            "remaining_quantity": lst.remaining_quantity, "unit_price": from_minor(lst.unit_price_minor),
            "currency": lst.currency, "status": lst.listing_status.value, "created_at": iso(lst.created_at)}


def payment_view(p: m.PaymentRecord | None) -> dict | None:
    if p is None:
        return None
    return {"id": p.id, "order_id": p.order_id, "kind": p.payment_kind.value, "reference": p.payment_reference,
            "amount": from_minor(p.amount_minor), "currency": p.currency, "status": p.payment_status.value,
            "failure_reason": p.failure_reason, "simulated": p.simulation_flag, "source": "PAYMENT_SIMULATOR",
            "refund_of_payment_id": p.refund_of_payment_id, "created_at": iso(p.created_at),
            "completed_at": iso(p.completed_at)}


def order_view(db: Session, o: m.PurchaseOrder) -> dict:
    payments = db.scalars(sa.select(m.PaymentRecord).filter_by(order_id=o.id).order_by(m.PaymentRecord.created_at)).all()
    iss = db.get(m.AnshIssuance, o.issuance_id)
    prop = db.get(m.Property, iss.property_id)
    return {"id": o.id, "listing_id": o.listing_id, "issuance_id": o.issuance_id,
            "property_name": prop.property_name, "ansh_symbol": symbols.display(prop),
            "buyer": user_brief(db.get(m.User, o.buyer_id)), "seller": user_brief(db.get(m.User, o.seller_id)),
            "quantity": o.quantity, "unit_price": from_minor(o.unit_price_minor),
            "total_amount": from_minor(o.total_amount_minor), "currency": o.currency, "status": o.order_status.value,
            "failure_reason": o.failure_reason, "created_at": iso(o.created_at), "updated_at": iso(o.updated_at),
            "payments": [payment_view(p) for p in payments],
            "transfer": executor.operation_view(db.get(m.LedgerOperation, o.transfer_operation_id)
                                                if o.transfer_operation_id else None)}


def _set_order(db: Session, o: m.PurchaseOrder, status: OrderStatus, actor_id: str | None, **kw) -> None:
    previous = o.order_status
    o.order_status = status
    audit(db, entity_type="purchase_order", entity_id=o.id, operation_type="ORDER_STATUS", actor_id=actor_id,
          previous_state=previous, new_state=status, **kw)


# ---------------------------------------------------------------- ledger effects

def _transfer_committed(db: Session, op: m.LedgerOperation) -> None:
    apply_deltas(db, op)
    payload = executor.payload_of(op)
    order_id = payload.get("order_id")
    iss = db.get(m.AnshIssuance, payload["issuance_id"])
    if order_id:
        o = db.get(m.PurchaseOrder, order_id)
        o.transfer_operation_id = op.id
        lst = db.get(m.MarketplaceListing, o.listing_id)
        lst.remaining_quantity -= o.quantity  # only after the confirmed transfer (Rule 5.4)
        lst.listing_status = ListingStatus.FILLED if lst.remaining_quantity == 0 else ListingStatus.PARTIALLY_FILLED
        if _paid_from_wallet(db, o):  # simulated settlement: seller receives demo cash only after the commit
            wallet.move(db, o.seller_id, WalletEntryKind.SALE_PROCEEDS, o.total_amount_minor, f"order:{o.id}:proceeds")
        _set_order(db, o, OrderStatus.COMPLETED, o.buyer_id, source=EventSource.DRUNIX_LEDGER,
                   ledger_transaction_id=op.transaction_id, operation_id=op.id)
    asset_event(db, event_type="ANSH_TRANSFERRED", source=EventSource.DRUNIX_LEDGER, property_id=iss.property_id,
                issuance_id=iss.id, reference_id=order_id or op.entity_id, ledger_transaction_id=op.transaction_id,
                description=f"{payload['quantity']:,} ANSH transferred from {payload['from_name']} to {payload['to_name']}.")
    audit(db, entity_type="ansh_transfer", entity_id=op.entity_id, operation_type="ANSH_TRANSFER",
          actor_id=payload.get("from_user_id"), new_state="COMMITTED", source=EventSource.DRUNIX_LEDGER,
          operation_id=op.id, ledger_transaction_id=op.transaction_id,
          detail={"quantity": payload["quantity"], "to_user_id": payload["to_user_id"]})


def _transfer_failed(db: Session, op: m.LedgerOperation) -> None:
    payload = executor.payload_of(op)
    audit(db, entity_type="ansh_transfer", entity_id=op.entity_id, operation_type="ANSH_TRANSFER",
          actor_id=payload.get("from_user_id"), new_state="FAILED", outcome="FAILED", operation_id=op.id,
          detail={"error_code": op.error_code, "error_message": op.error_message})
    order_id = payload.get("order_id")
    if not order_id:
        return
    o = db.get(m.PurchaseOrder, order_id)
    o.transfer_operation_id = op.id
    paid = db.scalar(sa.select(m.PaymentRecord).filter_by(order_id=o.id, payment_kind=PaymentKind.PURCHASE,
                                                          payment_status=PaymentStatus.SUCCESS))
    _set_order(db, o, OrderStatus.RECONCILIATION_REQUIRED, o.buyer_id, outcome="FAILED", operation_id=op.id)
    if paid is not None:
        # Rule 6.3: keep the successful payment, record an explicit (simulated) refund.
        refund = m.PaymentRecord(order_id=o.id, payment_kind=PaymentKind.REFUND, refund_of_payment_id=paid.id,
                                 payment_reference=f"SIM-REFUND-{uuid.uuid4().hex[:12].upper()}",
                                 amount_minor=paid.amount_minor, currency=paid.currency,
                                 payment_status=PaymentStatus.SUCCESS, completed_at=utcnow())
        db.add(refund)
        if _paid_from_wallet(db, o):
            wallet.move(db, o.buyer_id, WalletEntryKind.PURCHASE_REFUND, paid.amount_minor, f"order:{o.id}:refund")
        audit(db, entity_type="payment", entity_id=paid.id, operation_type="PAYMENT_REFUNDED", actor_id=None,
              new_state="REFUNDED", source=EventSource.PAYMENT_SIMULATOR,
              detail={"refund_reference": refund.payment_reference})
    o.failure_reason = f"Ledger transfer failed ({op.error_code}); simulated refund recorded."[:300]
    _set_order(db, o, OrderStatus.FAILED, o.buyer_id, outcome="FAILED", operation_id=op.id)


def _paid_from_wallet(db: Session, o: m.PurchaseOrder) -> bool:
    return db.scalar(sa.select(m.DemoCashEntry.id).filter_by(reference_key=f"order:{o.id}:payment")) is not None


def _transfer_unresolved(db: Session, op: m.LedgerOperation) -> None:
    order_id = executor.payload_of(op).get("order_id")
    if order_id:
        o = db.get(m.PurchaseOrder, order_id)
        o.transfer_operation_id = op.id
        if o.order_status != OrderStatus.RECONCILIATION_REQUIRED:
            _set_order(db, o, OrderStatus.RECONCILIATION_REQUIRED, o.buyer_id, outcome="PENDING", operation_id=op.id)


executor.register(OperationType.ANSH_TRANSFER, committed=_transfer_committed, failed=_transfer_failed,
                  unresolved=_transfer_unresolved)


def submit_transfer(db: Session, ledger: LedgerPort, settings: Settings, *, issuance: m.AnshIssuance,
                    sender: m.User, recipient: m.User, quantity: int, cost_minor: int = 0,
                    order_id: str | None = None, corr: str | None = None) -> m.LedgerOperation:
    entity_id = order_id or str(uuid.uuid4())
    return executor.submit_operation(
        db, ledger, settings, op_type=OperationType.ANSH_TRANSFER,
        entity_type="purchase_order" if order_id else "ansh_transfer", entity_id=entity_id,
        command=lambda op_id: {"command_version": 1, "operation_id": op_id, "property_id": issuance.property_id,
                               "from_holder_id": identity(sender), "to_holder_id": identity(recipient),
                               "quantity": quantity},
        context={"issuance_id": issuance.id, "order_id": order_id, "quantity": quantity,
                 "from_user_id": sender.id, "to_user_id": recipient.id,
                 "from_name": sender.full_name, "to_name": recipient.full_name,
                 "deltas": [delta(sender.id, owned=-quantity), delta(recipient.id, owned=quantity, cost_minor=cost_minor)]},
        correlation_id=corr, order_id=order_id)


# ---------------------------------------------------------------- listings

@router.get("/marketplace/listings")
def list_listings(request: Request, issuance_id: str | None = None, include_closed: bool = False,
                  page: int = 1, page_size: int = 20, db: Session = Depends(get_db),
                  user: m.User = Depends(current_user)):
    stmt = sa.select(m.MarketplaceListing).order_by(m.MarketplaceListing.created_at.desc())
    if not include_closed:
        stmt = stmt.where(m.MarketplaceListing.listing_status.in_(OPEN_LISTING))
    if issuance_id:
        stmt = stmt.where(m.MarketplaceListing.issuance_id == issuance_id)
    return envelope(request, paginate(db, stmt, page, page_size, lambda x: listing_view(db, x)))


@router.post("/marketplace/listings", status_code=201)
def create_listing(body: ListingIn, request: Request, db: Session = Depends(get_db),
                   user: m.User = Depends(current_user), ledger: LedgerPort = Depends(get_ledger)):
    def op(_key: str):
        iss = get_or_404(db, m.AnshIssuance, body.issuance_id, "Issuance")
        if iss.issuance_status != IssuanceStatus.CONFIRMED:
            raise invalid_state("ANSH can be listed only after a confirmed issuance.")
        balance = ledger_position(db, ledger, iss, user)
        listed = db.scalar(sa.select(sa.func.coalesce(sa.func.sum(m.MarketplaceListing.remaining_quantity), 0))
                           .where(m.MarketplaceListing.seller_id == user.id,
                                  m.MarketplaceListing.issuance_id == iss.id,
                                  m.MarketplaceListing.listing_status.in_(OPEN_LISTING)))
        check_available({**balance, "available": balance["available"] - listed}, body.quantity)  # Rule 5.1
        price = to_minor(body.unit_price, "unit_price") if body.unit_price else iss.issue_price_minor
        lst = m.MarketplaceListing(seller_id=user.id, issuance_id=iss.id, quantity=body.quantity,
                                   remaining_quantity=body.quantity, unit_price_minor=price, currency=body.currency,
                                   listing_status=ListingStatus.ACTIVE)
        db.add(lst)
        db.flush()
        audit(db, entity_type="listing", entity_id=lst.id, operation_type="LISTING_CREATED", actor_id=user.id,
              new_state=ListingStatus.ACTIVE, correlation_id=correlation_id(request),
              detail={"quantity": body.quantity, "unit_price": from_minor(price)})
        db.commit()
        return 201, listing_view(db, lst)

    return run_idempotent(request, db, "POST /marketplace/listings", {"user": user.id, **body.model_dump()}, op)


@router.get("/marketplace/listings/{listing_id}")
def get_listing(listing_id: str, request: Request, db: Session = Depends(get_db), user: m.User = Depends(current_user)):
    return envelope(request, listing_view(db, get_or_404(db, m.MarketplaceListing, listing_id, "Listing")))


@router.post("/marketplace/listings/{listing_id}/cancel")
def cancel_listing(listing_id: str, request: Request, db: Session = Depends(get_db), user: m.User = Depends(current_user)):
    lst = get_or_404(db, m.MarketplaceListing, listing_id, "Listing")
    if lst.seller_id != user.id:
        raise forbidden("Only the seller can cancel this listing.")
    if lst.listing_status not in OPEN_LISTING:
        raise invalid_state("Listing is not open.", status=lst.listing_status.value)
    pending = db.scalar(sa.select(sa.func.count()).select_from(m.PurchaseOrder).where(
        m.PurchaseOrder.listing_id == lst.id,
        m.PurchaseOrder.order_status.in_([OrderStatus.PAYMENT_PENDING, OrderStatus.PAYMENT_SUCCEEDED,
                                          OrderStatus.TRANSFER_PENDING, OrderStatus.RECONCILIATION_REQUIRED])))
    if pending:
        raise invalid_state("Listing has orders in progress.", pending_orders=pending)
    previous = lst.listing_status
    lst.listing_status = ListingStatus.CANCELLED
    audit(db, entity_type="listing", entity_id=lst.id, operation_type="LISTING_CANCELLED", actor_id=user.id,
          previous_state=previous, new_state=ListingStatus.CANCELLED)
    db.commit()
    return envelope(request, listing_view(db, lst))


# ---------------------------------------------------------------- orders

def _validate_purchase(db: Session, ledger: LedgerPort, lst: m.MarketplaceListing, buyer: m.User, quantity: int):
    """Rule 5.2, re-run immediately before execution."""
    if lst.listing_status not in OPEN_LISTING:
        raise invalid_state("Listing is not active.", status=lst.listing_status.value)
    if quantity > lst.remaining_quantity:
        raise ApiError(409, "INSUFFICIENT_AVAILABLE_ANSH", "The listing has insufficient remaining quantity.",
                       {"requested_quantity": quantity, "remaining_quantity": lst.remaining_quantity})
    if buyer.id == lst.seller_id:
        raise invalid_state("A seller cannot buy their own listing.")
    iss = db.get(m.AnshIssuance, lst.issuance_id)
    seller = db.get(m.User, lst.seller_id)
    check_available(ledger_position(db, ledger, iss, seller), quantity, allow_pledged_message=False)
    return iss, seller


@router.post("/marketplace/orders", status_code=201)
def create_order(body: OrderIn, request: Request, db: Session = Depends(get_db),
                 user: m.User = Depends(current_user), ledger: LedgerPort = Depends(get_ledger)):
    require_role(user, UserRole.INVESTOR)

    def op(key: str):
        lst = get_or_404(db, m.MarketplaceListing, body.listing_id, "Listing")
        if body.currency != lst.currency:
            raise ApiError(422, "INVALID_REQUEST", "Order currency must match the listing currency.")
        _validate_purchase(db, ledger, lst, user, body.quantity)
        o = m.PurchaseOrder(buyer_id=user.id, seller_id=lst.seller_id, listing_id=lst.id, issuance_id=lst.issuance_id,
                            quantity=body.quantity, unit_price_minor=lst.unit_price_minor,
                            total_amount_minor=body.quantity * lst.unit_price_minor,  # Rule 5.3: backend computes
                            currency=lst.currency, idempotency_key=f"order:{user.id}:{key}"[:128])
        db.add(o)
        db.flush()
        audit(db, entity_type="purchase_order", entity_id=o.id, operation_type="ORDER_CREATED", actor_id=user.id,
              new_state=OrderStatus.CREATED, correlation_id=correlation_id(request))
        _set_order(db, o, OrderStatus.VALIDATED, user.id)
        _set_order(db, o, OrderStatus.PAYMENT_PENDING, user.id)
        db.commit()
        return 201, order_view(db, o)

    return run_idempotent(request, db, "POST /marketplace/orders", {"user": user.id, **body.model_dump()}, op)


@router.get("/marketplace/orders")
def list_orders(request: Request, page: int = 1, page_size: int = 20, db: Session = Depends(get_db),
                user: m.User = Depends(current_user)):
    stmt = sa.select(m.PurchaseOrder).order_by(m.PurchaseOrder.created_at.desc())
    if user.role not in (UserRole.ADMIN, UserRole.ISSUER):
        stmt = stmt.where(sa.or_(m.PurchaseOrder.buyer_id == user.id, m.PurchaseOrder.seller_id == user.id))
    return envelope(request, paginate(db, stmt, page, page_size, lambda o: order_view(db, o)))


def _order_for(db: Session, order_id: str, user: m.User) -> m.PurchaseOrder:
    o = get_or_404(db, m.PurchaseOrder, order_id, "Order")
    if user.id not in (o.buyer_id, o.seller_id) and user.role not in (UserRole.ADMIN, UserRole.ISSUER):
        raise forbidden()
    return o


@router.get("/marketplace/orders/{order_id}")
def get_order(order_id: str, request: Request, db: Session = Depends(get_db), user: m.User = Depends(current_user)):
    return envelope(request, order_view(db, _order_for(db, order_id, user)))


@router.get("/marketplace/orders/{order_id}/status")
def order_status(order_id: str, request: Request, db: Session = Depends(get_db), user: m.User = Depends(current_user)):
    o = _order_for(db, order_id, user)
    v = order_view(db, o)
    return envelope(request, {"order_id": o.id, "status": v["status"], "payments": v["payments"], "transfer": v["transfer"]})


# ---------------------------------------------------------------- simulated payment

@router.post("/payments/simulate")
def simulate_payment(body: PaymentIn, request: Request, db: Session = Depends(get_db),
                     user: m.User = Depends(current_user), ledger: LedgerPort = Depends(get_ledger),
                     settings: Settings = Depends(get_settings)):
    def op(_key: str):
        o = get_or_404(db, m.PurchaseOrder, body.order_id, "Order")
        if o.buyer_id != user.id:
            raise forbidden("Only the buyer can pay for this order.")
        if o.order_status != OrderStatus.PAYMENT_PENDING:
            raise invalid_state("Order is not awaiting payment.", status=o.order_status.value)
        lst = db.get(m.MarketplaceListing, o.listing_id)
        # Re-validate before taking payment, so payment is not taken when the transfer cannot proceed.
        iss, seller = _validate_purchase(db, ledger, lst, user, o.quantity)
        if body.simulated_outcome == "SUCCESS" and wallet.balance(db, user.id) < o.total_amount_minor:
            raise ApiError(409, "INSUFFICIENT_DEMO_CASH", "Not enough demo cash for this order. Add demo funds first.",
                           {"balance": from_minor(wallet.balance(db, user.id)), "required": from_minor(o.total_amount_minor)})
        pay = m.PaymentRecord(order_id=o.id, payment_kind=PaymentKind.PURCHASE, amount_minor=o.total_amount_minor,
                              currency=o.currency, payment_reference=f"SIM-PAY-{uuid.uuid4().hex[:12].upper()}",
                              payment_status=PaymentStatus.INITIATED)
        db.add(pay)
        db.flush()
        corr = correlation_id(request)
        if body.simulated_outcome == "FAILED":
            pay.payment_status = PaymentStatus.FAILED
            pay.failure_reason = body.failure_reason or "Simulated payment declined."
            pay.completed_at = utcnow()
            audit(db, entity_type="payment", entity_id=pay.id, operation_type="PAYMENT_SIMULATED", actor_id=user.id,
                  new_state=PaymentStatus.FAILED, outcome="FAILED", source=EventSource.PAYMENT_SIMULATOR,
                  correlation_id=corr)
            o.failure_reason = pay.failure_reason
            _set_order(db, o, OrderStatus.PAYMENT_FAILED, user.id, outcome="FAILED")  # Rule 6.2: no transfer
            db.commit()
            raise ApiError(409, "PAYMENT_FAILED", pay.failure_reason, {"order": order_view(db, o)})
        # Simulated payment from the buyer's demo cash. Held until the DRUNIX transfer resolves:
        # commit credits the seller, failure refunds the buyer.
        wallet.move(db, user.id, WalletEntryKind.PURCHASE_PAYMENT, o.total_amount_minor, f"order:{o.id}:payment")
        pay.payment_status = PaymentStatus.SUCCESS
        pay.completed_at = utcnow()
        audit(db, entity_type="payment", entity_id=pay.id, operation_type="PAYMENT_SIMULATED", actor_id=user.id,
              new_state=PaymentStatus.SUCCESS, source=EventSource.PAYMENT_SIMULATOR, correlation_id=corr,
              detail={"amount": from_minor(pay.amount_minor), "reference": pay.payment_reference})
        _set_order(db, o, OrderStatus.PAYMENT_SUCCEEDED, user.id, source=EventSource.PAYMENT_SIMULATOR)
        _set_order(db, o, OrderStatus.TRANSFER_PENDING, user.id)
        db.commit()
        ledger_op = submit_transfer(db, ledger, settings, issuance=iss, sender=seller, recipient=user,
                                    quantity=o.quantity, cost_minor=o.total_amount_minor, order_id=o.id, corr=corr)
        o.transfer_operation_id = ledger_op.id
        db.commit()
        return executor.outcome(ledger_op, order_view(db, o))

    return run_idempotent(request, db, "POST /payments/simulate", {"user": user.id, **body.model_dump()}, op)


@router.get("/payments/{payment_id}")
def get_payment(payment_id: str, request: Request, db: Session = Depends(get_db), user: m.User = Depends(current_user)):
    p = get_or_404(db, m.PaymentRecord, payment_id, "Payment")
    _order_for(db, p.order_id, user)
    return envelope(request, payment_view(p))
