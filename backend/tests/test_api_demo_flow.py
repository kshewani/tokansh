"""The AGENTS.md section 8 demonstration, end to end through the HTTP API.

Uses the TEST-ONLY fake ledger. This proves application behaviour and business
rules; it is NOT evidence of DRUNIX integration (API_CONTRACTS section 13).
"""
from datetime import date

from scripts.seed_demo import sid

P = "/api/v1"
AARAV, MEERA = sid("user:aarav"), sid("user:meera")
TECHPARK = {"name": "TechPark One", "property_type": "COMMERCIAL_OFFICE", "address": "Demo Address, Whitefield",
            "city": "Bengaluru", "country": "India", "valuation": "1000000000.00", "proposed_supply": 100000,
            "issue_price": "10000.00", "currency": "INR"}


def data(resp, status=None):
    if status is not None:
        assert resp.status_code == status, resp.json()
    return resp.json()["data"]


def setup_issued(people):
    """Steps 1-3: onboard, approve (+ register on ledger), issue 100,000 ANSH."""
    meera = people["meera"]
    prop = data(meera.post(f"{P}/properties", TECHPARK), 201)
    assert prop["approval_status"] == "DRAFT" and prop["ledger"]["registered"] is False
    data(meera.post(f"{P}/properties/{prop['id']}/submit"), 200)
    approved = data(meera.post(f"{P}/properties/{prop['id']}/approve", {"notes": "Synthetic evidence reviewed"}), 200)
    assert approved["approval_status"] == "APPROVED" and approved["approved_supply"] == 100000
    assert approved["ledger"]["registered"] is True
    assert approved["ledger"]["registration_transaction_id"].startswith("TEST-ONLY-")
    iss = data(meera.post(f"{P}/ansh/issuances", {"property_id": prop["id"], "quantity": 100000}), 201)
    assert iss["status"] == "CONFIRMED" and iss["issued_quantity"] == 100000
    listing = data(meera.post(f"{P}/marketplace/listings", {"issuance_id": iss["id"], "quantity": 100000}), 201)
    return prop, iss, listing


def buy(people, listing, qty=500, outcome="SUCCESS"):
    aarav = people["aarav"]
    order = data(aarav.post(f"{P}/marketplace/orders", {"listing_id": listing["id"], "quantity": qty}), 201)
    assert order["status"] == "PAYMENT_PENDING" and order["total_amount"] == f"{qty * 10000}.00"
    return order, aarav.post(f"{P}/payments/simulate", {"order_id": order["id"], "simulated_outcome": outcome})


def holding(people, who="aarav"):
    pf = data(people[who].get(f"{P}/portfolios/{sid('user:' + who)}"), 200)
    return pf["ansh"][0] if pf["ansh"] else None


