"""Failure paths and critical invariants through the API (BUSINESS_RULES section 15).

Uses the TEST-ONLY fake ledger; not evidence of DRUNIX integration.
"""
from datetime import date, timedelta

from app.modules.distributions import allocate
from tests.test_api_demo_flow import AARAV, MEERA, P, TECHPARK, buy, data, holding, setup_issued


def transfers_sent(ledger):
    return [c for c in ledger.calls if c[0] == "TransferANSH"]


def test_failed_payment_never_transfers(people, ledger):
    _, iss, listing = setup_issued(people)
    order, resp = buy(people, listing, outcome="FAILED")
    assert resp.status_code == 409 and resp.json()["error"]["code"] == "PAYMENT_FAILED"
    o = data(people["aarav"].get(f"{P}/marketplace/orders/{order['id']}"))
    assert o["status"] == "PAYMENT_FAILED" and o["payments"][0]["status"] == "FAILED" and o["transfer"] is None
    assert transfers_sent(ledger) == [] and holding(people) is None
    assert ledger.balance(iss["ansh_asset_id"], "aarav") == (0, 0)


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
    ledger.next_outcome["IssueANSH"] = "UNAVAILABLE"
    r = meera.post(f"{P}/ansh/issuances", {"property_id": prop["id"], "quantity": 100000})
    assert r.status_code == 503
    iss = data(meera.get(f"{P}/ansh/issuances"))["items"][0]
    assert iss["status"] == "FAILED" and iss["issued_quantity"] == 0
    assert data(meera.get(f"{P}/portfolios/{MEERA}"))["ansh"] == []
    retry = data(meera.post(f"{P}/ansh/issuances", {"property_id": prop["id"], "quantity": 100000}), 201)
    assert retry["status"] == "CONFIRMED" and retry["id"] == iss["id"]


def test_unknown_outcome_is_reconciled_not_resubmitted(people, ledger):
    _, iss, listing = setup_issued(people)
    ledger.next_outcome["TransferANSH"] = "UNKNOWN"
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
    ledger.next_outcome["TransferANSH"] = "COMMIT_FAILED"
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
    r = aarav.client.post(f"{P}/marketplace/orders", json=body, headers={"X-Demo-User-Id": AARAV})
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
