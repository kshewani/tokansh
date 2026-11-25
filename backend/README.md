# TokANSH Backend

One FastAPI application (modular monolith, ADR-001) with the application database, the domain modules and the DRUNIX gateway client.

| Read this | For |
|---|---|
| [`../docs/API_CONTRACTS.md`](../docs/API_CONTRACTS.md) | Endpoints and conventions (section 15 lists implementation notes and deviations) |
| [`../docs/GATEWAY_ADAPTER_CONTRACT.md`](../docs/GATEWAY_ADAPTER_CONTRACT.md) | The private HTTP interface the Go DRUNIX adapter must expose |
| [`../docs/DATABASE.md`](../docs/DATABASE.md) | Database design, source-of-truth map, rule-to-constraint table |
| [`../docs/DATABASE_REFERENCE.md`](../docs/DATABASE_REFERENCE.md) | Every table, column, constraint and enum, plus all DML |

## Run the API

From `backend/`, Python 3.11 or newer:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head                 # creates data/tokansh.db
python -m scripts.seed_demo          # Meera, Admin, Aarav, Lender + simulated REITs
uvicorn app.main:app --reload        # http://localhost:8000/docs
```

Configuration comes from environment variables (see `../.env.example`). Ledger writes go through the
private TokANSH Go gateway in `../gateway` (set `DRUNIX_GATEWAY_URL=http://127.0.0.1:8001` plus
`TOKANSH_GATEWAY_SECRET` and `TOKANSH_OPERATOR_SECRET`). How the backend uses it, the command formats
and what is deployed are in [`../docs/GATEWAY_ADAPTER_CONTRACT.md`](../docs/GATEWAY_ADAPTER_CONTRACT.md).
**There is no simulator mode.** With the gateway unset or down, every ledger operation fails safely:
it is recorded as `FAILED / LEDGER_UNAVAILABLE`, nothing is reported as committed, and ownership does
not change. With DRUNIX running on the same machine, `../scripts/tokansh-app.sh start` launches the
gateway, this API and the website together (see the root README).

Then start the frontend (`cd ../frontend && npm install && npm run dev`) and open http://localhost:5173.
Vite forwards `/api` to `http://localhost:8000`.

## How each flow reaches DRUNIX

| Step | Endpoint | DRUNIX function | Without DRUNIX |
|---|---|---|---|
| Onboard, submit | `POST /properties`, `/submit` | none (application only) | works |
| Approve | `POST /properties/{id}/approve` | `RegisterApprovedProperty` | approval saved, registration `FAILED`, retry with `/register` |
| Issue | `POST /ansh/issuances` | `IssueANSH` | 503 `LEDGER_UNAVAILABLE`, issuance `FAILED` |
| List, buy | `POST /marketplace/listings`, `/orders` | `GetBalance` (read) | 503, nothing created |
| Pay | `POST /payments/simulate` | `TransferANSH` | 503 before any payment is taken |
| Transfer | `POST /ansh/transfers` | `GetBalance`, `TransferANSH` | 503 |
| Pledge, release | `POST /collateral/pledges`, `/release` | `PledgeANSH`, `ReleasePledge` (not in the chaincode yet) | 503 `LEDGER_FUNCTION_UNAVAILABLE` even with DRUNIX |
| Loans | `/loans/...` | none (lender simulator; fixed-term simple interest, paid interest-first) | works once a pledge is active |
| Distribution | `/distributions/...` | none: reconstructs record-date holdings from committed operations | works once ANSH is issued |
| Reconcile | `POST /ledger/operations/{id}/reconcile` | commit status by transaction id | 503 |

Demo sign-in: `POST /api/v1/auth/login` with `{"username", "password"}` returns a bearer token; send it
as `Authorization: Bearer <token>`. Usernames: `meera` (issuer), `admin`, `aarav` (investor) and the
fictional lenders `axim-bank`, `real-finance`, `horizon-credit`. Any non-empty password is accepted, so
this is **not** real authentication. Sessions live in memory: a restart (or a sleeping free Render
instance) signs everyone out. Login is refused when `APP_ENV=production` or `DEMO_AUTH_ENABLED=false`.
`GET /api/v1/auth/me` and `POST /api/v1/auth/logout` complete the set. Every service still checks the
caller's role. Consequential operations need an `Idempotency-Key` header.

