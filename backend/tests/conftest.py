import os
import sys
from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import Session

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db import Base, models as m  # noqa: E402
from app.db.enums import UserRole  # noqa: E402
from app.db.session import make_engine  # noqa: E402

NOW = datetime(2026, 11, 17, 6, 0, tzinfo=timezone.utc)
SUPPLY = 100_000
UNIT = 10_000 * 100  # INR 10,000 in paise


@pytest.fixture()
def engine(tmp_path):
    eng = make_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture()
def db(engine):
    with Session(engine) as session:
        yield session


@pytest.fixture()
def world(db):
    """Users, an approved+registered property and a confirmed issuance (as after real commits)."""
    meera = m.User(full_name="Meera", email="meera@x.example", role=UserRole.ISSUER)
    aarav = m.User(full_name="Aarav", email="aarav@x.example", role=UserRole.INVESTOR)
    lender = m.User(full_name="Lender", email="lender@x.example", role=UserRole.LENDER)
    db.add_all([meera, aarav, lender]); db.flush()
    prop = m.Property(property_name="TechPark One", property_type="OFFICE", address="a", city="Bengaluru",
                      country="India", illustrative_valuation_minor=SUPPLY * UNIT, issuer_id=meera.id,
                      proposed_supply=SUPPLY, proposed_issue_price_minor=UNIT,
                      approval_status="APPROVED", approved_supply=SUPPLY, approved_property_ref="TP1",
                      drunix_registration_transaction_id="tx-reg", ledger_registered_at=NOW)
    db.add(prop); db.flush()
    op = m.LedgerOperation(operation_type="ANSH_ISSUANCE", entity_type="issuance", entity_id="x",
                           idempotency_key="op-issue", transaction_id="tx-issue", status="COMMITTED",
                           confirmed_at=NOW)
    db.add(op); db.flush()
    iss = m.AnshIssuance(property_id=prop.id, approved_property_ref="TP1", ansh_asset_id="ANSH-TP1",
                         issuer_id=meera.id, approved_supply=SUPPLY, requested_quantity=SUPPLY,
                         issued_quantity=SUPPLY, issue_price_minor=UNIT, issuance_status="CONFIRMED",
                         ledger_operation_id=op.id, ledger_transaction_id="tx-issue", confirmed_at=NOW)
    db.add(iss); db.commit()
    return {"meera": meera, "aarav": aarav, "lender": lender, "property": prop, "issuance": iss, "op": op}
