"""Durable offering and purchase tests with an isolated mocked Gateway."""
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import httpx
import pytest
from sqlalchemy import event, select

from app.dependencies import DemoActor
from app.errors import ApplicationError
from app.marketplace import MarketplaceService, PurchaseRequest
from app.properties.models import ApplicationOperation, Property, PurchaseOperation, SaleOffering
from app.registration import LedgerOperation, SIGNER
from app.transfers import TransferGateway
from app.wallet import DemoCashEntry

PID = "f6169750-4676-4e99-887f-2bc5471bd518"
REG = "10000000-0000-4000-8000-000000000001"
ISSUER = "00000000-0000-4000-8000-000000000003"
BUYER = "00000000-0000-4000-8000-000000000006"
TX = "b" * 64


class CallLog(list):
    commit_successful = True
    submit_unknown = False
    mismatched_commit = False
    balance_unavailable = False

    def __init__(self):
        super().__init__()
        self.prepare_commands = []
        self.balances = {ISSUER: 100}
        self.committed_operations = set()


@pytest.fixture
def marketplace_bridge(application):
    cfg = application.state.settings
    cfg.drunix_gateway_url = "http://127.0.0.1:8001"
    cfg.tokansh_gateway_secret = "01" * 32
    cfg.tokansh_operator_secret = "02" * 32
    calls = CallLog()

    def handle(request):
        path = request.url.path.removeprefix("/v1/tokansh/")
        calls.append(path)
        if path == f"issuance-state/{PID}":
            data = {"schema_version": 1, "property_id": PID, "issuer_id": ISSUER,
                    "approved_supply": 100, "cumulative_issued_supply": 100,
                    "remaining_issuance_capacity": 0}
        elif path == f"properties/{PID}":
            data = {"property_id": PID, "issuer_id": ISSUER}
        elif path.startswith("balances/"):
            if calls.balance_unavailable:
                return httpx.Response(503)
            holder = path.rsplit("/", 1)[-1]
            data = {"schema_version": 1, "property_id": PID, "holder_id": holder,
                    "quantity": calls.balances.get(holder, 0)}
        elif path == "transfers/prepare":
            command = json.loads(request.content)
            calls.prepare_commands.append(command)
            data = {"version": 1, "channel": "mychannel", "chaincode": "tokansh",
                    "signer": SIGNER, "function": "TransferANSH", "command": command,
                    "request_digest": hashlib.sha256(json.dumps(command, separators=(",", ":")).encode()).hexdigest(),
                    "transaction_id": TX, "transaction": "test", "creator": "creator", "mac": "mac"}
        elif path == "transfers/submit":
            if calls.submit_unknown:
                return httpx.Response(503)
            data = {"state": "SUBMITTED", "transaction_id": TX}
        elif path == "transfers/commit-status":
            artifact = json.loads(request.content)
            if calls.commit_successful and not calls.mismatched_commit and artifact["command"]["operation_id"] not in calls.committed_operations:
                command = artifact["command"]
                calls.balances[command["from_holder_id"]] = calls.balances.get(command["from_holder_id"], 0) - command["quantity"]
                calls.balances[command["to_holder_id"]] = calls.balances.get(command["to_holder_id"], 0) + command["quantity"]
                calls.committed_operations.add(command["operation_id"])
            data = {"transaction_id": "c" * 64 if calls.mismatched_commit else TX,
                    "code": 0 if calls.commit_successful else 1,
                    "block_number": 7, "successful": calls.commit_successful}
        else:
            raise AssertionError(path)
        return httpx.Response(200, json={"data": data})

    with httpx.Client(transport=httpx.MockTransport(handle), trust_env=False, follow_redirects=False) as http:
        application.state.transfer_gateway = TransferGateway(cfg, http)
        yield calls


@pytest.fixture
def seeded_property(application):
    with application.state.database.sessions.begin() as session:
        session.add(Property(id=PID, name="TechPark One", location="Bengaluru", category="Office",
            valuation_minor=10000000, proposed_supply=100, issue_price_minor=100000,
            currency="INR", issuer_id=ISSUER, status="DRAFT", created_at="2026-01-01T00:00:00Z"))
        command = {"command_version": 1, "operation_id": REG, "property_id": PID,
                   "issuer_id": ISSUER, "approval_reference": "40000000-0000-4000-8000-000000000001",
                   "approval_digest": "a" * 64, "approved_supply": 100,
                   "issue_price_minor": "100000", "currency": "INR"}
        encoded = json.dumps(command, separators=(",", ":"))
        session.add(LedgerOperation(operation_id=REG, property_id=PID,
            request_digest=hashlib.sha256(encoded.encode()).hexdigest(), command_json=encoded,
            state="COMMITTED_VALID", channel="mychannel", chaincode="tokansh"))


def auth(client, username, key="test-key"):
    response = client.post("/api/v1/auth/login", json={"username": username, "password": "pw"})
    assert response.status_code == 200, response.text
    return {"Authorization": "Bearer " + response.json()["data"]["access_token"], "Idempotency-Key": key}


def test_offering_authorization_and_inventory(client, application, seeded_property, marketplace_bridge):
    issuer = auth(client, "Aarav", "offering")
    response = client.post("/api/v1/marketplace/offerings", headers=issuer,
                           json={"property_id": PID, "quantity": 5})
    assert response.status_code == 201, response.text
    offering = response.json()["data"]
    assert offering["price_minor"] == "100000" and offering["available_quantity"] == 5
    assert client.post("/api/v1/marketplace/offerings", headers=auth(client, "Meera", "wrong-owner"),
                       json={"property_id": PID, "quantity": 1}).status_code == 403
    assert client.post("/api/v1/marketplace/offerings", headers=auth(client, "axim-bank", "lender"),
                       json={"property_id": PID, "quantity": 1}).status_code == 403
    with application.state.database.sessions() as session:
        assert session.scalar(select(PurchaseOperation)) is None


