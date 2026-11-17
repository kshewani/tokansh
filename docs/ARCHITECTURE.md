# TokANSH — System Architecture

## 1. Architecture Objective

Design a modular, maintainable and extensible real estate
tokenization application.

The architecture must support:

- Property onboarding and approval.
- ANSH issuance and ownership management.
- Marketplace and secondary transfers.
- Payment and settlement workflows.
- Collateral-backed financing.
- Rental income distributions.
- Investor portfolio management.
- Asset intelligence and audit history.
- Integration with the DRUNIX enterprise distributed-ledger platform.

The MVP must be runnable locally without paid cloud infrastructure.

Architecture style: Modular Monolith.

Microservices and Kubernetes are explicitly out of scope for the MVP.

## 2. High-Level Architecture

```text
                      TOKANSH PLATFORM
                              |
                    +---------+---------+
                    |                   |
               React UI            FastAPI Backend
             TypeScript               Python
                    |                   |
                    |          +--------+---------+
                    |          |        |         |
                    |       Domain   Workflow  Integration
                    |       Services Services  Services
                    |          |        |         |
                    |          +--------+---------+
                    |                   |
                    |          +--------+---------+
                    |          |                  |
                    |     Application DB     Blockchain Adapter
                    |        SQLite            /          \
                    |                        Simulator    DRUNIX
                    |                                      |
                    |                                Go Chaincode
                    |
             Dashboards and UI
             Property Registry
             Marketplace
             Portfolio
             Financing
             Distributions
             Audit and Intelligence


       External Service Simulators
       ---------------------------
       Payment Gateway Simulator
       Lender Simulator
       Property Verification Simulator
       Valuation Simulator
       REIT Data Simulator
```

## 3. Technology Stack

### Frontend

- React
- TypeScript
- Vite
- Tailwind CSS
- shadcn/ui
- Recharts
- React Router
- TanStack Query

Responsibilities:

- User interface and navigation.
- Dashboard visualizations.
- Property and marketplace screens.
- Investor portfolio.
- Financing and distribution workflows.
- Form validation and user feedback.
- Display of transaction and lifecycle status.

The frontend must not independently enforce critical financial
or ownership business rules.

### Backend

- Python
- FastAPI
- Pydantic
- SQLAlchemy
- SQLite for MVP persistence
- Alembic for database migrations

Responsibilities:

- Domain business logic.
- Financial calculations.
- Workflow orchestration.
- Input validation.
- Database persistence.
- Blockchain adapter invocation.
- External service simulation.
- API security and role checks.
- Audit and reconciliation.

### Blockchain

- DRUNIX enterprise distributed-ledger platform.
- Go chaincode.
- Dedicated Go-based DRUNIX gateway adapter.
- FastAPI integration with the gateway through a documented interface.
- Test-only mocks for isolated automated tests.

DRUNIX is mandatory for all core ANSH ledger operations in every
running application environment, including local development and cloud demo.

Actual integration must use verified platform interfaces. Do not invent
APIs, SDKs, gateway protocols or transaction semantics.

There is no runtime simulator ledger implementation or fallback.

### Testing

- Pytest for backend.
- Frontend component and integration tests.
- Chaincode tests.
- End-to-end workflow tests.

## 4. Database Architecture and Strategy

TokANSH and DRUNIX have separate database responsibilities.

### 4.1 DRUNIX Internal Database

DRUNIX uses YugabyteDB internally as part of its platform
infrastructure.

This database belongs to the DRUNIX platform.

TokANSH must not:

- Directly modify DRUNIX internal database tables.
- Treat DRUNIX internal tables as an application API.
- Bypass DRUNIX transaction validation or endorsement.
- Depend on undocumented internal database schemas.
- Assume direct database access is supported.

TokANSH must interact with DRUNIX through its verified
client, chaincode invocation and query mechanisms.

The DRUNIX platform remains responsible for its internal
ledger persistence and transaction processing.

### 4.2 TokANSH Application Database — MVP

Use SQLite for the initial application database.

Reasons:

- Minimal infrastructure.
- No separate database server required.
- Simple local development.
- Suitable for the hackathon prototype's data volume.
- Straightforward backup and testing.
- No additional cloud or database infrastructure cost.

SQLite stores application-owned information such as:

