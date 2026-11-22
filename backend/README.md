# TokANSH M2 — Backend Foundation

FastAPI modular monolith with typed environment configuration, injected database sessions and demo actors, SQLAlchemy repositories/services, and Alembic-managed SQLite persistence. This milestone implements **off-chain property drafts only**. Approval, verification, approved-property registration, issuance, ownership and financial workflows are not implemented here.

## Local setup

Python 3.10+ is required. From `backend/`:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
cp .env.example .env
.venv/bin/python -m alembic upgrade head
.venv/bin/python -m app
```

`python -m app` uses `APP_HOST`, `APP_PORT` and `LOG_LEVEL`. The default bind address is loopback. Alternatively:

```bash
.venv/bin/python -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000
```

Configuration is loaded from the environment and a local `.env`. The default database is `backend/data/tokansh.db` when commands run from `backend/`; use an absolute SQLite URL when invoking commands elsewhere. Environment values override `.env`. Migration configuration never embeds credentials.

First-time setup and validation (run from `backend/`):

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock.txt
cp .env.example .env
.venv/bin/python -m alembic upgrade head
.venv/bin/python -m pytest -q
.venv/bin/python -m app
```

`requirements.lock.txt` records the complete development/test dependency set used for validation. `requirements.txt` and `requirements-dev.txt` declare the supported direct dependencies. No schema is automatically created or upgraded when the API starts: missing or outdated migrations make database-backed operations unavailable. OpenAPI, Swagger UI and ReDoc are available at `/openapi.json`, `/docs` and `/redoc` after starting the API.

This development environment lacked Debian's `ensurepip`. Validation used `python3 -m venv --without-pip .venv` followed by system pip with `--target .venv/lib/python3.10/site-packages`. Dependencies remained isolated; system packages were not changed. Normal setups should use the standard commands above.

## Implemented API

Successful responses use `{data, meta: {correlation_id}}`. Application errors use `{error: {code, message, details}, meta: {correlation_id}}`. Responses expose `X-Correlation-ID`, including errors. Incoming IDs must contain 1–128 ASCII letters, digits or `._:-`; missing IDs are generated as application correlation IDs, never ledger evidence.

| Method | Route | Behavior |
|---|---|---|
| GET | `/health` | Process liveness |
| GET | `/ready` | Overall readiness; **503** while mandatory gateway/DRUNIX transaction integration is unavailable |
| GET | `/api/v1/system/status` | Actual application/database observations and explicit unverified ledger components |
| GET | `/api/v1/system/configuration` | Non-secret environment/demo-auth flags only |
| POST | `/api/v1/properties` | Create an idempotent off-chain draft; 201 |
| GET | `/api/v1/properties` | Paginated property records |
| GET | `/api/v1/properties/{property_id}` | Fetch a property by its generated UUID |

Property endpoints require `X-Demo-Role`. Only `ADMIN` and `ISSUER` can create; all four supported demo roles can read. Actors are predefined application UUIDs. This is **spoofable local demo identity selection**, not production authentication or ledger authorization. Production configuration rejects enabled demo authentication; disabling it leaves property routes unavailable until real authentication is implemented. There is no global active-role state shared between users.

Creation also requires `Idempotency-Key` (1–128 characters using the same character set as correlation IDs). Its uniqueness scope is the demo actor; request fingerprints also include method, endpoint and canonical validated payload. The same actor/key/payload replays the original 201 resource after restarts; conflicting reuse returns 409 `IDEMPOTENCY_CONFLICT`. Incomplete persisted operations return `RECONCILIATION_REQUIRED`, without creating another property. A database uniqueness constraint handles concurrent duplicates.

Property, application operation and `APPLICATION` audit event commit together. An application operation's `COMPLETED` status denotes local database success, **not DRUNIX COMMITTED**. Operation/event IDs are application UUIDs. No fabricated ledger IDs or ledger state are stored.

Example creation payload matches the current frontend `NewProperty` contract:

```json
{
  "name": "TechPark One",
  "location": "Bengaluru, Karnataka",
  "category": "Commercial office",
  "valuation": "1000000000.00",
  "proposed_supply": 100000,
  "issue_price": "10000.00",
  "currency": "INR"
}
```

Money must be positive decimal **strings**, without exponents and with at most two decimal places (maximum 14 whole digits). Storage uses integer paise; responses use two-decimal strings. Quantities are positive whole integers bounded by JavaScript's safe integer range. No floating-point financial calculation or implicit rounding occurs. Property names are not assumed unique: independent properties can share names; idempotency protects duplicate requests.

