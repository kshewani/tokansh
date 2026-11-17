"""The database itself refuses rows that break a documented business rule.

Each test names the rule it protects. Service-layer checks come first in the
application; these constraints are the last line of defence.
"""
from datetime import date, datetime

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError, StatementError

from app.db import models as m
from tests.conftest import NOW, SUPPLY, UNIT


def rejected(db, *rows):
    db.add_all(rows)
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def position(w, **kw):
    base = dict(investor_id=w["aarav"].id, issuance_id=w["issuance"].id, owned_quantity=500,
                pledged_quantity=0, ledger_reference="tx-transfer", observed_at=NOW)
    return m.OwnershipPosition(**{**base, **kw})


def listing(w, **kw):
    base = dict(seller_id=w["meera"].id, issuance_id=w["issuance"].id, quantity=1000,
                remaining_quantity=1000, unit_price_minor=UNIT, listing_status="ACTIVE")
    return m.MarketplaceListing(**{**base, **kw})


def order(w, lst, **kw):
    base = dict(buyer_id=w["aarav"].id, seller_id=w["meera"].id, listing_id=lst.id,
                issuance_id=w["issuance"].id, quantity=500, unit_price_minor=UNIT,
                total_amount_minor=500 * UNIT, idempotency_key="order-1")
    return m.PurchaseOrder(**{**base, **kw})


def pledge(w, **kw):
    base = dict(investor_id=w["aarav"].id, issuance_id=w["issuance"].id, quantity=200,
                collateral_unit_value_minor=UNIT, collateral_value_minor=200 * UNIT)
    return m.CollateralPledge(**{**base, **kw})


def loan(w, pl, **kw):
    base = dict(borrower_id=w["aarav"].id, lender_id=w["lender"].id, pledge_id=pl.id,
                principal_minor=1_200_000 * 100, outstanding_minor=1_200_000 * 100,
                collateral_value_minor=200 * UNIT, ltv_bps=6000, max_ltv_bps=6000)
    return m.Loan(**{**base, **kw})


# ---- issuance (Rules 3.2, 3.4) ----

def test_issued_supply_cannot_exceed_approved_supply(db, world):
    world["issuance"].issued_quantity = SUPPLY + 1
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_issuance_cannot_be_confirmed_without_a_ledger_transaction(db, world):
    w = world
    rejected(db, m.AnshIssuance(property_id=w["property"].id, approved_property_ref="TP1", ansh_asset_id="A2",
                                issuer_id=w["meera"].id, approved_supply=10, requested_quantity=10,
                                issue_price_minor=UNIT, issuance_status="CONFIRMED"))


def test_supply_is_not_recognised_before_confirmation(db, world):
    w = world
    rejected(db, m.AnshIssuance(property_id=w["property"].id, approved_property_ref="TP1", ansh_asset_id="A3",
                                issuer_id=w["meera"].id, approved_supply=10, requested_quantity=10,
                                issued_quantity=10, issue_price_minor=UNIT, issuance_status="SUBMITTED"))


def test_property_ledger_reference_needs_registration_evidence(db, world):
    rejected(db, m.Property(property_name="P", property_type="OFFICE", address="a", city="c", country="India",
                            illustrative_valuation_minor=1, issuer_id=world["meera"].id,
                            approval_status="APPROVED", approved_property_ref="NO-TX"))


def test_unapproved_property_cannot_hold_a_ledger_reference(db, world):
    rejected(db, m.Property(property_name="P", property_type="OFFICE", address="a", city="c", country="India",
                            illustrative_valuation_minor=1, issuer_id=world["meera"].id,
                            approval_status="SUBMITTED", approved_property_ref="R2",
                            drunix_registration_transaction_id="tx-r2", ledger_registered_at=NOW))


def draft(w, **kw):
    base = dict(property_name="P", property_type="OFFICE", address="a", city="c", country="India",
                illustrative_valuation_minor=1, issuer_id=w["meera"].id)
    return m.Property(**{**base, **kw})


