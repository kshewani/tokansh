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

Current project stage: **Specification and architecture preparation.**

The initial documentation is being established before implementation.

Do not interpret the presence of a documented capability as proof that
it has already been implemented.

Implementation status must be reported accurately.

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
