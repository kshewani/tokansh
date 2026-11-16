# TokANSH — Agent Instructions

## 1. Product Identity

Product: TokANSH
Tagline: Unlocking Real Estate, One Ansh at a Time.

TokANSH is an enterprise-oriented real estate asset tokenization
prototype. It demonstrates fractional economic interests in real
estate through digital ANSH units and their lifecycle management.

The prototype must demonstrate the complete asset lifecycle:
property onboarding, approval, issuance, ownership, marketplace
transactions, settlement, portfolio management, collateral financing,
rental distributions and audit history.

## 2. Primary Objective

Build a polished, functional, jury-ready hackathon prototype.

Priorities:
1. Correct business rules and financial calculations.
2. A coherent end-to-end demonstration.
3. Reliable and transparent blockchain integration.
4. Institutional-grade fintech user experience.
5. Maintainable and testable code.

Do not sacrifice business correctness for visual effects.

## 3. Technology Stack

Frontend:
- React
- TypeScript
- Vite
- Tailwind CSS
- shadcn/ui
- Recharts

Backend:
- Python
- FastAPI
- Pydantic
- SQLite initially

Blockchain:
- DRUNIX distributed ledger platform
- Go chaincode
- A blockchain adapter integrating with DRUNIX
- Test-only mock implementations for isolated automated tests

Testing:
- Pytest for backend
- Appropriate frontend component and integration tests

Development environment:
- Ubuntu on WSL2
- Docker Desktop with WSL integration
- Git and GitHub

Do not introduce additional frameworks, infrastructure or services
without explaining why they are needed.

## 4. Architecture Principles

- Use a modular monolith for the application.
- Keep frontend, backend and chaincode responsibilities separate.
- Use clear service, repository and domain boundaries.
- Keep blockchain-specific implementation behind a dedicated adapter.
- DRUNIX is mandatory for all core ANSH ledger operations.
- Do not provide a runtime simulator mode or simulator fallback for core
  ANSH operations.
- Test mocks may be used only in isolated automated tests; they must never
  be used as the ledger implementation in the running application or demo.
- If DRUNIX is unavailable, fail safely and preserve pending or
  reconciliation states. Never report an uncommitted operation as successful.
- Do not introduce microservices or Kubernetes for this MVP.

## 5. Source of Truth

- DRUNIX: authoritative source for approved property references
  registered on the ledger, ANSH issuance, ownership, transfers,
  pledges, collateral releases and ledger transaction outcomes.
- Application database: property onboarding, documents, verification
  evidence, approval workflow, marketplace orders, workflow state,
  application read models and synthetic demo data.
- Payment simulator: simulated payment outcomes.
- Backend services: loan calculations, valuations and analytics.
- Lender simulator: simulated financing decisions and outcomes.
- REIT holdings: separate simulated external-data domain.

Property approval is an application workflow decision. Only the approved
property reference and its approved issuance constraints are registered
on DRUNIX before ANSH issuance. Property documents and review records
remain off-chain.

The application must not treat its local database as authoritative for
ledger-backed ownership, issuance, pledge or transfer state.

Never represent simulated records as actual blockchain transactions
or external financial integrations.

## 6. Critical Business Rules

- Issued supply must never exceed approved supply.
- Available ANSH = owned ANSH - pledged ANSH.
- Transfers cannot exceed available holdings.
- Pledged units cannot be transferred.
- Failed payment must never result in ownership transfer.
- Ownership is updated only after confirmed ledger commit.
- Ambiguous ledger outcomes require reconciliation, not blind retry.
- Loan-to-value = outstanding loan / collateral value * 100.
- Distribution entitlement is based on eligible holdings at
  the declared record date.
- Use integer minor units or decimal arithmetic for money.
  Never use binary floating-point for financial calculations.
- Implement idempotency and duplicate-operation protection.

## 7. Financial and Legal Representation

ANSH units represent the economic interests defined by the prototype.
Do not claim that an ANSH token automatically represents legal
property title, a legally recognised security, or enforceable ownership.

Clearly distinguish:
- Actual application functionality.
- DRUNIX-backed functionality.
- Simulated payment and financing workflows.
- Synthetic valuations, property verification and REIT data.

Never claim actual lending, guaranteed liquidity, atomic delivery
versus payment or real external integrations unless implemented
and independently verified.

Keep ANSH and REIT holdings as distinct asset classes.

## 8. Demo Scenario

Use the following synthetic demonstration:

Property: TechPark One
Illustrative property valuation: INR 100 crore
Total ANSH supply: 100,000
Illustrative issue price: INR 10,000 per ANSH

Personas:
- Meera: property owner / issuer
- Aarav: investor

Demonstrate:
1. Meera onboards TechPark One.
2. Issuer approves the property.
3. Issuer issues 100,000 ANSH.
4. Aarav purchases 500 ANSH.
5. Payment succeeds and ownership transfer is confirmed.
6. Aarav views his portfolio.
7. Aarav pledges 200 ANSH for simulated financing.
8. An attempted transfer of pledged units is rejected.
9. Rental income is distributed using record-date holdings.
10. Aarav repays the simulated loan and releases the pledge.
11. Portfolio and audit history reflect the updated state.

Use consistent data and state transitions across all screens.

## 9. DRUNIX Integration

Do not invent DRUNIX APIs, SDKs, gateway protocols or deployment
capabilities.

Verify integration details against the available DRUNIX source,
documentation and the hands-on knowledge of the DRUNIX developer.

Keep chaincode operations and ledger integration independently
testable.

The running application must obtain transaction identifiers and
commit evidence from actual DRUNIX operations. Never fabricate transaction
hashes, block numbers, endorsements or commit evidence.

Test mocks must be unmistakably test-only and must never be presented as
real DRUNIX execution.

## 10. UI and UX Standards

Build an institutional-grade fintech application.

Requirements:
- Consistent typography, spacing, colours and component styling.
- Clear navigation and information hierarchy.
- Professional financial dashboards and data tables.
- Responsive layouts.
- Accessible controls and meaningful labels.
- Loading, empty, error and success states.
- Confirmation for consequential actions.
- Clear distinction between available and pledged units.
- Explicit labels for simulated data and workflows.

Avoid generic AI-generated dashboard aesthetics, excessive gradients,
unnecessary animations and decorative elements without purpose.

## 11. Security and Engineering Standards

- Never commit private keys, credentials, tokens or secrets.
- Use environment variables for configuration.
- Provide .env.example without actual secrets.
- Validate all inputs on the backend.
- Enforce business rules on the backend, not just in the UI.
- Use structured error handling and meaningful logs.
- Add tests for critical business invariants.
- Keep dependencies and code changes minimal and justified.

## 12. Working Instructions for the Agent

- Read AGENTS.md and all relevant documents under docs/ before work.
- Do not assume undocumented business rules.
- Identify ambiguities and unresolved dependencies explicitly.
- Do not start implementation before architecture approval.
- For architecture tasks, produce proposals and wait for approval.
- For implementation tasks, work incrementally and test each feature.
- Do not silently change the agreed architecture or scope.
- Explain important design decisions and trade-offs.
- Never claim a feature is implemented or tested without evidence.
- Keep documentation updated when decisions change.

## 13. Delivery Standard

The final prototype must support a coherent end-to-end demo,
consistent financial state, reliable validation, and a professional
institutional user experience.

A genuine, verified DRUNIX integration is mandatory for the
core ANSH demonstration. If the network or an operation is unavailable,
show the failure or reconciliation state honestly. Never substitute
simulated ledger execution or falsely claim a successful commit.
