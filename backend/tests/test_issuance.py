"""Isolated issuance orchestration tests; no DRUNIX or persistent database access."""
import hashlib
import json

import pytest

from app.auth import AARAV_ID, MEERA_ID
from app.dependencies import DemoActor
from app.errors import ApplicationError
from app.issuance import IssuanceRequest, IssuanceService
from app.properties.models import Property
from app.registration import LedgerOperation, SIGNER


PROPERTY_ID = "20000000-0000-4000-8000-000000000001"
REGISTRATION_ID = "10000000-0000-4000-8000-000000000001"
APPROVAL_ID = "40000000-0000-4000-8000-000000000001"
PRICE = "1000000"
SUPPLY = 100000


class MockIssuanceGateway:
    def __init__(self, database, cumulative=0, policy="ONE_TIME_FULL_SUPPLY_ISSUANCE"):
        self.database = database
        self.cumulative = cumulative
        self.policy = policy
        self.calls = []

    def call(self, method, path, correlation_id, payload=None):
        self.calls.append((method, path, payload))
        if path == "contract-info":
            return {"supply_interpretation": self.policy}
        if path == f"properties/{PROPERTY_ID}":
            return {"property_id": PROPERTY_ID, "issuer_id": AARAV_ID,
                    "approved_supply": SUPPLY, "issue_price_minor": PRICE}
        if path == f"issuance-state/{PROPERTY_ID}":
            return {"cumulative_issued_supply": self.cumulative,
                    "remaining_issuance_capacity": SUPPLY - self.cumulative}
        if path == "issuances/prepare":
            digest = hashlib.sha256(json.dumps(payload, separators=(",", ":")).encode()).hexdigest()
            return {"version": 1, "function": "IssueANSH", "command": payload,
                    "request_digest": digest, "signer": SIGNER, "channel": "mychannel",
                    "chaincode": "tokansh", "transaction_id": "test-issuance-tx",
                    "transaction": "bytes", "creator": "creator", "mac": "mac"}
        if path == "issuances/submit":
            return {"state": "SUBMITTED", "transaction_id": payload["transaction_id"]}
        if path == "issuances/commit-status":
            return {"transaction_id": payload["transaction_id"], "code": 0,
                    "block_number": 4, "successful": True}
        if path.startswith("issuance-operations/"):
            return {"property_id": PROPERTY_ID, "issuer_id": AARAV_ID, "quantity": SUPPLY}
        raise AssertionError(path)


def seed(application):
    with application.state.database.sessions.begin() as session:
        session.add(Property(id=PROPERTY_ID, name="TechPark One", location="Bengaluru",
            category="Office", valuation_minor=100000000000, proposed_supply=SUPPLY,
            issue_price_minor=int(PRICE), currency="INR", issuer_id=AARAV_ID,
            status="DRAFT", created_at="2026-01-01T00:00:00Z"))
        command = {"command_version": 1, "operation_id": REGISTRATION_ID,
                   "property_id": PROPERTY_ID, "issuer_id": AARAV_ID,
                   "approval_reference": APPROVAL_ID, "approval_digest": "a" * 64,
                   "approved_supply": SUPPLY, "issue_price_minor": PRICE, "currency": "INR"}
        encoded = json.dumps(command, separators=(",", ":"))
        session.add(LedgerOperation(operation_id=REGISTRATION_ID, property_id=PROPERTY_ID,
            request_digest=hashlib.sha256(encoded.encode()).hexdigest(), command_json=encoded,
            state="COMMITTED_VALID", channel="mychannel", chaincode="tokansh"))


def request():
    return IssuanceRequest(property_id=PROPERTY_ID, quantity=SUPPLY, issue_price_minor=PRICE, currency="INR")


def test_authenticated_issuer_full_issuance_and_replay(application):
    seed(application)
    service = IssuanceService(application.state.database, MockIssuanceGateway(application.state.database))
    actor = DemoActor(AARAV_ID, "INVESTOR", "Aarav")
    first = service.claim(request(), actor, "issue-once", "test-correlation")
    replay = service.claim(request(), actor, "issue-once", "retry-correlation")
    assert first["state"] == replay["state"] == "COMMITTED_VALID"
    assert first["operation_id"] == replay["operation_id"]
    assert first["issuance"]["issuer_id"] == AARAV_ID


def test_cross_investor_and_partial_issuance_are_rejected(application):
    seed(application)
    bridge = MockIssuanceGateway(application.state.database)
    service = IssuanceService(application.state.database, bridge)
    with pytest.raises(ApplicationError) as error:
        service.claim(request(), DemoActor(MEERA_ID, "INVESTOR", "Meera"), "wrong-owner", "c")
    assert error.value.status == 403
    partial = IssuanceRequest(property_id=PROPERTY_ID, quantity=SUPPLY - 1, issue_price_minor=PRICE, currency="INR")
    with pytest.raises(ApplicationError) as error:
        service.claim(partial, DemoActor(AARAV_ID, "INVESTOR", "Aarav"), "partial", "c")
    assert error.value.code == "INCONSISTENT_ISSUANCE_ECONOMICS"


def test_old_policy_and_historical_supply_fail_closed(application):
    seed(application)
    actor = DemoActor(AARAV_ID, "INVESTOR", "Aarav")
    old = IssuanceService(application.state.database, MockIssuanceGateway(
        application.state.database, policy="LIFETIME_CUMULATIVE_ISSUANCE_CEILING"))
    with pytest.raises(ApplicationError) as error:
        old.claim(request(), actor, "old-policy", "c")
    assert error.value.code == "ISSUANCE_POLICY_UNSUPPORTED"
    historical = IssuanceService(application.state.database, MockIssuanceGateway(application.state.database, cumulative=1))
    with pytest.raises(ApplicationError) as error:
        historical.claim(request(), actor, "historical", "c")
    assert error.value.code == "ISSUANCE_ALREADY_COMPLETED"


def test_lender_cannot_become_issuance_actor(application):
    seed(application)
    service = IssuanceService(application.state.database, MockIssuanceGateway(application.state.database))
    with pytest.raises(ApplicationError) as error:
        # The route dependency performs this same role check before the service.
        from app.issuance import actor_for_issuance
        actor_for_issuance(DemoActor("00000000-0000-4000-8000-000000000004", "LENDER", "Axim", "axim-bank"))
    assert error.value.status == 403
