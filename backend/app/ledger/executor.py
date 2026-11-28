"""Ledger operation lifecycle (API_CONTRACTS section 8, ADR-011, Rules 6.3 and 6.4).

Follows the private gateway's once-only pattern (gateway/TRANSACTIONS.md):

1. CREATED      the operation and its exact command are committed BEFORE any gateway call.
2. VALIDATING   prepared: endorsed, signed artifact and DRUNIX transaction id saved.
                No ledger effect yet; never submitted.
3. SUBMITTED    claimed by a compare-and-set in the database, committed BEFORE submission.
                From here the transaction may be on the ledger.
4. COMMITTED / FAILED from the commit status, or RECONCILIATION_REQUIRED when unknown.

An ambiguous outcome is never resubmitted; it is reconciled by commit status
using the saved artifact. Domain effects run through handlers that each module
registers, identically for the first attempt and for reconciliation.
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
from app.ledger.port import (FUNCTIONS, CommitStatus, LedgerOutcomeUnknown, LedgerPort, LedgerRejected,
                             LedgerUnavailable)

log = logging.getLogger("tokansh.ledger")

Handler = Callable[[Session, m.LedgerOperation], None]
CommandBuilder = Callable[[str], dict]

# Chaincode rejections that are business rule violations, reported as 409 with the same code.
BUSINESS_CODES = {"INSUFFICIENT_AVAILABLE_ANSH", "PLEDGED_UNITS_RESTRICTED", "ISSUANCE_LIMIT_EXCEEDED",
                  "PROPERTY_NOT_APPROVED", "INVALID_OPERATION_STATE", "INVALID_REQUEST", "IDEMPOTENCY_CONFLICT",
                  "INITIAL_ISSUANCE_MUST_MATCH_APPROVED_SUPPLY", "ISSUANCE_ALREADY_COMPLETED"}
PENDING = {OperationStatus.CREATED, OperationStatus.VALIDATING, OperationStatus.SUBMITTED,
           OperationStatus.UNKNOWN, OperationStatus.RECONCILIATION_REQUIRED}
KIND = {OperationType.APPROVED_PROPERTY_REGISTRATION: "registration", OperationType.ANSH_ISSUANCE: "issuance",
        OperationType.ANSH_TRANSFER: "transfer", OperationType.ANSH_PLEDGE: "pledge",
        OperationType.ANSH_RELEASE: "release"}


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


def artifact_of(op: m.LedgerOperation) -> dict | None:
    return json.loads(op.artifact_json) if op.artifact_json else None


def _fail(op: m.LedgerOperation, code: str, message: str) -> None:
    op.status = OperationStatus.FAILED
    op.error_code = code
    op.error_message = message[:500]


def _unresolved(db: Session, op: m.LedgerOperation, message: str, order_id: str | None) -> None:
    op.status = OperationStatus.RECONCILIATION_REQUIRED
    op.error_code = "LEDGER_OUTCOME_UNKNOWN"
    op.error_message = message[:500]
    db.add(m.ReconciliationCase(ledger_operation_id=op.id, order_id=order_id,
                                reason=f"{op.operation_type.value} outcome unknown: {message}"[:300]))


def _apply_status(op: m.LedgerOperation, status: CommitStatus) -> None:
    op.transaction_id = op.transaction_id or status.transaction_id
    op.block_number = status.block_number
    op.validation_code = str(status.code)
    if status.successful:
        op.status = OperationStatus.COMMITTED
        op.confirmed_at = utcnow()
        op.error_code = op.error_message = None
    else:
        _fail(op, "LEDGER_COMMIT_FAILED", f"Transaction committed as invalid (validation code {status.code}).")


def submit_operation(db: Session, ledger: LedgerPort, settings: Settings, *, op_type: OperationType,
                     entity_type: str, entity_id: str, command: CommandBuilder,
                     context: dict | None = None, correlation_id: str | None = None,
                     order_id: str | None = None) -> m.LedgerOperation:
    """Run one ledger write. ``command(operation_id)`` builds the exact chaincode command."""
    kind = KIND[op_type]
    op_id = new_id()
    cmd = command(op_id)
    payload = {"kind": kind, "function": FUNCTIONS[kind], "command": cmd, **(context or {})}
    op = m.LedgerOperation(
        id=op_id, operation_type=op_type, entity_type=entity_type, entity_id=entity_id, idempotency_key=op_id,
        correlation_id=correlation_id, channel=settings.drunix_channel, chaincode=settings.drunix_chaincode,
        function_name=FUNCTIONS[kind], request_payload=json.dumps(payload, sort_keys=True),
        request_hash=hashlib.sha256(json.dumps(cmd, separators=(",", ":")).encode()).hexdigest(),
        status=OperationStatus.CREATED)
    db.add(op)
    db.commit()  # 1. intent survives a crash before any gateway call

    op.attempt_count += 1
    try:  # 2. prepare (endorse): no ledger effect, so every failure here is definitive
        artifact = ledger.prepare(kind, cmd)
    except LedgerRejected as exc:
        _fail(op, exc.code, exc.message)
    except LedgerUnavailable as exc:
        _fail(op, "LEDGER_UNAVAILABLE" if exc.code == "LEDGER_NOT_CONFIGURED" else exc.code, exc.message)
        log.warning("ledger prepare unavailable for %s %s: %s", op_type.value, op_id, exc.message)
    else:
        op.artifact_json = json.dumps(artifact, separators=(",", ":"))
        op.transaction_id = artifact["transaction_id"]
        op.status = OperationStatus.VALIDATING
        db.commit()
        # 3. claim the single submission before sending anything
        claimed = db.execute(sa.update(m.LedgerOperation).where(
            m.LedgerOperation.id == op_id, m.LedgerOperation.status == OperationStatus.VALIDATING
        ).values(status=OperationStatus.SUBMITTED, submitted_at=utcnow())).rowcount
        db.commit()
        db.refresh(op)
        if claimed != 1:
            raise ApiError(409, "RECONCILIATION_REQUIRED", "Submission was already claimed; reconcile, do not retry.")
        _submit_and_confirm(db, ledger, settings, op, kind, artifact, order_id)
    op.observed_at = utcnow()
    _settle(db, op)
    db.commit()
    return op


def _submit_and_confirm(db: Session, ledger: LedgerPort, settings: Settings, op: m.LedgerOperation, kind: str,
                        artifact: dict, order_id: str | None) -> None:
    try:
        ledger.submit(kind, artifact)
    except LedgerUnavailable as exc:  # connection never opened: the artifact was not delivered
        _fail(op, "LEDGER_UNAVAILABLE", exc.message)
        return
    except LedgerOutcomeUnknown as exc:
        _unresolved(db, op, exc.message, order_id)
        return
    last = "Commit outcome could not be established."
    for attempt in range(max(settings.commit_poll_attempts, 1)):
        if attempt and settings.commit_poll_interval_seconds:
            time.sleep(settings.commit_poll_interval_seconds)
        try:
            _apply_status(op, ledger.commit_status(kind, artifact))
            return
        except (LedgerOutcomeUnknown, LedgerUnavailable) as exc:
            last = exc.message
    _unresolved(db, op, last, order_id)


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
    """Establish an unresolved outcome from DRUNIX commit status (Rule 6.4). Never resubmits."""
    if op.status not in PENDING:
        raise ApiError(409, "INVALID_OPERATION_STATE", "Operation already has a definitive outcome.",
                       {"status": op.status.value})
    previous = op.status
    artifact = artifact_of(op)
    if op.status in (OperationStatus.CREATED, OperationStatus.VALIDATING):
        # The submission was never claimed, so nothing was sent to DRUNIX.
        _fail(op, "LEDGER_NOT_SUBMITTED", "Prepared but never submitted (process stopped before submission).")
    elif artifact is None:
        raise ApiError(409, "RECONCILIATION_REQUIRED",
                       "No prepared transaction is stored, so the outcome cannot be queried. Investigate manually.",
                       {"operation_id": op.id})
    else:
        try:
            _apply_status(op, ledger.commit_status(KIND[op.operation_type], artifact))
        except LedgerUnavailable as exc:
            raise ApiError(503, "LEDGER_UNAVAILABLE", exc.message)
        except LedgerOutcomeUnknown as exc:
            raise ApiError(409, "RECONCILIATION_REQUIRED", f"Still unknown: {exc.message}", {"operation_id": op.id})
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
          ledger_transaction_id=op.transaction_id if op.status == OperationStatus.COMMITTED else None,
          outcome="RESOLVED")
    db.commit()
    return op


def outcome(op: m.LedgerOperation, data: dict, created: bool = False) -> tuple[int, dict]:
    """HTTP result for a ledger-backed request: success only after a confirmed commit."""
    if op.status == OperationStatus.COMMITTED:
        return (201 if created else 200), data
    if op.status in PENDING:
        return 202, data
    code = op.error_code or "LEDGER_SUBMISSION_FAILED"
    if code in ("LEDGER_UNAVAILABLE", "LEDGER_NOT_CONFIGURED", "LEDGER_FUNCTION_UNAVAILABLE", "LEDGER_TIMEOUT"):
        status = 503
        code = "LEDGER_UNAVAILABLE" if code == "LEDGER_NOT_CONFIGURED" else code
    elif code in BUSINESS_CODES:
        status = 409
    elif code == "LEDGER_COMMIT_FAILED":
        status = 502
    else:
        status = 502
    raise LedgerOutcomeError(status, code, op.error_message or "Ledger operation failed.", {"result": data})


def operation_view(op: m.LedgerOperation | None) -> dict | None:
    from app.core.serial import iso
    if op is None:
        return None
    # A transaction id exists from preparation; show it only once the transaction may be on the ledger.
    visible_tx = op.transaction_id if op.status not in (OperationStatus.CREATED, OperationStatus.VALIDATING) \
        and op.error_code not in ("LEDGER_UNAVAILABLE", "LEDGER_NOT_SUBMITTED") else None
    return {"operation_id": op.id, "operation_type": op.operation_type.value, "status": op.status.value,
            "ledger_transaction_id": visible_tx, "block_number": op.block_number,
            "validation_code": op.validation_code, "error_code": op.error_code, "error_message": op.error_message,
            "function": op.function_name, "channel": op.channel, "chaincode": op.chaincode,
            "entity_type": op.entity_type, "entity_id": op.entity_id, "attempt_count": op.attempt_count,
            "created_at": iso(op.created_at), "submitted_at": iso(op.submitted_at),
            "confirmed_at": iso(op.confirmed_at), "source": "DRUNIX_LEDGER"}
