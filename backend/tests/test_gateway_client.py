"""The real gateway client against Kamlesh's private gateway contract (httpx MockTransport, no network)."""
import hashlib
import json

import httpx
import pytest

from app.core.config import Settings
from app.ledger.gateway_client import GatewayLedgerClient, canonical
from app.ledger.port import LedgerOutcomeUnknown, LedgerRejected, LedgerUnavailable

GW, OP = "a" * 64, "b" * 64
CMD = {"command_version": 1, "operation_id": "11111111-1111-4111-8111-111111111111",
       "property_id": "22222222-2222-4222-8222-222222222222", "quantity": 10}


def settings(**kw):
    return Settings(**{"drunix_gateway_url": "http://127.0.0.1:8001", "tokansh_gateway_secret": GW,
                       "tokansh_operator_secret": OP, **kw})


def client(handler, **kw):
    return GatewayLedgerClient(settings(**kw), transport=httpx.MockTransport(handler))


def artifact(cmd=CMD, **over):
    a = {"version": 1, "channel": "mychannel", "chaincode": "tokansh", "signer": "Org1MSP:abc", "function": "IssueANSH",
         "command": cmd, "request_digest": hashlib.sha256(canonical(cmd).encode()).hexdigest(),
         "transaction_id": "f" * 64, "transaction": "AAAA", "creator": "BBBB", "mac": "c" * 64}
    a.update(over)
    return a


def ok(data, status=200):
    return httpx.Response(status, json={"data": data})


def test_prepare_uses_typed_route_with_both_secrets():
    seen = {}

    def h(req):
        seen.update(path=req.url.path, auth=req.headers.get("authorization"), cap=req.headers.get("x-operator-capability"),
                    body=json.loads(req.content))
        return ok(artifact())
    a = client(h).prepare("issuance", CMD)
    assert seen["path"] == "/v1/tokansh/issuances/prepare" and seen["auth"] == "Bearer " + GW and seen["cap"] == OP
    assert seen["body"] == CMD and a["transaction_id"] == "f" * 64


def test_artifact_that_does_not_match_the_command_is_refused():
    bad = artifact(command={**CMD, "quantity": 11})
    with pytest.raises(LedgerUnavailable) as e:
        client(lambda r: ok(bad)).prepare("issuance", CMD)
    assert e.value.code == "INVALID_ARTIFACT"
    with pytest.raises(LedgerUnavailable):
        client(lambda r: ok(artifact()), drunix_signer="Org1MSP:other").prepare("issuance", CMD)


def test_chaincode_business_rejection_maps_to_api_code():
    resp = httpx.Response(409, json={"error": {"code": "INSUFFICIENT_BALANCE", "message": "Sender has insufficient ANSH."}})
    with pytest.raises(LedgerRejected) as e:
        client(lambda r: resp).prepare("transfer", CMD)
    assert e.value.code == "INSUFFICIENT_AVAILABLE_ANSH"


def test_submit_outcomes():
    a = artifact()
    client(lambda r: ok({"state": "SUBMITTED", "transaction_id": a["transaction_id"]})).submit("issuance", a)
    with pytest.raises(LedgerOutcomeUnknown):  # gateway reports UNKNOWN after sending
        client(lambda r: httpx.Response(503, json={"data": {"state": "UNKNOWN"}, "error": {"code": "LEDGER_OUTCOME_UNKNOWN", "message": "x"}})).submit("issuance", a)

    def timeout(req):
        raise httpx.ReadTimeout("slow", request=req)
    with pytest.raises(LedgerOutcomeUnknown):
        client(timeout).submit("issuance", a)

    def refused(req):
        raise httpx.ConnectError("refused", request=req)
    with pytest.raises(LedgerUnavailable):  # connection never opened: not submitted
        client(refused).submit("issuance", a)


