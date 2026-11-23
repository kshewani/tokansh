from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

from app.config import Settings
from app.auth import DemoIdentity
from app.main import create_app
from client_support import SyncASGIClient

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
    app.state.gateway.client.close()
    app.state.database.engine.dispose()


@pytest.fixture
def client(application):
    with SyncASGIClient(application) as client:
        yield client


@pytest.fixture
def property_payload():
    return {"name": "TechPark One", "location": "Bengaluru, Karnataka", "category": "Commercial office",
            "valuation": "1000000000.00", "proposed_supply": 100000, "issue_price": "10000.00", "currency": "INR"}


@pytest.fixture
def auth_headers(client):
    def factory(username, password="test-password"):
        response = client.post("/api/v1/auth/login", json={"username": username, "password": password})
        assert response.status_code == 200, response.text
        return {"Authorization": "Bearer " + response.json()["data"]["access_token"]}
    return factory


@pytest.fixture
def issuer_headers(application):
    # The issuer is intentionally not a public investor login. This fixture
    # creates the existing issuer-only identity inside the test application.
    identity = DemoIdentity("issuer", "Issuer", "ISSUER", "00000000-0000-4000-8000-000000000002")
    token = application.state.sessions.create(identity)
    return {"Authorization": "Bearer " + token, "Idempotency-Key": "create-techpark-one", "X-Correlation-ID": "test-correlation"}
