import json
import shutil
import subprocess
from pathlib import Path

import pytest
from alembic import command
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import Settings
from app.main import create_app
from conftest import migration_config


def test_health_status_and_readiness_are_distinct(client):
    assert client.get("/health").status_code == 200
    response = client.get("/api/v1/system/status")
    assert response.status_code == 200
    data = response.json()["data"]
    components = {item["name"]: item["status"] for item in data["components"]}
    assert components["FastAPI"] == components["Application database"] == "CONNECTED"
    assert components["Go gateway"] == "UNAVAILABLE"
    assert components["DRUNIX peers"] == "UNKNOWN"
    assert components["DRUNIX transaction capability"] == "UNAVAILABLE"
    assert data["last_ledger_operation"] is None
    assert client.get("/ready").status_code == 503
    assert client.get("/ready").json()["data"]["ready"] is False


def test_existing_frontend_parser_accepts_actual_backend_payload(client):
    node = shutil.which("node")
    linux_node = Path.home() / ".nvm/versions/node/v24.22.3/bin/node"
    if linux_node.exists():
        node = str(linux_node)
    if node is None:
        pytest.skip("Node.js 24 is needed only for the cross-stack parser test")
    frontend = Path(__file__).resolve().parents[2] / "frontend"
    result = subprocess.run([node, "--experimental-strip-types", "--input-type=module", "-e",
        "import {parseSystemStatus} from './src/api/systemStatus.ts';"
        "let input='';for await(const chunk of process.stdin)input+=chunk;"
        "const value=parseSystemStatus(JSON.parse(input).data);"
        "if(value.last_ledger_operation!==null)throw Error('Unexpected ledger evidence');"
        "console.log(value.components.length);"],
        input=json.dumps(client.get("/api/v1/system/status").json()), text=True,
        cwd=frontend, capture_output=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert int(result.stdout.strip()) == 9


def test_missing_migrations_fail_safely_without_autocreating_tables(settings):
    app = create_app(settings)
    with TestClient(app) as client:
        response = client.get("/api/v1/system/status")
        database = next(item for item in response.json()["data"]["components"] if item["name"] == "Application database")
        assert database["status"] == "UNAVAILABLE"
        response = client.get("/api/v1/properties", headers={"X-Demo-Role": "ISSUER"})
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "DATABASE_UNAVAILABLE"


def test_migrations_upgrade_downgrade_and_model_alignment(settings):
    config = migration_config(settings.database_url)
    command.upgrade(config, "head")
    command.check(config)
    app = create_app(settings)
    assert app.state.database.ready()
    app.state.database.engine.dispose()
    command.downgrade(config, "base")
    assert not app.state.database.ready()
    app.state.database.engine.dispose()
    command.upgrade(config, "head")
    assert app.state.database.ready()
    app.state.database.engine.dispose()


def test_cors_allows_local_frontend_headers_but_rejects_other_origins(client):
    headers = {"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST",
               "Access-Control-Request-Headers": "Content-Type,Idempotency-Key,X-Correlation-ID,X-Demo-Role"}
    allowed = client.options("/api/v1/properties", headers=headers)
    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert allowed.headers["access-control-allow-credentials"] == "true"
    denied = client.options("/api/v1/properties", headers={**headers, "Origin": "https://untrusted.example"})
    assert denied.status_code == 400
    assert "access-control-allow-origin" not in denied.headers
    response = client.get("/api/v1/system/status", headers={"Origin": "http://localhost:5173", "X-Correlation-ID": "from-react"})
    assert response.headers["X-Correlation-ID"] == response.json()["meta"]["correlation_id"] == "from-react"
    assert "X-Correlation-ID" in response.headers["access-control-expose-headers"]


def test_safe_configuration_and_errors_do_not_leak_details(client):
    safe = client.get("/api/v1/system/configuration").json()["data"]
    assert safe == {"app_env": "test", "demo_auth_enabled": True, "ledger_integration": "NOT_IMPLEMENTED"}
    missing = client.get("/not-a-route", headers={"X-Correlation-ID": "not-found-reference"})
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "RESOURCE_NOT_FOUND"
    assert missing.json()["meta"]["correlation_id"] == missing.headers["X-Correlation-ID"] == "not-found-reference"
    invalid = client.get("/health", headers={"X-Correlation-ID": "invalid reference"})
    assert invalid.status_code == 400
    assert invalid.json()["error"]["code"] == "INVALID_REQUEST"


def test_unexpected_errors_are_structured_correlated_and_cors_visible(application):
    def failure():
        raise RuntimeError("sensitive test-only exception contents")

    application.add_api_route("/test-only-failure", failure)
    with TestClient(application) as client:
        response = client.get("/test-only-failure", headers={"Origin": "http://localhost:5173", "X-Correlation-ID": "server-error-reference"})
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert response.headers["X-Correlation-ID"] == "server-error-reference"
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "sensitive" not in response.text


@pytest.mark.parametrize("values", [
    {"app_env": "production", "demo_auth_enabled": True},
    {"database_url": "postgresql://localhost/app"}, {"database_url": "sqlite:///:memory:"},
    {"database_url": "not-a-url"}, {"database_url": "sqlite+aiosqlite:///test.db"},
    {"cors_origins": "*"}, {"cors_origins": "http://localhost:5173/path"},
    {"cors_origins": "http://user:password@localhost:5173"}, {"app_port": 0},
])
def test_configuration_rejects_unsafe_values(values):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **values)


def test_settings_load_supported_environment_variables(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'configured.db'}")
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:5173")
    settings = Settings(_env_file=None)
    assert settings.app_env == "test"
    assert settings.allowed_origins == ["http://localhost:5173"]


def test_production_without_auth_cannot_access_property_workflows(settings, property_payload):
    command.upgrade(migration_config(settings.database_url), "head")
    app = create_app(settings.model_copy(update={"app_env": "production", "demo_auth_enabled": False}))
    with TestClient(app) as client:
        response = client.post("/api/v1/properties", json=property_payload,
                               headers={"X-Demo-Role": "ISSUER", "Idempotency-Key": "test"})
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "AUTH_NOT_CONFIGURED"


def test_unimplemented_ledger_operations_never_fall_back(client):
    for path in ["/api/v1/ansh/issuances", "/api/v1/collateral/pledges"]:
        response = client.post(path, json={})
        assert response.status_code == 404
        assert "COMMITTED" not in response.text


def test_openapi_describes_existing_request_response_and_error_contracts(client):
    schema = client.get("/openapi.json").json()
    create = schema["paths"]["/api/v1/properties"]["post"]
    assert create["requestBody"]["required"]
    assert create["responses"]["201"]["content"]["application/json"]["schema"]["$ref"].endswith("Envelope_PropertyRead_")
    assert create["responses"]["422"]["content"]["application/json"]["schema"]["$ref"].endswith("ErrorEnvelope")
    assert schema["paths"]["/ready"]["get"]["responses"]["503"]["content"]["application/json"]["schema"]["$ref"].endswith("Envelope_Readiness_")
    headers = {parameter["name"] for parameter in create["parameters"] if parameter["in"] == "header"}
    assert {"X-Demo-Role", "Idempotency-Key"} <= headers
