"""Add presentation metadata for the fixed showcase catalogue.

The fields are nullable so this revision is additive for historical property
rows.  Friendly symbols are application metadata; the property UUID remains
the ledger identity.
"""
import re

from alembic import op
import sqlalchemy as sa


revision = "0005_showcase_metadata"
down_revision = "0004_marketplace"
branch_labels = None
depends_on = None


def _symbol(name: str, used: set[str]) -> str:
    words = re.findall(r"[A-Za-z0-9]+", name.upper())
    known = {
        "SILVER OAK": "OAK", "GREEN ACRES": "GREEN", "URBAN NEST": "NEST",
        "CORNERSTONE": "CORNER", "HILLCREST": "HILL", "METRO": "METRO",
        "PALM HAVEN": "PALM", "SUMMIT": "SUMMIT", "TECHPARK": "TECHPARK",
    }
    upper = " ".join(words)
    base = next((value for key, value in known.items() if key in upper), None)
    if base is None:
        base = "-".join(words[:2])[:24] or "PROPERTY"
    candidate = base
    suffix = 2
    while candidate in used:
        candidate = f"{base}-{suffix}"
        suffix += 1
    used.add(candidate)
    return candidate


def upgrade():
    op.add_column("properties", sa.Column("friendly_symbol", sa.String(32), nullable=True))
    op.add_column("properties", sa.Column("size_description", sa.String(120), nullable=True))
    op.add_column("properties", sa.Column("description", sa.String(500), nullable=True))
    op.add_column("properties", sa.Column("risk_profile", sa.String(240), nullable=True))

    connection = op.get_bind()
    rows = connection.execute(sa.text("SELECT id, name FROM properties ORDER BY created_at, id")).mappings()
    used: set[str] = set()
    for row in rows:
        connection.execute(
            sa.text("UPDATE properties SET friendly_symbol = :symbol WHERE id = :id"),
            {"symbol": _symbol(row["name"], used), "id": row["id"]},
        )
    op.create_index("uq_properties_friendly_symbol", "properties", ["friendly_symbol"], unique=True)


def downgrade():
    op.drop_index("uq_properties_friendly_symbol", table_name="properties")
    with op.batch_alter_table("properties", recreate="always") as batch:
        batch.drop_column("risk_profile")
        batch.drop_column("description")
        batch.drop_column("size_description")
        batch.drop_column("friendly_symbol")
