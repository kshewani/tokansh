# TokANSH — Architecture Decision Register

**Product:** TokANSH
**Tagline:** Unlocking Real Estate, One Ansh at a Time
**Status:** Initial decisions approved for MVP
**Last updated:** 2026-11-16

This document records the architectural and engineering decisions governing
the TokANSH MVP. These decisions must be followed by developers and AI coding
agents unless explicitly revised and recorded here.

---

## 1. Decision Status

- **Accepted:** Decision approved for the MVP.
- **Pending verification:** Requires technical validation or external confirmation.
- **Deferred:** Deliberately excluded from the current MVP.

---

## 2. Accepted Architecture Decisions

### ADR-001: Modular Monolith

**Status:** Accepted

Use a modular monolith for the TokANSH application.

- Do not introduce microservices for the MVP.
- Keep business capabilities separated into logical modules.
- Use clearly defined interfaces between modules.
- Keep the blockchain integration behind a dedicated adapter boundary.

**Rationale:** This reduces implementation and operational complexity while
preserving maintainability and future evolution.

### ADR-002: Frontend Technology

**Status:** Accepted

Use:

- React
- TypeScript
- Vite
- Tailwind CSS
- shadcn/ui
- Recharts
- React Router
- TanStack Query

The UI must provide a polished, institutional-grade financial application
experience.

### ADR-003: Backend Technology

**Status:** Accepted

Use:

- Python
- FastAPI
- Pydantic
- SQLAlchemy
- Alembic

The backend owns business workflows, orchestration, validation, application
persistence and integration with external services.

### ADR-004: Go-Based DRUNIX Gateway Adapter

**Status:** Accepted as the preferred integration approach;
implementation details require validation against the official DRUNIX repository.

Use a separate Go integration component to communicate with DRUNIX through
the supported application gateway/client interface.

FastAPI communicates with this component through a documented private
application interface.

Do not attempt to embed Go gateway code directly into the Python process
without an explicitly designed interoperability mechanism.

Do not invent DRUNIX endpoints, SDK methods, network configuration or
authentication requirements.

### ADR-005: DRUNIX Is Mandatory for Core ANSH Operations

**Status:** Accepted

A self-hosted DRUNIX development network is a mandatory component of the
TokANSH MVP and hackathon demonstration.

The following operations must execute against DRUNIX:

- ANSH issuance
- ANSH ownership recording and verification
- ANSH transfer
- ANSH pledge
- ANSH collateral release
- Relevant asset lifecycle records where supported by the implemented
  chaincode design

Before ANSH issuance, the approved property reference and approved issuance
constraints must be registered through `RegisterApprovedProperty` and
confirmed committed on DRUNIX.

Core ANSH operations must never silently fall back to a simulator.

If DRUNIX is unavailable, the application must report the failure or retain
an explicitly pending/reconciliation state. It must not claim that a
simulated operation changed ledger state.

### ADR-006: Self-Hosted DRUNIX Development Network

**Status:** Accepted

Build and operate the development network using the public DRUNIX source
repository and its supported test-network implementation.

- Run the network locally using Docker and WSL2 Ubuntu initially.
- Use the official DRUNIX network scripts and configuration as the starting
  point.
- Validate the actual network topology, dependencies and startup procedure.
- Do not assume that a standard Hyperledger Fabric deployment procedure is
  fully compatible without verification.
- Keep the network reproducible through version-controlled scripts and
  configuration.

The local network is a development/test environment, not a production-grade
distributed deployment.

### ADR-007: Separate Ledger State from Application State

**Status:** Accepted

DRUNIX is authoritative for core ANSH ledger state, including issuance,
ownership, transfers and pledges.

TokANSH application persistence is responsible for:

- Property onboarding, document management, verification evidence and
  application-level approval decisions
- Marketplace orders and workflow metadata
- Simulated lending workflows
- Simulated payment records
- Application users and roles
- Read models and portfolio projections
- Application audit records
- Supporting analytics and reporting data

Property approval is an application-level decision, not a DRUNIX transaction.
After approval, the backend must register the approved property reference and
approved issuance constraints on DRUNIX. ANSH issuance must remain blocked
until that registration is confirmed committed.

Application projections must not override authoritative ledger state.

### ADR-008: No Direct Access to DRUNIX Internal YugabyteDB

**Status:** Accepted

