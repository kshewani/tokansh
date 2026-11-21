"""The ledger port: the only way the application reaches DRUNIX (ADR-004, ADR-007).

It mirrors the private TokANSH Go gateway (gateway/TRANSACTIONS.md): every ledger
write is three typed steps.

1. ``prepare(kind, command)``: endorsement only. No ledger effect. Returns a signed
   artifact holding the genuine DRUNIX transaction id.
2. ``submit(kind, artifact)``: sends the endorsed transaction for ordering, once.
3. ``commit_status(kind, artifact)``: the authoritative commit outcome.

The production implementation is ``GatewayLedgerClient``. Test doubles live under
``backend/tests`` only and are never importable as a runtime mode.
"""
from dataclasses import dataclass
from typing import Any, Protocol

# Ledger write kinds and the chaincode function each one invokes.
FUNCTIONS = {
    "registration": "RegisterApprovedProperty",
    "issuance": "IssueANSH",
    "transfer": "TransferANSH",
    "pledge": "PledgeANSH",       # proposed; not yet in the chaincode
    "release": "ReleasePledge",   # proposed; not yet in the chaincode
}


@dataclass
class CommitStatus:
    transaction_id: str
    code: int                     # Fabric validation code; 0 = VALID
    block_number: int
    successful: bool


class LedgerUnavailable(Exception):
    """Nothing reached the ledger: not configured, unreachable before sending, or endorsement unavailable."""

    def __init__(self, message: str, code: str = "LEDGER_UNAVAILABLE"):
        super().__init__(message)
        self.code = code
        self.message = message


class LedgerRejected(Exception):
    """The chaincode refused the command during endorsement (a business rule). No ledger effect."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class LedgerOutcomeUnknown(Exception):
    """The request may have reached the ledger; reconcile by transaction id, never resubmit."""

    def __init__(self, message: str = "Ledger outcome could not be established."):
        super().__init__(message)
        self.message = message


class LedgerPort(Protocol):
    def prepare(self, kind: str, command: dict[str, Any]) -> dict[str, Any]: ...

    def submit(self, kind: str, artifact: dict[str, Any]) -> None: ...

    def commit_status(self, kind: str, artifact: dict[str, Any]) -> CommitStatus: ...

    def get_position(self, property_id: str, holder_id: str) -> dict[str, int]: ...

    def health(self) -> dict[str, Any]: ...
