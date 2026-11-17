# TokANSH — Go DRUNIX Gateway Adapter: Private HTTP Contract

**Status:** Implemented on the Python side (`backend/app/ledger/gateway_client.py`). The Go adapter that serves it is **not built yet**.
**Scope:** The private interface between FastAPI and the Go adapter (ADR-004, API_CONTRACTS section 9). It is a TokANSH contract, **not a DRUNIX API**. The adapter turns these calls into DRUNIX gateway calls (evaluate, submit, commit status) using the identity, TLS and endpoints of the DRUNIX network, which must be verified against the DRUNIX source and the running network.

Base URL: `DRUNIX_GATEWAY_URL`. The adapter must never be exposed publicly.

## 1. Endpoints

### `POST /v1/transactions/submit`

```json
{"channel": "mychannel", "chaincode": "tokansh", "function": "TransferANSH",
 "args": ["ANSH-TECHPARK-ONE-1A2B3C4D", "meera", "aarav", "500"],
 "operation_id": "uuid", "correlation_id": "uuid"}
```

Response (any HTTP status; the body decides):

```json
{"state": "COMMIT_CONFIRMED", "transaction_id": "<as returned by DRUNIX>", "block_number": 42,
 "validation_code": "VALID", "result": {}, "error": null}
```

| `state` | Meaning | Backend action |
|---|---|---|
| `NOT_SUBMITTED` | Definitively never ordered (endorsement refused, bad request) | `FAILED`, `error.code` kept (business codes become 409) |
| `SUBMITTED` | Ordered; commit not yet observed | Polls `/status`; still unknown -> `RECONCILIATION_REQUIRED` |
| `COMMIT_CONFIRMED` | Committed and valid | `COMMITTED`, projections updated |
| `COMMIT_FAILED` | Committed as invalid | `FAILED` (`LEDGER_COMMIT_FAILED`) |
| `UNKNOWN` | Outcome cannot be established | `RECONCILIATION_REQUIRED`, never resubmitted |

The Python client also treats a timeout or an unreadable response as `UNKNOWN`, and a refused connection as "not submitted". `COMMIT_CONFIRMED` without a `transaction_id` is treated as `UNKNOWN`.

### `GET /v1/transactions/{transaction_id}/status?channel=...`

Same body shape as submit. Used for polling and reconciliation.

### `POST /v1/transactions/evaluate`

`{"channel", "chaincode", "function", "args"}` -> `{"result": {...}}` or `{"error": {"code", "message"}}`.

### `GET /health`

`{"status": "CONNECTED" | "DEGRADED" | "UNAVAILABLE", "detail": "..."}`. Reports real gateway connectivity, not just that the adapter process is up.

## 2. Chaincode functions the backend calls

Proposed TokANSH chaincode (DRUNIX_INTEGRATION 6.2). Arguments are strings, in this order.

| Function | Args | Must enforce |
|---|---|---|
| `RegisterApprovedProperty` | propertyRef, issuerIdentity, approvedSupply | unique reference |
| `IssueANSH` | assetId, propertyRef, quantity, issuerIdentity | property registered; quantity <= approved supply; one issuance per asset |
| `TransferANSH` | assetId, fromIdentity, toIdentity, quantity | quantity <= owned - pledged (at execution time) |
| `PledgeANSH` | assetId, ownerIdentity, quantity, pledgeId | quantity <= available; unique pledgeId |
| `ReleasePledge` | assetId, ownerIdentity, pledgeId | pledge exists and is active |
| `GetPosition` (evaluate) | assetId, ownerIdentity | returns `{"owned": int, "pledged": int}`; unknown position = zero or error `POSITION_NOT_FOUND` |

Business rejections should use the error codes `INSUFFICIENT_AVAILABLE_ANSH`, `PLEDGED_UNITS_RESTRICTED`, `ISSUANCE_LIMIT_EXCEEDED`, `PROPERTY_NOT_APPROVED` and `INVALID_OPERATION_STATE`, so the API can report them as 409.

## 3. Open points to verify against DRUNIX

1. The Go gateway client API and versions in the DRUNIX repository (`drunix-network/asset-transfer-basic/application-gateway-go`).
2. Whether submit returns after commit (Fabric-style `Submit`) or needs a separate commit-status wait.
3. How to obtain the block number for a transaction.
4. Identity model: one custodial client identity with owner references in arguments (assumed here) or per-user identities.
5. Whether `operation_id` can be passed to the chaincode for duplicate detection.
