"""TEST-ONLY in-memory stand-in for the private TokANSH gateway.

!!! This is NOT DRUNIX and NOT a runtime ledger mode. !!!
It lives under backend/tests, is never imported by the application, and every
transaction id it produces starts with "TEST-ONLY-" so it can never be mistaken
for real commit evidence (AGENTS.md section 9).

It mirrors the gateway's prepare -> submit -> commit-status contract
(gateway/TRANSACTIONS.md) and the chaincode rules in chaincode/tokansh: supply
ceiling, balances, holder transfers. It also implements the proposed PledgeANSH /
ReleasePledge so the application's pledge logic can be tested before the real
chaincode supports them.
"""
import hashlib
import itertools
import json

from app.ledger.port import CommitStatus, LedgerOutcomeUnknown, LedgerRejected, LedgerUnavailable


class FakeLedger:
    def __init__(self):
        self.properties: dict[str, dict] = {}     # property_id -> {issuer_id, supply, issued}
        self.owned: dict[tuple[str, str], int] = {}
        self.pledged: dict[tuple[str, str], int] = {}
        self.pledges: dict[str, tuple[str, str, int]] = {}  # pledge_id -> (property, holder, qty)
        self.calls: list[tuple[str, str]] = []   # (step, kind)
        self.submitted: list[str] = []            # kinds actually submitted
        self.status: dict[str, CommitStatus] = {}
        self.pending: dict[str, tuple[str, dict]] = {}
        self._tx = itertools.count(1)
        self._block = itertools.count(10)
        self.available = True
        self.hide_status = False
        # kind -> UNAVAILABLE | REJECT:<CODE> | SUBMIT_UNKNOWN | COMMIT_FAILED | STATUS_UNKNOWN
        self.next_outcome: dict[str, str] = {}

    # ---- helpers for tests
    def balance(self, property_id: str, holder_id: str) -> tuple[int, int]:
        return self.owned.get((property_id, holder_id), 0), self.pledged.get((property_id, holder_id), 0)

    def _guard(self):
        if not self.available:
            raise LedgerUnavailable("TEST-ONLY fake ledger offline")

    # ---- LedgerPort
    def health(self):
        return {"status": "CONNECTED" if self.available else "UNAVAILABLE", "detail": "TEST-ONLY fake ledger"}

    def get_position(self, property_id, holder_id):
        self._guard()
        owned, pledged = self.balance(property_id, holder_id)
        return {"owned": owned, "pledged": pledged}

    def prepare(self, kind, command):
        self._guard()
        self.calls.append(("prepare", kind))
        mode = self.next_outcome.get(kind, "")
        if mode == "UNAVAILABLE":
            self.next_outcome.pop(kind)
            raise LedgerUnavailable("TEST-ONLY fake ledger offline (one-shot)")
        if mode.startswith("REJECT:"):
            self.next_outcome.pop(kind)
            raise LedgerRejected(mode.split(":", 1)[1], "TEST-ONLY rejection")
        self._validate(kind, command)
        tx = f"TEST-ONLY-TX-{next(self._tx):05d}"
        digest = hashlib.sha256(json.dumps(command, separators=(",", ":")).encode()).hexdigest()
        artifact = {"version": 1, "channel": "mychannel", "chaincode": "tokansh", "signer": "TEST-ONLY",
                    "command": command, "request_digest": digest, "transaction_id": tx,
                    "transaction": "VEVTVC1PTkxZ", "creator": "VEVTVC1PTkxZ", "mac": "0" * 64}
        self.pending[tx] = (kind, command)
        return artifact

    def submit(self, kind, artifact):
        self._guard()
        self.calls.append(("submit", kind))
        tx = artifact["transaction_id"]
        mode = self.next_outcome.pop(kind, "")
        k, command = self.pending.pop(tx)
        self.submitted.append(kind)
        block = next(self._block)
        if mode == "COMMIT_FAILED":
            self.status[tx] = CommitStatus(tx, 11, block, False)  # MVCC_READ_CONFLICT
            return
        self._apply(k, command)  # the transaction commits on the "ledger"
        self.status[tx] = CommitStatus(tx, 0, block, True)
        if mode == "SUBMIT_UNKNOWN":
            self.hide_status = True
            raise LedgerOutcomeUnknown("TEST-ONLY: submit response lost")
        if mode == "STATUS_UNKNOWN":
            self.hide_status = True

    def commit_status(self, kind, artifact):
        self._guard()
        self.calls.append(("status", kind))
        if self.hide_status or artifact["transaction_id"] not in self.status:
            raise LedgerOutcomeUnknown("TEST-ONLY: status unavailable")
        return self.status[artifact["transaction_id"]]

    # ---- chaincode-like rules (checked at endorsement, as on DRUNIX)
    def _validate(self, kind, c):
        if kind == "registration":
            if c["property_id"] in self.properties:
                raise LedgerRejected("INVALID_OPERATION_STATE", "property already registered")
        elif kind == "issuance":
            p = self.properties.get(c["property_id"])
            if p is None:
                raise LedgerRejected("PROPERTY_NOT_APPROVED", "property not registered")
            if p["issued"]:
                raise LedgerRejected("ISSUANCE_ALREADY_COMPLETED", "already issued")
            if c["quantity"] > p["supply"]:
                raise LedgerRejected("ISSUANCE_LIMIT_EXCEEDED", "exceeds approved supply")
            if c["quantity"] != p["supply"]:  # mirrors ONE_TIME_FULL_SUPPLY_ISSUANCE
                raise LedgerRejected("INITIAL_ISSUANCE_MUST_MATCH_APPROVED_SUPPLY", "must equal approved supply")
        elif kind == "transfer":
            owned, pledged = self.balance(c["property_id"], c["from_holder_id"])
            if c["quantity"] > owned - pledged:  # chaincode enforces available balance
                raise LedgerRejected("INSUFFICIENT_AVAILABLE_ANSH", "insufficient available balance")
        elif kind == "pledge":
            owned, pledged = self.balance(c["property_id"], c["holder_id"])
            if c["quantity"] > owned - pledged or c["pledge_id"] in self.pledges:
                raise LedgerRejected("INSUFFICIENT_AVAILABLE_ANSH", "cannot pledge")
        elif kind == "release":
            if c["pledge_id"] not in self.pledges:
                raise LedgerRejected("INVALID_OPERATION_STATE", "no such pledge")

    def _apply(self, kind, c):
        if kind == "registration":
            self.properties[c["property_id"]] = {"issuer_id": c["issuer_id"], "supply": c["approved_supply"], "issued": 0}
        elif kind == "issuance":
            p = self.properties[c["property_id"]]
            p["issued"] += c["quantity"]
            key = (c["property_id"], p["issuer_id"])
            self.owned[key] = self.owned.get(key, 0) + c["quantity"]
        elif kind == "transfer":
            a, b = (c["property_id"], c["from_holder_id"]), (c["property_id"], c["to_holder_id"])
            self.owned[a] -= c["quantity"]
            self.owned[b] = self.owned.get(b, 0) + c["quantity"]
        elif kind == "pledge":
            key = (c["property_id"], c["holder_id"])
            self.pledged[key] = self.pledged.get(key, 0) + c["quantity"]
            self.pledges[c["pledge_id"]] = (c["property_id"], c["holder_id"], c["quantity"])
        elif kind == "release":
            prop, holder, qty = self.pledges.pop(c["pledge_id"])
            self.pledged[(prop, holder)] -= qty
