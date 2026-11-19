# TokANSH

**Unlocking Real Estate, One Ansh at a Time**

TokANSH is a real-estate tokenisation and asset lifecycle management
prototype built around DRUNIX enterprise distributed ledger technology.

The platform demonstrates how fractional real-estate interests represented
by ANSH units can be issued, owned, transferred, pledged as collateral,
released and incorporated into supporting financial workflows.

The emphasis is not merely on token issuance, but on the complete lifecycle
of tokenised asset interests.

> **Prototype disclaimer:** TokANSH is a hackathon prototype. ANSH does not
> automatically represent registered legal property title or direct legal
> ownership of the underlying property. Lending, payment processing,
> valuations and other supporting services may be simulated and must be
> identified as such.

---

## 1. Project Objectives

TokANSH demonstrates:

- Property onboarding and approval workflows.
- DRUNIX-backed ANSH issuance.
- Ledger-backed ownership records.
- ANSH marketplace and transfers.
- Investor portfolio management.
- ANSH collateral pledges and release.
- Simulated collateral-backed financing.
- Rental income entitlement calculations.
- Simulated rental distributions.
- Asset lifecycle history and auditability.
- Consolidated ANSH and REIT portfolio views.

Core ANSH ledger operations must execute against DRUNIX. They must never
silently fall back to simulated ledger state.

## 2. Demonstration Scenario

The primary demonstration uses the illustrative property TechPark One.

| Attribute | Value |
|---|---:|
| Property valuation | ₹100 crore |
| Total ANSH supply | 100,000 |
| Issue price | ₹10,000 per ANSH |
| Investor | Aarav |
| Investor purchase | 500 ANSH |
| Purchase value | ₹50 lakh |
| Collateral pledge | 200 ANSH |
| Available after pledge | 300 ANSH |

The demonstration covers:

1. Meera registers TechPark One and submits its documents.
2. The application reviewer verifies the evidence and approves the property.
3. The backend registers the approved property reference and issuance
   constraints through `RegisterApprovedProperty` on DRUNIX.
4. After confirmed DRUNIX commitment, 100,000 ANSH are issued.
5. Aarav purchases 500 ANSH.
6. Simulated payment succeeds and the DRUNIX transfer commits.
7. Aarav views his portfolio.
8. Aarav pledges 200 ANSH through DRUNIX.
9. An attempted transfer involving pledged units is rejected.
10. Rental entitlement is calculated using verified record-date DRUNIX
    ownership.
11. Rental payment is simulated.
12. Aarav completes simulated loan repayment.
13. Collateral release commits through DRUNIX.
14. Portfolio and lifecycle history reflect the final state.

## 3. Architecture Overview

TokANSH uses a modular monolith architecture.

### Application components

| Component | Technology | Responsibility |
|---|---|---|
| Frontend | React + TypeScript | User experience |
| Backend | Python + FastAPI | Business workflows and orchestration |
| Gateway adapter | Go | DRUNIX connectivity |
| Ledger | DRUNIX | Core ANSH state and transactions |
| Application database | SQLite initially | Application workflows and projections |
| Ledger state database | DRUNIX-managed YugabyteDB in the researched test-network configuration | Internal DRUNIX state |

The Go gateway adapter is a separate integration component. FastAPI
communicates with it through a documented internal interface.

### Logical architecture

```text
React + TypeScript
        |
        v
Python + FastAPI
        |
        +----------------------+
        |                      |
        v                      v
Application Database     Go DRUNIX Gateway
                               |
                               v
                         DRUNIX Network
                               |
                               v
                         TokANSH Chaincode
```

### Source-of-truth boundaries

**DRUNIX is authoritative for:**

- Approved property references and approved issuance constraints registered
  through `RegisterApprovedProperty`.
- ANSH issuance.
- ANSH ownership.
- ANSH transfers.
- ANSH pledges.
- ANSH collateral release.
- Relevant ledger-backed asset lifecycle records.

**TokANSH application database is responsible for:**

- Property onboarding, document management, verification evidence and
  application-level approval decisions.
- Marketplace orders and workflow metadata.
- Simulated payments.
- Simulated loan applications and repayments.
- Distribution calculations and simulated payments.
- Application users and demonstration roles.
- Application audit records.
- Read models and portfolio projections.

Property approval is an application-level decision, not a DRUNIX
transaction. ANSH issuance must remain blocked until the approved property
reference and issuance constraints have been registered and confirmed
committed on DRUNIX.

Distribution entitlement must use verified record-date ownership from
DRUNIX. If a reliable historical snapshot or event reconstruction is
unavailable, entitlement calculation must remain pending or unavailable;
application projections must not be presented as authoritative.

TokANSH must never directly access DRUNIX internal YugabyteDB tables.