**Lenders** (`GET /api/v1/financing/lenders`): Axim Bank 10% (6/12 months, max LTV 60%), Real Finance
9% (6/12/24 months, 55%), Horizon Credit 12% (3/6/12 months, 70%, capped by the platform's
`MAX_LTV_BPS`). A loan application names a lender and offer; rate and tenure must match the offer.
Each lender signs in separately and acts only on its own loans. All simulated.

**Demo wallet** (`GET /api/v1/wallet`, `POST /api/v1/wallet/fund`, `POST /api/v1/wallet/withdraw`):
simulated INR cash. Disbursement credits the borrower once; repayment debits the wallet and fails with
`INSUFFICIENT_DEMO_CASH` when short. No bank or real money.

## Code layout

```text
app/
├── main.py              create_app(): routers, error envelope, correlation id, CORS
├── core/                config, errors, money (paise <-> "0.00"), idempotency, audit, deps
├── ledger/
│   ├── port.py          LedgerPort interface and result types
│   ├── gateway_client.py  HTTP client for the Go adapter (the only runtime implementation)
│   ├── executor.py      write-before-submit, commit evidence, reconciliation, effect handlers
│   └── projections.py   ownership read model; record-date reconstruction
├── modules/             one module per domain: properties, issuance, marketplace (+ payments),
│                        transfers, portfolio, financing (pledges, loans, release),
│                        distributions, audit_api, system
└── db/                  models, enums, types, session (unchanged design, see below)
```

## API tests

| File | Covers |
|---|---|
| `test_api_demo_flow.py` | The 11-step demo of AGENTS.md section 8, end to end over HTTP |
| `test_api_failures.py` | Failed payment, chaincode rejection at endorsement, prepared-but-never-submitted, interest, DRUNIX unavailable, unknown outcome + reconciliation, commit failure + refund, idempotency, supply and role checks, pledge and LTV limits, record-date rule, rounding |
| `test_gateway_client.py` | The client against the private gateway contract: typed routes, both secrets, artifact checks, business-code mapping, submit/status ambiguity, loopback-only configuration; the running app never uses a test double |

These use `tests/fakes/fake_ledger.py`, a **test-only** stand-in whose transaction ids all start
with `TEST-ONLY-`. They prove application behaviour, not DRUNIX integration (API_CONTRACTS 13).

`tests/e2e_server.py` starts the API with that fake for automated browser tests of the frontend.
It refuses to run without `TOKANSH_E2E_TEST=1` and is not a demo mode.

---

# Application database

## Layout

```text
backend/
├── alembic.ini
├── alembic/
│   ├── env.py                      reads DATABASE_URL; batch mode for SQLite
│   └── versions/                   0001 initial schema, 0002 issuer proposal, 0003 ledger payload
├── app/db/
│   ├── base.py                     declarative base, naming convention, column helpers
│   ├── types.py                    UTCDateTime
│   ├── enums.py                    all status and type enumerations
│   ├── session.py                  engine, SQLite pragmas, FastAPI session dependency
│   └── models/                     one file per domain module (26 tables)
├── scripts/
│   ├── seed_demo.py                synthetic demo data
│   ├── gen_db_reference.py         regenerates docs/DATABASE_REFERENCE.md
│   └── playbook.py                 parser for the DML playbook
├── sql/dml_playbook.sql
├── tests/
└── requirements.txt
```

## Quick start

Run from `backend/`. Python 3.11 or newer.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

