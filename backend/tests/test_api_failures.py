"""Failure paths and critical invariants through the API (BUSINESS_RULES section 15).

Uses the TEST-ONLY fake ledger; not evidence of DRUNIX integration.
"""
from datetime import date, timedelta

from app.modules.distributions import allocate
from tests.test_api_demo_flow import AARAV, MEERA, P, TECHPARK, buy, data, holding, setup_issued


def transfers_sent(ledger):
    return [k for k in ledger.submitted if k == "transfer"]


def test_failed_payment_never_transfers(people, ledger):
    _, iss, listing = setup_issued(people)
    order, resp = buy(people, listing, outcome="FAILED")
    assert resp.status_code == 409 and resp.json()["error"]["code"] == "PAYMENT_FAILED"
    o = data(people["aarav"].get(f"{P}/marketplace/orders/{order['id']}"))
    assert o["status"] == "PAYMENT_FAILED" and o["payments"][0]["status"] == "FAILED" and o["transfer"] is None
    assert transfers_sent(ledger) == [] and holding(people) is None
    assert ledger.balance(iss["property_id"], AARAV) == (0, 0)


def test_ledger_unavailable_fails_safely_and_can_retry(people, ledger):
    meera = people["meera"]
    prop = data(meera.post(f"{P}/properties", TECHPARK), 201)
    meera.post(f"{P}/properties/{prop['id']}/submit")
    ledger.available = False
    approved = meera.post(f"{P}/properties/{prop['id']}/approve", {})
    assert approved.status_code == 202  # approval is an application decision...
    body = data(approved)
    assert body["approval_status"] == "APPROVED" and body["ledger"]["registered"] is False  # ...registration is not
    assert body["ledger"]["operation"]["status"] == "FAILED"
    assert body["ledger"]["operation"]["error_code"] == "LEDGER_UNAVAILABLE"
    assert body["ledger"]["operation"]["ledger_transaction_id"] is None  # nothing fabricated
    r = meera.post(f"{P}/ansh/issuances", {"property_id": prop["id"], "quantity": 100000})
    assert r.status_code == 409 and r.json()["error"]["code"] == "PROPERTY_NOT_APPROVED"
    r = meera.post(f"{P}/properties/{prop['id']}/register")
    assert r.status_code == 503 and r.json()["error"]["code"] == "LEDGER_UNAVAILABLE"
    status = data(meera.get(f"{P}/system/status"))
    assert next(c for c in status["components"] if c["name"] == "DRUNIX gateway adapter")["status"] == "UNAVAILABLE"

    ledger.available = True
    assert data(meera.post(f"{P}/properties/{prop['id']}/register"), 200)["ledger"]["registered"] is True
    ledger.next_outcome["issuance"] = "UNAVAILABLE"
    r = meera.post(f"{P}/ansh/issuances", {"property_id": prop["id"], "quantity": 100000})
    assert r.status_code == 503
    iss = data(meera.get(f"{P}/ansh/issuances"))["items"][0]
    assert iss["status"] == "FAILED" and iss["issued_quantity"] == 0
    assert data(meera.get(f"{P}/portfolios/{MEERA}"))["ansh"] == []
    retry = data(meera.post(f"{P}/ansh/issuances", {"property_id": prop["id"], "quantity": 100000}), 201)
    assert retry["status"] == "CONFIRMED" and retry["id"] == iss["id"]