def test_successful_purchase_settles_cash_and_inventory(client, application, seeded_property, marketplace_bridge):
    offering = client.post("/api/v1/marketplace/offerings", headers=auth(client, "Aarav", "offer"),
                           json={"property_id": PID, "quantity": 5}).json()["data"]
    buyer = auth(client, "Meera", "purchase")
    assert client.post("/api/v1/demo-wallet/fund", headers={**buyer, "Idempotency-Key": "fund"},
                       json={"amount_minor": "500000"}).status_code == 200
    response = client.post("/api/v1/marketplace/purchases", headers=buyer,
                           json={"offering_id": offering["id"], "quantity": 2})
    assert response.status_code == 200, response.text
    purchase = response.json()["data"]
    assert purchase["state"] == "SETTLED" and purchase["total_amount_minor"] == "200000"
    assert purchase["buyer_id"] == BUYER and purchase["seller_id"] == ISSUER
    assert purchase["property_id"] == PID and purchase["price_minor"] == "100000" and purchase["currency"] == "INR"
    current = client.get(f"/api/v1/marketplace/offerings/{offering['id']}", headers=buyer).json()["data"]
    assert current["sold_quantity"] == 2 and current["reserved_quantity"] == 0 and current["available_quantity"] == 3
    wallet = client.get("/api/v1/demo-wallet", headers=buyer).json()["data"]
    assert wallet["balance_minor"] == "300000" and wallet["reserved_minor"] == "0" and wallet["available_minor"] == "300000"
    with application.state.database.sessions() as session:
        entries = session.scalars(select(DemoCashEntry)).all()
        assert sorted(entry.kind for entry in entries) == ["DEMO_FUNDS", "PURCHASE_DEBIT", "SALE_PROCEEDS"]
        debit = next(entry for entry in entries if entry.kind == "PURCHASE_DEBIT")
        proceeds = next(entry for entry in entries if entry.kind == "SALE_PROCEEDS")
        assert (debit.investor_id, debit.amount_minor) == (BUYER, 200000)
        assert (proceeds.investor_id, proceeds.amount_minor) == (ISSUER, 200000)
    command = marketplace_bridge.prepare_commands[-1]
    assert {command["property_id"], command["from_holder_id"], command["to_holder_id"], command["quantity"]} == {
        PID, ISSUER, BUYER, 2,
    }
    assert command["operation_id"] == purchase["operation_id"]


def test_purchase_idempotency_and_oversell_protection(client, seeded_property, marketplace_bridge):
    offering = client.post("/api/v1/marketplace/offerings", headers=auth(client, "Aarav", "offer"),
                           json={"property_id": PID, "quantity": 1}).json()["data"]
    buyer = auth(client, "Meera", "purchase")
    client.post("/api/v1/demo-wallet/fund", headers={**buyer, "Idempotency-Key": "fund"},
                json={"amount_minor": "100000"})
    payload = {"offering_id": offering["id"], "quantity": 1}
    first = client.post("/api/v1/marketplace/purchases", headers=buyer, json=payload)
    replay = client.post("/api/v1/marketplace/purchases", headers=buyer, json=payload)
    assert first.json()["data"] == replay.json()["data"]
    conflict = client.post("/api/v1/marketplace/purchases", headers=buyer, json={**payload, "quantity": 2})
    assert conflict.status_code == 409


def test_direct_issuer_transfer_cannot_consume_committed_offering(client, seeded_property, marketplace_bridge):
    client.post("/api/v1/marketplace/offerings", headers=auth(client, "Aarav", "offer"),
                json={"property_id": PID, "quantity": 5})
    response = client.post("/api/v1/ansh/transfers", headers=auth(client, "Aarav", "direct-transfer"), json={
        "asset_id": PID, "from_user_id": ISSUER, "to_user_id": BUYER,
        "quantity": 96, "kind": "TRANSFER", "payment_outcome": "SUCCESS"})
    assert response.status_code == 409 and response.json()["error"]["code"] == "INSUFFICIENT_BALANCE"
    assert "transfers/prepare" not in marketplace_bridge


def test_issuance_state_endpoint_is_issuer_scoped(client, seeded_property, marketplace_bridge):
    path = f"/api/v1/properties/{PID}/issuance-state"
    assert client.get(path).status_code == 401
    assert client.get(path, headers=auth(client, "axim-bank", "lender")).status_code == 403
    assert client.get(path, headers=auth(client, "Meera", "other-investor")).status_code == 403
    response = client.get(path, headers=auth(client, "Aarav", "issuer"))
    assert response.status_code == 200
    assert response.json()["data"] == {"property_id": PID, "approved_supply": 100,
        "issued_supply": 100, "remaining_supply": 0, "state": "UNKNOWN", "source": "DRUNIX"}


def test_issuance_state_gateway_failure_is_not_presented_as_live_state(client, application, seeded_property):
    cfg = application.state.settings
    cfg.drunix_gateway_url = "http://127.0.0.1:8001"
    cfg.tokansh_gateway_secret = "01" * 32
    cfg.tokansh_operator_secret = "02" * 32
    application.state.transfer_gateway = TransferGateway(
        cfg, httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(503)),
                          trust_env=False, follow_redirects=False))
    response = client.get(f"/api/v1/properties/{PID}/issuance-state", headers=auth(client, "Aarav", "issuer-failure"))
    assert response.status_code in {502, 503}
    assert response.json()["error"]["code"] in {"GATEWAY_UNAVAILABLE", "GATEWAY_BAD_RESPONSE"}


