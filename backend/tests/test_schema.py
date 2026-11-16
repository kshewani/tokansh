"""Structural guarantees of the application schema."""
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from pathlib import Path

from app.db import Base
from app.db.session import make_engine

BACKEND = Path(__file__).resolve().parent.parent

EXPECTED_TABLES = {  # ARCHITECTURE section 13 plus the documented additions
    "users", "properties", "property_documents", "property_reviews", "property_valuations",
    "ansh_issuances", "ownership_positions", "marketplace_listings", "purchase_orders", "payment_records",
    "ledger_operations", "ledger_events", "ledger_event_cursors", "reconciliation_cases",
    "idempotency_records", "collateral_pledges", "loans", "credit_assessments", "loan_repayments",
    "ownership_snapshots", "ownership_snapshot_lines", "distributions", "distribution_entitlements",
    "reit_holdings", "asset_events", "audit_events",
}


def _alembic(url: str) -> Config:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def _shape(engine):
    insp = sa.inspect(engine)
    out = {}
    for t in insp.get_table_names():
        if t == "alembic_version":
            continue
        out[t] = {
            "columns": {c["name"]: (str(c["type"]), c["nullable"]) for c in insp.get_columns(t)},
            "checks": sorted(c["name"] for c in insp.get_check_constraints(t)),
            "uniques": sorted(tuple(u["column_names"]) for u in insp.get_unique_constraints(t)),
            "fks": sorted((tuple(f["constrained_columns"]), f["referred_table"]) for f in insp.get_foreign_keys(t)),
            "indexes": sorted(i["name"] for i in insp.get_indexes(t)),
        }
    return out


def test_all_expected_tables_exist():
    assert set(Base.metadata.tables) == EXPECTED_TABLES


def test_migration_builds_exactly_the_model_schema(tmp_path):
    migrated = make_engine(f"sqlite:///{tmp_path / 'migrated.db'}")
    command.upgrade(_alembic(str(migrated.url)), "head")
    direct = make_engine(f"sqlite:///{tmp_path / 'direct.db'}")
    Base.metadata.create_all(direct)
    assert _shape(migrated) == _shape(direct)


def test_migration_downgrades_cleanly(tmp_path):
    url = f"sqlite:///{tmp_path / 'down.db'}"
    command.upgrade(_alembic(url), "head")
    command.downgrade(_alembic(url), "base")
    assert sa.inspect(make_engine(url)).get_table_names() == ["alembic_version"]


def test_no_binary_floating_point_or_numeric_columns():
    """ADR-015: money is integer minor units; SQLite would store NUMERIC as a float."""
    bad = [f"{t.name}.{c.name}" for t in Base.metadata.tables.values() for c in t.columns
           if isinstance(c.type, (sa.Float, sa.Numeric))]
    assert bad == []


def test_money_columns_are_integers_with_a_currency():
    for t in Base.metadata.tables.values():
        money_cols = [c for c in t.columns if c.name.endswith("_minor")]
        for c in money_cols:
            assert isinstance(c.type, sa.BigInteger), f"{t.name}.{c.name}"
        if money_cols:
            assert any("currency" in c.name for c in t.columns), f"{t.name} has money but no currency"


def test_every_table_has_a_uuid_primary_key():
    for t in Base.metadata.tables.values():
        pk = list(t.primary_key.columns)
        assert len(pk) == 1 and pk[0].name == "id" and pk[0].type.length == 36, t.name


def test_every_datetime_column_is_timezone_aware():
    for t in Base.metadata.tables.values():
        for c in t.columns:
            if isinstance(c.type, sa.TypeDecorator) and isinstance(c.type.impl, sa.DateTime):
                assert c.type.impl.timezone, f"{t.name}.{c.name}"
            assert not type(c.type) is sa.DateTime, f"{t.name}.{c.name} must use UTCDateTime"


def test_reit_holdings_are_isolated_from_ansh_tables():
    """ADR-019: REIT is a separate asset class."""
    reit = Base.metadata.tables["reit_holdings"]
    assert {fk.column.table.name for fk in reit.foreign_keys} == {"users"}
    for t in Base.metadata.tables.values():
        assert all(fk.column.table.name != "reit_holdings" for fk in t.foreign_keys), t.name


def test_sqlite_enforces_foreign_keys(tmp_path):
    eng = make_engine(f"sqlite:///{tmp_path / 'fk.db'}")
    with eng.connect() as c:
        assert c.execute(sa.text("PRAGMA foreign_keys")).scalar() == 1


def test_generated_reference_document_is_current():
    from scripts import gen_db_reference as gen
    assert gen.OUT.read_text(encoding="utf-8") == gen.render(), "run: python -m scripts.gen_db_reference"