- Property application workflows.
- Marketplace listings and orders.
- Purchase workflow records.
- Payment simulation records.
- Loan simulation details.
- Distribution processing records.
- Application read models.
- Dashboard projections.
- Synthetic valuations and REIT data.
- Audit metadata and reconciliation records.

SQLite must not become an independent authority for
ledger-controlled ownership.

### 4.3 Future Database Evolution

YugabyteDB YSQL is the preferred candidate for future distributed
TokANSH application persistence if production requirements justify it.

Potential reasons to migrate:

- Distributed application deployment.
- Higher concurrent write workloads.
- Database replication and fault tolerance.
- Horizontal scalability.
- Production availability requirements.

Do not deploy a separate YugabyteDB cluster for the MVP merely
because DRUNIX internally uses YugabyteDB.

### 4.4 Database Abstraction

Keep domain services independent of database-specific behaviour.

Use:

- SQLAlchemy repositories.
- Alembic migrations.
- Explicit database configuration.
- Repository interfaces or equivalent persistence boundaries.
- PostgreSQL-compatible query patterns where practical.

Avoid SQLite-specific SQL and database assumptions.

A future SQLite-to-YugabyteDB migration will still require
compatibility testing, migration validation and performance testing.
It must not be assumed to be automatic.

## 5. Application Domain Modules

Implement the backend as a modular monolith.

### Property Registry

Responsibilities:

- Property onboarding and metadata.
- Document references and document management.
- Verification workflow.
- Property approval and rejection by authorised application users.
- Property status and audit history.
- Property-to-ANSH association.
- Registration of the approved property reference and approved
  issuance constraints on DRUNIX before ANSH issuance.

Property documents, verification evidence and reviewer decisions remain
in the TokANSH application database. Property approval is not a DRUNIX
chaincode operation. DRUNIX records the approved property reference
and its issuance constraints.

### ANSH Issuance

Responsibilities:

- Approved supply validation.
- Issue-price configuration.
- Issuance requests.
- Issuance records.
- Issued and remaining supply queries.

### Marketplace

Responsibilities:

- ANSH listings.
- Purchase orders.
- Listing availability.
- Order validation.
- Purchase workflow.
- Order status.

### Settlement

Responsibilities:

- Payment simulation.
- Payment outcome handling.
- Ledger transfer submission.
- Commit confirmation.
- Reconciliation.
- Duplicate-operation protection.

### Portfolio

Responsibilities:

- Investor holdings.
- Available and pledged units.
- Acquisition cost.
- Illustrative market value.
- Portfolio allocation.
- Transaction history.
- Financing obligations.
- Rental distributions.

REIT holdings must remain a separate asset class from ANSH.

### Collateral Financing

Responsibilities:

- Collateral eligibility.
- Pledge and release.
- Collateral valuation.
- LTV calculation.
- Financing simulation.
- Loan tracking.
- Repayment processing.

### Distribution

Responsibilities:

- Distribution declaration.
- Record-date processing.
- Investor entitlement calculation.
- Distribution records.
- Investor distribution history.

### Asset Intelligence

Responsibilities:

- Property valuation indicators.
- Rental yield indicators.
- Asset performance.
- Portfolio concentration.
- Indicative collateral capacity.
- Synthetic market insights.

### Audit and Lifecycle

Responsibilities:

- Application event history.
- Ledger event references.
- Workflow history.
- Transaction traceability.
- Event source classification.
- Reconciliation status.

## 6. Source-of-Truth Boundaries

This distinction is mandatory.

### DRUNIX Ledger

Committed DRUNIX ledger state is authoritative for:

- Approved property references and approved issuance constraints registered
  through `RegisterApprovedProperty`.
- ANSH issuance.
- ANSH ownership.
- ANSH transfers.
- Pledge and release state, where implemented and supported.
- Ledger-confirmed lifecycle events.

### TokANSH Application Database

SQLite is authoritative for:

- Property onboarding, document management, verification evidence and
  application-level approval decisions.
- Marketplace listings.
- Application purchase orders.
- Application workflow state.
- Payment simulation records.
- Loan simulation records.
- Distribution processing metadata.
- Dashboard projections.
- Synthetic valuations.
- REIT market data.
- Application audit metadata.

The application database must never silently override ledger ownership.

### External Simulators

