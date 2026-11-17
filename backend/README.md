# TokANSH Backend — Application Database

This directory currently holds the database layer of the FastAPI backend: models, migrations, seed data, the DML playbook and tests. API routes and services are added by their own modules.

| Read this | For |
|---|---|
| [`../docs/DATABASE.md`](../docs/DATABASE.md) | Design, source-of-truth map, rule-to-constraint table, open decisions |
| [`../docs/DATABASE_REFERENCE.md`](../docs/DATABASE_REFERENCE.md) | Every table, column, constraint and enum, plus all DML |
| [`sql/dml_playbook.sql`](sql/dml_playbook.sql) | The runnable DML for the demo journey |

## Layout

```text
backend/
├── alembic.ini
├── alembic/
│   ├── env.py                      reads DATABASE_URL; batch mode for SQLite
│   └── versions/                   0001 initial schema, 0002 issuer proposal
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
pytest                                            # 60 tests
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