Responses retain existing `id`, `name`, `location`, `category`, `valuation`, `unit_price`, `approved_supply`, `status`, `issuer_id` and nullable `ledger_transaction_id` fields. M2 adds `proposed_supply`, `currency`, `created_at`, `verification_status` and `ledger_registration_status`. Drafts always have `approved_supply: 0`, `status: DRAFT`, `verification_status: NOT_VERIFIED`, `ledger_registration_status: NOT_REGISTERED` and no ledger transaction ID. Proposed supply never implies approved/issued supply. Authoritative fields and other unexpected inputs are rejected.

List responses follow the existing pagination convention: `items`, `page`, `page_size`, `total_items`, `total_pages`; defaults 1/20 and maximum page size 100. Empty lists have zero total pages. Unimplemented routes, including ledger operations, return structured 404 errors without a fallback.

## React development integration

Keep the frontend's existing behavior. In `frontend/.env.local`:

```dotenv
VITE_API_MODE=real
VITE_API_BASE_URL=http://localhost:8000
```

The base URL must **not** include `/api/v1`. Restart Vite after changing its environment. CORS permits `http://localhost:5173` and `http://127.0.0.1:5173`, credentials and the documented request headers; correlation IDs are exposed. Other origins are not granted browser access. CORS is not authentication.

The status endpoint returns the existing frontend `SystemStatus` shape (`components` with `name`, `status` and optional `detail`; `last_ledger_operation: null`). FastAPI can be `CONNECTED` while the database is `UNAVAILABLE`. Database readiness requires the expected migration and application tables. Without M3.2 gateway configuration, the gateway remains `UNAVAILABLE` and DRUNIX connectivity remains `UNKNOWN`. With configuration, live read observations determine gateway and network connectivity; transaction capability stays `UNAVAILABLE`. Individual DRUNIX internals remain `UNKNOWN`. No network-down claim is made about an independently running DRUNIX deployment.

The frontend System Status screen can consume this response. Its business screens intentionally remain unavailable in Connected Mode; wiring the property UI and secure identity/session handling are later integration work. Preview Mode remains unchanged.

## Migrations and tests

Startup never calls `create_all` or automatically runs migrations. Run Alembic explicitly. SQLAlchemy metadata and the initial versioned migration are checked for agreement. The initial schema deliberately permits only `DRAFT` properties; future workflow milestones require reviewed migrations.

```bash
.venv/bin/python -m pytest
.venv/bin/python -m alembic check
```

Tests use temporary file-backed SQLite databases and actual migrations. They exercise precision, validation, role checks, idempotency/restart recovery, concurrent duplicate submissions, transactional rollback, pagination, CORS and honest component status. Isolated failure injection is test-only. The default suite uses isolated gateway test doubles; real read verification is explicitly opt-in as described below.

M2-specific error codes include `DATABASE_UNAVAILABLE`, `AUTHENTICATION_REQUIRED`, `AUTH_NOT_CONFIGURED` and `INTERNAL_ERROR`, alongside existing validation/conflict/reconciliation codes. Database URLs, SQL parameters, request bodies and raw exception contents are not returned in errors or logged by application handlers.

## M3.2 read-only DRUNIX integration

See [gateway setup, private API and verification](../gateway/README.md). Start that service separately, then configure `DRUNIX_GATEWAY_URL=http://127.0.0.1:8001` and optionally `DRUNIX_GATEWAY_TIMEOUT_SECONDS=7` in the backend environment. With no URL, reads fail explicitly; there is no fallback. HTTPX is now a runtime dependency (the existing lock already pins it).

`GET /api/v1/diagnostics/drunix/basic/assets` requires `X-Demo-Role: ADMIN`. It returns the standard `{data,meta}` envelope containing `source: DRUNIX_EVALUATE`, `channel`, `chaincode`, `function`, `observed_at` and the basic-chaincode assets in `result`. These are diagnostic sample assets, not TokANSH properties or ANSH holdings. Errors are structured and sanitized. HTTP 502 means malformed/untrusted upstream data, 503 unavailable connectivity and 504 timeout. Correlation IDs propagate across both HTTP boundaries; reads do not need idempotency keys.

The shared synchronous HTTPX client is injected through `get_gateway` and closed at application shutdown. Proxy environment variables and redirects are disabled; only explicit loopback origins are accepted. Responses have bounded size, strict schemas, fresh observation timestamps and matching correlation metadata. Python 3.10 parsing supports Go RFC3339Nano timestamps. No signing material enters Python.

