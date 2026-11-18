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

The status endpoint returns the existing frontend `SystemStatus` shape (`components` with `name`, `status` and optional `detail`; `last_ledger_operation: null`). FastAPI can be `CONNECTED` while the database is `UNAVAILABLE`. Database readiness requires the expected migration and application tables. The gateway and transaction capability remain `UNAVAILABLE`; DRUNIX network internals remain `UNKNOWN` because M2 does not query them. No network-down claim is made about an independently running DRUNIX deployment.

The frontend System Status screen can consume this response. Its business screens intentionally remain unavailable in Connected Mode; wiring the property UI and secure identity/session handling are later integration work. Preview Mode remains unchanged.

## Migrations and tests

Startup never calls `create_all` or automatically runs migrations. Run Alembic explicitly. SQLAlchemy metadata and the initial versioned migration are checked for agreement. The initial schema deliberately permits only `DRAFT` properties; future workflow milestones require reviewed migrations.

```bash
.venv/bin/python -m pytest
.venv/bin/python -m alembic check
```

Tests use temporary file-backed SQLite databases and actual migrations. They exercise precision, validation, role checks, idempotency/restart recovery, concurrent duplicate submissions, transactional rollback, pagination, CORS and honest component status. Isolated failure injection is test-only. These tests do not verify DRUNIX integration.

M2-specific error codes include `DATABASE_UNAVAILABLE`, `AUTHENTICATION_REQUIRED`, `AUTH_NOT_CONFIGURED` and `INTERNAL_ERROR`, alongside existing validation/conflict/reconciliation codes. Database URLs, SQL parameters, request bodies and raw exception contents are not returned in errors or logged by application handlers.
