"""Ledger operation lifecycle (API_CONTRACTS section 8, ADR-011, Rules 6.3 and 6.4).

1. The LedgerOperation row is written and committed BEFORE submission.
2. The adapter result is mapped to an application state. Nothing becomes
   COMMITTED without a DRUNIX transaction id and confirmed commit status.
3. An ambiguous outcome is never retried blindly: the operation moves to
   RECONCILIATION_REQUIRED and a ReconciliationCase is opened.
4. Domain effects (projections, workflow states) run through handlers that each
   module registers, the same way for the first attempt and for reconciliation.
"""
import hashlib
import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import ApiError
from app.db import models as m
from app.db.base import new_id
from app.db.enums import OperationStatus, OperationType, ReconciliationStatus
from app.db.types import utcnow
from app.ledger.port import LedgerPort, LedgerResult, LedgerUnavailable, SubmissionState

log = logging.getLogger("tokansh.ledger")

Handler = Callable[[Session, m.LedgerOperation], None]

# Chaincode rejections that are business rule violations, reported as 409 with the same code.
BUSINESS_CODES = {"INSUFFICIENT_AVAILABLE_ANSH", "PLEDGED_UNITS_RESTRICTED", "ISSUANCE_LIMIT_EXCEEDED",
                  "PROPERTY_NOT_APPROVED", "INVALID_OPERATION_STATE", "INVALID_REQUEST"}
PENDING = {OperationStatus.CREATED, OperationStatus.VALIDATING, OperationStatus.SUBMITTED,
           OperationStatus.UNKNOWN, OperationStatus.RECONCILIATION_REQUIRED}


@dataclass
class Handlers:
    committed: Handler
    failed: Handler
    unresolved: Handler | None = None


_HANDLERS: dict[OperationType, Handlers] = {}


def register(op_type: OperationType, *, committed: Handler, failed: Handler, unresolved: Handler | None = None):
    _HANDLERS[op_type] = Handlers(committed, failed, unresolved)


class LedgerOutcomeError(ApiError):
    """A ledger operation definitively failed. The response is stored for idempotent replay."""
    store = True


def payload_of(op: m.LedgerOperation) -> dict:
    return json.loads(op.request_payload) if op.request_payload else {}


def submit_operation(db: Session, ledger: LedgerPort, settings: Settings, *, op_type: OperationType,
                     entity_type: str, entity_id: str, function: str, args: list[str],
                     context: dict | None = None, correlation_id: str | None = None,
                     order_id: str | None = None) -> m.LedgerOperation:
    op_id = new_id()
    payload = {"function": function, "args": args, **(context or {})}
    op = m.LedgerOperation(
        id=op_id, operation_type=op_type, entity_type=entity_type, entity_id=entity_id, idempotency_key=op_id,
        correlation_id=correlation_id, channel=settings.drunix_channel, chaincode=settings.drunix_chaincode,
        function_name=function, request_payload=json.dumps(payload, sort_keys=True),
        request_hash=hashlib.sha256(json.dumps(args).encode()).hexdigest(), status=OperationStatus.CREATED)
    db.add(op)
    db.commit()  # write-before-submit: the intent survives a crash during submission

    op.status = OperationStatus.VALIDATING
    op.attempt_count += 1
    op.submitted_at = utcnow()
    try:
        result = ledger.submit(function=function, args=args, operation_id=op_id, correlation_id=correlation_id)
    except LedgerUnavailable as exc:
        # Connection was never established: the transaction definitively did not reach DRUNIX.
        op.status = OperationStatus.FAILED
        op.error_code = "LEDGER_UNAVAILABLE"
        op.error_message = exc.message[:500]
        log.warning("ledger unavailable for %s %s: %s", op_type, op_id, exc.message)
    else:
        _apply(db, ledger, settings, op, result, poll=True, order_id=order_id)
    op.observed_at = utcnow()
    _settle(db, op)
    db.commit()
    return op


def _apply(db: Session, ledger: LedgerPort, settings: Settings, op: m.LedgerOperation, result: LedgerResult,
           *, poll: bool, order_id: str | None = None) -> None:
    if result.transaction_id and not op.transaction_id:
        op.transaction_id = result.transaction_id
    op.validation_code = result.validation_code or op.validation_code
    if result.block_number is not None:
        op.block_number = result.block_number

    state = result.state
    if state == SubmissionState.COMMIT_CONFIRMED and not op.transaction_id:
        state = SubmissionState.UNKNOWN  # never record a commit without DRUNIX evidence
        result.error_message = "Adapter reported a commit without a transaction id."

    if state == SubmissionState.COMMIT_CONFIRMED:
        op.status = OperationStatus.COMMITTED
        op.confirmed_at = utcnow()
        op.error_code = op.error_message = None
    elif state == SubmissionState.COMMIT_FAILED:
        op.status = OperationStatus.FAILED
        op.error_code = result.error_code or "LEDGER_COMMIT_FAILED"
        op.error_message = (result.error_message or "Transaction was invalidated at commit.")[:500]
    elif state == SubmissionState.NOT_SUBMITTED:
        op.status = OperationStatus.FAILED
        op.error_code = result.error_code or "LEDGER_SUBMISSION_FAILED"
        op.error_message = (result.error_message or "Transaction was not accepted by the ledger.")[:500]
    else:  # SUBMITTED or UNKNOWN
        op.status = OperationStatus.SUBMITTED if op.transaction_id else OperationStatus.UNKNOWN
        if poll and op.transaction_id:
            for _ in range(max(settings.commit_poll_attempts, 0)):
                if settings.commit_poll_interval_seconds:
                    time.sleep(settings.commit_poll_interval_seconds)
                try:
                    status = ledger.commit_status(op.transaction_id)
                except LedgerUnavailable:
                    break
                if status.state in (SubmissionState.COMMIT_CONFIRMED, SubmissionState.COMMIT_FAILED):
                    _apply(db, ledger, settings, op, status, poll=False)
                    return
        op.status = OperationStatus.RECONCILIATION_REQUIRED
        op.error_code = "LEDGER_OUTCOME_UNKNOWN"
        op.error_message = (result.error_message or "Commit outcome could not be established.")[:500]
        db.add(m.ReconciliationCase(ledger_operation_id=op.id, order_id=order_id,
                                    reason=f"{op.operation_type} outcome unknown: {op.error_message}"[:300]))