def test_full_demo_scenario(people, ledger):
    meera, aarav, lender = people["meera"], people["aarav"], people["lender"]
    prop, iss, listing = setup_issued(people)
    asset = prop["id"]  # DRUNIX keys holdings by property UUID and holder UUID
    assert ledger.balance(asset, MEERA) == (100000, 0)

    # 4-5. Aarav buys 500 ANSH; payment succeeds; transfer commits.
    order, paid = buy(people, listing)
    done = data(paid, 200)
    assert done["status"] == "COMPLETED"
    assert done["payments"][0]["status"] == "SUCCESS" and done["payments"][0]["simulated"] is True
    assert done["transfer"]["status"] == "COMMITTED" and done["transfer"]["ledger_transaction_id"].startswith("TEST-ONLY-")
    assert ledger.balance(asset, AARAV) == (500, 0)

    # 6. Portfolio.
    h = holding(people)
    assert (h["owned_units"], h["pledged_units"], h["available_units"]) == (500, 0, 500)
    assert h["acquisition_cost"] == "5000000.00" and h["source"] == "DRUNIX_PROJECTION"
    lst = data(meera.get(f"{P}/marketplace/listings/{listing['id']}"))
    assert lst["remaining_quantity"] == 99500 and lst["status"] == "PARTIALLY_FILLED"
    verified = data(aarav.get(f"{P}/portfolios/{AARAV}", verify="true"))["ansh"][0]["ledger_verification"]
    assert verified["status"] == "VERIFIED"

    # 7. Pledge 200 ANSH; simulated loan of INR 12 lakh at 60% LTV.
    pledge = data(aarav.post(f"{P}/collateral/pledges", {"issuance_id": iss["id"], "quantity": 200}), 201)
    assert pledge["status"] == "ACTIVE" and pledge["collateral_value"] == "2000000.00"
    h = holding(people)
    assert (h["owned_units"], h["pledged_units"], h["available_units"]) == (500, 200, 300)
    loan = data(aarav.post(f"{P}/loans/applications", {"pledge_id": pledge["id"], "principal": "1200000.00"}), 201)
    assert loan["ltv_percent"] == "60.00" and loan["status"] == "REQUESTED" and loan["simulated"] is True
    assert loan["interest_quote"] == "120000.00" and loan["total_due"] == "1320000.00"  # 10% for 12 months
    data(lender.post(f"{P}/loans/{loan['id']}/assess", {}), 200)
    data(lender.post(f"{P}/loans/{loan['id']}/approve", {}), 200)
    assert data(lender.post(f"{P}/loans/{loan['id']}/disburse"), 200)["status"] == "ACTIVE"

    # 8. Transferring 350 ANSH (includes pledged units) is rejected; nothing reaches the ledger.
    calls = len(ledger.submitted)
    r = aarav.post(f"{P}/ansh/transfers", {"issuance_id": iss["id"], "to_user_id": MEERA, "quantity": 350})
    assert r.status_code == 409 and r.json()["error"]["code"] == "PLEDGED_UNITS_RESTRICTED"
    assert r.json()["error"]["details"]["available_quantity"] == 300
    assert len(ledger.submitted) == calls and ledger.balance(asset, AARAV) == (500, 200)
    # Release before repayment is refused.
    r = aarav.post(f"{P}/collateral/pledges/{pledge['id']}/release")
    assert r.status_code == 409

    # 9. Rental distribution from record-date holdings (pledged units stay eligible, Rule 10.4).
    today = date.today().isoformat()
    dist = data(meera.post(f"{P}/distributions", {"issuance_id": iss["id"], "period_label": "November 2026 rent",
                                                 "total_amount": "1000000.00", "record_date": today,
                                                 "distribution_date": today}), 201)
    dist = data(meera.post(f"{P}/distributions/{dist['id']}/calculate"), 200)
    assert dist["snapshot"]["method"] == "EVENT_RECONSTRUCTION" and dist["snapshot"]["is_verified"] is True
    assert dist["entitlements_total"] == "1000000.00"
    mine = data(aarav.get(f"{P}/distributions/{dist['id']}/entitlements"))["items"]
    assert len(mine) == 1 and mine[0]["amount"] == "5000.00" and mine[0]["eligible_quantity"] == 500
    paid = data(meera.post(f"{P}/distributions/{dist['id']}/simulate-payment"), 200)
    assert paid["status"] == "COMPLETED"

    # 10. Repay in two parts, then release the pledge.
    assert data(aarav.post(f"{P}/loans/{loan['id']}/repayments", {"amount": "200000.00"}), 200)["status"] == "PARTIALLY_REPAID"
    r = aarav.post(f"{P}/loans/{loan['id']}/repayments", {"amount": "1120000.01"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "REPAYMENT_EXCEEDS_OUTSTANDING"
    repaid = data(aarav.post(f"{P}/loans/{loan['id']}/repayments", {"amount": "1120000.00"}), 200)
    assert repaid["status"] == "REPAID" and repaid["outstanding"] == "0.00" and repaid["total_outstanding"] == "0.00"
    released = data(aarav.post(f"{P}/collateral/pledges/{pledge['id']}/release"), 200)
    assert released["status"] == "RELEASED" and released["release_operation"]["status"] == "COMMITTED"

    # 11. Portfolio and audit history reflect the final state.
    h = holding(people)
    assert (h["owned_units"], h["pledged_units"], h["available_units"]) == (500, 0, 500)
    assert ledger.balance(asset, AARAV) == (500, 0)
    events = data(meera.get(f"{P}/assets/{prop['id']}/history"))["items"]
    types = {e["event_type"] for e in events}
    assert {"PROPERTY_ONBOARDED", "PROPERTY_APPROVED", "PROPERTY_REGISTERED", "ANSH_ISSUED", "ANSH_TRANSFERRED",
            "ANSH_PLEDGED", "ANSH_PLEDGE_RELEASED", "DISTRIBUTION_DECLARED", "DISTRIBUTION_PAID"} <= types
    for e in events:
        if e["source"] == "DRUNIX_LEDGER":
            assert e["ledger_transaction_id"] and e["simulated"] is False
    audit = data(meera.get(f"{P}/audit/events", page_size=100))
    assert any(a["source"] == "PAYMENT_SIMULATOR" and a["simulated"] for a in audit["items"])
    assert any(a["operation_type"] == "ANSH_TRANSFER_REJECTED" for a in audit["items"])
    # Now the 350 transfer is allowed.
    ok = aarav.post(f"{P}/ansh/transfers", {"issuance_id": iss["id"], "to_user_id": MEERA, "quantity": 350})
    assert ok.status_code == 201 and data(ok)["status"] == "COMMITTED"
    assert holding(people)["owned_units"] == 150
