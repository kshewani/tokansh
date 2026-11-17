"""HTTP client for the TokANSH Go DRUNIX gateway adapter (ADR-004).

The adapter's private HTTP interface is a TokANSH-owned contract documented in
docs/GATEWAY_ADAPTER_CONTRACT.md. It is not a DRUNIX API. This client never
fabricates transaction ids, blocks or commit evidence: it only passes on what
the adapter reports, and maps transport failures conservatively:

* cannot connect / not configured  -> LedgerUnavailable (nothing was sent)
* timeout or broken response after sending -> UNKNOWN (must be reconciled)
"""
import logging
from typing import Any

import httpx

from app.core.config import Settings
from app.ledger.port import LedgerQueryError, LedgerResult, LedgerUnavailable, SubmissionState

log = logging.getLogger("tokansh.ledger")


class GatewayLedgerClient:
    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None):
        self.settings = settings
        self._base = settings.drunix_gateway_url
        self._client = httpx.Client(base_url=self._base or "http://unconfigured.invalid",
                                    timeout=settings.drunix_timeout_seconds, transport=transport)

    @property
    def configured(self) -> bool:
        return bool(self._base)

    def _require_configured(self) -> None:
        if not self.configured:
            raise LedgerUnavailable("DRUNIX gateway adapter is not configured (DRUNIX_GATEWAY_URL is empty).",
                                    code="LEDGER_NOT_CONFIGURED")

    def submit(self, *, function: str, args: list[str], operation_id: str, correlation_id: str | None) -> LedgerResult:
        self._require_configured()
        body = {"channel": self.settings.drunix_channel, "chaincode": self.settings.drunix_chaincode,
                "function": function, "args": args, "operation_id": operation_id, "correlation_id": correlation_id}
        try:
            resp = self._client.post("/v1/transactions/submit", json=body)
        except httpx.ConnectError as exc:
            raise LedgerUnavailable(f"DRUNIX gateway adapter unreachable: {exc}") from exc
        except httpx.TimeoutException:
            log.warning("ledger submit timed out; outcome unknown", extra={"operation_id": operation_id})
            return LedgerResult(SubmissionState.UNKNOWN, error_code="LEDGER_OUTCOME_UNKNOWN",
                                error_message="Timed out waiting for the gateway adapter.")
        except httpx.HTTPError as exc:
            return LedgerResult(SubmissionState.UNKNOWN, error_code="LEDGER_OUTCOME_UNKNOWN", error_message=str(exc))
        return self._parse(resp)

    def commit_status(self, transaction_id: str) -> LedgerResult:
        self._require_configured()
        try:
            resp = self._client.get(f"/v1/transactions/{transaction_id}/status",
                                    params={"channel": self.settings.drunix_channel})
        except httpx.ConnectError as exc:
            raise LedgerUnavailable(f"DRUNIX gateway adapter unreachable: {exc}") from exc
        except httpx.HTTPError as exc:
            return LedgerResult(SubmissionState.UNKNOWN, transaction_id=transaction_id,
                                error_code="LEDGER_OUTCOME_UNKNOWN", error_message=str(exc))
        result = self._parse(resp)
        result.transaction_id = result.transaction_id or transaction_id
        return result

    def evaluate(self, *, function: str, args: list[str]) -> dict[str, Any]:
        self._require_configured()
        body = {"channel": self.settings.drunix_channel, "chaincode": self.settings.drunix_chaincode,
                "function": function, "args": args}
        try:
            resp = self._client.post("/v1/transactions/evaluate", json=body)
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            raise LedgerUnavailable(f"DRUNIX gateway adapter unreachable: {exc}") from exc
        data = _json(resp)
        if resp.status_code >= 500 and not data.get("error"):
            raise LedgerUnavailable(f"Gateway adapter error HTTP {resp.status_code}.")
        if resp.status_code >= 400 or data.get("error"):
            err = data.get("error") or {}
            raise LedgerQueryError(err.get("code", "LEDGER_QUERY_FAILED"), err.get("message", "Ledger query failed."))
        return data.get("result") or {}

    def health(self) -> dict[str, Any]:
        if not self.configured:
            return {"status": "UNAVAILABLE", "detail": "DRUNIX_GATEWAY_URL is not configured."}
        try:
            resp = self._client.get("/health", timeout=5.0)
        except httpx.HTTPError as exc:
            return {"status": "UNAVAILABLE", "detail": f"Gateway adapter unreachable ({type(exc).__name__})."}
        data = _json(resp)
        if resp.status_code != 200:
            return {"status": "DEGRADED", "detail": f"Gateway adapter returned HTTP {resp.status_code}."}
        status = data.get("status", "UNKNOWN")
        return {"status": status if status in {"CONNECTED", "DEGRADED", "UNAVAILABLE"} else "UNKNOWN",
                "detail": data.get("detail", "Reported by the gateway adapter.")}

    @staticmethod
    def _parse(resp: httpx.Response) -> LedgerResult:
        data = _json(resp)
        state_raw = data.get("state")
        try:
            state = SubmissionState(state_raw)
        except ValueError:
            # A response we cannot interpret is never treated as success or failure.
            return LedgerResult(SubmissionState.UNKNOWN, transaction_id=data.get("transaction_id"),
                                error_code="LEDGER_OUTCOME_UNKNOWN",
                                error_message=f"Unrecognised adapter response (HTTP {resp.status_code}).")
        err = data.get("error") or {}
        block = data.get("block_number")
        return LedgerResult(state=state, transaction_id=data.get("transaction_id"),
                            validation_code=data.get("validation_code"),
                            block_number=int(block) if block is not None else None,
                            error_code=err.get("code"), error_message=err.get("message"),
                            payload=data.get("result") or {})


def _json(resp: httpx.Response) -> dict:
    try:
        data = resp.json()
        return data if isinstance(data, dict) else {}
    except ValueError:
        return {}
