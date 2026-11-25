import sqlalchemy as sa

from app.db import models as m
from scripts.seed_demo import TECHPARK_SUPPLY, TECHPARK_UNIT_VALUE, TECHPARK_VALUATION, seed

LEDGER_BACKED = [m.AnshIssuance, m.OwnershipPosition, m.CollateralPledge, m.MarketplaceListing,
                 m.LedgerOperation, m.LedgerEvent, m.OwnershipSnapshot]


def count(db, model):
    return db.execute(sa.select(sa.func.count()).select_from(model)).scalar_one()


def test_seed_is_idempotent(db):
    first = seed(db, with_property=True)
    second = seed(db, with_property=True)
    assert first == {"users": 6, "reit_holdings": 2, "properties": 1}
    assert second == {"users": 0, "reit_holdings": 0, "properties": 0}
    assert count(db, m.User) == 6 and count(db, m.PropertyDocument) == 3 and count(db, m.PropertyValuation) == 2


def test_seed_never_fabricates_ledger_backed_state(db):
    seed(db, with_property=True)
    for model in LEDGER_BACKED:
        assert count(db, model) == 0, model.__tablename__
    prop = db.execute(sa.select(m.Property)).scalar_one()
    assert prop.approval_status == "DRAFT" and prop.approved_property_ref is None
    assert prop.city == "Bengaluru"  # matches the UI's TechPark One (frontend/src/demo/scenario.ts)
    assert (prop.proposed_supply, prop.proposed_issue_price_minor) == (TECHPARK_SUPPLY, TECHPARK_UNIT_VALUE)


def test_seed_figures_match_the_documented_demo(db):
    assert TECHPARK_VALUATION == TECHPARK_SUPPLY * TECHPARK_UNIT_VALUE  # INR 100 crore = 100,000 x INR 10,000
    seed(db)
    assert all(r.is_simulated for r in db.execute(sa.select(m.ReitHolding)).scalars())
    assert count(db, m.Property) == 0
