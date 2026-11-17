"""TEST-ONLY in-memory stand-in for the DRUNIX gateway adapter.

!!! This is NOT DRUNIX and NOT a runtime ledger mode. !!!
It lives under backend/tests, is never imported by the application, and every
transaction id it produces starts with "TEST-ONLY-" so it can never be mistaken
for real commit evidence (AGENTS.md section 9, DRUNIX_INTEGRATION 8.1).

It mimics the proposed TokANSH chaincode invariants (DRUNIX_INTEGRATION 6.3) so
application behaviour can be tested in isolation.
"""
import itertools
from dataclasses import dataclass, field

from app.ledger.port import LedgerResult, LedgerUnavailable, SubmissionState


@dataclass
class _Asset:
    property_ref: str
    supply: int
    issued: int = 0
    owned: dict = field(default_factory=dict)
    pledged: dict = field(default_factory=dict)
    pledges: dict = field(default_factory=dict)  # pledge_id -> (owner, qty)


class FakeLedger:
    def __init__(self):
        self.properties: dict[str, dict] = {}
        self.assets: dict[str, _Asset] = {}
        self.calls: list[tuple[str, list[str]]] = []
        self.transactions: dict[str, LedgerResult] = {}
        self._tx = itertools.count(1)
        self._block = itertools.count(10)
        self.available = True
        self.next_outcome: dict[str, str] = {}  # function -> UNKNOWN | COMMIT_FAILED | UNAVAILABLE | SUBMITTED_THEN_COMMIT

    # ---- helpers for tests
    def balance(self, asset: str, owner: str) -> tuple[int, int]:
        a = self.assets[asset]
        return a.owned.get(owner, 0), a.pledged.get(owner, 0)

    def _tx_id(self) -> str:
        return f"TEST-ONLY-TX-{next(self._tx):05d}"

    def _reject(self, code: str, msg: str) -> LedgerResult:
        return LedgerResult(SubmissionState.NOT_SUBMITTED, error_code=code, error_message=msg)

    # ---- LedgerPort
    def health(self):
        return {"status": "CONNECTED" if self.available else "UNAVAILABLE", "detail": "TEST-ONLY fake ledger"}

    def submit(self, *, function, args, operation_id, correlation_id):
        if not self.available:
            raise LedgerUnavailable("fake ledger offline")
        self.calls.append((function, list(args)))
        mode = self.next_outcome.pop(function, None)
        if mode == "UNAVAILABLE":
            raise LedgerUnavailable("fake ledger offline (one-shot)")
        err = self._validate(function, args)
        if err:
            return err
        tx = self._tx_id()
        if mode == "COMMIT_FAILED":
            res = LedgerResult(SubmissionState.COMMIT_FAILED, transaction_id=tx, validation_code="MVCC_READ_CONFLICT",
                               block_number=next(self._block))
            self.transactions[tx] = res
            return res
        if mode in ("UNKNOWN", "SUBMITTED_THEN_COMMIT"):
            # The transaction did commit on the "ledger", but the client never learned it.
            self._apply(function, args)
            self.transactions[tx] = LedgerResult(SubmissionState.COMMIT_CONFIRMED, transaction_id=tx,
                                                 validation_code="VALID", block_number=next(self._block))
            self.hide_status = mode == "UNKNOWN"
            return LedgerResult(SubmissionState.UNKNOWN, transaction_id=tx, error_message="commit wait timed out")
        self._apply(function, args)
        res = LedgerResult(SubmissionState.COMMIT_CONFIRMED, transaction_id=tx, validation_code="VALID",
                           block_number=next(self._block))
        self.transactions[tx] = res
        return res

    hide_status = False

    def commit_status(self, transaction_id):
        if not self.available:
            raise LedgerUnavailable("fake ledger offline")
        if self.hide_status:
            return LedgerResult(SubmissionState.UNKNOWN, transaction_id=transaction_id)
        res = self.transactions.get(transaction_id)
        return res or LedgerResult(SubmissionState.UNKNOWN, transaction_id=transaction_id)

    def evaluate(self, *, function, args):
        if not self.available:
            raise LedgerUnavailable("fake ledger offline")
        if function == "GetPosition":
            asset, owner = args
            if asset not in self.assets:
                return {"owned": 0, "pledged": 0}
            owned, pledged = self.balance(asset, owner)
            return {"owned": owned, "pledged": pledged}
        raise NotImplementedError(function)

    # ---- chaincode-like rules
    def _validate(self, fn, a):
        if fn == "RegisterApprovedProperty":
            if a[0] in self.properties:
                return self._reject("INVALID_OPERATION_STATE", "property already registered")
        elif fn == "IssueANSH":
            asset, ref, qty = a[0], a[1], int(a[2])
            if ref not in self.properties:
                return self._reject("PROPERTY_NOT_APPROVED", "property not registered")
            if qty > self.properties[ref]["supply"] or asset in self.assets:
                return self._reject("ISSUANCE_LIMIT_EXCEEDED", "exceeds registered supply")
        elif fn == "TransferANSH":
            asset, frm, _to, qty = a[0], a[1], a[2], int(a[3])
            owned, pledged = self.balance(asset, frm)
            if qty > owned - pledged:
                code = "PLEDGED_UNITS_RESTRICTED" if qty <= owned else "INSUFFICIENT_AVAILABLE_ANSH"
                return self._reject(code, "insufficient available balance")
        elif fn == "PledgeANSH":
            asset, owner, qty, pid = a[0], a[1], int(a[2]), a[3]
            owned, pledged = self.balance(asset, owner)
            if qty > owned - pledged or pid in self.assets[asset].pledges:
                return self._reject("INSUFFICIENT_AVAILABLE_ANSH", "cannot pledge")
        elif fn == "ReleasePledge":
            asset, _owner, pid = a
            if pid not in self.assets[asset].pledges:
                return self._reject("INVALID_OPERATION_STATE", "no such pledge")
        return None

    def _apply(self, fn, a):
        if fn == "RegisterApprovedProperty":
            self.properties[a[0]] = {"issuer": a[1], "supply": int(a[2])}
        elif fn == "IssueANSH":
            asset = _Asset(property_ref=a[1], supply=self.properties[a[1]]["supply"], issued=int(a[2]))
            asset.owned[a[3]] = int(a[2])
            self.assets[a[0]] = asset
        elif fn == "TransferANSH":
            asset = self.assets[a[0]]
            qty = int(a[3])
            asset.owned[a[1]] -= qty
            asset.owned[a[2]] = asset.owned.get(a[2], 0) + qty
        elif fn == "PledgeANSH":
            asset = self.assets[a[0]]
            asset.pledged[a[1]] = asset.pledged.get(a[1], 0) + int(a[2])
            asset.pledges[a[3]] = (a[1], int(a[2]))
        elif fn == "ReleasePledge":
            asset = self.assets[a[0]]
            owner, qty = asset.pledges.pop(a[2])
            asset.pledged[owner] -= qty