def test_unknown_outcome_is_reconciled_not_resubmitted(people, ledger):
    _, iss, listing = setup_issued(people)
    ledger.next_outcome["transfer"] = "SUBMIT_UNKNOWN"
    order, resp = buy(people, listing)
    assert resp.status_code == 202
    o = data(resp)
    assert o["status"] == "RECONCILIATION_REQUIRED" and o["transfer"]["status"] == "RECONCILIATION_REQUIRED"
    assert holding(people) is None  # ownership is not updated without a confirmed commit
    cases = data(people["meera"].get(f"{P}/reconciliation/cases"))["items"]
    assert len(cases) == 1 and cases[0]["status"] == "OPEN" and cases[0]["order_id"] == order["id"]

    ledger.hide_status = False  # the ledger can now report the commit status
    op = data(people["meera"].post(f"{P}/ledger/operations/{o['transfer']['operation_id']}/reconcile"), 200)
    assert op["status"] == "COMMITTED"
    assert len(transfers_sent(ledger)) == 1  # reconciled by query, never resubmitted
    assert data(people["aarav"].get(f"{P}/marketplace/orders/{order['id']}"))["status"] == "COMPLETED"
    assert holding(people)["owned_units"] == 500
    assert data(people["meera"].get(f"{P}/reconciliation/cases"))["items"][0]["status"] == "RESOLVED"
    r = people["meera"].post(f"{P}/ledger/operations/{op['operation_id']}/reconcile")
    assert r.status_code == 409


def test_commit_failure_after_payment_records_refund(people, ledger):
    _, iss, listing = setup_issued(people)
    ledger.next_outcome["transfer"] = "COMMIT_FAILED"
    order, resp = buy(people, listing)
    assert resp.status_code == 502 and resp.json()["error"]["code"] == "LEDGER_COMMIT_FAILED"
    o = data(people["aarav"].get(f"{P}/marketplace/orders/{order['id']}"))
    assert o["status"] == "FAILED"
    kinds = {(p["kind"], p["status"]) for p in o["payments"]}
    assert kinds == {("PURCHASE", "SUCCESS"), ("REFUND", "SUCCESS")}  # payment kept, refund explicit
    assert holding(people) is None
    lst = data(people["meera"].get(f"{P}/marketplace/listings/{listing['id']}"))
    assert lst["remaining_quantity"] == 100000


def test_idempotency(people, ledger):
    _, iss, listing = setup_issued(people)
    aarav = people["aarav"]
    body = {"listing_id": listing["id"], "quantity": 10}
    first = data(aarav.post(f"{P}/marketplace/orders", body, idem="same-key"), 201)
    again = aarav.post(f"{P}/marketplace/orders", body, idem="same-key")
    assert again.status_code == 201 and again.json()["data"]["id"] == first["id"]
    assert again.json()["meta"]["idempotent_replay"] is True
    clash = aarav.post(f"{P}/marketplace/orders", {**body, "quantity": 11}, idem="same-key")
    assert clash.status_code == 409 and clash.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    pay = {"order_id": first["id"]}
    aarav.post(f"{P}/payments/simulate", pay, idem="pay-1")
    aarav.post(f"{P}/payments/simulate", pay, idem="pay-1")
    assert len(transfers_sent(ledger)) == 1
    assert len(data(aarav.get(f"{P}/marketplace/orders/{first['id']}"))["payments"]) == 1
    r = aarav.client.post(f"{P}/marketplace/orders", json=body, headers=aarav.auth)
    assert r.status_code == 400  # Idempotency-Key is mandatory for financial operations


def test_supply_and_permission_rules(people, ledger):
    meera, aarav = people["meera"], people["aarav"]
    prop = data(meera.post(f"{P}/properties", TECHPARK), 201)
    r = meera.post(f"{P}/ansh/issuances", {"property_id": prop["id"], "quantity": 10})
    assert r.json()["error"]["code"] == "PROPERTY_NOT_APPROVED"
    meera.post(f"{P}/properties/{prop['id']}/submit")
    r = aarav.post(f"{P}/properties/{prop['id']}/approve", {})
    assert r.status_code == 403 and r.json()["error"]["code"] == "INSUFFICIENT_PERMISSIONS"
    meera.post(f"{P}/properties/{prop['id']}/approve", {"approved_supply": 90000})
    r = meera.post(f"{P}/ansh/issuances", {"property_id": prop["id"], "quantity": 90001})
    assert r.status_code == 409 and r.json()["error"]["code"] == "ISSUANCE_LIMIT_EXCEEDED"
    assert data(meera.post(f"{P}/ansh/issuances", {"property_id": prop["id"], "quantity": 90000}), 201)["status"] == "CONFIRMED"
    r = meera.post(f"{P}/ansh/issuances", {"property_id": prop["id"], "quantity": 1})
    assert r.status_code == 409
    assert aarav.client.get(f"{P}/properties").status_code == 401
    r = meera.post(f"{P}/properties", {**TECHPARK, "valuation": "10.001"})
    assert r.status_code == 422  # more than two decimal places