def test_concurrent_purchases_cannot_oversell_or_double_spend(client, seeded_property, marketplace_bridge):
    offering = client.post("/api/v1/marketplace/offerings", headers=auth(client, "Aarav", "offer"),
                           json={"property_id": PID, "quantity": 1}).json()["data"]
    buyer = auth(client, "Meera", "fund-buyer")
    client.post("/api/v1/demo-wallet/fund", headers={**buyer, "Idempotency-Key": "fund"},
                json={"amount_minor": "200000"})

    barrier = Barrier(2)

    def purchase(key):
        barrier.wait()
        return client.post("/api/v1/marketplace/purchases", headers={**buyer, "Idempotency-Key": key},
                           json={"offering_id": offering["id"], "quantity": 1})

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(purchase, ["purchase-a", "purchase-b"]))
    assert sorted(response.status_code for response in responses) == [200, 409]
    current = client.get(f"/api/v1/marketplace/offerings/{offering['id']}", headers=buyer).json()["data"]
    assert current["sold_quantity"] == 1 and current["reserved_quantity"] == 0 and current["available_quantity"] == 0


def test_definitive_invalid_commit_releases_inventory_and_cash_once(client, application, seeded_property, marketplace_bridge):
    marketplace_bridge.commit_successful = False
    offering = client.post("/api/v1/marketplace/offerings", headers=auth(client, "Aarav", "invalid-offer"),
                           json={"property_id": PID, "quantity": 2}).json()["data"]
    buyer = auth(client, "Meera", "invalid-purchase")
    assert client.post("/api/v1/demo-wallet/fund", headers={**buyer, "Idempotency-Key": "invalid-fund"},
                       json={"amount_minor": "200000"}).status_code == 200
    response = client.post("/api/v1/marketplace/purchases", headers=buyer,
                           json={"offering_id": offering["id"], "quantity": 1})
    assert response.status_code == 200
    purchase = response.json()["data"]
    assert purchase["state"] == "COMMITTED_INVALID"
    current = client.get(f"/api/v1/marketplace/offerings/{offering['id']}", headers=buyer).json()["data"]
    assert current["sold_quantity"] == 0 and current["reserved_quantity"] == 0 and current["available_quantity"] == 2
    wallet = client.get("/api/v1/demo-wallet", headers=buyer).json()["data"]
    assert wallet["balance_minor"] == "200000" and wallet["reserved_minor"] == "0" and wallet["available_minor"] == "200000"
    with application.state.database.sessions() as session:
        assert [entry.kind for entry in session.scalars(select(DemoCashEntry)).all()] == ["DEMO_FUNDS"]
    calls = list(marketplace_bridge)
    replay = client.post(f"/api/v1/marketplace/purchases/{purchase['operation_id']}/reconcile", headers=buyer)
    assert replay.status_code == 200 and replay.json()["data"] == purchase
    assert marketplace_bridge == calls


def test_offering_guards_financing_reservations_and_authoritative_price(client, application, seeded_property, marketplace_bridge):
    unissued_id = "f6169750-4676-4e99-887f-2bc5471bd519"
    with application.state.database.sessions.begin() as session:
        session.add(Property(id=unissued_id, name="Unissued", location="Bengaluru", category="Office",
            valuation_minor=10000000, proposed_supply=100, issue_price_minor=100000,
            currency="INR", issuer_id=ISSUER, status="DRAFT", created_at="2026-01-01T00:00:00Z"))
    issuer = auth(client, "Aarav", "guard-offer")
    unissued = client.post("/api/v1/marketplace/offerings", headers=issuer,
                           json={"property_id": unissued_id, "quantity": 1})
    assert unissued.status_code == 409 and unissued.json()["error"]["code"] == "PROPERTY_NOT_REGISTERED"
    too_large = client.post("/api/v1/marketplace/offerings", headers=issuer,
                            json={"property_id": PID, "quantity": 101})
    assert too_large.status_code == 409 and too_large.json()["error"]["code"] == "INSUFFICIENT_TRANSFERABLE_BALANCE"
    caller_price = client.post("/api/v1/marketplace/offerings", headers=issuer,
                               json={"property_id": PID, "quantity": 1, "price_minor": "1"})
    assert caller_price.status_code == 422
    first = client.post("/api/v1/marketplace/offerings", headers=issuer,
                        json={"property_id": PID, "quantity": 5})
    assert first.status_code == 201 and first.json()["data"]["price_minor"] == "100000"
    second = client.post("/api/v1/marketplace/offerings", headers=issuer,
                         json={"property_id": PID, "quantity": 1})
    assert second.status_code == 409 and second.json()["error"]["code"] == "ACTIVE_OFFERING_EXISTS"



def test_offering_respects_existing_financing_reservation(client, seeded_property, marketplace_bridge):
    finance = client.post("/api/v1/financing/applications",
                          headers={**auth(client, "Aarav", "finance-guard"), "Idempotency-Key": "finance-guard"},
                          json={"property_id": PID, "asset_class": "ANSH", "quantity": 5,
                                "unit_value_minor": "1000000", "ltv_percent": 60,
                                "annual_rate_bps": 1000, "term_months": 12})
    assert finance.status_code == 201
    loan_id = finance.json()["data"]["id"]
    assert client.post(f"/api/v1/financing/applications/{loan_id}/assess",
                       headers=auth(client, "axim-bank"), json={}).status_code == 200
    assert client.post(f"/api/v1/financing/applications/{loan_id}/approve",
                       headers=auth(client, "axim-bank"), json={}).status_code == 200
    response = client.post("/api/v1/marketplace/offerings", headers=auth(client, "Aarav", "finance-offer"),
                           json={"property_id": PID, "quantity": 96})
    assert response.status_code == 409 and response.json()["error"]["code"] == "INSUFFICIENT_TRANSFERABLE_BALANCE"