DRUNIX uses YugabyteDB as an internal state database in the researched
test-network configuration.

TokANSH must not:

- Connect directly to DRUNIX internal database tables.
- Read or update internal DRUNIX database records.
- Treat internal database access as a substitute for chaincode or gateway
  operations.

All ledger interactions must use supported DRUNIX application interfaces.

### ADR-009: Application Database

**Status:** Accepted for local MVP; cloud choice requires reassessment.

Use SQLite initially for TokANSH application persistence.

Use SQLAlchemy and Alembic. Keep domain services reasonably independent of
database-specific SQL.

Before public-cloud deployment, assess whether PostgreSQL is more appropriate
for concurrent access and operational requirements.

This decision does not affect DRUNIX's internal YugabyteDB.

### ADR-010: Simulation Boundaries

**Status:** Accepted

Simulation is permitted for supporting workflows where real external
integrations are unavailable.

Permitted examples:

- Credit assessment
- Lender approval
- Loan disbursement
- Loan repayment processing
- Property valuation
- Payment provider responses
- Rental payment distribution
- External REIT data

All simulated services and outcomes must be clearly identified in the UI
and documentation.

Simulation must never be presented as a real bank, payment provider,
property registry or financial institution integration.

Simulation must never create fabricated DRUNIX transaction evidence.

### ADR-011: Transaction Finality

**Status:** Accepted

A transaction submission or endorsement is not proof of ledger commitment.

For core ANSH operations:

1. Validate the requested business operation.
2. Submit the transaction through the supported DRUNIX gateway.
3. Obtain and track the transaction identifier returned by DRUNIX.
4. Verify the transaction's commit status.
5. Update application projections only after confirmed commitment.

If the result is ambiguous because of a timeout or connectivity failure,
reconcile the transaction status before retrying.

Never blindly retry a transaction that may already have committed.

### ADR-012: Purchase and Transfer Orchestration

**Status:** Accepted

The MVP may use a simulated payment provider.

The purchase workflow must distinguish payment state from ledger state.

- Payment failure must not cause an ANSH transfer.
- Payment success does not itself establish ownership.
- Ownership changes only after DRUNIX confirms the transfer commitment.
- Payment success followed by ledger failure requires reconciliation.
- Do not claim atomic delivery-versus-payment unless the implemented
  platform provides and demonstrates that capability.

### ADR-013: Collateral Restrictions

**Status:** Accepted

ANSH units can be pledged as collateral in the simulated lending workflow.

- Only available, unpledged units may be pledged.
- Pledged units remain owned by the investor but are restricted.
- Pledged units cannot be transferred.
- Full loan repayment triggers a collateral-release workflow.
- Units become available again only after DRUNIX confirms the release.
- Partial collateral release is out of scope for the MVP.

### ADR-014: Distribution Processing

**Status:** Accepted

Rental distribution calculation is an application workflow.

- Calculate entitlement using record-date eligible holdings.
- Use committed DRUNIX ledger state as the authority for record-date ownership.
- Preserve the verified ownership snapshot or ledger event reference used
  for the calculation.
- If a reliable historical snapshot or event reconstruction is unavailable,
  leave entitlement calculation pending or unavailable; do not present an
  unverified application projection as authoritative.
- Keep distribution and simulated payment records in the application database.
- Clearly label rental payments as simulated.
- Do not claim that simulated rental payments were executed on DRUNIX.

Pledged units remain investor-owned and are included in distribution
eligibility unless an explicitly defined contractual rule states otherwise.

### ADR-015: Financial Data Representation

**Status:** Accepted

- Never use binary floating-point values for financial calculations.
- Use fixed-precision decimal values or integer minor currency units.
- Define currency explicitly.
- Define deterministic rounding rules.
- Record sufficient information to reproduce financial calculations.

### ADR-016: Container-Based Development

**Status:** Accepted

Containerise the application components and DRUNIX development environment.

Use Docker and Docker Compose initially.

- Runtime dependencies must be reproducible.
- Persist required database and ledger data using explicit volumes.
- Keep runtime state outside the Git repository.
- Do not commit private keys, certificates, credentials or secrets.
- Provide safe environment-variable templates.

### ADR-017: Public-Cloud Demonstration

**Status:** Accepted

The complete TokANSH application, including its DRUNIX network, must be
deployable to a public cloud for the hackathon demonstration.