## 4. Technology Stack

### Frontend

- React
- TypeScript
- Vite
- Tailwind CSS
- shadcn/ui
- Recharts
- React Router
- TanStack Query

### Backend

- Python
- FastAPI
- Pydantic
- SQLAlchemy
- Alembic

### Blockchain integration

- Hyperledger-derived DRUNIX platform.
- Go application gateway adapter.
- Go-based TokANSH chaincode.
- Official DRUNIX test-network implementation as the development starting point.

Actual DRUNIX interfaces, versions and deployment requirements must be
verified against the selected repository version.

### Infrastructure

- Docker
- Docker Compose
- WSL2 Ubuntu for local development.
- AWS as the preferred initial public-cloud target.

Kubernetes is not required for the MVP.

## 5. Repository Structure

```text
tokansh/
|
|-- AGENTS.md
|-- README.md
|
|-- docs/
|   |-- PRODUCT_VISION.md
|   |-- MVP_SCOPE.md
|   |-- ARCHITECTURE.md
|   |-- DOMAIN_MODEL.md
|   |-- BUSINESS_RULES.md
|   |-- DRUNIX_INTEGRATION.md
|   |-- DECISIONS.md
|   |-- API_CONTRACTS.md
|   |-- UI_DESIGN_GUIDELINES.md
|   |-- TEST_STRATEGY.md
|   |-- DEMO_SCRIPT.md
|
|-- frontend/
|-- backend/
|-- chaincode/
|-- scripts/
|-- tests/
|
|-- .gitignore
|-- .env.example
```

Additional directories and files may be introduced when implementation
requires them. Keep the structure consistent with the approved architecture.

## 6. Development Environment

Primary development environment:

- Windows 11
- WSL2 Ubuntu 22.04
- Docker Desktop with WSL integration
- Git
- Node.js
- Python
- Go

The project workspace is:

```text
/home/kshewani/projects/tokansh
```

The Windows File Explorer path is:

```text
\\wsl.localhost\Ubuntu-22.04\home\kshewani\projects\tokansh
```

Run Linux development commands from the WSL Ubuntu environment unless
explicitly instructed otherwise.

## 7. Prerequisites

Install and verify the following tools:

- Git
- Docker Engine / Docker Desktop WSL2 integration
- Docker Compose
- Node.js and npm
- Python
- Go

DRUNIX has additional platform-specific prerequisites. Follow the official
DRUNIX repository documentation for the selected version rather than
assuming standard Fabric setup procedures are fully compatible.

Check the installed versions before beginning network deployment.

## 8. Configuration and Secrets

Use environment-specific configuration.

A safe `.env.example` should document required variable names without
containing actual secrets.

Never commit:

- Private keys.
- Signing keys.
- Certificates containing private material.
- Passwords.
- API tokens.
- Cloud credentials.
- Production connection strings.
- Runtime ledger data.

Use appropriate local secret handling during development and cloud secret
management where available.

## 9. Local Development Workflow

The intended implementation sequence is:

1. Verify development prerequisites.
2. Prepare the local Docker environment.
3. Deploy the self-hosted DRUNIX development network.
4. Create/configure the required channel and organisations.
5. Deploy TokANSH chaincode.
6. Verify ANSH issuance and transfer directly on DRUNIX.
7. Implement the Go gateway adapter.
8. Implement FastAPI business workflows.
9. Implement the application database and migrations.
10. Implement the React frontend.
11. Integrate the complete application.
12. Execute the end-to-end test scenarios.

Exact commands must be documented as the DRUNIX environment is validated.

Do not assume network scripts, gateway methods or chaincode lifecycle
commands without checking the selected DRUNIX source version.

## 10. Running the Application

The final local environment should be reproducible using Docker Compose.

The intended workflow is:

```bash
# Start the DRUNIX network and required infrastructure.
# Exact network commands must be verified against the selected DRUNIX version.

# Start TokANSH application services.
docker compose up -d --build

# Inspect running containers.
docker compose ps

# Inspect application logs.
docker compose logs -f
```

The final Compose configuration must define the actual services and
dependencies before these commands are treated as a complete setup guide.

Do not use this section as evidence that the application or DRUNIX network
has already been implemented.

## 11. API Documentation

FastAPI should provide generated OpenAPI documentation during development.

Expected endpoints:

- `/docs`
- `/redoc`
- `/openapi.json`

The application API contract is maintained in:

`docs/API_CONTRACTS.md`

## 12. Testing

Testing guidance is maintained in:

`docs/TEST_STRATEGY.md`

Required validation includes:

- Backend unit tests.
- Go gateway tests.
- Chaincode tests.
- API contract tests.
- Actual DRUNIX network integration tests.
- End-to-end application tests.
- Failure and reconciliation tests.
- Local deployment tests.
- Public-cloud deployment tests.