def test_financing_cannot_reserve_units_committed_to_active_offering(client, seeded_property, marketplace_bridge):
    client.post("/api/v1/marketplace/offerings", headers=auth(client, "Aarav", "fin-active-offer"),
                json={"property_id": PID, "quantity": 100})
    response = client.post("/api/v1/financing/applications",
                           headers={**auth(client, "Aarav", "fin-active"), "Idempotency-Key": "fin-active"},
                           json={"property_id": PID, "asset_class": "ANSH", "quantity": 1,
                                 "unit_value_minor": "1000000", "ltv_percent": 60,
                                 "annual_rate_bps": 1000, "term_months": 12})
    assert response.status_code == 409 and response.json()["error"]["code"] == "INSUFFICIENT_COLLATERAL"


def test_failed_offering_creation_leaves_no_persisted_row(client, application, seeded_property, marketplace_bridge):
    marketplace_bridge.balance_unavailable = True
    response = client.post("/api/v1/marketplace/offerings", headers=auth(client, "Aarav", "failed-offer"),
                           json={"property_id": PID, "quantity": 1})
    assert response.status_code in {502, 503}
    with application.state.database.sessions() as session:
        assert session.scalar(select(SaleOffering)) is None


def test_offering_create_and_close_preserve_authoritative_ownership(client, seeded_property, marketplace_bridge):
    issuer = auth(client, "Aarav", "close-offer")
    before = client.get(f"/api/v1/ansh/balances/{PID}/{ISSUER}", headers=issuer)
    issuance_before = client.get(f"/api/v1/properties/{PID}/issuance-state", headers=issuer)
    offering = client.post("/api/v1/marketplace/offerings", headers=issuer,
                           json={"property_id": PID, "quantity": 5}).json()["data"]
    closed = client.post(f"/api/v1/marketplace/offerings/{offering['id']}/close", headers=issuer)
    after = client.get(f"/api/v1/ansh/balances/{PID}/{ISSUER}", headers=issuer)
    issuance_after = client.get(f"/api/v1/properties/{PID}/issuance-state", headers=issuer)
    assert closed.status_code == 200 and closed.json()["data"]["status"] == "CLOSED"
    assert before.json()["data"] == after.json()["data"]
    assert issuance_before.json()["data"] == issuance_after.json()["data"]
    assert offering["offered_quantity"] == 5 and offering["sold_quantity"] == 0


def test_unresolved_purchase_blocks_offering_close(client, seeded_property, marketplace_bridge):
    marketplace_bridge.submit_unknown = True
    issuer = auth(client, "Aarav", "unknown-offer")
    offering = client.post("/api/v1/marketplace/offerings", headers=issuer,
                           json={"property_id": PID, "quantity": 1}).json()["data"]
    buyer = auth(client, "Meera", "unknown-purchase")
    client.post("/api/v1/demo-wallet/fund", headers={**buyer, "Idempotency-Key": "unknown-fund"},
                json={"amount_minor": "100000"})
    purchase = client.post("/api/v1/marketplace/purchases", headers=buyer,
                           json={"offering_id": offering["id"], "quantity": 1})
    assert purchase.status_code == 202 and purchase.json()["data"]["state"] == "UNKNOWN"
    closed = client.post(f"/api/v1/marketplace/offerings/{offering['id']}/close", headers=issuer)
    assert closed.status_code == 409 and closed.json()["error"]["code"] == "PURCHASE_RESERVATION_PENDING"


@pytest.mark.parametrize("quantity", [0, -1, 1.5])
def test_purchase_rejects_nonpositive_or_nonintegral_quantity(client, seeded_property, marketplace_bridge, quantity):
    offering = client.post("/api/v1/marketplace/offerings", headers=auth(client, "Aarav", f"bad-quantity-offer-{quantity}"),
                           json={"property_id": PID, "quantity": 1}).json()["data"]
    response = client.post("/api/v1/marketplace/purchases", headers={**auth(client, "Meera", f"bad-quantity-{quantity}"),
                                                                        "Idempotency-Key": f"bad-quantity-{quantity}"},
                           json={"offering_id": offering["id"], "quantity": quantity})
    assert response.status_code == 422


def test_purchase_validation_rejects_self_purchase_inventory_cash_and_caller_overrides(client, seeded_property, marketplace_bridge):
    issuer = auth(client, "Aarav", "purchase-validation-offer")
    offering = client.post("/api/v1/marketplace/offerings", headers=issuer,
                           json={"property_id": PID, "quantity": 1}).json()["data"]
    self_purchase = client.post("/api/v1/marketplace/purchases", headers={**issuer, "Idempotency-Key": "self"},
                                json={"offering_id": offering["id"], "quantity": 1})
    assert self_purchase.status_code == 422 and self_purchase.json()["error"]["code"] == "SELF_PURCHASE_NOT_ALLOWED"
    buyer = auth(client, "Meera", "purchase-validation")
    insufficient_cash = client.post("/api/v1/marketplace/purchases", headers=buyer,
                                    json={"offering_id": offering["id"], "quantity": 1})
    assert insufficient_cash.status_code == 409 and insufficient_cash.json()["error"]["code"] == "INSUFFICIENT_AVAILABLE_CASH"
    override = client.post("/api/v1/marketplace/purchases", headers={**buyer, "Idempotency-Key": "override"},
                           json={"offering_id": offering["id"], "quantity": 1, "buyer_id": ISSUER,
                                 "seller_id": BUYER, "property_id": PID, "price_minor": "1", "currency": "USD"})
    assert override.status_code == 422
    over_inventory = client.post("/api/v1/marketplace/purchases", headers={**buyer, "Idempotency-Key": "inventory"},
                                 json={"offering_id": offering["id"], "quantity": 2})
    assert over_inventory.status_code == 409 and over_inventory.json()["error"]["code"] == "INSUFFICIENT_OFFERING_INVENTORY"