def test_commit_status_is_validated():
    a = artifact()
    s = client(lambda r: ok({"transaction_id": a["transaction_id"], "code": 0, "block_number": 12, "successful": True})
               ).commit_status("issuance", a)
    assert s.successful and s.block_number == 12
    with pytest.raises(LedgerOutcomeUnknown):  # inconsistent: successful with a non-zero code
        client(lambda r: ok({"transaction_id": a["transaction_id"], "code": 11, "block_number": 12, "successful": True})
               ).commit_status("issuance", a)


def test_registration_uses_its_own_routes():
    paths = []

    def h(req):
        paths.append(req.url.path)
        return ok({"state": "SUBMITTED", "transaction_id": "f" * 64}) if req.url.path.endswith("submit") else \
            ok({"transaction_id": "f" * 64, "code": 0, "block_number": 1, "successful": True})
    c, a = client(h), artifact(function="RegisterApprovedProperty")
    c.submit("registration", a)
    c.commit_status("registration", a)
    assert paths == ["/v1/tokansh/property-registrations/submit", "/v1/tokansh/commit-status"]


def test_pledge_is_not_available_until_the_chaincode_supports_it():
    with pytest.raises(LedgerUnavailable) as e:
        client(lambda r: ok({})).prepare("pledge", {"command_version": 1})
    assert e.value.code == "LEDGER_FUNCTION_UNAVAILABLE"


def test_configuration_rules():
    for kw in ({"drunix_gateway_url": ""}, {"drunix_gateway_url": "http://localhost:8001"},
               {"drunix_gateway_url": "http://10.0.0.5:8001"}, {"tokansh_operator_secret": GW},
               {"tokansh_gateway_secret": "short"}):
        c = client(lambda r: ok({}), **kw)
        assert not c.configured and c.health()["status"] == "UNAVAILABLE"
        with pytest.raises(LedgerUnavailable):
            c.prepare("issuance", CMD)


def test_balance_and_health_reads():
    pid, hid = CMD["property_id"], "33333333-3333-4333-8333-333333333333"

    def h(req):
        assert req.method == "GET" and "x-operator-capability" not in req.headers
        if req.url.path.endswith("contract-info"):
            return ok({"contract": "tokansh", "functions": ["RegisterApprovedProperty", "IssueANSH", "TransferANSH"]})
        return ok({"schema_version": 1, "property_id": pid, "holder_id": hid, "quantity": 7})
    c = client(h)
    assert c.get_position(pid, hid) == {"owned": 7, "pledged": 0}
    assert c.health()["status"] == "CONNECTED"
    assert client(lambda r: httpx.Response(404, json={"error": {"code": "PROPERTY_NOT_FOUND", "message": "x"}})
                  ).get_position(pid, hid) == {"owned": 0, "pledged": 0}


def test_running_app_never_uses_a_test_double():
    import pathlib
    from app.main import create_app
    app = create_app(Settings(database_url="sqlite://"))
    assert isinstance(app.state.ledger, GatewayLedgerClient)
    src = pathlib.Path(__file__).resolve().parents[1] / "app"
    assert not [p for p in src.rglob("*.py") if "fake" in p.read_text().lower().replace("fabricate", "")]


def test_full_supply_issuance_codes_map_to_api_codes():
    for code in ("INITIAL_ISSUANCE_MUST_MATCH_APPROVED_SUPPLY", "ISSUANCE_ALREADY_COMPLETED"):
        resp = httpx.Response(422, json={"error": {"code": code, "message": "x"}})
        with pytest.raises(LedgerRejected) as e:
            client(lambda r, resp=resp: resp).prepare("issuance", CMD)
        assert e.value.code == code
    old = httpx.Response(503, json={"error": {"code": "ISSUANCE_POLICY_UNSUPPORTED", "message": "x"}})
    with pytest.raises(LedgerUnavailable) as e:
        client(lambda r: old).prepare("issuance", CMD)
    assert e.value.code == "LEDGER_FUNCTION_UNAVAILABLE"