System Status probes gateway liveness and actual GetAllAssets evaluation independently. Gateway liveness alone never proves DRUNIX connectivity. A failed bridge makes network status UNKNOWN; a successful bridge returning a ledger connectivity error makes it UNAVAILABLE. An invalid diagnostic payload leaves connectivity UNKNOWN. Peer/orderer/validation/database internals remain UNKNOWN. Read connectivity does not prove transaction submission or commitment: `/ready` remains 503, transaction capability remains UNAVAILABLE and `last_ledger_operation` stays null. The existing configuration field `ledger_integration: NOT_IMPLEMENTED` continues to describe core ANSH transaction integration, preserving its M2 contract.

Frontend behavior and Connected Mode business restrictions are unchanged. Local demo role headers remain spoofable; this endpoint is not production authentication. No submission, automatic retries, ledger transaction IDs or commitment evidence are implemented.

## M3.3b private transaction foundation

[Private gateway contracts and operator lifecycle](../gateway/TRANSACTIONS.md) describe the implementation. SQLite migration `0002_registration` owns durable ledger operations separately from M2 draft operations. No browser API or Connected Mode business workflow is enabled. Apply migrations explicitly; retain recovery artifacts and credentials until all operations have been reconciled. Real ledger writes and deployment were not performed during this milestone.

## M4.2 supervised investor transfers (local implementation)

The new FastAPI routes use the existing private Gateway and its typed
`TransferANSH` prepare → submit → commit-status sequence. No new migration is
needed: `application_operations` stores transfer workflow, simulated settlement,
operation UUID and the private recovery artifact. Registration's `ledger_operations`
and M2 property behavior are unchanged. Investor identities remain the predefined
`DEMO_ACTORS`; there is no investor registry, wallet signing or holder-consent proof.
The platform's pinned Org1 User1 signs on behalf of these UUID accounts.

Configure existing `DRUNIX_GATEWAY_URL=http://127.0.0.1:8001`,
`TOKANSH_GATEWAY_SECRET` and `TOKANSH_OPERATOR_SECRET` exclusively on the backend.
The browser sends no bearer secret or operator capability. FastAPI attaches the
Gateway bearer and operator capability only to its private Gateway requests.
`TOKANSH_TRANSFER_SECRET` is not required or used. Never put Gateway credentials
in Vite configuration, browser storage or Git. Production transfers fail closed.
Browser-facing routes reuse the existing `X-Demo-Role` selection and actor/ownership
checks. This spoofable identity mechanism is accepted only for the controlled local
hackathon demo, not production authentication or proof of holder consent.
Use the existing persistent, migrated, owner-only SQLite database; preserve its
backups and recovery artifacts privately.

| Method | Endpoint | Behavior |
|---|---|---|
| POST | `/api/v1/ansh/transfers` | Initiate acquisition or secondary transfer |
| GET | `/api/v1/ansh/transfers/{operation_id}` | Cached workflow details, never artifact bytes |
| GET | `/api/v1/ansh/transfers/{operation_id}/status` | Same cached status; no Gateway call or mutation |
| POST | `/api/v1/ansh/transfers/{operation_id}/reconcile` | Commit-status query only; updates SQLite, never resubmits |
| GET | `/api/v1/ansh/balances/{property_id}/{holder_id}` | Fresh authenticated Gateway balance evaluation |

Transfer initiation and status/reconcile require `X-Demo-Role: INVESTOR` or `ISSUER`
only; no Authorization header is needed. Initiation additionally
requires `Idempotency-Key` (1–128 letters/digits/`._:-`). Balance reads require only
a supported demo role. Existing React origins and demo request headers are unchanged.
All responses preserve `{data,meta}` and correlation IDs. Example acquisition body:

```json
{
  "asset_id": "f6169750-4676-4e99-887f-2bc5471bd518",
  "from_user_id": "00000000-0000-4000-8000-000000000002",
  "to_user_id": "00000000-0000-4000-8000-000000000003",
  "quantity": 4,
  "kind": "ACQUISITION",
  "payment_outcome": "SUCCESS"
}
```