def test_pledge_and_ltv_limits(people, ledger):
    _, iss, listing = setup_issued(people)
    buy(people, listing, qty=100)
    aarav = people["aarav"]
    r = aarav.post(f"{P}/collateral/pledges", {"issuance_id": iss["id"], "quantity": 101})
    assert r.status_code == 409 and r.json()["error"]["code"] == "INSUFFICIENT_AVAILABLE_ANSH"
    pledge = data(aarav.post(f"{P}/collateral/pledges", {"issuance_id": iss["id"], "quantity": 100}), 201)
    r = aarav.post(f"{P}/loans/applications", {"pledge_id": pledge["id"], "principal": "600000.01"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "LTV_LIMIT_EXCEEDED"
    loan = data(aarav.post(f"{P}/loans/applications", {"pledge_id": pledge["id"], "principal": "600000.00"}), 201)
    assert loan["ltv_percent"] == "60.00"
    r = aarav.post(f"{P}/ansh/transfers", {"issuance_id": iss["id"], "to_user_id": MEERA, "quantity": 1})
    assert r.json()["error"]["code"] == "PLEDGED_UNITS_RESTRICTED"


def test_distribution_uses_record_date_not_current_holdings(people, ledger):
    _, iss, listing = setup_issued(people)
    buy(people, listing)
    meera = people["meera"]
    future = (date.today() + timedelta(days=3)).isoformat()
    d = data(meera.post(f"{P}/distributions", {"issuance_id": iss["id"], "period_label": "Future", "total_amount": "100.00",
                                               "record_date": future, "distribution_date": future}), 201)
    r = meera.post(f"{P}/distributions/{d['id']}/calculate")
    assert r.status_code == 409  # record date not reached
    past = (date.today() - timedelta(days=1)).isoformat()
    d = data(meera.post(f"{P}/distributions", {"issuance_id": iss["id"], "period_label": "Past", "total_amount": "100.00",
                                               "record_date": past, "distribution_date": past}), 201)
    r = meera.post(f"{P}/distributions/{d['id']}/calculate")
    # Nothing was committed by yesterday, so today's holdings must NOT be used.
    assert r.status_code == 409 and r.json()["error"]["code"] == "RECONCILIATION_REQUIRED"
    dup = meera.post(f"{P}/distributions", {"issuance_id": iss["id"], "period_label": "Past", "total_amount": "100.00",
                                            "record_date": past, "distribution_date": past})
    assert dup.status_code == 409


def test_allocation_reconciles_exactly():
    shares = allocate(100, {"a": 1, "b": 1, "c": 1})
    assert sum(a for a, _ in shares.values()) == 100
    assert sorted(a for a, _ in shares.values()) == [33, 33, 34]
    assert allocate(100_000_000, {"meera": 99_500, "aarav": 500})["aarav"] == (500_000, 0)
    odd = allocate(1_000_001, {"x": 3, "y": 7, "z": 11})
    assert sum(a for a, _ in odd.values()) == 1_000_001


# ---------------------------------------------------------------- 3-step lifecycle (prepare / submit / status)

def test_prepare_rejection_is_definitive_and_reports_business_code(people, ledger):
    meera = people["meera"]
    prop = data(meera.post(f"{P}/properties", TECHPARK), 201)
    meera.post(f"{P}/properties/{prop['id']}/submit")
    meera.post(f"{P}/properties/{prop['id']}/approve", {})
    ledger.next_outcome["issuance"] = "REJECT:ISSUANCE_LIMIT_EXCEEDED"
    r = meera.post(f"{P}/ansh/issuances", {"property_id": prop["id"], "quantity": 100000})
    assert r.status_code == 409 and r.json()["error"]["code"] == "ISSUANCE_LIMIT_EXCEEDED"
    assert ledger.submitted.count("issuance") == 0  # refused at endorsement: nothing submitted


def test_status_unknown_after_submit_needs_reconciliation(people, ledger):
    _, iss, listing = setup_issued(people)
    ledger.next_outcome["transfer"] = "STATUS_UNKNOWN"
    order, resp = buy(people, listing)
    assert resp.status_code == 202 and data(resp)["status"] == "RECONCILIATION_REQUIRED"
    assert data(resp)["transfer"]["ledger_transaction_id"].startswith("TEST-ONLY-")
    ledger.hide_status = False
    op_id = data(resp)["transfer"]["operation_id"]
    assert data(people["meera"].post(f"{P}/ledger/operations/{op_id}/reconcile"), 200)["status"] == "COMMITTED"
    assert ledger.submitted.count("transfer") == 1


def test_registration_command_matches_the_chaincode_contract(people, ledger):
    meera = people["meera"]
    prop = data(meera.post(f"{P}/properties", TECHPARK), 201)
    meera.post(f"{P}/properties/{prop['id']}/submit")
    seen = {}
    real_prepare = ledger.prepare

    def spy(kind, command):
        seen[kind] = command
        return real_prepare(kind, command)
    ledger.prepare = spy
    approved = data(meera.post(f"{P}/properties/{prop['id']}/approve", {}), 200)
    cmd = seen["registration"]
    assert list(cmd) == ["command_version", "operation_id", "property_id", "issuer_id", "approval_reference",
                         "approval_digest", "approved_supply", "issue_price_minor", "currency"]
    review = data(meera.get(f"{P}/properties/{prop['id']}"))["reviews"][0]
    assert cmd["property_id"] == prop["id"] and cmd["issuer_id"] == MEERA and cmd["approval_reference"] == review["id"]
    assert len(cmd["approval_digest"]) == 64 and cmd["issue_price_minor"] == "1000000" and cmd["approved_supply"] == 100000
    assert approved["ledger"]["approved_property_ref"] == prop["id"]


def test_prepared_but_never_submitted_is_closed_without_resubmitting(api, people, ledger):
    from sqlalchemy.orm import Session
    from app.db import models as m
    from app.db.enums import OperationStatus, OperationType
    with Session(api.app.state.engine) as db:
        op = m.LedgerOperation(operation_type=OperationType.ANSH_TRANSFER, entity_type="ansh_transfer", entity_id="x",
                               idempotency_key="k-crash", status=OperationStatus.VALIDATING, transaction_id="TEST-ONLY-crash",
                               artifact_json='{"transaction_id":"TEST-ONLY-crash"}')
        db.add(op)
        db.commit()
        op_id = op.id
    r = data(people["meera"].post(f"{P}/ledger/operations/{op_id}/reconcile"), 200)
    assert r["status"] == "FAILED" and r["error_code"] == "LEDGER_NOT_SUBMITTED" and r["ledger_transaction_id"] is None
    assert ledger.calls == []  # no gateway call at all


def test_issue_price_cannot_differ_from_registered_price(people, ledger):
    meera = people["meera"]
    prop = data(meera.post(f"{P}/properties", TECHPARK), 201)
    meera.post(f"{P}/properties/{prop['id']}/submit")
    meera.post(f"{P}/properties/{prop['id']}/approve", {})
    r = meera.post(f"{P}/ansh/issuances", {"property_id": prop["id"], "quantity": 10, "issue_price": "9000.00"})
    assert r.status_code == 422


def test_interest_quote_rounds_half_up_and_is_paid_first():
    from app.modules.financing import interest_quote
    assert interest_quote(120000000, 1000, 12) == 12000000           # Rs 12,00,000 at 10% for a year = Rs 1,20,000
    assert interest_quote(100, 1, 1) == 0 and interest_quote(600000, 1, 1) == 5  # 0.5 paisa rounds up
    assert interest_quote(100000, 0, 36) == 0



def test_demo_login_sessions(api, people):
    r = api.post("/api/v1/auth/login", json={"username": "Nobody", "password": "x"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "INVALID_CREDENTIALS"
    assert api.post("/api/v1/auth/login", json={"username": "aarav", "password": ""}).status_code == 422
    aarav = people["aarav"]
    assert data(aarav.get("/api/v1/auth/me"))["user"]["role"] == "INVESTOR"
    forged = api.get(f"{P}/properties", headers={"Authorization": "Bearer not-a-session"})
    assert forged.status_code == 401 and forged.json()["error"]["code"] == "INVALID_SESSION"
    assert api.get(f"{P}/properties", headers={"X-Demo-User-Id": AARAV}).status_code == 401  # old header ignored
    api.post("/api/v1/auth/logout", headers=aarav.auth)
    assert aarav.get("/api/v1/auth/me").status_code == 401


def test_demo_login_is_refused_in_production(tmp_path, ledger):
    from fastapi.testclient import TestClient
    from app.core.config import Settings
    from app.main import create_app
    app = create_app(Settings(database_url=f"sqlite:///{tmp_path / 'p.db'}", app_env="production"), ledger=ledger)
    with TestClient(app) as c:
        r = c.post("/api/v1/auth/login", json={"username": "aarav", "password": "x"})
        assert r.status_code == 503 and r.json()["error"]["code"] == "AUTH_NOT_CONFIGURED"



def test_lender_catalogue_and_offer_rules(people, ledger):
    _, iss, listing = setup_issued(people)
    buy(people, listing, qty=100)
    aarav = people["aarav"]
    lenders = data(aarav.get(f"{P}/financing/lenders"))["items"]
    by_name = {l["username"]: l for l in lenders}
    assert set(by_name) == {"axim-bank", "real-finance", "horizon-credit"}
    horizon = by_name["horizon-credit"]["offers"][0]
    assert horizon["max_ltv_percent"] == "70.00" and horizon["effective_max_ltv_percent"] == "60.00"  # platform cap
    pledge = data(aarav.post(f"{P}/collateral/pledges", {"issuance_id": iss["id"], "quantity": 100}), 201)
    base = {"pledge_id": pledge["id"], "principal": "500000.00", "lender_id": by_name["real-finance"]["id"]}
    r = aarav.post(f"{P}/loans/applications", {**base, "interest_rate_bps": 1000})
    assert r.status_code == 422 and r.json()["error"]["code"] == "INVALID_OFFER"  # Real Finance quotes 9%
    r = aarav.post(f"{P}/loans/applications", {**base, "principal": "550000.01"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "LTV_LIMIT_EXCEEDED"  # 55% offer limit
    loan = data(aarav.post(f"{P}/loans/applications", {**base, "term_months": 24}), 201)
    assert loan["interest_rate_percent"] == "9.00" and loan["term_months"] == 24 and loan["offer_id"] == "real-flex"
    assert loan["lender"]["name"] == "Real Finance"
    # Axim Bank cannot act on a Real Finance loan; Real Finance can.
    assert people["lender"].post(f"{P}/loans/{loan['id']}/assess", {}).status_code == 403
    from tests.conftest import Actor
    real = Actor(aarav.client, "real-finance")
    assert data(real.post(f"{P}/loans/{loan['id']}/assess", {}), 200)["status"] == "UNDER_REVIEW"


def test_demo_wallet_moves_cash_once(people):
    aarav = people["aarav"]
    assert data(aarav.get(f"{P}/wallet"))["balance"] == "0.00"
    w = data(aarav.post(f"{P}/wallet/fund", {"amount": "5000.00"}, idem="top-up-1"), 200)
    again = aarav.post(f"{P}/wallet/fund", {"amount": "5000.00"}, idem="top-up-1")
    assert w["balance"] == "5000.00" and again.json()["data"]["balance"] == "5000.00"  # replay, not a second credit
    r = aarav.post(f"{P}/wallet/withdraw", {"amount": "5000.01"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "INSUFFICIENT_DEMO_CASH"
    w = data(aarav.post(f"{P}/wallet/withdraw", {"amount": "2000.00"}), 200)
    assert w["balance"] == "3000.00" and [e["kind"] for e in w["entries"]] == ["WITHDRAWAL", "DEMO_FUNDS"]
    assert all(e["simulated"] for e in w["entries"])
    assert people["lender"].get(f"{P}/wallet").status_code == 403