def test_draft_property_may_omit_its_proposal(db, world):
    db.add(draft(world)); db.flush(); db.rollback()


def test_property_cannot_be_submitted_without_supply_and_price(db, world):
    rejected(db, draft(world, approval_status="SUBMITTED"))
    rejected(db, draft(world, approval_status="SUBMITTED", proposed_supply=100))
    rejected(db, draft(world, approval_status="SUBMITTED", proposed_issue_price_minor=UNIT))


def test_proposed_supply_and_price_must_be_positive(db, world):
    rejected(db, draft(world, proposed_supply=0))
    rejected(db, draft(world, proposed_issue_price_minor=-1))


# ---- ownership (Rules 4.2, 4.3) ----

def test_available_is_owned_minus_pledged(db, world):
    p = position(world, pledged_quantity=200)
    db.add(p); db.commit()
    assert p.available_quantity == 300
    q = db.execute(sa.select(m.OwnershipPosition.available_quantity)).scalar_one()
    assert q == 300


def test_pledged_cannot_exceed_owned(db, world):
    rejected(db, position(world, pledged_quantity=501))


def test_quantities_cannot_be_negative(db, world):
    rejected(db, position(world, owned_quantity=-1))


def test_one_position_per_investor_and_issuance(db, world):
    db.add(position(world)); db.commit()
    rejected(db, position(world))


def test_position_must_say_which_ledger_observation_it_came_from(db, world):
    rejected(db, position(world, ledger_reference=None))


# ---- marketplace and settlement (Rules 5.3, 5.5, 6.x) ----

def test_order_total_must_equal_quantity_times_price(db, world):
    lst = listing(world); db.add(lst); db.flush()
    rejected(db, order(world, lst, total_amount_minor=500 * UNIT - 1))


def test_duplicate_idempotency_key_cannot_create_a_second_order(db, world):
    lst = listing(world); db.add(lst); db.flush()
    db.add(order(world, lst)); db.commit()
    rejected(db, order(world, lst))


def test_order_cannot_complete_without_a_ledger_transfer(db, world):
    lst = listing(world); db.add(lst); db.flush()
    rejected(db, order(world, lst, order_status="COMPLETED"))


def test_listing_cannot_be_oversold(db, world):
    rejected(db, listing(world, remaining_quantity=1001))
    rejected(db, listing(world, remaining_quantity=-1))


def test_payments_are_always_flagged_simulated(db, world):
    lst = listing(world); db.add(lst); db.flush()
    o = order(world, lst); db.add(o); db.flush()
    rejected(db, m.PaymentRecord(order_id=o.id, payment_reference="PAY-1", amount_minor=500 * UNIT,
                                 simulation_flag=False))


def test_refund_must_reference_the_original_payment(db, world):
    lst = listing(world); db.add(lst); db.flush()
    o = order(world, lst); db.add(o); db.flush()
    rejected(db, m.PaymentRecord(order_id=o.id, payment_reference="REF-1", amount_minor=1, payment_kind="REFUND"))


# ---- ledger evidence (ADR-011, AGENTS.md section 9) ----

def test_operation_cannot_be_committed_without_a_transaction_id(db):
    rejected(db, m.LedgerOperation(operation_type="ANSH_TRANSFER", entity_type="order", entity_id="o",
                                   idempotency_key="k1", status="COMMITTED", confirmed_at=NOW))


def test_unknown_outcome_cannot_carry_a_confirmation_time(db):
    rejected(db, m.LedgerOperation(operation_type="ANSH_TRANSFER", entity_type="order", entity_id="o",
                                   idempotency_key="k2", transaction_id="tx-9", status="UNKNOWN",
                                   confirmed_at=NOW))


def test_same_ledger_transaction_cannot_be_recorded_twice(db, world):
    rejected(db, m.LedgerOperation(operation_type="ANSH_TRANSFER", entity_type="order", entity_id="o",
                                   idempotency_key="k3", transaction_id="tx-issue", status="SUBMITTED"))