def test_cash_contention_allows_one_purchase_and_never_over_reserves_cash(client, seeded_property, marketplace_bridge):
    offering = client.post("/api/v1/marketplace/offerings", headers=auth(client, "Aarav", "cash-offer"),
                           json={"property_id": PID, "quantity": 2}).json()["data"]
    buyer = auth(client, "Meera", "cash-contention")
    client.post("/api/v1/demo-wallet/fund", headers={**buyer, "Idempotency-Key": "cash-fund"},
                json={"amount_minor": "100000"})
    barrier = Barrier(2)

    def purchase(key):
        barrier.wait()
        return client.post("/api/v1/marketplace/purchases", headers={**buyer, "Idempotency-Key": key},
                           json={"offering_id": offering["id"], "quantity": 1})

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(purchase, ["cash-a", "cash-b"]))
    assert sorted(response.status_code for response in responses) == [200, 409]
    wallet = client.get("/api/v1/demo-wallet", headers=buyer).json()["data"]
    current = client.get(f"/api/v1/marketplace/offerings/{offering['id']}", headers=buyer).json()["data"]
    assert wallet["balance_minor"] == "0" and wallet["reserved_minor"] == "0" and wallet["available_minor"] == "0"
    assert current["sold_quantity"] == 1 and current["reserved_quantity"] == 0 and current["available_quantity"] == 1


def test_purchase_reservation_competes_with_withdrawal_without_overdraw(client, seeded_property, marketplace_bridge):
    marketplace_bridge.submit_unknown = True
    offering = client.post("/api/v1/marketplace/offerings", headers=auth(client, "Aarav", "cash-race-offer"),
                           json={"property_id": PID, "quantity": 1}).json()["data"]
    buyer = auth(client, "Meera", "cash-race")
    client.post("/api/v1/demo-wallet/fund", headers={**buyer, "Idempotency-Key": "cash-race-fund"},
                json={"amount_minor": "100000"})
    barrier = Barrier(2)

    def purchase():
        barrier.wait()
        return client.post("/api/v1/marketplace/purchases", headers={**buyer, "Idempotency-Key": "cash-race-purchase"},
                           json={"offering_id": offering["id"], "quantity": 1})

    def withdraw():
        barrier.wait()
        return client.post("/api/v1/demo-wallet/withdraw",
                           headers={**buyer, "Idempotency-Key": "cash-race-withdraw"},
                           json={"amount_minor": "100000"})

    with ThreadPoolExecutor(max_workers=2) as pool:
        purchase_response, withdrawal_response = [future.result() for future in (
            pool.submit(purchase), pool.submit(withdraw))]
    assert purchase_response.status_code in {202, 409}
    assert withdrawal_response.status_code in {200, 409}
    assert (purchase_response.status_code == 202) ^ (withdrawal_response.status_code == 200)
    wallet = client.get("/api/v1/demo-wallet", headers=buyer).json()["data"]
    assert int(wallet["balance_minor"]) >= 0
    assert int(wallet["reserved_minor"]) <= int(wallet["balance_minor"])
    if purchase_response.status_code == 202:
        assert wallet["balance_minor"] == "100000" and wallet["reserved_minor"] == "100000"
    else:
        assert wallet["balance_minor"] == "0" and wallet["reserved_minor"] == "0"


def test_offering_creation_competes_with_financing_approval(client, application, seeded_property, marketplace_bridge):
    finance = client.post("/api/v1/financing/applications",
                          headers={**auth(client, "Aarav", "race-finance"), "Idempotency-Key": "race-finance"},
                          json={"property_id": PID, "asset_class": "ANSH", "quantity": 1,
                                "unit_value_minor": "1000000", "ltv_percent": 60,
                                "annual_rate_bps": 1000, "term_months": 12})
    loan_id = finance.json()["data"]["id"]
    assert client.post(f"/api/v1/financing/applications/{loan_id}/assess",
                       headers=auth(client, "axim-bank"), json={}).status_code == 200
    barrier = Barrier(2)

    def create_offer():
        barrier.wait()
        return client.post("/api/v1/marketplace/offerings", headers=auth(client, "Aarav", "race-offer"),
                           json={"property_id": PID, "quantity": 100})

    def approve_finance():
        barrier.wait()
        return client.post(f"/api/v1/financing/applications/{loan_id}/approve",
                           headers=auth(client, "axim-bank"), json={})

    with ThreadPoolExecutor(max_workers=2) as pool:
        offer_response, approval_response = [future.result() for future in (
            pool.submit(create_offer), pool.submit(approve_finance))]
    assert offer_response.status_code in {201, 409}
    assert approval_response.status_code == 200
    active_offer = offer_response.status_code == 201
    approved = approval_response.json()["data"]["state"] == "APPROVED"
    assert active_offer ^ approved
    with application.state.database.sessions() as session:
        active_row = session.scalar(select(SaleOffering))
        loan_row = session.scalar(select(ApplicationOperation).where(ApplicationOperation.id == loan_id))
        loan_state = json.loads(loan_row.response_json)["state"]
        if active_offer:
            assert active_row is not None and loan_state == "REJECTED"
        else:
            assert active_row is None and loan_state == "APPROVED"


