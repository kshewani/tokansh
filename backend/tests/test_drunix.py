"""All HTTPX transports here are isolated test doubles, never runtime ledger modes."""
import json
import os
from datetime import datetime, timezone

import httpx
import pytest
from client_support import SyncASGIClient
from pydantic import ValidationError

from app.config import Settings
from app.drunix import GatewayAdapter, get_gateway
from app.auth import DemoIdentity
from app.errors import ApplicationError

ASSET = {"ID": "asset1", "Color": "blue", "Size": 5, "Owner": "test-only", "AppraisedValue": 300}


def observation(function="GetAllAssets", result=None):
    return {"source": "DRUNIX_EVALUATE", "channel": "mychannel", "chaincode": "basic", "function": function,
            "observed_at": datetime.now(timezone.utc).isoformat(), "result": [ASSET] if result is None else result}


def response(request, data, status=200):
    correlation = request.headers["X-Correlation-ID"]
    return httpx.Response(status, json={"data": data, "meta": {"correlation_id": correlation}},
                          headers={"X-Correlation-ID": correlation})


def adapter(handler):
    return GatewayAdapter("http://127.0.0.1:8001", httpx.Client(transport=httpx.MockTransport(handler)))


@pytest.mark.parametrize("url", ["https://example.com:8001", "http://0.0.0.0:8001", "http://127.0.0.1:8001/path",
                                 "http://user:secret@localhost:8001", "http://localhost", "http://localhost:8001?x=1"])
def test_only_explicit_private_gateway_urls_are_allowed(url):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, drunix_gateway_url=url)


@pytest.mark.parametrize("timeout", [0, -1, 13, float("inf"), float("nan")])
def test_gateway_timeout_is_bounded(timeout):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, drunix_gateway_timeout_seconds=timeout)


def test_successful_reads_preserve_provenance_and_have_no_transaction_evidence():
    def upstream(request):
        if request.url.path.endswith("/exists"):
            return response(request, observation("AssetExists", True))
        if request.url.path.endswith("/asset1"):
            return response(request, observation("ReadAsset", ASSET))
        return response(request, observation())
    gateway = adapter(upstream)
    try:
        assert gateway.all_assets("test-ref").result[0].ID == "asset1"
        assert gateway.read_asset("asset1", "test-ref").result.ID == "asset1"
        assert gateway.asset_exists("asset1", "test-ref").result is True
        result = gateway.all_assets("test-ref").model_dump()
        assert "transaction_id" not in result and "ledger_transaction_id" not in result
        assert result["source"] == "DRUNIX_EVALUATE"
    finally:
        gateway.client.close()


@pytest.mark.parametrize("digits", [1, 2, 3, 4, 5, 6, 7, 8, 9])
def test_go_rfc3339_fractional_precision_is_supported(digits):
    data = observation()
    data["observed_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S") + "." + "1" * digits + "Z"
    gateway = adapter(lambda request: response(request, data))
    try:
        assert gateway.all_assets("test-ref").result[0].ID == "asset1"
    finally:
        gateway.client.close()


@pytest.mark.parametrize("mutate", [
    lambda data: {**data, "transaction_id": "fabricated"},
    lambda data: {**data, "source": "MOCK"},
    lambda data: {**data, "channel": "wrong"},
    lambda data: {**data, "function": "InitLedger"},
    lambda data: {**data, "observed_at": "not-a-timestamp"},
    lambda data: {**data, "observed_at": "2020-01-01T00:00:00Z"},
    lambda data: {**data, "result": [{**ASSET, "Size": True}]},
    lambda data: {**data, "result": [{"ID": "asset1"}]},
    lambda data: {**data, "result": [ASSET, ASSET]},
])
def test_malformed_or_synthetic_upstream_is_rejected(mutate):
    gateway = adapter(lambda request: response(request, mutate(observation())))
    try:
        with pytest.raises(ApplicationError) as error:
            gateway.all_assets("test-ref")
        assert error.value.code == "GATEWAY_BAD_RESPONSE"
    finally:
        gateway.client.close()


@pytest.mark.parametrize("kind,code,status", [("timeout", "GATEWAY_TIMEOUT", 504),
                                               ("connection", "GATEWAY_UNAVAILABLE", 503),
                                               ("json", "GATEWAY_BAD_RESPONSE", 502),
                                               ("correlation", "GATEWAY_BAD_RESPONSE", 502),
                                               ("oversize", "GATEWAY_BAD_RESPONSE", 502)])
def test_transport_and_payload_errors_are_explicit(kind, code, status):
    def upstream(request):
        if kind == "timeout":
            raise httpx.ReadTimeout("test-only internal detail", request=request)
        if kind == "connection":
            raise httpx.ConnectError("test-only internal detail", request=request)
        if kind == "json":
            return httpx.Response(200, content="{bad", headers={"Content-Type": "application/json", "X-Correlation-ID": "test-ref"})
        if kind == "oversize":
            return httpx.Response(200, content=" " * ((1 << 20) + 1), headers={"Content-Type": "application/json"})
        return httpx.Response(200, json={"data": observation(), "meta": {"correlation_id": "wrong"}})
    gateway = adapter(upstream)
    try:
        with pytest.raises(ApplicationError) as error:
            gateway.all_assets("test-ref")
        assert (error.value.code, error.value.status) == (code, status)
        assert "internal detail" not in error.value.message
    finally:
        gateway.client.close()