def test_duplicate_event_delivery_is_ignored_by_uniqueness(db):
    ev = dict(transaction_id="tx-1", event_name="TransferSettled", block_number=7, chaincode="tokansh",
              payload_json="{}")
    db.add(m.LedgerEvent(**ev)); db.commit()
    rejected(db, m.LedgerEvent(**ev))


def test_application_event_cannot_claim_to_be_a_ledger_event(db, world):
    pid = world["property"].id
    rejected(db, m.AssetEvent(property_id=pid, event_type="TRANSFER", event_description="x",
                              event_source="DRUNIX_LEDGER", occurred_at=NOW))
    rejected(db, m.AssetEvent(property_id=pid, event_type="APPROVED", event_description="x",
                              event_source="APPLICATION", ledger_transaction_id="tx-fake", occurred_at=NOW))
    rejected(db, m.AssetEvent(property_id=pid, event_type="PAYMENT", event_description="x",
                              event_source="PAYMENT_SIMULATOR", is_simulated=False, occurred_at=NOW))
    rejected(db, m.AssetEvent(property_id=pid, event_type="TRANSFER", event_description="x",
                              event_source="DRUNIX_LEDGER", ledger_transaction_id="tx-1", is_simulated=True,
                              occurred_at=NOW))


def test_reconciliation_case_cannot_be_resolved_silently(db, world):
    rejected(db, m.ReconciliationCase(ledger_operation_id=world["op"].id, reason="timeout", status="RESOLVED"))


# ---- collateral and loans (Rules 8.x, 9.x) ----

def test_collateral_value_is_quantity_times_unit_value(db, world):
    rejected(db, pledge(world, collateral_value_minor=200 * UNIT + 1))


def test_pledge_cannot_be_active_without_a_ledger_pledge(db, world):
    rejected(db, pledge(world, pledge_status="ACTIVE"))


def test_pledge_cannot_be_released_without_a_ledger_release(db, world):
    rejected(db, pledge(world, pledge_status="RELEASED", pledge_operation_id=world["op"].id))


def test_loan_balance_cannot_go_negative_or_above_principal(db, world):
    pl = pledge(world); db.add(pl); db.flush()
    rejected(db, loan(world, pl, outstanding_minor=-1))
    pl = pledge(world); db.add(pl); db.flush()
    rejected(db, loan(world, pl, outstanding_minor=1_200_000 * 100 + 1))


def test_repaid_loan_must_have_zero_balance(db, world):
    pl = pledge(world); db.add(pl); db.flush()
    rejected(db, loan(world, pl, loan_status="REPAID"))


def test_one_loan_per_pledge(db, world):
    pl = pledge(world); db.add(pl); db.flush()
    db.add(loan(world, pl)); db.commit()
    rejected(db, loan(world, pl))


# ---- distributions (Rules 10.x) ----

def snapshot(db, w, verified=True):
    s = m.OwnershipSnapshot(issuance_id=w["issuance"].id, record_date=date(2026, 11, 20),
                            method="EVENT_RECONSTRUCTION", ledger_reference="tx-transfer",
                            total_eligible_quantity=SUPPLY, is_verified=verified)
    db.add(s); db.flush()
    return s


def distribution(w, **kw):
    base = dict(property_id=w["property"].id, issuance_id=w["issuance"].id, declared_by=w["meera"].id,
                period_label="2026-Q3 rent", total_amount_minor=1_000_000 * 100,
                record_date=date(2026, 11, 20), distribution_date=date(2026, 11, 21))
    return m.Distribution(**{**base, **kw})


def test_distribution_cannot_be_processed_without_a_record_date_snapshot(db, world):
    rejected(db, distribution(world, distribution_status="PROCESSING"))


def test_distribution_cannot_be_declared_twice(db, world):
    db.add(distribution(world)); db.commit()
    rejected(db, distribution(world))


def test_distribution_cannot_pay_before_its_record_date(db, world):
    rejected(db, distribution(world, distribution_date=date(2026, 11, 19)))


