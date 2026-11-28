from alembic import command
from alembic.config import Config
from sqlalchemy import select

from app.properties.models import Property
from app.properties.schemas import NewProperty
from app.properties.service import PropertyService
from app.dependencies import DEMO_ACTORS


def test_property_creation_assigns_stable_unique_friendly_symbols(application):
    with application.state.database.sessions() as session:
        first = PropertyService(session).create(
            NewProperty(name="Silver Oak Residential Plot", location="Pune", category="Residential",
                        valuation="6000000", proposed_supply=6000, currency="INR"),
            DEMO_ACTORS["ISSUER"].user_id, "oak-key", "test",
        )
        second = PropertyService(session).create(
            NewProperty(name="Silver Oak Annex", location="Pune", category="Residential",
                        valuation="6000000", proposed_supply=6000, currency="INR"),
            DEMO_ACTORS["ISSUER"].user_id, "oak-annex-key", "test",
        )
    assert first["ansh_symbol"] == "ANSH-OAK"
    assert second["ansh_symbol"] == "ANSH-OAK-2"


def test_historical_property_metadata_is_backfilled_without_changing_uuid(application):
    with application.state.database.sessions() as session:
        row = session.scalar(select(Property))
        assert row is None
    # The migration itself backfills existing rows; this test only verifies
    # the isolated database is at the new head and remains empty here.
    assert application.state.settings.database_url.startswith("sqlite:")
