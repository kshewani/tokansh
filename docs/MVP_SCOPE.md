# TokANSH — MVP Scope

## 1. Objective

Deliver a functional, jury-ready prototype demonstrating the
complete lifecycle of fractional real estate economic interests.

The MVP must demonstrate how an asset moves from onboarding and
issuance through investment, ownership, transfer, financing,
income distribution and lifecycle tracking.

The objective is a compelling end-to-end demonstration, not
a production-ready financial platform.

## 2. MVP Modules

### Module 1 — Executive Dashboard
- Total platform property valuation.
- Total ANSH issued.
- Total investor holdings.
- Active properties.
- Marketplace activity.
- Financing and collateral summary.
- Rental distribution summary.
- Recent platform activity.

### Module 2 — Property Registry
- Property listing and details.
- Property onboarding workflow.
- Property valuation and supporting information.
- Approval and rejection workflow.
- Issuance status and associated ANSH supply.

### Module 3 — ANSH Issuance
- Configure approved supply.
- Define issue price.
- Issue ANSH against approved property.
- Display total, issued and remaining supply.
- Record issuance events.

### Module 4 — Marketplace
- Browse available ANSH listings.
- View property and investment details.
- Display unit price and available quantity.
- Purchase ANSH.
- Show order and transaction status.
- Support successful and failed payment scenarios.

### Module 5 — Settlement
- Simulate payment authorization.
- Support payment success and failure.
- Submit ownership transfer only after payment success.
- Confirm ownership update after ledger commit.
- Record transaction references and statuses.
- Provide reconciliation handling for ambiguous outcomes.

### Module 6 — Investor Portfolio
- Display ANSH holdings by property.
- Show owned, available and pledged units.
- Show illustrative acquisition cost and current value.
- Display portfolio allocation.
- Display transaction history.
- Show financing obligations and distributions.
- Display REIT holdings separately from ANSH.

### Module 7 — Collateral Financing
- Select eligible ANSH holdings.
- Pledge selected units.
- Calculate indicative collateral value.
- Calculate indicative LTV.
- Simulate financing approval and disbursement.
- Track loan principal and repayment.
- Reject transfers involving pledged units.
- Release collateral after repayment.

### Module 8 — Rental Distributions
- Declare property rental distribution.
- Configure distribution amount and record date.
- Calculate investor entitlements from eligible holdings.
- Record distribution outcomes.
- Display investor distribution history.

### Module 9 — Asset Intelligence
- Property valuation indicators.
- Rental yield indicators.
- Property performance metrics.
- Portfolio concentration.
- Indicative collateral capacity.
- Synthetic market insights.

All synthetic data must be labelled.

### Module 10 — Audit and Lifecycle
- Property onboarding and approval history.
- ANSH issuance events.
- Ownership transfers.
- Pledges and releases.
- Financing and repayments.
- Distribution declarations and records.
- Transaction and workflow status.

Distinguish ledger-confirmed events from simulated and
application-only events.

## 3. Personas and Demo Roles

The prototype will support three demonstration roles:

1. Admin / Issuer
   - Property approval.
   - ANSH issuance.
   - Platform monitoring.
   - Distribution declaration.

2. Investor
   - Marketplace purchases.
   - Portfolio management.
   - Collateral pledging.
   - Loan repayment.
   - Distribution history.

3. Lender
   - Collateral review.
   - Financing simulation.
   - Loan status management.
   - Collateral release.

Role switching is a demonstration convenience, not production
authentication or authorization.

## 4. Mandatory End-to-End Demo Journey

The following sequence must work consistently across the UI,
backend and blockchain adapter.

### Phase A — Property Onboarding and Issuance

1. Admin opens the property registry.
2. Meera submits TechPark One.
3. Admin reviews and approves the property.
4. Admin issues 100,000 ANSH.
5. The system displays issuance and supply information.

### Phase B — Investor Purchase

6. Aarav opens the marketplace.
7. Aarav selects TechPark One.
8. Aarav purchases 500 ANSH at INR 10,000 per unit.
9. Payment simulation returns success.
10. Ownership transfer is submitted to the ledger.
11. Ledger commit is confirmed.
12. Aarav's portfolio reflects 500 ANSH.

### Phase C — Collateral Financing

13. Aarav selects 200 ANSH for collateral.
14. The system calculates indicative collateral value and LTV.
15. Aarav submits a financing request.
16. Lender approves the simulated financing.
17. The system records the pledge and loan.
18. Aarav's available ANSH becomes 300.
19. An attempted transfer of pledged units is rejected.

### Phase D — Rental Distribution

20. Admin declares a rental distribution for TechPark One.
21. The system applies the declared record date.
22. Eligible holdings are determined using ownership at that date.
23. Aarav's entitlement is calculated.
24. Distribution history is updated.

### Phase E — Repayment and Release

25. Aarav repays the simulated loan.
26. The loan outstanding balance is updated.
27. The collateral pledge is released.
28. Aarav's available ANSH returns to 500.
29. Portfolio and audit history reflect all changes.

## 5. Demonstration Data

### Property: TechPark One

| Attribute | Value |
|---|---:|
| Property valuation | INR 100 crore |
| Total ANSH supply | 100,000 |
| Issue price | INR 10,000 |
| Total issuance value | INR 100 crore |