def _settle(db: Session, op: m.LedgerOperation) -> None:
    handlers = _HANDLERS.get(op.operation_type)
    if handlers is None:
        return
    if op.status == OperationStatus.COMMITTED:
        handlers.committed(db, op)
    elif op.status == OperationStatus.FAILED:
        handlers.failed(db, op)
    elif handlers.unresolved is not None:
        handlers.unresolved(db, op)


def reconcile(db: Session, ledger: LedgerPort, settings: Settings, op: m.LedgerOperation,
              actor_id: str | None) -> m.LedgerOperation:
    """Query the commit status of an unresolved operation by its transaction id (Rule 6.4)."""
    if op.status not in PENDING:
        raise ApiError(409, "INVALID_OPERATION_STATE", "Operation already has a definitive outcome.",
                       {"status": op.status.value})
    if not op.transaction_id:
        raise ApiError(409, "RECONCILIATION_REQUIRED",
                       "No DRUNIX transaction id was returned, so the outcome cannot be queried by id. "
                       "Investigate the ledger state manually; do not resubmit blindly.", {"operation_id": op.id})
    try:
        result = ledger.commit_status(op.transaction_id)
    except LedgerUnavailable as exc:
        raise ApiError(503, "LEDGER_UNAVAILABLE", exc.message)
    previous = op.status
    if result.state in (SubmissionState.COMMIT_CONFIRMED, SubmissionState.COMMIT_FAILED):
        _apply(db, ledger, settings, op, result, poll=False)
        op.observed_at = utcnow()
        _settle(db, op)
        for case in db.scalars(sa.select(m.ReconciliationCase).filter_by(
                ledger_operation_id=op.id, status=ReconciliationStatus.OPEN)):
            case.status = ReconciliationStatus.RESOLVED
            case.resolved_at = utcnow()
            case.resolved_by = actor_id
            case.resolution = f"Commit status queried from DRUNIX: {op.status.value}."
    from app.core.audit import audit
    audit(db, entity_type="ledger_operation", entity_id=op.id, operation_type="LEDGER_RECONCILIATION",
          actor_id=actor_id, previous_state=previous, new_state=op.status, operation_id=op.id,
          ledger_transaction_id=op.transaction_id, outcome="RESOLVED" if op.status not in PENDING else "PENDING")
    db.commit()
    return op


def outcome(op: m.LedgerOperation, data: dict, created: bool = False) -> tuple[int, dict]:
    """HTTP result for a ledger-backed request: success only after a confirmed commit."""
    if op.status == OperationStatus.COMMITTED:
        return (201 if created else 200), data
    if op.status in PENDING:
        return 202, data
    code = op.error_code or "LEDGER_SUBMISSION_FAILED"
    if code in ("LEDGER_UNAVAILABLE", "LEDGER_NOT_CONFIGURED"):
        status, code = 503, "LEDGER_UNAVAILABLE"
    elif code in BUSINESS_CODES:
        status = 409
    elif code == "LEDGER_COMMIT_FAILED":
        status = 502
    else:
        status, code = 502, "LEDGER_SUBMISSION_FAILED"
    raise LedgerOutcomeError(status, code, op.error_message or "Ledger operation failed.", {"result": data})


def operation_view(op: m.LedgerOperation | None) -> dict | None:
    from app.core.serial import iso
    if op is None:
        return None
    return {"operation_id": op.id, "operation_type": op.operation_type.value, "status": op.status.value,
            "ledger_transaction_id": op.transaction_id, "block_number": op.block_number,
            "validation_code": op.validation_code, "error_code": op.error_code, "error_message": op.error_message,
            "function": op.function_name, "channel": op.channel, "chaincode": op.chaincode,
            "entity_type": op.entity_type, "entity_id": op.entity_id, "attempt_count": op.attempt_count,
            "created_at": iso(op.created_at), "submitted_at": iso(op.submitted_at),
            "confirmed_at": iso(op.confirmed_at), "source": "DRUNIX_LEDGER"}