Mocked or simulated tests must not be reported as actual DRUNIX integration
tests.

## 13. Public-Cloud Deployment

The complete TokANSH application, including the self-hosted DRUNIX network,
must be deployable to public cloud for the hackathon demonstration.

Preferred initial target:

- AWS Linux virtual machine.
- Docker Engine.
- Docker Compose.
- Persistent storage.
- Secure environment configuration.
- HTTPS-enabled application entry point.

The deployment must keep internal DRUNIX management interfaces and database
services private.

Before provisioning cloud resources:

1. Estimate compute and storage requirements.
2. Check current free-tier eligibility.
3. Estimate network and data-transfer costs.
4. Obtain approval for paid resources.
5. Document shutdown and cleanup procedures.

No cloud infrastructure should be provisioned without explicit cost review.

## 14. Important Business and Technical Rules

- DRUNIX is mandatory for core ANSH ledger operations.
- No simulator fallback for issuance, transfer, pledge or release.
- Ownership changes only after confirmed ledger commitment.
- Endorsement and submission do not prove commitment.
- Unknown transaction outcomes require reconciliation.
- Pledged ANSH cannot be transferred.
- Full loan repayment is required for MVP collateral release.
- Partial collateral release is out of scope.
- Lending and payment workflows may be simulated.
- ANSH and REIT holdings remain distinct.
- Financial calculations must use decimal-safe representations.
- No direct access to DRUNIX internal YugabyteDB.
- Never fabricate ledger transaction identifiers or evidence.

## 15. Documentation Guide

| Document | Purpose |
|---|---|
| `AGENTS.md` | Instructions for AI coding agents |
| `PRODUCT_VISION.md` | Product vision and objectives |
| `MVP_SCOPE.md` | MVP capabilities and acceptance criteria |
| `ARCHITECTURE.md` | Technical architecture |
| `DOMAIN_MODEL.md` | Domain entities and relationships |
| `BUSINESS_RULES.md` | Business and financial invariants |
| `DRUNIX_INTEGRATION.md` | DRUNIX architecture and integration research |
| `DECISIONS.md` | Accepted architectural decisions |
| `API_CONTRACTS.md` | Application API specifications |
| `UI_DESIGN_GUIDELINES.md` | UI and UX standards |
| `TEST_STRATEGY.md` | Test plan and quality gates |
| `DEMO_SCRIPT.md` | Hackathon demonstration plan |

All documentation must remain consistent with `DECISIONS.md`.

## 16. Project Status

Current project stage: **M2 backend foundation plus M3.2 read-only DRUNIX diagnostics.**

- The frontend preserves Preview Mode and offers read-only Connected Mode System Status.
- The FastAPI backend provides configuration, dependency injection, local-development CORS,
  structured errors, SQLite persistence, Alembic migrations and idempotent property draft
  creation/listing/details. See [backend setup and scope](backend/README.md).
- Approval, property verification, DRUNIX registration, issuance and other ledger workflows
  remain unimplemented. Connected business screens remain unavailable.
- The private Go gateway supports verified read-only queries against the existing `basic`
  chaincode. See [gateway setup and verification](gateway/README.md). This does not enable
  ANSH workflows or prove commitment; overall readiness remains unavailable.

The specifications describe the intended complete MVP; they are not evidence that all
capabilities currently exist.

## 17. Project Constraints

- Local development first.
- Public-cloud demonstration required.
- AWS preferred.
- Cloud expenditure must be controlled.
- DRUNIX mandatory for core ANSH operations.
- No production credentials in Git.
- No direct access to DRUNIX internal database.
- No unnecessary microservices or Kubernetes.
- Simulation permitted only for clearly identified supporting workflows.

## 18. Contribution and AI Development Guidelines

Before implementation, read:

1. `AGENTS.md`
2. `docs/DECISIONS.md`
3. `docs/PRODUCT_VISION.md`
4. `docs/MVP_SCOPE.md`
5. `docs/ARCHITECTURE.md`
6. `docs/DOMAIN_MODEL.md`
7. `docs/BUSINESS_RULES.md`
8. `docs/DRUNIX_INTEGRATION.md`
9. `docs/API_CONTRACTS.md`
10. `docs/UI_DESIGN_GUIDELINES.md`
11. `docs/TEST_STRATEGY.md`
12. `docs/DEMO_SCRIPT.md`

AI coding agents must:

- Respect accepted architectural decisions.
- Avoid inventing DRUNIX APIs or capabilities.
- Work incrementally.
- Explain important implementation decisions.
- Include tests for business rules.
- Update relevant documentation when behaviour changes.
- Never commit secrets or runtime state.
- Stop and report unresolved architectural conflicts.

