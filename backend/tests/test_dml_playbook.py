"""Executes sql/dml_playbook.sql end to end, so the documented DML always matches the schema."""
import uuid

import sqlalchemy as sa
from alembic import command

from app.db.session import make_engine
from scripts import playbook
from scripts.seed_demo import seed, sid
from sqlalchemy.orm import Session
from tests.test_schema import _alembic

TX = {"tx_register": "T-REG", "tx_issue": "T-ISSUE", "tx_transfer": "T-XFER", "tx_unknown": "T-UNK",
      "tx_pledge": "T-PLEDGE", "tx_release": "T-REL"}  # stand-ins for ids DRUNIX would return
BLOCKS = {"block_register": 5, "block_issue": 6, "block_transfer": 7, "block_pledge": 8, "block_release": 9}
FIXED = {"record_date": "2026-11-20", "distribution_date": "2026-11-21", "request_hash": "a" * 64,
         "reject_detail": '{"code": "PLEDGED_UNITS_RESTRICTED", "requested_quantity": 350, "available_quantity": 300}'}


def run_playbook(tmp_path):
    url = f"sqlite:///{tmp_path / 'playbook.db'}"
    command.upgrade(_alembic(url), "head")  # the migrated schema, exactly as deployed
    engine = make_engine(url)
    with Session(engine) as s:
        seed(s)
    values = {**TX, **BLOCKS, **FIXED, **{k: sid(f"user:{k}") for k in ("meera", "aarav", "lender", "admin")}}
    results = {}
    steps = playbook.load()
    with engine.begin() as conn:
        for stmt in playbook.statements(steps):
            needed = playbook.params(stmt)
            for name in needed - values.keys():
                values[name] = str(uuid.uuid4())
            res = conn.execute(sa.text(stmt), {k: values[k] for k in needed})
            if stmt.lstrip().upper().startswith("SELECT"):
                results[stmt] = res.mappings().all()
            else:
                assert res.rowcount >= 1, f"statement changed no rows:\n{stmt}"
    return engine, values, results, steps


def test_playbook_runs_and_reaches_the_documented_final_state(tmp_path):
    engine, v, results, steps = run_playbook(tmp_path)
    assert len(steps) == 13 and len(playbook.statements(steps)) > 80
    one = lambda q, **p: engine.connect().execute(sa.text(q), p).mappings().one()

    aarav = one("SELECT * FROM ownership_positions WHERE investor_id=:i", i=v["aarav"])
    assert (aarav["owned_quantity"], aarav["pledged_quantity"]) == (500, 0)  # BUSINESS_RULES section 14
    assert aarav["ledger_reference"] == TX["tx_release"] and aarav["reconciliation_status"] == "ACTIVE"
    meera = one("SELECT owned_quantity FROM ownership_positions WHERE investor_id=:i", i=v["meera"])
    assert meera["owned_quantity"] == 99_500

    assert one("SELECT order_status FROM purchase_orders WHERE id=:i", i=v["order_id"])["order_status"] == "COMPLETED"
    assert one("SELECT order_status FROM purchase_orders WHERE id=:i", i=v["order_failed_id"])["order_status"] == "PAYMENT_FAILED"
    assert one("SELECT order_status FROM purchase_orders WHERE id=:i", i=v["order_unknown_id"])["order_status"] == "FAILED"
    assert one("SELECT remaining_quantity FROM marketplace_listings")["remaining_quantity"] == 99_500

    loan = one("SELECT loan_status, outstanding_minor FROM loans")
    assert (loan["loan_status"], loan["outstanding_minor"]) == ("REPAID", 0)
    assert one("SELECT pledge_status FROM collateral_pledges")["pledge_status"] == "RELEASED"
    ent = one("SELECT entitlement_amount_minor, entitlement_status FROM distribution_entitlements WHERE investor_id=:i", i=v["aarav"])
    assert (ent["entitlement_amount_minor"], ent["entitlement_status"]) == (5_000 * 100, "PAID")

    ops = engine.connect().execute(sa.text("SELECT status, COUNT(*) AS n FROM ledger_operations GROUP BY status")).mappings().all()
    assert {r["status"]: r["n"] for r in ops} == {"COMMITTED": 5, "FAILED": 1}
    assert one("SELECT COUNT(*) AS n FROM reconciliation_cases WHERE status='OPEN'")["n"] == 0


def test_playbook_read_queries_reconcile(tmp_path):
    _, _, results, _ = run_playbook(tmp_path)
    by = lambda needle: next(rows for sql, rows in results.items() if needle in sql)
    supply = by("total_owned")[0]
    assert supply["issued_quantity"] == supply["total_owned"] == 100_000          # Rule 4.3
    dist = by("total_entitled")[0]
    assert dist["total_amount_minor"] == dist["total_entitled"] == 1_000_000 * 100  # Rule 10.5
    portfolio = by("available_quantity")[0]
    assert (portfolio["property_name"], portfolio["available_quantity"]) == ("TechPark One", 500)
    assert len(by("FROM reit_holdings")) == 2
    assert {r["event_source"] for r in by("FROM asset_events")} == {"DRUNIX_LEDGER"}
    assert by("'UNKNOWN', 'RECONCILIATION_REQUIRED'") == []