Each simulator owns its simulated outcomes:

- Payment simulator: payment status.
- Lender simulator: financing decisions.
- Valuation simulator: illustrative property valuation.
- Property verification simulator: demo verification outcome.
- REIT simulator: synthetic REIT market information.

Every simulated record must be explicitly identified as simulated.

## 7. Blockchain Adapter Architecture

Define a stable application-level blockchain interface.

Illustrative operations:

- register_property(...)
- approve_property(...)
- issue_ansh(...)
- get_property(...)
- get_ownership(...)
- transfer_ansh(...)
- pledge_ansh(...)
- release_pledge(...)
- get_asset_history(...)

These are application-level operations, not claims about actual
DRUNIX API names or SDK capabilities.

### DRUNIX Adapter

Responsibilities:

- Invoke verified DRUNIX chaincode.
- Query committed ledger state.
- Submit supported ledger operations.
- Capture genuine transaction identifiers.
- Obtain transaction commit status.
- Handle endorsement, submission and commit failures.
- Expose relevant ledger event history.

Never claim successful ledger execution before confirmation.

### Runtime Configuration

The running application always uses the DRUNIX gateway adapter for
core ANSH ledger operations.

There is no BLOCKCHAIN_MODE setting and no runtime ledger simulator.

Local development must use the self-hosted DRUNIX development network.
Cloud demonstration must use the deployed DRUNIX network.

Automated unit tests may use isolated mock implementations. These mocks
must not be selectable as a runtime application configuration.

## 8. Payment and Ownership Transfer Workflow

Payment and ledger transfer are separate operations unless
a verified atomic settlement capability exists.

Expected sequence:

1. Validate investor, listing and requested quantity.
2. Query authoritative seller ownership.
3. Validate available balance and transfer eligibility.
4. Create a uniquely identified purchase operation.
5. Invoke the payment simulator.
6. If payment fails, mark the purchase as failed.
7. Do not invoke ownership transfer after payment failure.
8. If payment succeeds, submit the ledger transfer.
9. Wait for ledger commit confirmation.
10. Update application read models.
11. Mark the purchase as completed.
12. Record payment and ledger references.

### Failure Scenarios

Payment failure:

- No ledger transfer.
- No ownership update.
- Record failed payment and purchase status.

Ledger submission failure:

- Do not mark ownership transfer successful.
- Record the failed or uncertain outcome.
- Apply reconciliation rules.

Ambiguous ledger outcome:

- Query transaction status and ledger ownership.
- Reconcile before retrying.
- Never blindly resubmit an uncertain operation.

Payment success followed by ledger failure:

- Preserve the payment success record.
- Mark the purchase as requiring reconciliation.
- Do not claim that ownership was transferred.
- Provide an explicit exception workflow.

Do not claim atomic delivery versus payment unless the
underlying systems provide and verify it.

## 9. Collateral Financing Workflow

Pledge sequence:

1. Investor selects eligible ANSH holdings.
2. Backend queries authoritative ownership.
3. Backend calculates available units.
4. Backend validates pledge quantity.
5. Lender simulator evaluates the financing request.
6. Submit the supported ledger pledge operation.
7. Confirm ledger commit.
8. Update application loan and collateral projections.
9. Recalculate available holdings.

Repayment and release sequence:

1. Record simulated repayment.
2. Update outstanding loan balance.
3. Validate collateral release eligibility.
4. Submit ledger release operation.
5. Confirm ledger commit.
6. Update application projections.

Pledged units must not be transferable.

The exact pledge and release semantics must be verified against
DRUNIX capabilities and the implemented chaincode.

## 10. Rental Distribution Workflow

1. Administrator declares a distribution.
2. Capture the distribution record date.
3. Obtain authoritative ownership balances at that date.
4. Determine eligible holdings according to the declared rules.
5. Calculate investor entitlements.
6. Record the distribution calculation.
7. Display distribution outcomes and history.

Historical ownership must not be inferred from current holdings.

If historical ledger snapshots are unavailable, use a verified
event-history reconstruction.

If the simulator uses an application snapshot, clearly identify
the snapshot as simulator-derived.

The distribution logic must be deterministic and testable.

## 11. Financial Data and Calculations