def test_offering_creation_competes_with_direct_transfer(client, application, seeded_property, marketplace_bridge):
    barrier = Barrier(2)

    def create_offer():
        barrier.wait()
        return client.post("/api/v1/marketplace/offerings", headers=auth(client, "Aarav", "race-transfer-offer"),
                           json={"property_id": PID, "quantity": 100})

    def direct_transfer():
        barrier.wait()
        return client.post("/api/v1/ansh/transfers", headers=auth(client, "Aarav", "race-direct-transfer"), json={
            "asset_id": PID, "from_user_id": ISSUER, "to_user_id": BUYER,
            "quantity": 1, "kind": "TRANSFER", "payment_outcome": "SUCCESS"})

    with ThreadPoolExecutor(max_workers=2) as pool:
        offer_response, transfer_response = [future.result() for future in (
            pool.submit(create_offer), pool.submit(direct_transfer))]
    assert offer_response.status_code in {201, 409}
    assert transfer_response.status_code in {200, 409}
    assert (offer_response.status_code == 201) ^ (transfer_response.status_code == 200)
    with application.state.database.sessions() as session:
        offering = session.scalar(select(SaleOffering))
        operation = session.scalar(select(ApplicationOperation))
        if offer_response.status_code == 201:
            assert offering is not None and operation is not None and operation.status == "FAILED"
        else:
            assert offering is None and operation is not None and operation.status == "COMMITTED_VALID"