def test_one_entitlement_per_investor_per_distribution(db, world):
    s = snapshot(db, world)
    d = distribution(world, snapshot_id=s.id); db.add(d); db.flush()
    ent = dict(distribution_id=d.id, investor_id=world["aarav"].id, snapshot_id=s.id, eligible_quantity=500,
               total_eligible_quantity=SUPPLY, entitlement_amount_minor=5_000 * 100)
    db.add(m.DistributionEntitlement(**ent)); db.commit()
    rejected(db, m.DistributionEntitlement(**ent))


def test_documented_entitlement_example_reconciles(db, world):
    """Rule 10.3: 500 / 100,000 x INR 10,00,000 = INR 5,000, and the rows sum to the declared total."""
    s = snapshot(db, world)
    d = distribution(world, snapshot_id=s.id); db.add(d); db.flush()
    holders = {world["aarav"].id: 500, world["meera"].id: SUPPLY - 500}
    for investor, units in holders.items():
        db.add(m.DistributionEntitlement(distribution_id=d.id, investor_id=investor, snapshot_id=s.id,
                                         eligible_quantity=units, total_eligible_quantity=SUPPLY,
                                         entitlement_amount_minor=d.total_amount_minor * units // SUPPLY))
    db.commit()
    rows = db.execute(sa.select(m.DistributionEntitlement)).scalars().all()
    aarav = next(r for r in rows if r.investor_id == world["aarav"].id)
    assert aarav.entitlement_amount_minor == 5_000 * 100
    assert sum(r.entitlement_amount_minor for r in rows) == d.total_amount_minor


def test_entitlement_cannot_be_paid_without_a_reference(db, world):
    s = snapshot(db, world)
    d = distribution(world, snapshot_id=s.id); db.add(d); db.flush()
    rejected(db, m.DistributionEntitlement(distribution_id=d.id, investor_id=world["aarav"].id, snapshot_id=s.id,
                                           eligible_quantity=500, total_eligible_quantity=SUPPLY,
                                           entitlement_amount_minor=1, entitlement_status="PAID"))


def test_only_one_snapshot_per_issuance_and_record_date(db, world):
    snapshot(db, world); db.commit()
    with pytest.raises(IntegrityError):
        snapshot(db, world)
    db.rollback()


# ---- general ----

def test_unknown_enum_value_is_rejected(db, world):
    with pytest.raises((StatementError, IntegrityError)):
        db.add(position(world, reconciliation_status="MADE_UP")); db.flush()
    db.rollback()
    with pytest.raises(IntegrityError):  # and the CHECK holds even for raw SQL
        db.execute(sa.text("UPDATE users SET role = 'ROOT'")); db.flush()
    db.rollback()


def test_naive_timestamps_are_refused(db, world):
    with pytest.raises(StatementError):
        db.add(position(world, observed_at=datetime(2026, 11, 17, 6, 0))); db.flush()
    db.rollback()


def test_timestamps_come_back_as_utc(db, world):
    db.add(position(world)); db.commit(); db.expire_all()
    got = db.execute(sa.select(m.OwnershipPosition.observed_at)).scalar_one()
    assert got == NOW and got.utcoffset().total_seconds() == 0


def test_rows_cannot_reference_missing_parents(db, world):
    rejected(db, position(world, investor_id="00000000-0000-0000-0000-000000000000"))


def test_parent_rows_cannot_be_deleted_from_under_children(db, world):
    db.add(position(world)); db.commit()
    with pytest.raises(IntegrityError):
        db.execute(sa.delete(m.User).where(m.User.id == world["aarav"].id)); db.flush()
    db.rollback()


def test_failed_workflow_rolls_back_completely(db, world):
    """TEST_STRATEGY section 12: a failed ledger operation leaves no false ownership update."""
    db.add(position(world))
    db.add(m.LedgerOperation(operation_type="ANSH_TRANSFER", entity_type="order", entity_id="o",
                             idempotency_key="k9", status="COMMITTED"))  # invalid: no tx id
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
    assert db.execute(sa.select(sa.func.count()).select_from(m.OwnershipPosition)).scalar_one() == 0
