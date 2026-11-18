from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

BACKEND = Path(__file__).resolve().parents[1]


def migration_config(url: str) -> Config:
    config = Config(str(BACKEND / "alembic.ini"))
    config.attributes["database_url"] = url
    return config


@pytest.fixture
def settings(tmp_path):
    return Settings(_env_file=None, app_env="test", database_url=f"sqlite:///{tmp_path / 'test.db'}")


@pytest.fixture
def application(settings):
    command.upgrade(migration_config(settings.database_url), "head")
    app = create_app(settings)
    yield app
    app.state.database.engine.dispose()


@pytest.fixture
def client(application):
    with TestClient(application) as client:
        yield client


@pytest.fixture
def property_payload():
    return {"name": "TechPark One", "location": "Bengaluru, Karnataka", "category": "Commercial office",
            "valuation": "1000000000.00", "proposed_supply": 100000, "issue_price": "10000.00", "currency": "INR"}


@pytest.fixture
def issuer_headers():
    return {"X-Demo-Role": "ISSUER", "Idempotency-Key": "create-techpark-one", "X-Correlation-ID": "test-correlation"}
