"""HTTP client for the private TokANSH Go gateway (gateway/, contract in gateway/TRANSACTIONS.md).

The gateway exposes one typed route per chaincode function: no arbitrary invocation.
This client never fabricates transaction ids, blocks or commit evidence. It passes on
what the gateway reports and maps failures conservatively:

* not configured, or the connection could not be opened  -> LedgerUnavailable (nothing sent)
* endorsement refused by a chaincode business rule      -> LedgerRejected
* any other failure while submitting or reading status  -> LedgerOutcomeUnknown (reconcile)

Security boundary (same as the gateway's own Python client): loopback literal URL
only, no proxies, no redirects, bearer secret on every call, operator capability
on writes, bounded response size.
"""
import hashlib
import json
import logging
import re
from typing import Any

import httpx

from app.core.config import Settings
from app.ledger.port import (FUNCTIONS, CommitStatus, LedgerOutcomeUnknown, LedgerRejected, LedgerUnavailable)

log = logging.getLogger("tokansh.ledger")

LOOPBACK = re.compile(r"http://(?:127\.0\.0\.1|\[::1\]):([0-9]{1,5})/?")
SECRET = re.compile(r"[0-9a-fA-F]{64}")
MAX_BODY = 2 << 20

# kind -> (prepare, submit, commit-status) routes under /v1/tokansh/
ROUTES = {
    "registration": ("property-registrations/prepare", "property-registrations/submit", "commit-status"),
    "issuance": ("issuances/prepare", "issuances/submit", "issuances/commit-status"),
    "transfer": ("transfers/prepare", "transfers/submit", "transfers/commit-status"),
}
# Gateway business codes (HTTP status, code) -> TokANSH API error code.
BUSINESS = {
    "INSUFFICIENT_BALANCE": "INSUFFICIENT_AVAILABLE_ANSH",
    "ISSUANCE_LIMIT_EXCEEDED": "ISSUANCE_LIMIT_EXCEEDED",
    "IDEMPOTENCY_CONFLICT": "IDEMPOTENCY_CONFLICT",
    "PROPERTY_NOT_FOUND": "PROPERTY_NOT_APPROVED",
    "PROPERTY_ALREADY_REGISTERED": "INVALID_OPERATION_STATE",
    "UNAUTHORIZED": "LEDGER_UNAUTHORIZED",
    "INVALID_REQUEST": "INVALID_REQUEST",
}


def canonical(command: dict) -> str:
    """Compact JSON in field order, as the gateway digests it (Go json.Marshal of the struct)."""
    return json.dumps(command, separators=(",", ":"))


def _unique(pairs):
    out = {}
    for k, v in pairs:
        if k in out:
            raise ValueError("duplicate JSON field")
        out[k] = v
    return out


