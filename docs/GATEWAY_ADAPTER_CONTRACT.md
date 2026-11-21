# TokANSH — Backend ↔ DRUNIX Gateway Integration

**Status:** The backend uses the private TokANSH Go gateway in [`gateway/`](../gateway/README.md)
(contract: [`gateway/TRANSACTIONS.md`](../gateway/TRANSACTIONS.md)) and the chaincode in
[`chaincode/tokansh`](../chaincode/tokansh/README.md). This replaces the generic submit/evaluate
adapter proposed earlier in this file.

## 1. Lifecycle used by the backend

`backend/app/ledger/executor.py` follows the gateway's once-only pattern:

| Step | Ledger operation status | What happens | Ledger effect |
|---|---|---|---|
| 1 | `CREATED` | Operation row and exact chaincode command committed before any gateway call | none |
| 2 | `VALIDATING` | `POST …/prepare`: endorsement; signed artifact and DRUNIX transaction id saved (`ledger_operations.artifact_json`) | none |
| 3 | `SUBMITTED` | Database compare-and-set claims the single submission, committed **before** `POST …/submit` | may be on ledger |
| 4 | `COMMITTED` / `FAILED` / `RECONCILIATION_REQUIRED` | `POST …commit-status`; code 0 = valid | final, or reconcile |

Prepare failures are definitive (no ledger effect). A refused connection on submit means the artifact
was not delivered. Any other submit or status failure is `RECONCILIATION_REQUIRED`; reconciliation
re-queries commit status with the saved artifact and never resubmits. An operation left in
`VALIDATING` (process stopped before the claim) reconciles to `FAILED / LEDGER_NOT_SUBMITTED`.

## 2. Functions and commands

| Business step | Gateway routes (`/v1/tokansh/`) | Chaincode command (v1) | Status |
|---|---|---|---|
| Register approved property | `property-registrations/prepare`, `…/submit`, `commit-status` | `command_version, operation_id, property_id, issuer_id, approval_reference, approval_digest, approved_supply, issue_price_minor, currency` | Deployed (v1.0+) |
| Issue ANSH | `issuances/prepare`, `…/submit`, `…/commit-status` | `command_version, operation_id, property_id, quantity` | Deployed v1.1 |
| Transfer / purchase | `transfers/prepare`, `…/submit`, `…/commit-status` | `command_version, operation_id, property_id, from_holder_id, to_holder_id, quantity` | Chaincode v1.2, **not yet deployed** |
| Balance check | `GET balances/{property_id}/{holder_id}` | `GetBalance` | Deployed v1.1 |
| Readiness | `GET contract-info` | `GetContractInfo` | Deployed |
| Pledge | none yet | proposed: `command_version, operation_id, property_id, holder_id, pledge_id, quantity` | **Not implemented**: returns `LEDGER_FUNCTION_UNAVAILABLE` |
| Release pledge | none yet | proposed: `command_version, operation_id, property_id, holder_id, pledge_id` | **Not implemented** |

Identifiers on the ledger are application UUIDs: the property id is the approved property reference,
and holder ids are user ids. One pinned service identity (Org1 User1) signs every transaction on
behalf of these accounts (platform-mediated custody; not holder signatures). `approval_reference` is
the property review id and `approval_digest` is the SHA-256 of the off-chain approval record.

Until the chaincode records pledges, `GetBalance` has no pledged quantity, so the backend treats
ledger-pledged units as 0 and pledges fail safely. The rule "pledged units cannot be transferred"
needs `PledgeANSH`/`ReleasePledge` with an available-balance check in `TransferANSH`.

## 3. Configuration (backend)

| Variable | Value |
|---|---|
| `DRUNIX_GATEWAY_URL` | Loopback literal only, e.g. `http://127.0.0.1:8001` |
| `TOKANSH_GATEWAY_SECRET`, `TOKANSH_OPERATOR_SECRET` | The same two distinct 64-hex secrets as the gateway process |
| `DRUNIX_SIGNER` | Optional pin `Org1MSP:<sha256 of signer certificate>`; artifacts must match |
| `DRUNIX_GATEWAY_TIMEOUT_SECONDS` | Default 7 |

The backend holds the operator capability so the UI's Approve, Issue, Buy and Transfer actions can
submit. That is a deliberate local-demo choice; the team may instead keep writes as operator steps.

The gateway accepts only loopback calls, so the API, gateway and DRUNIX must run on one machine
(`scripts/tokansh-app.sh` starts the gateway, API and website together). Hosted on Render without a
gateway, every ledger step returns `LEDGER_UNAVAILABLE`.

## 4. Error mapping

| Gateway | Backend API |
|---|---|
| 409 `INSUFFICIENT_BALANCE` | 409 `INSUFFICIENT_AVAILABLE_ANSH` |
| 422 `ISSUANCE_LIMIT_EXCEEDED` | 409 `ISSUANCE_LIMIT_EXCEEDED` |
| 409 `IDEMPOTENCY_CONFLICT` | 409 `IDEMPOTENCY_CONFLICT` |
| 404 `PROPERTY_NOT_FOUND` (prepare) | 409 `PROPERTY_NOT_APPROVED` |
| 503 `LEDGER_UNAVAILABLE`, 504 `LEDGER_TIMEOUT` on prepare | 503, operation `FAILED` (no ledger effect) |
| Any failure after submission | 202, operation `RECONCILIATION_REQUIRED` |
| Commit status code ≠ 0 | 502 `LEDGER_COMMIT_FAILED` |