export DATABASE_URL=sqlite:///./data/tokansh.db   # the default if unset
alembic upgrade head                              # creates data/tokansh.db with all 26 tables
python -m scripts.seed_demo                       # 4 demo users + simulated REIT holdings
pytest                                            # 78 tests (60 database + 18 API)
```

`data/` and `*.db` are already git-ignored.

## Commands

| Task | Command |
|---|---|
| Create or upgrade the database | `alembic upgrade head` |
| Roll back everything | `alembic downgrade base` |
| Check models and migrations agree | `alembic check` |
| New migration after a model change | `alembic revision --autogenerate -m "what changed"` |
| Seed users and REIT data | `python -m scripts.seed_demo` |
| Also seed TechPark One as a draft | `python -m scripts.seed_demo --with-property` |
| Regenerate the reference document | `python -m scripts.gen_db_reference` |
| Run tests | `pytest` |
| Reset a local database | delete `data/tokansh.db`, then `alembic upgrade head` |

## Seed data

All seed data is synthetic. Re-running the seed is safe; existing rows are skipped.

| Seeded | Detail |
|---|---|
| Users | Meera (ISSUER), Platform Admin (ADMIN), Aarav (INVESTOR), Demo Lender (LENDER) |
| REIT holdings | Two invented REITs for Aarav, flagged simulated |
| `--with-property` | TechPark One (Bengaluru) as `DRAFT`, ₹100 crore, proposing 100,000 ANSH at ₹10,000, with three document references and two valuations |

The seed never creates issuances, positions, pledges, listings or ledger operations. Those rows may only follow a real DRUNIX commit, and a test asserts the seed leaves them empty.

## Using the database from code

```python
from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models as m
from app.db.session import get_session

def portfolio(user_id: str, db: Session = Depends(get_session)):
    rows = db.execute(select(m.OwnershipPosition).where(m.OwnershipPosition.investor_id == user_id)).scalars()
    return [{"owned": r.owned_quantity, "pledged": r.pledged_quantity, "available": r.available_quantity,
             "ledger_reference": r.ledger_reference, "observed_at": r.observed_at} for r in rows]
```

Rules for anyone writing to these tables:

1. **Money is paise.** `amount_minor = 1000000` is ₹10,000. Convert at the API boundary; never store or compute with floats.
2. **Timestamps are aware UTC.** Use `app.db.types.utcnow()`. A naive `datetime` raises an error.
3. **Create engines with `make_engine`.** It enables SQLite foreign keys.
4. **Write the `ledger_operations` row before calling the gateway**, then update it with what DRUNIX returns. Update projections only after `COMMITTED`.
5. **Never generate a transaction id.** The database rejects a commit without one, and rejects the same id twice.
6. **Guard status updates** with the expected current status in `WHERE`, as the playbook does, and check that one row changed.

## The DML playbook

`sql/dml_playbook.sql` lists every statement for the demo, in order: onboarding, approval, DRUNIX registration, issuance, listing, purchase (success, payment failure, unknown ledger outcome), pledge, loan, distribution, repayment and release, then the read queries.

`tests/test_dml_playbook.py` runs the whole file against a migrated database and checks the documented end state: Aarav owns 500 ANSH with 0 pledged, the loan is repaid, entitlements sum to the declared amount, and no reconciliation case is open. The transaction ids used in that test are stand-ins; in the running application they come from DRUNIX.

## Tests

| File | Covers |
|---|---|
| `test_schema.py` | Table list, migration equals models, clean downgrade, no float/numeric columns, UUID keys, UTC timestamps, REIT isolation, foreign keys on, reference document current |
| `test_invariants.py` | One test per business rule: the database must refuse the bad row |
| `test_seed.py` | Seed is idempotent and creates no ledger-backed state |
| `test_dml_playbook.py` | Playbook runs end to end and reconciles |

These tests use SQLite only and do not touch DRUNIX. They are not DRUNIX integration tests.

## Moving to PostgreSQL later

Set `DATABASE_URL` to a PostgreSQL URL, add a driver such as `psycopg`, and run `alembic upgrade head`. The schema uses portable types and SQL, but this has not been run yet; test it before relying on it.