- Use Decimal arithmetic or integer minor currency units.
- Never use binary floating-point for money.
- Store currency explicitly.
- Validate ANSH quantities and precision.
- Apply deterministic rounding rules.
- Prevent duplicate financial operations.
- Record calculation inputs and outcomes where necessary.

Core calculations:

Available ANSH = Owned ANSH - Pledged ANSH

LTV = Outstanding Loan / Collateral Value * 100

Investor Distribution =
Eligible Investor Units / Total Eligible Units
* Declared Distribution Amount

The distribution calculation must use eligible holdings at the
declared record date.

## 12. API Architecture

Organize FastAPI routes by domain, using the paths in API_CONTRACTS.md section 7
(the frontend follows them):

- /api/v1/dashboard
- /api/v1/properties
- /api/v1/ansh/issuances, /api/v1/ansh/transfers
- /api/v1/marketplace, /api/v1/payments
- /api/v1/portfolios
- /api/v1/collateral, /api/v1/loans
- /api/v1/distributions
- /api/v1/assets
- /api/v1/audit, /api/v1/ledger
- /api/v1/system

Use:

- Pydantic request and response schemas.
- Domain service layer.
- Repository layer.
- Explicit error responses.
- Idempotency keys for consequential operations.
- OpenAPI documentation.

Do not expose internal database models directly as API contracts.

## 13. Data Model — Logical Entities

Recommended application entities:

- users
- properties
- property_documents
- issuance_records
- marketplace_listings
- purchase_orders
- payment_records
- blockchain_operations
- portfolio_snapshots
- collateral_pledges
- loans
- loan_repayments
- distributions
- distribution_entitlements
- asset_events
- audit_events
- reit_holdings

Use explicit relationships, constraints, timestamps and indexes.

Ledger-owned information must retain its ledger reference and
must not become independently editable application state.

Application read models should record:

- Source of data.
- Ledger reference, where applicable.
- Observation timestamp.
- Reconciliation status.
- Whether the data is simulated.

## 14. Security and Operational Controls

- Never commit credentials, tokens or private keys.
- Use environment variables for configuration.
- Provide .env.example without real secrets.
- Validate all inputs in the backend.
- Enforce business rules server-side.
- Implement role checks even for demo personas.
- Treat role switching as demonstration-only.
- Record consequential operations in audit history.
- Avoid logging credentials or key material.
- Make errors visible and actionable.

## 15. Local Deployment Architecture

The MVP must run locally without cloud expenditure.

Components:

- React development server.
- FastAPI backend.
- SQLite application database.
- Self-hosted DRUNIX development network.
- Go-based DRUNIX gateway adapter.
- FastAPI backend.
- SQLite application database.

Docker should be used where it simplifies repeatable infrastructure.

Do not require Kubernetes.

Core ANSH operations must not fall back to a simulator when DRUNIX
is unavailable. The application must show a safe failure or pending
reconciliation state rather than claim an operation succeeded.

The complete application and DRUNIX network must subsequently be
deployable to a public-cloud environment for the hackathon demonstration.

## 16. DRUNIX Integration Questions

These questions must be verified before implementing the real adapter:

1. Exact DRUNIX client and chaincode invocation mechanism.
2. Supported transaction submission interface.
3. Transaction commit and query interfaces.
4. Identity and signing requirements.
5. Supported private-data and access-control semantics.
6. Historical state query capabilities.
7. Exact pledge and release contract semantics.
8. Transaction idempotency capabilities.
9. Event history and transaction status availability.
10. Supported integration approach for external applications.

Do not infer these capabilities from DRUNIX's internal use of
YugabyteDB.

## 17. Architecture Acceptance Criteria

The architecture is acceptable when:

- Frontend and backend responsibilities are clearly separated.
- Backend domain services enforce business rules.
- Blockchain integration is isolated behind an adapter.
- Core ANSH ledger operations execute through the DRUNIX adapter.
- Test-only mocks are isolated from runtime application configuration.
- DRUNIX internal database is not directly accessed by TokANSH.
- SQLite is used for MVP application persistence.
- Future YugabyteDB migration remains feasible.
- Ledger and application database responsibilities are explicit.
- Payment and transfer failures are handled safely.
- Pledged units cannot be transferred.
- Distribution uses record-date ownership.
- Simulated services cannot be mistaken for real integrations.
- The application runs locally without paid cloud infrastructure.
