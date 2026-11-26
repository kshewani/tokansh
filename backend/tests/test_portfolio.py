"""Authenticated multi-property portfolio observations."""
import hashlib
import json

import pytest

from app.errors import ApplicationError
from app.properties.models import Property
from app.registration import LedgerOperation


AARAV = "00000000-0000-4000-8000-000000000003"
MEERA = "00000000-0000-4000-8000-000000000006"
P1 = "f6169750-4676-4e99-887f-2bc5471bd518"
P2 = "f6169750-4676-4e99-887f-2bc5471bd519"


class PortfolioGateway:
    def __init__(self):
        self.fail = set()
        self.quantities = {(P1, AARAV): 500, (P2, AARAV): 300, (P1, MEERA): 9500, (P2, MEERA): 4700}

    def call(self, method, path, correlation_id, payload=None):
        property_id = path.rsplit("/", 1)[-1]
        if property_id in self.fail:
            raise ApplicationError(503, "GATEWAY_UNAVAILABLE", "test gateway unavailable")
        return {"schema_version": 1, "property_id": property_id, "issuer_id": MEERA,
                "approved_supply": 10000 if property_id == P1 else 5000,
                "cumulative_issued_supply": 10000 if property_id == P1 else 5000,
                "remaining_issuance_capacity": 0}

    def balance(self, property_id, holder_id, correlation_id):
        if property_id in self.fail:
            raise ApplicationError(503, "GATEWAY_UNAVAILABLE", "test gateway unavailable")
        return {"schema_version": 1, "property_id": property_id, "holder_id": holder_id,
                "quantity": self.quantities.get((property_id, holder_id), 0), "source": "DRUNIX_EVALUATE"}


def auth(client, username):
    response = client.post("/api/v1/auth/login", json={"username": username, "password": "test"})
    assert response.status_code == 200
    return {"Authorization": "Bearer " + response.json()["data"]["access_token"]}


def register_row(session, property_id, name, issuer=MEERA, supply=10000, price=100000):
    session.add(Property(id=property_id, name=name, location="Bengaluru", category="Office",
                         valuation_minor=supply * price, proposed_supply=supply,
                         issue_price_minor=price, currency="INR", issuer_id=issuer,
                         status="DRAFT", created_at=property_id))
    command = {"command_version": 1, "operation_id": property_id,
               "property_id": property_id, "issuer_id": issuer,
               "approval_reference": "40000000-0000-4000-8000-000000000001",
               "approval_digest": "a" * 64, "approved_supply": supply,
               "issue_price_minor": str(price), "currency": "INR"}
    encoded = json.dumps(command, separators=(",", ":"))
    session.add(LedgerOperation(operation_id=property_id, property_id=property_id,
                                request_digest=hashlib.sha256(encoded.encode()).hexdigest(),
                                command_json=encoded, state="COMMITTED_VALID",
                                channel="mychannel", chaincode="tokansh"))


@pytest.fixture
def portfolio_gateway(application):
    gateway = PortfolioGateway()
    application.state.transfer_gateway = gateway
    return gateway


@pytest.fixture
def portfolio_properties(application):
    with application.state.database.sessions.begin() as session:
        register_row(session, P1, "Property A", supply=10000)
        register_row(session, P2, "Property B", supply=5000, price=200000)


def test_portfolio_discovers_independent_property_balances_and_prices(client, portfolio_properties, portfolio_gateway):
    response = client.get("/api/v1/portfolio", headers=auth(client, "Aarav"))
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["investor_id"] == AARAV
    assert {(item["property_id"], item["owned_units"]) for item in data["items"]} == {(P1, 500), (P2, 300)}
    assert data["items"][1]["initial_issue_price_minor"] == "200000"
    assert data["aggregate"]["total_indicative_value_minor"] == "110000000"
    assert data["aggregate"]["status"] == "COMPLETE"


def test_portfolio_does_not_infer_holdings_from_local_history_and_is_session_scoped(client, portfolio_properties, portfolio_gateway):
    aarav = client.get("/api/v1/portfolio", headers=auth(client, "Aarav")).json()["data"]
    meera = client.get("/api/v1/portfolio", headers=auth(client, "Meera")).json()["data"]
    assert aarav["investor_id"] == AARAV and meera["investor_id"] == MEERA
    assert aarav["items"][0]["owned_units"] != meera["items"][0]["owned_units"]


def test_partial_gateway_failure_is_explicit_and_never_a_zero_balance(client, portfolio_properties, portfolio_gateway):
    portfolio_gateway.fail.add(P2)
    response = client.get("/api/v1/portfolio", headers=auth(client, "Aarav"))
    assert response.status_code == 200
    data = response.json()["data"]
    item = next(value for value in data["items"] if value["property_id"] == P2)
    assert item["observation_status"] == "UNAVAILABLE"
    assert item["owned_units"] is None and item["issued_supply"] is None
    assert data["aggregate"]["status"] == "PARTIAL"
    assert data["aggregate"]["total_indicative_value_minor"] is None


def test_lender_cannot_read_investor_portfolio(client, portfolio_properties, portfolio_gateway):
    response = client.get("/api/v1/portfolio", headers=auth(client, "axim-bank"))
    assert response.status_code == 403