`asset_id` is the registered property UUID. For acquisition the selected investor
must be the recipient, and the seller must match the issuer read from DRUNIX.
For secondary movement use `kind: TRANSFER`, sender equal to the selected demo
holder, and a different recipient UUID. Example: investor `.003` sends to a
synthetic holder such as `00000000-0000-4000-8000-000000000005`. Recipient UUIDs do
not imply registered/KYC-verified users. There is currently only one predefined
investor login; that investor can acquire and then transfer to another holder.
Quantity is a positive integer bounded by 9007199254740991; no floating-point
quantity or monetary calculation is used. Balance precheck is advisory; chaincode
atomically enforces the final available balance. No pledge model is enabled here.

Payment is always explicitly `simulated: true`; `payment_outcome` defaults to
SUCCESS. FAILED persists `PAYMENT_FAILED` and never prepares/submits a transaction.
There is no actual payment processor, price settlement or atomic DvP. Invalid commit
after simulated success needs manual simulated compensation/review.

Successful response `data` includes `operation_id`, `transaction_id`,
`state: COMMITTED_VALID`, `ownership_confirmed: true`, request, simulated payment,
and `commit: {transaction_id, code: 0, block_number, successful: true}` from the
Gateway's real commit-status response. No transaction IDs or block numbers are
synthesized by the runtime. Pending/ambiguous initiation returns HTTP 202 with
`ownership_confirmed: false`, persisted operation ID and transaction ID when known.
Insufficient balance returns sanitized HTTP 409 `INSUFFICIENT_BALANCE` and the
operation ID in `error.details`. Only the initiating actor can inspect/reconcile
its workflow. GET statuses label `status_source: PERSISTED_WORKFLOW`; terminal
cached evidence is not a fresh ledger reconciliation or current portfolio balance.

A durable unique actor/key claim precedes preparation; the endorsed artifact is
persisted before a compare-and-set claims `SUBMISSION_PENDING`. The same key/body
returns the stored workflow without preparing or submitting again; changed payloads
conflict. SQLite is never authoritative for holdings. PREPARING/PREPARED after a
process crash requires operator review; this API intentionally has no resume-submit,
force or retry endpoint. SUBMISSION_PENDING/SUBMITTED/UNKNOWN can only reconcile
using the stored original artifact. Failed or ambiguous submission is never retried;
only confirmed valid commit permits `ownership_confirmed`. Keep the same key and
operation ID; do not create a new key to bypass uncertainty. Local database integrity
and single supervised operator are trusted, with no global exactly-once claim.

Frontend integration: call this API, retain the key/operation ID, show pending or
UNKNOWN honestly, use the explicit reconciliation endpoint when needed, and fetch
balances afresh for portfolios. Disable repeated clicks and do not retry financial
POSTs automatically. No React screen is enabled by this change. The running backend
has not been restarted; deployment/configuration needs a separately authorized
checkpoint. No live transfers were executed during implementation.

## Financing and demo cash wallet — local hackathon only

All routes use `{data,meta}` / structured error envelopes and existing
`X-Demo-Role: INVESTOR` or `LENDER`. Demo-role headers are spoofable local workspace
selection, **not production authentication**. Gateway secrets remain server-side.
No new credentials are required. Production execution is disabled.

| Method | Endpoint | Role / behavior |
|---|---|---|
| GET | `/api/v1/financing/lenders` | Either role; three fictional lenders and illustrative offers |
| GET | `/api/v1/financing/eligibility/{property_id}` | Investor; fresh DRUNIX ownership and global simulation reservations |
| GET | `/api/v1/financing/applications` | Investor's own loans; lender's selected workspace queue |
| POST | `/api/v1/financing/applications` | Investor; `Idempotency-Key` required |
| POST | `/api/v1/financing/applications/{id}/assess`, `/approve`, `/reject`, `/disburse` | Lender only; assigned institution only |
| POST | `/api/v1/financing/applications/{id}/repay`, `/release` | Borrower only; full wallet repayment, then separate reservation release |
| GET | `/api/v1/demo-wallet` | Investor's simulated INR cash balance |
| GET | `/api/v1/demo-wallet/activity` | Investor's saved simulated cash entries |
| POST | `/api/v1/demo-wallet/fund` | Explicit Add Demo Funds; `Idempotency-Key` required |
| POST | `/api/v1/demo-wallet/withdraw` | Simulated bank withdrawal; `Idempotency-Key` required |

Lender queue and decision requests accept `?lender_id=axim-bank`, `real-finance`
or `horizon-credit`. The server validates this allowlist and application assignment.
Omitting the parameter defaults to `axim-bank` for existing client compatibility.
The single LENDER persona can select any listed institution; this does not establish
real institutional membership or tenant isolation. Investors cannot self-assess,
approve, reject or disburse, even when repeating an already-completed action.