class GatewayLedgerClient:
    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None):
        self.settings = settings
        self._client = httpx.Client(timeout=settings.drunix_timeout_seconds, transport=transport,
                                    trust_env=False, follow_redirects=False)

    # ------------------------------------------------------------ configuration
    def _config_problem(self) -> str | None:
        s = self.settings
        m = LOOPBACK.fullmatch(s.drunix_gateway_url or "")
        if not s.drunix_gateway_url:
            return "DRUNIX gateway is not configured (DRUNIX_GATEWAY_URL is empty)."
        if m is None or not 1 <= int(m[1]) <= 65535:
            return "DRUNIX_GATEWAY_URL must be a loopback address such as http://127.0.0.1:8001."
        if not SECRET.fullmatch(s.tokansh_gateway_secret or "") or not SECRET.fullmatch(s.tokansh_operator_secret or ""):
            return "TOKANSH_GATEWAY_SECRET and TOKANSH_OPERATOR_SECRET must be 64 hex characters."
        if s.tokansh_gateway_secret.lower() == s.tokansh_operator_secret.lower():
            return "TOKANSH_GATEWAY_SECRET and TOKANSH_OPERATOR_SECRET must differ."
        return None

    @property
    def configured(self) -> bool:
        return self._config_problem() is None

    def _require(self) -> None:
        problem = self._config_problem()
        if problem:
            raise LedgerUnavailable(problem, code="LEDGER_NOT_CONFIGURED")

    # ------------------------------------------------------------ transport
    def _call(self, method: str, path: str, payload: Any = None) -> tuple[int, dict]:
        """Returns (status, parsed body). Raises httpx errors and ValueError to the caller."""
        s = self.settings
        headers = {"Authorization": "Bearer " + s.tokansh_gateway_secret}
        if method == "POST":
            headers["X-Operator-Capability"] = s.tokansh_operator_secret
        url = s.drunix_gateway_url.rstrip("/") + "/v1/tokansh/" + path
        with self._client.stream(method, url, headers=headers, json=payload) as resp:
            body = bytearray()
            for chunk in resp.iter_bytes():
                body.extend(chunk)
                if len(body) > MAX_BODY:
                    raise ValueError("gateway response too large")
            if resp.headers.get("content-type", "").split(";")[0] != "application/json":
                raise ValueError("gateway response is not JSON")
            data = json.loads(body, object_pairs_hook=_unique)
            if not isinstance(data, dict):
                raise ValueError("gateway response is not an object")
            return resp.status_code, data

    # ------------------------------------------------------------ writes
    def prepare(self, kind: str, command: dict) -> dict:
        self._require()
        if kind not in ROUTES:
            raise LedgerUnavailable(f"{FUNCTIONS.get(kind, kind)} is not available in the deployed TokANSH chaincode yet.",
                                    code="LEDGER_FUNCTION_UNAVAILABLE")
        try:
            status, frame = self._call("POST", ROUTES[kind][0], command)
        except httpx.HTTPError as exc:  # endorsement only: no ledger effect either way
            raise LedgerUnavailable(f"DRUNIX gateway unreachable during preparation ({type(exc).__name__}).") from exc
        except ValueError as exc:
            raise LedgerUnavailable(f"Gateway returned an unsupported response: {exc}", code="GATEWAY_BAD_RESPONSE") from exc
        if status != 200:
            err = frame.get("error") if isinstance(frame.get("error"), dict) else {}
            code = err.get("code", "")
            if code in BUSINESS:
                raise LedgerRejected(BUSINESS[code], err.get("message") or "The chaincode refused the command.")
            raise LedgerUnavailable(f"Gateway preparation failed (HTTP {status} {code or 'error'}).",
                                    code="LEDGER_TIMEOUT" if code == "LEDGER_TIMEOUT" else "LEDGER_UNAVAILABLE")
        artifact = frame.get("data")
        self._check_artifact(kind, command, artifact)
        return artifact

    def _check_artifact(self, kind: str, command: dict, a: Any) -> None:
        s = self.settings
        digest = hashlib.sha256(canonical(command).encode()).hexdigest()
        ok = (isinstance(a, dict) and a.get("version") == 1 and a.get("command") == command
              and a.get("request_digest") == digest and a.get("channel") == s.drunix_channel
              and a.get("chaincode") == s.drunix_chaincode
              and isinstance(a.get("transaction_id"), str) and a["transaction_id"]
              and all(isinstance(a.get(k), str) and a[k] for k in ("transaction", "creator", "mac", "signer"))
              and ("function" not in a or a["function"] == FUNCTIONS[kind])
              and (not s.drunix_signer or a.get("signer") == s.drunix_signer))
        if not ok:
            raise LedgerUnavailable("The prepared transaction does not match the request; nothing was submitted.",
                                    code="INVALID_ARTIFACT")

    def submit(self, kind: str, artifact: dict) -> None:
        self._require()
        try:
            status, frame = self._call("POST", ROUTES[kind][1], artifact)
        except httpx.ConnectError as exc:
            # The TCP connection never opened, so the artifact was not delivered.
            raise LedgerUnavailable(f"DRUNIX gateway unreachable; transaction not submitted ({exc}).") from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise LedgerOutcomeUnknown(f"Submission outcome unknown ({type(exc).__name__}).") from exc
        expected = {"state": "SUBMITTED", "transaction_id": artifact["transaction_id"]}
        if status != 200 or frame.get("data") != expected:
            raise LedgerOutcomeUnknown(f"Submission outcome unknown (gateway HTTP {status}).")

    def commit_status(self, kind: str, artifact: dict) -> CommitStatus:
        self._require()
        try:
            status, frame = self._call("POST", ROUTES[kind][2], artifact)
        except httpx.ConnectError as exc:
            raise LedgerUnavailable(f"DRUNIX gateway unreachable ({exc}).") from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise LedgerOutcomeUnknown(f"Commit status unavailable ({type(exc).__name__}).") from exc
        r = frame.get("data") if status == 200 else None
        if (not isinstance(r, dict) or set(r) != {"transaction_id", "code", "block_number", "successful"}
                or r["transaction_id"] != artifact["transaction_id"]
                or type(r["code"]) is not int or r["code"] < 0 or type(r["block_number"]) is not int
                or r["block_number"] < 0 or type(r["successful"]) is not bool or r["successful"] != (r["code"] == 0)):
            raise LedgerOutcomeUnknown(f"Commit status unavailable (gateway HTTP {status}).")
        return CommitStatus(r["transaction_id"], r["code"], r["block_number"], r["successful"])

    # ------------------------------------------------------------ reads
    def get_position(self, property_id: str, holder_id: str) -> dict[str, int]:
        """Owned units from GetBalance. The chaincode has no pledge records yet, so pledged is 0."""
        self._require()
        try:
            status, frame = self._call("GET", f"balances/{property_id}/{holder_id}")
        except (httpx.HTTPError, ValueError) as exc:
            raise LedgerUnavailable(f"DRUNIX balance read failed ({type(exc).__name__}).") from exc
        if status == 404:
            return {"owned": 0, "pledged": 0}
        b = frame.get("data") if status == 200 else None
        if (not isinstance(b, dict) or b.get("property_id") != property_id or b.get("holder_id") != holder_id
                or type(b.get("quantity")) is not int or b["quantity"] < 0):
            code = (frame.get("error") or {}).get("code", "") if isinstance(frame.get("error"), dict) else ""
            raise LedgerUnavailable(f"DRUNIX balance read failed (HTTP {status} {code}).".strip())
        return {"owned": b["quantity"], "pledged": 0}

    def health(self) -> dict[str, Any]:
        problem = self._config_problem()
        if problem:
            return {"status": "UNAVAILABLE", "detail": problem}
        try:
            status, frame = self._call("GET", "contract-info")
        except (httpx.HTTPError, ValueError) as exc:
            return {"status": "UNAVAILABLE", "detail": f"Gateway unreachable ({type(exc).__name__})."}
        info = frame.get("data") if status == 200 else None
        if not isinstance(info, dict) or not isinstance(info.get("functions"), list):
            return {"status": "DEGRADED", "detail": f"Gateway answered HTTP {status} without contract information."}
        missing = [f for f in ("IssueANSH", "TransferANSH") if f not in info["functions"]]
        detail = f"DRUNIX evaluate ok: {info.get('contract', 'tokansh')} with {len(info['functions'])} functions"
        return {"status": "DEGRADED" if missing else "CONNECTED",
                "detail": detail + (f"; missing {', '.join(missing)}" if missing else "") + ". Pledges not on-chain yet."}
