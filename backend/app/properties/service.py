import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import ApplicationError
from app.properties.models import ApplicationOperation, Property, PropertyEvent
from app.properties.repository import PropertyRepository
from app.properties.schemas import NewProperty, PropertyRead
from app.registration import LedgerOperation


def property_read(record: Property, registration: LedgerOperation | None = None) -> dict:
    approved_supply = 0
    ledger_status = "NOT_REGISTERED"
    transaction_id = None
    if registration is not None and registration.state == "COMMITTED_VALID":
        try:
            command = json.loads(registration.command_json)
            if (command.get("property_id") == record.id and command.get("issuer_id") == record.issuer_id
                    and command.get("approved_supply") == record.proposed_supply
                    and command.get("issue_price_minor") == str(record.issue_price_minor)
                    and command.get("currency") == record.currency):
                approved_supply = record.proposed_supply
                ledger_status = "REGISTERED"
                transaction_id = registration.transaction_id
        except (TypeError, ValueError, json.JSONDecodeError):
            pass
    return PropertyRead(
        id=record.id, name=record.name, location=record.location, category=record.category,
        valuation=format(Decimal(record.valuation_minor) / 100, ".2f"), proposed_supply=record.proposed_supply,
        unit_price=format(Decimal(record.issue_price_minor) / 100, ".2f"), currency=record.currency,
        issuer_id=record.issuer_id, status=record.status, approved_supply=approved_supply,
        ledger_registration_status=ledger_status, ledger_transaction_id=transaction_id,
        created_at=record.created_at,
    ).model_dump()


class PropertyService:
    def __init__(self, session: Session, default_issue_price_minor: int = 100000):
        self.session = session
        self.repository = PropertyRepository(session)
        self.default_issue_price_minor = default_issue_price_minor

    def get(self, property_id: str) -> dict:
        record = self.repository.get(property_id)
        if record is None:
            raise ApplicationError(404, "RESOURCE_NOT_FOUND", "Property not found.")
        return property_read(record, self.session.scalar(select(LedgerOperation).where(LedgerOperation.property_id == record.id)))

    def page(self, page: int, page_size: int) -> dict:
        records, total = self.repository.page(page, page_size)
        registrations = {row.property_id: row for row in self.session.scalars(select(LedgerOperation).where(
            LedgerOperation.property_id.in_([record.id for record in records]))).all()}
        return {"items": [property_read(record, registrations.get(record.id)) for record in records], "page": page, "page_size": page_size,
                "total_items": total, "total_pages": (total + page_size - 1) // page_size}

    @staticmethod
    def replay(operation: ApplicationOperation, request_hash: str) -> dict:
        if operation.request_hash != request_hash:
            raise ApplicationError(409, "IDEMPOTENCY_CONFLICT", "This key was already used with different request parameters.")
        if operation.status != "COMPLETED" or operation.response_json is None:
            raise ApplicationError(409, "RECONCILIATION_REQUIRED", "The original operation requires reconciliation.",
                                   {"operation_id": operation.id})
        return json.loads(operation.response_json)

    def create(self, command: NewProperty, actor_id: str, key: str, correlation_id: str) -> dict:
        serialized = json.dumps(command.model_dump(), sort_keys=True, separators=(",", ":"))
        request_hash = hashlib.sha256(("POST /api/v1/properties\n" + serialized).encode()).hexdigest()
        try:
            with self.session.begin():
                existing = self.repository.operation(actor_id, key)
                if existing:
                    return self.replay(existing, request_hash)
                now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                operation = ApplicationOperation(id=str(uuid4()), actor_id=actor_id, idempotency_key=key,
                    request_hash=request_hash, status="PROCESSING", correlation_id=correlation_id, created_at=now)
                self.session.add(operation)
                # Database uniqueness serializes concurrent uses of the same actor/key.
                self.session.flush()
                price_minor = (int(Decimal(command.issue_price) * 100) if command.issue_price is not None
                               else self.default_issue_price_minor)
                record = Property(id=str(uuid4()), name=command.name, location=command.location,
                    category=command.category, valuation_minor=int(Decimal(command.valuation) * 100),
                    proposed_supply=command.proposed_supply, issue_price_minor=price_minor,
                    currency=command.currency, issuer_id=actor_id, status="DRAFT", created_at=now)
                self.session.add(record)
                self.session.flush()
                self.session.add(PropertyEvent(id=str(uuid4()), property_id=record.id, operation_id=operation.id,
                    actor_id=actor_id, event_type="PROPERTY_CREATED", event_source="APPLICATION", created_at=now))
                result = property_read(record)
                operation.response_json = json.dumps(result, sort_keys=True)
                operation.response_status = 201
                operation.status = "COMPLETED"  # Off-chain application operation, never DRUNIX COMMITTED.
            return result
        except IntegrityError:
            self.session.rollback()
            existing = self.repository.operation(actor_id, key)
            if existing:
                return self.replay(existing, request_hash)
            raise
