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


# ---------------------------------------------------------------- API fixtures

from fastapi.testclient import TestClient  # noqa: E402

from app.core.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402
from scripts.seed_demo import seed, sid  # noqa: E402
from tests.fakes.fake_ledger import FakeLedger  # noqa: E402


@pytest.fixture()
def ledger():
    """TEST-ONLY fake ledger. Never used by the running application."""
    return FakeLedger()


@pytest.fixture()
def api(tmp_path, ledger):
    url = f"sqlite:///{tmp_path / 'api.db'}"
    eng = make_engine(url)
    Base.metadata.create_all(eng)
    with Session(eng) as s:
        seed(s)
    eng.dispose()
    settings = Settings(database_url=url, drunix_gateway_url="http://test-only.invalid",
                        commit_poll_attempts=2, commit_poll_interval_seconds=0)
    app = create_app(settings, ledger=ledger)
    with TestClient(app) as client:
        yield client
    app.state.engine.dispose()


class Actor:
    """Calls the API as one demonstration user, with a fresh Idempotency-Key per call."""

    def __init__(self, client, key):
        self.client, self.id = client, sid(f"user:{key}")
        self._n = 0

    def _h(self, idem=None):
        self._n += 1
        return {"X-Demo-User-Id": self.id, "Idempotency-Key": idem or f"{self.id}-{self._n}"}

    def get(self, path, **params):
        return self.client.get(path, headers=self._h(), params=params)

    def post(self, path, json=None, idem=None):
        return self.client.post(path, json=json or {}, headers=self._h(idem))


@pytest.fixture()
def people(api):
    return {k: Actor(api, k) for k in ("meera", "admin", "aarav", "lender")}