AWS is the preferred initial target.

Initial deployment preference:

- Linux virtual machine
- Docker Engine
- Docker Compose
- HTTPS-enabled application entry point
- Persistent storage
- Secure environment-specific configuration

Do not introduce Kubernetes for the MVP unless a concrete requirement
justifies it.

Cloud deployment must be validated independently; a successful local
deployment does not prove cloud readiness.

### ADR-018: Public-Cloud Cost Control

**Status:** Accepted

Avoid cloud expenditure during initial development.

Before provisioning cloud resources:

- Estimate compute, storage, network and data-transfer costs.
- Check current free-tier or promotional eligibility.
- Obtain explicit approval for any paid resource.
- Provide a clear shutdown and cleanup procedure.

Do not assume that a public-cloud deployment will be free.

### ADR-019: REIT and ANSH Asset Separation

**Status:** Accepted

ANSH holdings and REIT holdings are distinct asset classes.

- Maintain separate domain representations.
- Do not treat REIT units as ANSH.
- A consolidated portfolio may display both asset classes.
- REIT data may be simulated for the MVP.
- REIT collateral is out of scope.

### ADR-020: Legal and Financial Representation

**Status:** Accepted

The prototype must not imply that an ANSH token automatically confers
registered legal property title, direct legal ownership of property,
regulated investment status or enforceable rights.

All illustrative property values, valuations, financing and investment
returns must be clearly identified as demonstration data or simulations.

---

## 3. Pending Technical Verification

The following items must be validated before their implementation is treated
as complete:

1. Exact DRUNIX source version and compatible Go toolchain.
2. DRUNIX test-network prerequisites and startup procedure.
3. Actual peer, orderer and validation-service configuration.
4. Supported chaincode lifecycle and deployment commands.
5. Go gateway API and dependency compatibility.
6. Certificate, identity, MSP and TLS configuration.
7. Channel and organisation configuration.
8. Transaction commit-status and reconciliation behaviour.
9. Chaincode event and history-query capabilities.
10. Resource requirements for local and cloud deployment.
11. Hackathon acceptance of a self-hosted DRUNIX network.

Unknown platform details must be verified against source code or actual
execution. Do not invent them.

---

## 4. Deferred from the MVP

Unless explicitly added to the approved scope, defer:

- Kubernetes deployment
- Production-grade high availability
- Production identity-provider integration
- Real bank lending integration
- Real payment gateway integration
- Real property registry integration
- Real property valuation integration
- Partial collateral release
- REIT collateral
- Production regulatory and legal certification
- Production-grade multi-region disaster recovery

---

## 5. Change Control

Any change to an accepted decision must:

1. Identify the decision being changed.
2. Explain the reason and business/technical impact.
3. Describe alternatives considered.
4. Identify affected specification documents.
5. Update this register and the affected documents.
6. Receive explicit approval before implementation.

AI coding agents must not independently reverse accepted decisions.

---

## 6. Governing Documentation

This register must be read together with:

- `PRODUCT_VISION.md`
- `MVP_SCOPE.md`
- `ARCHITECTURE.md`
- `DOMAIN_MODEL.md`
- `BUSINESS_RULES.md`
- `DRUNIX_INTEGRATION.md`
- `API_CONTRACTS.md`
- `UI_DESIGN_GUIDELINES.md`
- `TEST_STRATEGY.md`
- `DEMO_SCRIPT.md`
- `AGENTS.md`

When documents appear to conflict, stop and report the conflict rather than
silently choosing an interpretation.

### M5 local-MVP scope clarification — simulation reservations, not pledges

For the expressly scoped M5 hackathon financing experience, reservations,
lender decisions, disbursement and repayment are **off-chain simulations** stored
in the application database. They do not implement ADR-013's enforceable on-chain
pledge/release controls. Reserved units remain transferable on DRUNIX; actual
ownership and M4 transferable balances stay unchanged. REIT units are excluded.
Fresh ledger balances cap approval, and serialized application-state checks prevent
overlapping simulation reservations, but cannot prevent subsequent ledger transfers.
UI/API labels must explicitly disclose this boundary. Actual on-chain restrictions
remain unimplemented and must not be claimed from this milestone. This limited
scope does not approve real lending, legal collateral enforceability or production
identity/credit controls.