### Investor: Aarav

| Attribute | Value |
|---|---:|
| Initial purchase | 500 ANSH |
| Purchase value | INR 50 lakh |
| Collateral pledge | 200 ANSH |
| Available after pledge | 300 ANSH |
| Available after repayment and release | 500 ANSH |

All values are illustrative.

### Distribution Example

Use a configurable synthetic distribution amount and record date.
The investor entitlement must be calculated using eligible holdings
at the record date, not the holdings at the time the screen is viewed.

## 6. Functional Requirements

- All primary navigation items must lead to functional screens.
- Forms must validate input and provide meaningful feedback.
- Financial calculations must use deterministic decimal arithmetic.
- Backend services must enforce business rules.
- State changes must persist across application restarts.
- Related modules must use consistent underlying data.
- Transactions must have explicit statuses.
- Critical operations must be protected against duplicate execution.
- Failed operations must not produce partial business outcomes.
- Audit history must be consistent with actual state transitions.

## 7. Simulation Boundaries

The following may be simulated for the MVP:

- Payment gateway.
- Bank financing and disbursement.
- Property verification.
- External valuation feeds.
- Market intelligence.
- REIT market data.
- External rental payment execution.

Simulated workflows must be labelled in the UI and recorded as
simulated in the application data.

Core ANSH ledger operations must execute against the actual DRUNIX
network. There is no runtime simulator ledger mode or fallback.
Test-only mocks may be used for isolated automated tests but cannot
be used in the running application or hackathon demonstration.

## 8. Blockchain Requirements

The DRUNIX adapter and chaincode must support the following
verified ledger operations:

- Register an approved property reference and its approved
  ANSH issuance constraints.
- ANSH issuance against a registered approved property reference.
- Ownership and available-balance queries.
- ANSH transfers.
- Pledge and collateral release operations.
- Relevant ANSH asset lifecycle records.

Property onboarding, document verification and approval remain
TokANSH application workflows. They are not DRUNIX chaincode
approval operations.

The actual DRUNIX implementation must be based on verified
platform capabilities and developer documentation. Core ANSH
operations must never fall back to simulated ledger state.

## 9. Out of Scope

The following are explicitly excluded from the initial MVP:

- Production user authentication and KYC.
- Real property title registration.
- Legal enforceability of tokenized property interests.
- Real bank lending or loan disbursement.
- Real payment gateway integration.
- Production custody and key management.
- Public blockchain interoperability.
- Real-world secondary market liquidity.
- Production REIT integration.
- Regulatory compliance certification.
- Multi-cloud deployment.
- Kubernetes deployment.
- Production high availability and disaster recovery.

These may be future roadmap items.

## 10. Acceptance Criteria

The MVP is considered demonstrable when:

1. A property can be onboarded and approved.
2. ANSH can be issued against the approved property.
3. An investor can purchase ANSH.
4. Payment failure prevents ownership transfer.
5. Successful payment leads to confirmed ownership transfer.
6. Portfolio holdings reflect the transfer.
7. An investor can pledge eligible units.
8. Pledged units cannot be transferred.
9. Financing and repayment workflows function.
10. Rental distribution entitlement is calculated correctly.
11. Repayment releases collateral.
12. Portfolio and audit history reflect all lifecycle events.
13. Data remains consistent across all modules.
14. Simulated operations are never misrepresented as real integrations.
15. The approved property reference and issuance constraints are
    committed to DRUNIX before ANSH issuance.
16. ANSH issuance is confirmed only after actual DRUNIX commit.
17. Ownership, transfers, pledges and collateral releases are verified
    against committed DRUNIX ledger state.
18. Transaction IDs and commit evidence originate from actual DRUNIX
    responses and are not fabricated.
19. Failed or unknown ledger outcomes preserve safe pending or
    reconciliation states; they do not update ownership optimistically.
20. The complete local application operates against the self-hosted
    DRUNIX development network.
21. The complete application and DRUNIX network are deployed to the
    public-cloud demonstration environment and pass end-to-end tests.
22. The cloud demonstration verifies actual ledger operations, not
    simulator or mock results.

## 11. Delivery Priorities

Priority 1 — Mandatory:
- Property registry, off-chain verification and approval.
- Registration of approved property references and issuance constraints
  on DRUNIX.
- Reproducible self-hosted DRUNIX development network.
- Real DRUNIX chaincode and gateway integration.
- Complete application and DRUNIX deployment to the public-cloud
  demonstration environment.
- ANSH issuance.
- Marketplace purchase.
- Payment and ownership transfer workflow.
- Investor portfolio.
- Pledging and transfer restrictions.
- Loan repayment and collateral release.
- Rental distribution.
- Audit history.

Priority 2 — Important:
- Executive dashboard.
- Lender role.
- Asset intelligence.
- REIT portfolio representation.

Priority 3 — Polish:
- Advanced charts.
- Additional filtering and search.
- Rich lifecycle visualizations.
- Responsive refinements.
- Presentation-quality empty and error states.

Priority 1 must work end-to-end before spending significant time
on Priority 2 or Priority 3 enhancements.