Application example (`X-Demo-Role: INVESTOR`, stable `Idempotency-Key`):

```json
{"property_id":"f6169750-4676-4e99-887f-2bc5471bd518","asset_class":"ANSH","quantity":1,"lender_id":"axim-bank","offer_id":"axim-standard","unit_value_minor":"1000000","ltv_percent":60,"annual_rate_bps":1000,"term_months":12}
```

The catalogue supplies exact rates, maximum LTV and supported tenures. Requests
must match the selected offer's rate/tenure and stay within its LTV limit; REITs
are rejected. Old request shapes default to Axim's standard offer. Invalid terms
are rejected rather than silently repriced. Each new JSON loan saves `lender_id`,
`offer_id`, immutable `terms_snapshot` and latest `reviewer_context`; its timeline
records acting roles and timestamps. Unit values, offers, decisions and all cash
movements are illustrative. Simple fixed-term interest uses integer-paise half-up
rounding; principal rounds down. No accrual, fees or partial repayments.

Workflow: APPLIED → ASSESSED → APPROVED → DISBURSED → REPAID → RELEASED.
Lenders may reject APPLIED/ASSESSED requests; inadequate holdings also reject them.
Approval rechecks fresh DRUNIX holdings before a short `BEGIN IMMEDIATE` transaction
which checks reservations **across every lender and legacy loan**. Network I/O
holds no SQLite write lock. APPROVED/DISBURSED/REPAID reserve units until release.
These are application reservations, **not blockchain locks or legal pledges**:
reserved ANSH remain transferable on DRUNIX. A read can become stale after it is
observed; there is no atomic ledger pledge. M4 balances/transfers are unchanged.

Disbursement credits principal once in the same transaction as the loan update.
Repayment debits the full quoted amount and updates the loan atomically; insufficient
cash leaves both unchanged. Repayment retains the reservation until explicit release.
Repeated completed actions have no additional effect. Unique `(loan_id,kind)` entries
also protect against duplicate disbursement/repayment. No global exactly-once claim
is made outside this trusted SQLite service.

Wallet mutation body: `{"amount_minor":"60000"}` (integer paise string, no decimals).
`fund` explicitly creates simulated money; `withdraw` debits it and records
`SIMULATED_COMPLETED`, without contacting a bank or collecting bank credentials.
All entry responses contain an off-chain `id`, `kind`, `amount_minor`,
`balance_after_minor`, `loan_id`, `created_at`, `currency: "INR"`, `simulated: true`
and `status: "SIMULATED_COMPLETED"`. Wallet balances are strings. Amounts and total
cash are capped at 9,007,199,254,740,991 paise. A stable wallet key returns the original
entry; reusing it with a different amount/action conflicts. Top-ups and withdrawals
share a key namespace; internal loan keys are separate. Do not retry mutations with
new keys after an uncertain HTTP outcome; reuse the original key or inspect history.

### Additive migration and compatibility

Migration `0003_demo_cash` adds `demo_cash_accounts` and `demo_cash_entries` with
foreign keys, nonnegative balance checks, bounded amounts and uniqueness constraints.
Application JSON stays in `application_operations`; historical records are not
rewritten. The migration **does not credit existing DISBURSED loans** or infer cash
from synthetic distributions. An empty wallet reads as zero without creating an account.
Legacy loans remain visible to their borrower and reserve units globally. A legacy
DISBURSED loan can be repaid using explicitly added demo funds, then released.
Loans without a lender assignment cannot enter lender decision queues or be newly
disbursed; deliberate legacy assignment would require a separately reviewed change.

A separately authorized operator must back up the persistent database and execute
`cd backend && .venv/bin/alembic upgrade head` with the intended existing DATABASE_URL
before deploying this version. No startup migration is performed. Readiness requires
`0003_demo_cash`; an old schema fails closed. No live database migration or service
restart was performed during implementation. Existing audited M3 runbook schema
assertions for revision 0002 require a separate update before reuse with this schema.

Frontend follow-up: add lender comparison/workspace selection, separate lender decision
controls from investor actions, and connect explicit wallet funding/withdrawal/repayment.
Current M5 investor-side lender buttons will correctly return 403. No browser secrets
or new Gateway/chaincode endpoints are needed. Financing and cash remain simulated;
only fresh ANSH ownership reads are DRUNIX-backed.