---

**TokANSH — Unlocking Real Estate, One Ansh at a Time.**

## Local WSL application lifecycle

With DRUNIX already started separately, use these commands from this repository:

```bash
./scripts/tokansh-app.sh start
./scripts/tokansh-app.sh status
./scripts/tokansh-app.sh logs
./scripts/tokansh-app.sh stop
./scripts/tokansh-app.sh restart
```

The launcher manages only its own Gateway (:8001), FastAPI (:8000) and Vite
(http://127.0.0.1:5173) processes. SQLite is a file, not a managed service.
`status` reports process ownership/liveness; `logs` prints a bounded tail, not a
continuous follower. It never manages DRUNIX or its recovery script.

Prerequisites: existing backend `.venv`, installed frontend dependencies, Linux Node
on PATH or in the existing NVM installation, Go and the pinned cached dependencies,
and Linux/WSL pidfd support. Start builds `gateway/cmd/gateway` outside the repository
with dependency downloads/toolchain downloads disabled; build timeout is 120 seconds.
Missing dependencies require manual setup; nothing is installed automatically.

Configuration is read from `~/.config/tokansh/local.env` as **dotenv**, not executable
shell code. Use the existing backend/Gateway `.env.example` files as references.
The file must be owned by the current user with mode 0600, its directory mode 0700.
Do not regenerate/rotate secrets or copy signing keys. The profile must provide the
existing Org1 User1 identity paths, MSP, peer endpoint, TLS CA/server name and two
distinct existing 32-byte secrets encoded as 64 hex characters. Profile values
supersede inherited shell values. Gateway bind, backend bind, channel, diagnostic
chaincode and evaluation timeout must match the reviewed local defaults:
127.0.0.1:8001, 127.0.0.1:8000, mychannel, basic and 5s. The backend's bridge URL is
http://127.0.0.1:8001; typed registration still targets tokansh internally.

The existing database must be `~/.local/share/tokansh/tokansh.db`, with owner-only
file/directory permissions and migration revision `0002_registration`. An optional
DATABASE_URL must select that same file using an absolute SQLite URL. The launcher
checks the existing schema through mode=ro; it never initializes, resets, migrates
or restores a database. It does not replace the full transaction preflight runbook.
SQLite WAL sidecars remain subject to SQLite's normal read-only-open requirements.

Frontend mode is preserved: absent VITE_API_MODE means Preview Mode. To select the
existing Connected Mode explicitly, configure VITE_API_MODE=real and
VITE_API_BASE_URL=http://127.0.0.1:8000. Only these two Vite settings and a minimal
system environment reach the frontend child; signing paths/secrets are not passed.
Never put secrets in frontend `.env` files or VITE_* values.

Logs, the compiled Gateway and process records live in
`~/.local/state/tokansh/app/` under an owner-only directory. Logs append across
restarts and are not rotated automatically; inspect them privately and retain/delete
only when no longer needed. Do not share raw logs without reviewing/redacting them.

Repeated starts reuse matching managed processes. Occupied unmanaged ports fail
without killing their owner. Boot ID, PID start time and executable
identify owned processes; pidfds prevent signalling a reused PID. Stale records
are discarded without signalling another process. Shutdown sends TERM, waits up to
eight seconds, then uses KILL only for the still-matching process. Child workers rely
on their application's graceful shutdown; this is not a general process-tree manager.
A failed start rolls back only processes created by that invocation. It leaves
previously managed processes and all data intact. Concurrent lifecycle commands fail
with a lock message; they do not launch duplicates.

Startup checks process health (up to 30 seconds per service, plus bounded HTTP calls)
and performs one authenticated GET /v1/tokansh/contract-info evaluation. Wrong metadata,
authentication failure, timeout or unavailable DRUNIX fails startup honestly; there
is no ledger fallback or automatic evaluation retry. This read proves connectivity,
not transaction/financial readiness: `/ready` remains unavailable. No prepare,
submit, commit-status, lifecycle deployment or blockchain-writing request is made.
The launcher does not authorize Connected Mode financial workflows.

Before stop/restart, finish any operator transaction or preserve its reconciliation
state. Interrupting an in-flight operation can leave an ambiguous outcome; reconcile
with the existing runbook and never blindly resubmit. Only start/stop the application
through this launcher for ownership tracking; it will not adopt another developer's
already-running services.

Offline launcher tests (temporary processes/configuration/SQLite fixtures only):

```bash
PYTHONDONTWRITEBYTECODE=1 backend/.venv/bin/python -B -m unittest discover -s scripts -p 'test_tokansh_app.py'
bash -n scripts/tokansh-app.sh
```
