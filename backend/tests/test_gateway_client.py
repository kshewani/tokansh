"""The real gateway client's mapping of adapter responses (no network: httpx MockTransport)."""
import httpx
import pytest

from app.core.config import Settings
from app.ledger.gateway_client import GatewayLedgerClient
from app.ledger.port import LedgerUnavailable, SubmissionState


def client(handler, url="http://adapter.test"):
    return GatewayLedgerClient(Settings(drunix_gateway_url=url), transport=httpx.MockTransport(handler))


def submit(c):
    return c.submit(function="IssueANSH", args=["a"], operation_id="op-1", correlation_id="c")


def test_not_configured_is_unavailable_never_success():
    c = GatewayLedgerClient(Settings(drunix_gateway_url=""))
    with pytest.raises(LedgerUnavailable):
        submit(c)
    assert c.health()["status"] == "UNAVAILABLE"


def test_commit_confirmed_passes_through_evidence():
    def h(req):
        assert req.url.path == "/v1/transactions/submit"
        return httpx.Response(200, json={"state": "COMMIT_CONFIRMED", "transaction_id": "abc", "block_number": 7,
                                         "validation_code": "VALID"})
    r = submit(client(h))
    assert (r.state, r.transaction_id, r.block_number) == (SubmissionState.COMMIT_CONFIRMED, "abc", 7)


def test_timeout_is_unknown_not_failure():
    def h(req):
        raise httpx.ReadTimeout("slow", request=req)
    assert submit(client(h)).state == SubmissionState.UNKNOWN


def test_connect_error_is_unavailable():
    def h(req):
        raise httpx.ConnectError("refused", request=req)
    with pytest.raises(LedgerUnavailable):
        submit(client(h))


def test_unrecognised_response_is_unknown():
    assert submit(client(lambda req: httpx.Response(500, text="boom"))).state == SubmissionState.UNKNOWN
    assert submit(client(lambda req: httpx.Response(200, json={"state": "DONE"}))).state == SubmissionState.UNKNOWN


def test_endorsement_rejection_maps_error():
    r = submit(client(lambda req: httpx.Response(409, json={"state": "NOT_SUBMITTED", "error": {
        "code": "INSUFFICIENT_AVAILABLE_ANSH", "message": "no"}})))
    assert r.state == SubmissionState.NOT_SUBMITTED and r.error_code == "INSUFFICIENT_AVAILABLE_ANSH"


def test_commit_without_transaction_id_is_never_committed(people, ledger):
    from app.core.config import Settings as S
    from app.db import models as m
    from app.db.enums import OperationStatus, OperationType
    from app.ledger import executor
    from app.ledger.port import LedgerResult
    from sqlalchemy.orm import Session

    class Liar:
        def submit(self, **kw):
            return LedgerResult(SubmissionState.COMMIT_CONFIRMED, transaction_id=None)

    engine = people["meera"].client.app.state.engine
    with Session(engine) as db:
        op = executor.submit_operation(db, Liar(), S(commit_poll_attempts=0), op_type=OperationType.ANSH_PLEDGE,
                                       entity_type="test", entity_id="x", function="Noop", args=[])
        assert op.status == OperationStatus.RECONCILIATION_REQUIRED
        assert db.query(m.ReconciliationCase).count() == 1


def test_running_app_never_uses_a_test_double():
    import pathlib
    from app.main import create_app
    app = create_app(Settings(database_url="sqlite://"))
    assert isinstance(app.state.ledger, GatewayLedgerClient)
    src = pathlib.Path(__file__).resolve().parents[1] / "app"
    assert not [p for p in src.rglob("*.py") if "fake" in p.read_text().lower().replace("fabricate", "")]