def test_atomic_reservation_failure_leaves_no_partial_state(client, application, seeded_property, marketplace_bridge):
    offering = client.post("/api/v1/marketplace/offerings", headers=auth(client, "Aarav", "atomic-offer"),
                           json={"property_id": PID, "quantity": 1}).json()["data"]
    buyer = auth(client, "Meera", "atomic-purchase")
    client.post("/api/v1/demo-wallet/fund", headers={**buyer, "Idempotency-Key": "atomic-fund"},
                json={"amount_minor": "100000"})

    def fail_purchase_insert(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("INSERT INTO PURCHASE_OPERATIONS"):
            raise RuntimeError("injected reservation failure")

    event.listen(application.state.database.engine, "before_cursor_execute", fail_purchase_insert)
    try:
        response = client.post("/api/v1/marketplace/purchases", headers=buyer,
                               json={"offering_id": offering["id"], "quantity": 1})
    finally:
        event.remove(application.state.database.engine, "before_cursor_execute", fail_purchase_insert)
    assert response.status_code == 500
    current = client.get(f"/api/v1/marketplace/offerings/{offering['id']}", headers=buyer).json()["data"]
    wallet = client.get("/api/v1/demo-wallet", headers=buyer).json()["data"]
    assert current["reserved_quantity"] == 0 and wallet["reserved_minor"] == "0"
    assert "transfers/prepare" not in marketplace_bridge
    with application.state.database.sessions() as session:
        assert session.scalar(select(PurchaseOperation)) is None


def test_unknown_purchase_retains_reservations_and_reconcile_does_not_duplicate_transfer(client, seeded_property, marketplace_bridge):
    marketplace_bridge.submit_unknown = True
    offering = client.post("/api/v1/marketplace/offerings", headers=auth(client, "Aarav", "unknown-recovery-offer"),
                           json={"property_id": PID, "quantity": 1}).json()["data"]
    buyer = auth(client, "Meera", "unknown-recovery")
    client.post("/api/v1/demo-wallet/fund", headers={**buyer, "Idempotency-Key": "unknown-recovery-fund"},
                json={"amount_minor": "100000"})
    response = client.post("/api/v1/marketplace/purchases", headers=buyer,
                           json={"offering_id": offering["id"], "quantity": 1})
    purchase = response.json()["data"]
    assert purchase["state"] == "UNKNOWN"
    prepare_count = len([path for path in marketplace_bridge if path == "transfers/prepare"])
    submit_count = len([path for path in marketplace_bridge if path == "transfers/submit"])
    current = client.get(f"/api/v1/marketplace/offerings/{offering['id']}", headers=buyer).json()["data"]
    wallet = client.get("/api/v1/demo-wallet", headers=buyer).json()["data"]
    assert current["reserved_quantity"] == 1 and wallet["reserved_minor"] == "100000"
    assert prepare_count == 1 and submit_count == 1

    marketplace_bridge.submit_unknown = False
    reconciled = client.post(f"/api/v1/marketplace/purchases/{purchase['operation_id']}/reconcile", headers=buyer)
    assert reconciled.status_code == 200 and reconciled.json()["data"]["state"] == "SETTLED"
    assert len([path for path in marketplace_bridge if path == "transfers/prepare"]) == prepare_count
    assert len([path for path in marketplace_bridge if path == "transfers/submit"]) == submit_count

def test_mismatched_commit_evidence_retains_reservations_without_wallet_entries(client, application, seeded_property, marketplace_bridge):
    marketplace_bridge.mismatched_commit = True
    offering = client.post("/api/v1/marketplace/offerings", headers=auth(client, "Aarav", "mismatch-offer"),
                           json={"property_id": PID, "quantity": 1}).json()["data"]
    buyer = auth(client, "Meera", "mismatch-purchase")
    client.post("/api/v1/demo-wallet/fund", headers={**buyer, "Idempotency-Key": "mismatch-fund"},
                json={"amount_minor": "100000"})
    response = client.post("/api/v1/marketplace/purchases", headers=buyer,
                           json={"offering_id": offering["id"], "quantity": 1})
    assert response.status_code == 202 and response.json()["data"]["state"] == "UNKNOWN"
    before = list(marketplace_bridge)
    retry = client.post(f"/api/v1/marketplace/purchases/{response.json()['data']['operation_id']}/reconcile", headers=buyer)
    assert retry.status_code == 200 and retry.json()["data"]["state"] == "UNKNOWN"
    assert [path for path in marketplace_bridge if path == "transfers/prepare"] == [path for path in before if path == "transfers/prepare"]
    with application.state.database.sessions() as session:
        assert [entry.kind for entry in session.scalars(select(DemoCashEntry)).all()] == ["DEMO_FUNDS"]
    current = client.get(f"/api/v1/marketplace/offerings/{offering['id']}", headers=buyer).json()["data"]
    wallet = client.get("/api/v1/demo-wallet", headers=buyer).json()["data"]
    assert current["reserved_quantity"] == 1 and wallet["reserved_minor"] == "100000"


def test_reservation_survives_service_recreation_before_transfer_initiation(client, application, seeded_property, marketplace_bridge):
    offering = client.post("/api/v1/marketplace/offerings", headers=auth(client, "Aarav", "restart-offer"),
                           json={"property_id": PID, "quantity": 1}).json()["data"]
    buyer = auth(client, "Meera", "restart-purchase")
    client.post("/api/v1/demo-wallet/fund", headers={**buyer, "Idempotency-Key": "restart-fund"},
                json={"amount_minor": "100000"})
    actor = DemoActor(BUYER, "INVESTOR", "Meera")
    reserved, created = MarketplaceService(application.state.database, application.state.transfer_gateway,
                                            application.state.settings)._purchase_reservation(
        PurchaseRequest(offering_id=offering["id"], quantity=1), actor, "restart-key", "restart-correlation")
    assert created and reserved.state == "RESERVED"
    restarted = MarketplaceService(application.state.database, application.state.transfer_gateway, application.state.settings)
    result = restarted.reconcile(reserved.id, actor, "restart-reconcile")
    assert result["state"] == "SETTLED"
    assert len([path for path in marketplace_bridge if path == "transfers/prepare"]) == 1
    assert len([path for path in marketplace_bridge if path == "transfers/submit"]) == 1


def test_withdrawal_cannot_consume_cash_reserved_by_unknown_purchase(client, seeded_property, marketplace_bridge):
    marketplace_bridge.submit_unknown = True
    offering = client.post("/api/v1/marketplace/offerings", headers=auth(client, "Aarav", "withdraw-offer"),
                           json={"property_id": PID, "quantity": 1}).json()["data"]
    buyer = auth(client, "Meera", "withdraw-purchase")
    client.post("/api/v1/demo-wallet/fund", headers={**buyer, "Idempotency-Key": "withdraw-fund"},
                json={"amount_minor": "100000"})
    response = client.post("/api/v1/marketplace/purchases", headers=buyer,
                           json={"offering_id": offering["id"], "quantity": 1})
    assert response.json()["data"]["state"] == "UNKNOWN"
    withdrawal = client.post("/api/v1/demo-wallet/withdraw", headers={**buyer, "Idempotency-Key": "withdraw-attempt"},
                             json={"amount_minor": "100000"})
    assert withdrawal.status_code == 409 and withdrawal.json()["error"]["code"] == "INSUFFICIENT_AVAILABLE_CASH"


def test_nondefinitive_transfer_exception_retains_reservation(client, application, seeded_property, marketplace_bridge):
    marketplace_bridge.submit_unknown = True
    offering = client.post("/api/v1/marketplace/offerings", headers=auth(client, "Aarav", "exception-offer"),
                           json={"property_id": PID, "quantity": 1}).json()["data"]
    buyer = auth(client, "Meera", "exception-purchase")
    client.post("/api/v1/demo-wallet/fund", headers={**buyer, "Idempotency-Key": "exception-fund"},
                json={"amount_minor": "100000"})
    purchase = client.post("/api/v1/marketplace/purchases", headers={**buyer, "Idempotency-Key": "exception-key"},
                           json={"offering_id": offering["id"], "quantity": 1})
    assert purchase.status_code == 202 and purchase.json()["data"]["state"] == "UNKNOWN"
    # Model a timeout/error after the durable transfer claim: it is not
    # evidence of a definitive non-commit and must retain both reservations.
    result = MarketplaceService(application.state.database, application.state.transfer_gateway,
                                application.state.settings)._transfer_error(
        purchase.json()["data"]["operation_id"], ApplicationError(504, "GATEWAY_TIMEOUT", "ambiguous"))
    assert result["state"] == "UNKNOWN"


def test_confirmed_transfer_with_local_settlement_failure_is_recoverable(client, application, seeded_property, marketplace_bridge):
    offering = client.post("/api/v1/marketplace/offerings", headers=auth(client, "Aarav", "settle-failure-offer"),
                           json={"property_id": PID, "quantity": 1}).json()["data"]
    buyer = auth(client, "Meera", "settle-failure")
    client.post("/api/v1/demo-wallet/fund", headers={**buyer, "Idempotency-Key": "settle-failure-fund"},
                json={"amount_minor": "100000"})

    def fail_settlement_insert(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("INSERT INTO DEMO_CASH_ENTRIES") and parameters and parameters[1] == BUYER:
            raise RuntimeError("injected local settlement failure")

    event.listen(application.state.database.engine, "before_cursor_execute", fail_settlement_insert)
    try:
        response = client.post("/api/v1/marketplace/purchases", headers=buyer,
                               json={"offering_id": offering["id"], "quantity": 1})
    finally:
        event.remove(application.state.database.engine, "before_cursor_execute", fail_settlement_insert)
    assert response.status_code == 500
    purchase_id = response.json()["error"].get("operation_id") if response.headers.get("content-type", "").startswith("application/json") else None
    with application.state.database.sessions() as session:
        row = session.scalar(select(PurchaseOperation))
        assert row is not None and row.state == "COMMITTED_PENDING_SETTLEMENT"
        purchase_id = row.id
    prepare_count = len([path for path in marketplace_bridge if path == "transfers/prepare"])
    submit_count = len([path for path in marketplace_bridge if path == "transfers/submit"])
    reconciled = client.post(f"/api/v1/marketplace/purchases/{purchase_id}/reconcile", headers=buyer)
    assert reconciled.status_code == 200 and reconciled.json()["data"]["state"] == "SETTLED"
    repeated = client.post(f"/api/v1/marketplace/purchases/{purchase_id}/reconcile", headers=buyer)
    assert repeated.status_code == 200 and repeated.json()["data"] == reconciled.json()["data"]
    assert len([path for path in marketplace_bridge if path == "transfers/prepare"]) == prepare_count
    assert len([path for path in marketplace_bridge if path == "transfers/submit"]) == submit_count
    current = client.get(f"/api/v1/marketplace/offerings/{offering['id']}", headers=buyer).json()["data"]
    assert current["sold_quantity"] == 1 and current["reserved_quantity"] == 0
    with application.state.database.sessions() as session:
        entries = session.scalars(select(DemoCashEntry)).all()
        assert sorted(entry.kind for entry in entries) == ["DEMO_FUNDS", "PURCHASE_DEBIT", "SALE_PROCEEDS"]


def test_prepared_transfer_recovery_retains_artifact_without_duplicate_submission(client, application, seeded_property, marketplace_bridge):
    offering = client.post("/api/v1/marketplace/offerings", headers=auth(client, "Aarav", "prepared-offer"),
                           json={"property_id": PID, "quantity": 1}).json()["data"]
    buyer = auth(client, "Meera", "prepared-purchase")
    client.post("/api/v1/demo-wallet/fund", headers={**buyer, "Idempotency-Key": "prepared-fund"},
                json={"amount_minor": "100000"})
    actor = DemoActor(BUYER, "INVESTOR", "Meera")
    purchase, created = MarketplaceService(application.state.database, application.state.transfer_gateway,
                                            application.state.settings)._purchase_reservation(
        PurchaseRequest(offering_id=offering["id"], quantity=1), actor, "prepared-key", "prepared-correlation")
    assert created and purchase.state == "RESERVED"
    frozen = {"command_version": 1, "operation_id": purchase.id, "property_id": PID,
              "from_holder_id": ISSUER, "to_holder_id": BUYER, "quantity": 1}
    artifact = {"version": 1, "channel": "mychannel", "chaincode": "tokansh", "signer": SIGNER,
                "function": "TransferANSH", "command": frozen,
                "request_digest": hashlib.sha256(json.dumps(frozen, separators=(",", ":")).encode()).hexdigest(),
                "transaction_id": TX, "transaction": "prepared", "creator": "creator", "mac": "mac"}
    transfer_data = {"type": "ANSH_TRANSFER", "request": {"asset_id": PID, "from_user_id": ISSUER,
        "to_user_id": BUYER, "quantity": 1, "kind": "ACQUISITION", "payment_outcome": "SUCCESS"},
        "payment": {"simulated": True, "status": "SUCCESS"}, "artifact": artifact,
        "transaction_id": TX, "commit": None}
    with application.state.database.sessions.begin() as session:
        session.add(ApplicationOperation(id=purchase.id, actor_id=BUYER,
            idempotency_key="purchase-transfer:" + purchase.id, request_hash="d" * 64,
            status="PREPARED", response_json=json.dumps(transfer_data),
            correlation_id="prepared-correlation", created_at="2026-01-01T00:00:00Z"))
    prepared_count = len([path for path in marketplace_bridge if path == "transfers/prepare"])
    submitted_count = len([path for path in marketplace_bridge if path == "transfers/submit"])
    restarted = MarketplaceService(application.state.database, application.state.transfer_gateway,
                                    application.state.settings)
    result = restarted.reconcile(purchase.id, actor, "prepared-reconcile")
    repeated = restarted.reconcile(purchase.id, actor, "prepared-reconcile-again")
    assert result["operation_id"] == purchase.id and result["transfer_operation_id"] == purchase.id
    assert result["state"] == "RESERVED" and repeated["state"] == "RESERVED"
    assert result["transaction_id"] is None
    assert len([path for path in marketplace_bridge if path == "transfers/prepare"]) == prepared_count
    assert len([path for path in marketplace_bridge if path == "transfers/submit"]) == submitted_count
    with application.state.database.sessions() as session:
        stored = session.get(ApplicationOperation, purchase.id)
        assert stored.status == "PREPARED" and json.loads(stored.response_json)["artifact"] == artifact
        offering_row = session.get(SaleOffering, offering["id"])
        assert offering_row.reserved_quantity == 1 and offering_row.sold_quantity == 0
# End of focused marketplace integrity tests.