def test_missing_asset_error_is_sanitized_and_invalid_ids_never_reach_gateway():
    calls = []
    def upstream(request):
        calls.append(request.url.path)
        correlation = request.headers["X-Correlation-ID"]
        return httpx.Response(404, json={"error": {"code": "ASSET_NOT_FOUND", "message": "private test-only upstream details"},
                                        "meta": {"correlation_id": correlation}}, headers={"X-Correlation-ID": correlation})
    gateway = adapter(upstream)
    try:
        with pytest.raises(ApplicationError) as missing:
            gateway.read_asset("missing", "test-ref")
        assert missing.value.status == 404 and "private" not in missing.value.message
        with pytest.raises(ApplicationError):
            gateway.read_asset("../invoke", "test-ref")
        assert len(calls) == 1
    finally:
        gateway.client.close()


@pytest.mark.parametrize("network_ok", [True, False])
def test_system_status_reports_actual_read_connectivity_but_not_commit_readiness(application, network_ok):
    def upstream(request):
        if request.url.path == "/health":
            return response(request, {"status": "UP", "mode": "READ_ONLY"})
        if network_ok:
            return response(request, observation())
        ref = request.headers["X-Correlation-ID"]
        return httpx.Response(503, json={"error": {"code": "LEDGER_UNAVAILABLE", "message": "test-only"}, "meta": {"correlation_id": ref}}, headers={"X-Correlation-ID": ref})
    gateway = adapter(upstream)
    application.dependency_overrides[get_gateway] = lambda: gateway
    try:
        with SyncASGIClient(application) as client:
            result = client.get("/api/v1/system/status").json()["data"]
            components = {c["name"]: c["status"] for c in result["components"]}
            assert components["Go gateway"] == "CONNECTED"
            assert components["DRUNIX network connectivity"] == ("CONNECTED" if network_ok else "UNAVAILABLE")
            assert components["Ordering service"] == components["DRUNIX peers"] == "UNKNOWN"
            assert components["DRUNIX transaction capability"] == "UNAVAILABLE"
            assert result["last_ledger_operation"] is None
            assert client.get("/ready").status_code == 503
    finally:
        gateway.client.close()


def test_disconnected_bridge_never_claims_network_connectivity(application):
    def offline(request):
        raise httpx.ConnectError("offline", request=request)
    gateway = adapter(offline)
    application.dependency_overrides[get_gateway] = lambda: gateway
    try:
        with SyncASGIClient(application) as client:
            components = {c["name"]: c["status"] for c in client.get("/api/v1/system/status").json()["data"]["components"]}
            assert components["Go gateway"] == "UNAVAILABLE"
            assert components["DRUNIX network connectivity"] == "UNKNOWN"
    finally:
        gateway.client.close()


def test_diagnostic_route_is_admin_only_and_does_not_enable_business_routes(application):
    gateway = adapter(lambda request: response(request, observation()))
    application.dependency_overrides[get_gateway] = lambda: gateway
    try:
        with SyncASGIClient(application) as client:
            path = "/api/v1/diagnostics/drunix/basic/assets"
            assert client.get(path).status_code == 401
            assert client.get(path, headers={"X-Demo-Role": "INVESTOR"}).status_code == 401
            token = application.state.sessions.create(DemoIdentity("admin", "Admin", "ADMIN",
                                                                   "00000000-0000-4000-8000-000000000001"))
            result = client.get(path, headers={"Authorization": "Bearer " + token, "X-Correlation-ID": "diag-ref"})
            assert result.status_code == 200
            assert result.json()["data"]["result"][0]["ID"] == "asset1"
            assert result.json()["meta"]["correlation_id"] == "diag-ref"
            assert "transaction_id" not in result.text
            assert client.post("/api/v1/ansh/issuances", json={}).status_code == 401
    finally:
        gateway.client.close()


def test_real_private_gateway_integration(application):
    url = os.getenv("TOKANSH_TEST_GATEWAY_URL")
    if not url:
        pytest.skip("opt-in real Go gateway read integration")
    assert application.state.settings.drunix_gateway_url == url
    gateway = application.state.gateway
    with SyncASGIClient(application) as client:
        token = application.state.sessions.create(DemoIdentity("admin", "Admin", "ADMIN",
                                                               "00000000-0000-4000-8000-000000000001"))
        result = client.get("/api/v1/diagnostics/drunix/basic/assets", headers={"Authorization": "Bearer " + token})
        assert result.status_code == 200, result.text
        data = result.json()["data"]
        assert sorted(a["ID"] for a in data["result"]) == [f"asset{i}" for i in range(1, 7)]
        assert gateway.read_asset("asset1", "real-read-test").result.ID == "asset1"
        assert gateway.asset_exists("asset1", "real-exists-test").result is True
        status = client.get("/api/v1/system/status").json()["data"]
        assert next(c for c in status["components"] if c["name"] == "DRUNIX network connectivity")["status"] == "CONNECTED"
        assert status["last_ledger_operation"] is None
        assert client.get("/ready").status_code == 503
