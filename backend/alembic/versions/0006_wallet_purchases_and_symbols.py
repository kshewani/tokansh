"""wallet-paid ANSH purchases; friendly ANSH symbols

* demo_cash_entries.kind gains PURCHASE_PAYMENT, SALE_PROCEEDS and PURCHASE_REFUND:
  the buyer pays from simulated demo cash, the seller is credited only after the
  DRUNIX transfer commits, and a failed transfer refunds the buyer.
* properties.friendly_symbol: presentation-only symbol (ANSH-<symbol>), unique.
  Existing rows are backfilled from the property name.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-28
"""
import re

from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

OLD = ("DEMO_FUNDS", "WITHDRAWAL", "DISBURSEMENT", "REPAYMENT")
NEW = OLD + ("PURCHASE_PAYMENT", "SALE_PROCEEDS", "PURCHASE_REFUND")
KNOWN = (("SILVER OAK", "OAK"), ("GREEN ACRES", "GREEN"), ("URBAN NEST", "NEST"), ("CORNERSTONE", "CORNER"),
         ("HILLCREST", "HILL"), ("METRO", "METRO"), ("PALM HAVEN", "PALM"), ("SUMMIT", "SUMMIT"),
         ("TECHPARK", "TECHPARK"))


def _kind(values):
    return sa.Enum(*values, name="wallet_entry_kind", native_enum=False, create_constraint=True, length=40)


def _symbol(name: str, used: set) -> str:
    normalized = " ".join(re.findall(r"[A-Za-z0-9]+", name.upper()))
    base = next((s for h, s in KNOWN if h in normalized), None) or ("-".join(normalized.split()[:2]) or "PROPERTY")[:24]
    base = re.sub(r"[^A-Z0-9-]", "-", base).strip("-") or "PROPERTY"
    candidate, n = base, 2
    while candidate in used:
        candidate, n = f"{base}-{n}", n + 1
    used.add(candidate)
    return candidate


def upgrade() -> None:
    with op.batch_alter_table("demo_cash_entries") as batch:
        batch.alter_column("kind", existing_type=_kind(OLD), type_=_kind(NEW), existing_nullable=False)
    with op.batch_alter_table("properties") as batch:
        batch.add_column(sa.Column("friendly_symbol", sa.String(32), nullable=True))
    conn, used = op.get_bind(), set()
    for pid, name in conn.execute(sa.text("SELECT id, property_name FROM properties ORDER BY created_at, id")).all():
        conn.execute(sa.text("UPDATE properties SET friendly_symbol = :s WHERE id = :id"), {"s": _symbol(name, used), "id": pid})
    with op.batch_alter_table("properties") as batch:
        batch.create_unique_constraint("uq_properties_friendly_symbol", ["friendly_symbol"])


def downgrade() -> None:
    with op.batch_alter_table("properties") as batch:
        batch.drop_constraint("uq_properties_friendly_symbol", type_="unique")
        batch.drop_column("friendly_symbol")
    op.execute("DELETE FROM demo_cash_entries WHERE kind IN ('PURCHASE_PAYMENT','SALE_PROCEEDS','PURCHASE_REFUND')")
    with op.batch_alter_table("demo_cash_entries") as batch:
        batch.alter_column("kind", existing_type=_kind(NEW), type_=_kind(OLD), existing_nullable=False)
