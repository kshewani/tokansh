# TokANSH — Hackathon Demonstration Script

**Version:** 1.0
**Status:** Proposed MVP demonstration
**Last updated:** 2026-11-16

---

## 1. Purpose

This document defines the end-to-end TokANSH hackathon demonstration.

It describes:

- The business problem.
- The product proposition.
- The demonstration personas.
- The application screens.
- The transaction sequence.
- The DRUNIX operations.
- The simulated supporting workflows.
- Expected results.
- Presenter talking points.
- Technical evidence.
- Failure and recovery handling.

The demonstration must prove that TokANSH does more than issue digital tokens.
It must demonstrate how tokenised real estate interests can be managed
through ownership transfers, collateral restrictions, financing workflows,
income distributions and asset lifecycle operations.

## 2. Demonstration Objectives

The presentation should establish five capabilities:

1. Real estate assets can be represented through ANSH units.
2. Core ANSH issuance and ownership operations execute on DRUNIX.
3. Ownership restrictions and collateral lifecycle rules are enforced.
4. Financing and income distribution workflows can be built around ANSH.
5. The application provides a consolidated view of asset ownership,
   transactions and lifecycle activity.

The demo must clearly distinguish actual DRUNIX operations from simulated
supporting financial services.

## 3. Product Introduction

### 3.1 Product

**TokANSH**

**Tagline:** Unlocking Real Estate, One Ansh at a Time

### 3.2 Meaning

ANSH represents a fractional unit of an underlying real estate asset within
the TokANSH prototype.

The platform demonstrates the lifecycle of these units, including issuance,
ownership, transfers, collateral pledges, release and income distributions.

ANSH must not be represented as automatically conferring registered legal
property title or direct legal ownership of the underlying property.

### 3.3 Problem statement

Real estate investment traditionally involves:

- High capital requirements.
- Limited access to fractional participation.
- Complex ownership administration.
- Limited secondary-market flexibility.
- Difficulty using property interests within digital financial workflows.
- Fragmented asset and transaction information.

TokANSH demonstrates a technology platform intended to address these
challenges through tokenised asset representation and lifecycle management.

### 3.4 Differentiation

The demonstration must emphasise what happens after issuance:

- Ownership verification.
- Transfer restrictions.
- Ledger-backed transfers.
- Collateral management.
- Financing workflows.
- Income distribution.
- Consolidated portfolio information.
- Asset lifecycle traceability.

## 4. Demonstration Environment

### 4.1 Deployment

The presentation environment should use the publicly accessible TokANSH
application deployed in the selected public cloud.

The deployed environment must include:

- React frontend.
- FastAPI backend.
- Go DRUNIX gateway adapter.
- Self-hosted DRUNIX network.
- DRUNIX chaincode.
- DRUNIX state database.
- TokANSH application database.

The local environment remains the primary development and recovery
environment.

### 4.2 Infrastructure readiness

Before the presentation, verify:

- Public application URL works.
- HTTPS certificate is valid.
- Frontend loads.
- FastAPI is healthy.
- Application database is accessible.
- Go gateway is connected.
- DRUNIX network is operational.
- Chaincode is deployed and accessible.
- Required test identities and permissions work.
- Persistent data is available.
- No administrative or database interfaces are unnecessarily exposed.

### 4.3 Transaction evidence

For core ANSH operations, capture:

- Actual DRUNIX transaction identifier.
- Submission result.
- Confirmed commit status.
- Relevant ledger query result.
- Resulting ownership or collateral state.

Do not use fabricated transaction IDs or hardcoded success responses.

## 5. Demonstration Personas

### 5.1 Meera — Property Owner / Issuer

Meera owns or represents TechPark One and wants to make fractional ANSH units
available to investors.

Her journey:

- Register property.
- Complete approval workflow.
- Issue ANSH.
- Make ANSH available for purchase.
- Review ownership and lifecycle activity.

### 5.2 Aarav — Investor

Aarav wants to invest in fractional real estate interests and use his ANSH
holdings within supporting financial workflows.

His journey:

- Explore available ANSH.
- Purchase 500 ANSH.
- Review portfolio.
- Pledge 200 ANSH.
- Explore simulated financing.
- Receive a simulated rental distribution.
- Repay the simulated loan.
- Release collateral.

### 5.3 Lender — Financing Participant

The lender reviews the collateral-backed financing request.

The MVP demonstrates this through a simulated lender workflow, not an actual
financial institution integration.

## 6. Primary Demonstration Data

### 6.1 Property

| Attribute | Value |
|---|---|
| Property name | TechPark One |
| Property valuation | ₹100 crore |
| Total ANSH supply | 100,000 |
| Issue price | ₹10,000 per ANSH |
| Currency | INR |

All values are illustrative demonstration data.

### 6.2 Investor transaction

| Attribute | Value |
|---|---|
| Investor | Aarav |
| Purchase quantity | 500 ANSH |
| Purchase value | ₹50,00,000 |
| Pledge quantity | 200 ANSH |
| Available after pledge | 300 ANSH |

### 6.3 Supporting financing

Loan amount, collateral valuation, interest rate, repayment schedule and
distribution amount must be selected and documented in the approved demo
dataset before the final rehearsal.

Do not invent these values during the presentation.

## 7. Recommended Presentation Sequence

The following sequence is designed for an approximately 10–15 minute
demonstration. Adjust timing to the hackathon presentation rules.

| Stage | Activity | Suggested time |
|---|---|---:|
| 1 | Introduction and problem | 1 min |
| 2 | Product and architecture | 1 min |
| 3 | Property approval, DRUNIX registration and ANSH issuance | 2 min |
| 4 | Investor purchase and DRUNIX transfer | 2 min |
| 5 | Portfolio and collateral pledge | 2 min |
| 6 | Pledged-unit transfer rejection | 1 min |
| 7 | Lending and rental distribution | 2 min |
| 8 | Repayment and collateral release | 2 min |
| 9 | Closing and impact | 1 min |

The final sequence should be rehearsed against the actual presentation time.

## 8. Act 1 — Introduction

**Presenter:** Product overview

Suggested talking points:

"Real estate is one of the world's largest asset classes, but participation
often requires significant capital and complex ownership administration.

TokANSH explores how fractional real estate interests can be represented
digitally and managed throughout their lifecycle.

Our focus is not simply token issuance. It is what happens after tokenisation:
how units are transferred, restricted, used as collateral and associated
with income distributions."

Show:

- TokANSH dashboard.
- Product name and tagline.
- High-level capability overview.

Avoid claiming that the prototype has already solved legal ownership,
regulatory or liquidity challenges.

## 9. Act 2 — Architecture

Show the high-level application architecture.

Explain:

- React provides the user experience.
- FastAPI manages business workflows.
- Go provides the DRUNIX gateway integration.
- DRUNIX executes core ANSH ledger operations.
- SQLite stores application workflow data in the MVP.
- Lending and payment supporting services are simulated.

Emphasise:

"Core ANSH issuance, ownership, transfer and collateral operations are
executed on DRUNIX. Supporting lending and payment workflows are simulated
for this prototype."

If useful, show the DRUNIX network status screen.

Do not expose private keys, internal database credentials or administrative
network interfaces.

## 10. Act 3 — Meera Registers TechPark One

**Persona:** Meera — Admin / Issuer

### Actions

1. Open Property Registry.
2. Select Register Property.
3. Enter TechPark One details.
4. Enter illustrative valuation of ₹100 crore.
5. Enter proposed ANSH supply of 100,000.
6. Review property information.
7. Submit the property for approval.
8. Complete the approval workflow.

### Expected result

- Property is visible in the registry.
- Approval status is displayed.
- The relevant ledger state is shown where the implemented chaincode
  records the property lifecycle.

### Presenter talking point

"TokANSH starts with an asset, not with a token. We first establish the
property information and the eligibility workflow for ANSH issuance."

Do not claim independent property verification unless an actual verification
service is integrated.

## 11. Act 4 — Issue 100,000 ANSH on DRUNIX

**Persona:** Meera — Admin / Issuer

### Actions

1. Open ANSH Issuance.
2. Select TechPark One.
3. Enter 100,000 ANSH.
4. Set issue price to ₹10,000.
5. Review issuance parameters.
6. Submit issuance.
7. Wait for DRUNIX commitment confirmation.
8. Open the issuance transaction details.

### Expected result

- 100,000 ANSH are issued.
- Actual DRUNIX transaction identifier is displayed.
- Commitment status is confirmed.
- Ledger query reflects the issuance.
- Application issuance projection matches ledger state.

### Presenter talking point

"The issuance is not a UI-only record. The chaincode operation is executed
on our DRUNIX network, and we verify its committed state before reporting
the issuance as successful."

### Technical evidence

Capture the actual transaction ID and a corresponding authoritative ledger
query result.

## 12. Act 5 — Aarav Purchases 500 ANSH

**Persona:** Aarav — Investor

### Actions

1. Switch to Aarav's demonstration role.
2. Open Marketplace.
3. Find TechPark One.
4. Select 500 ANSH.
5. Review the purchase value.
6. Confirm purchase.
7. Execute simulated payment.
8. Wait for DRUNIX transfer submission.
9. Verify transaction commitment.
10. Open Aarav's portfolio.

### Expected result

Purchase value:

500 × ₹10,000 = ₹50,00,000.

- Simulated payment status is visible.
- DRUNIX transfer status is committed.
- Actual transaction identifier is visible.
- Seller and buyer ownership reflect the transfer.
- Aarav's portfolio displays 500 ANSH.

### Presenter talking point

"The payment workflow and the ownership transfer are separate operations.
The payment is simulated, but the ownership transfer is actually executed
and committed on DRUNIX."

Do not describe the process as atomic delivery-versus-payment.

## 13. Act 6 — Aarav Pledges 200 ANSH

**Persona:** Aarav — Investor

### Actions

1. Open Portfolio.
2. Select TechPark One.
3. Review 500 owned ANSH.
4. Open Collateral Management.
5. Select 200 ANSH for pledge.
6. Review the collateral information.
7. Confirm pledge.
8. Submit pledge through DRUNIX.
9. Verify commitment.
10. Refresh the portfolio.

### Expected result

| Balance | Quantity |
|---|---:|
| Total owned | 500 |
| Pledged | 200 |
| Available | 300 |

The units remain owned by Aarav but are restricted from transfer.

### Presenter talking point

"TokANSH allows an investor to use ANSH holdings within a collateral
workflow while preserving ownership information and enforcing restrictions
on pledged units."

## 14. Act 7 — Demonstrate Pledged-Unit Transfer Rejection

This is a key business-rule demonstration.

### Actions

1. Attempt to transfer more than 300 available ANSH.
2. Alternatively, attempt to transfer a quantity that includes pledged units.
3. Submit the request.

### Expected result

- Operation is rejected.
- Pledged units remain unchanged.
- No successful transfer is recorded.
- Available balance remains 300.
- The user receives a clear explanation.

The rejection must be enforced by the authoritative ledger business rules,
not merely by disabling a frontend button.

### Presenter talking point

"This is where the ledger-backed business rules matter. A pledged asset
cannot be transferred as though it were freely available."

## 15. Act 8 — Simulated Financing

**Persona:** Aarav and Lender

### Actions

1. Open Financing.
2. Create a loan application.
3. Select the committed collateral pledge.
4. Enter the agreed demonstration loan amount.
5. Run simulated credit assessment.
6. Switch to the lender demonstration role.
7. Review the collateral and application.
8. Simulate approval.
9. Simulate disbursement.

### Expected result

- Loan application is recorded.
- Collateral details reference the confirmed DRUNIX pledge.
- Simulated assessment result is displayed.
- Simulated approval and disbursement are recorded.
- Loan balance and LTV are calculated.

### Presenter talking point

"The collateral state is backed by DRUNIX, while credit assessment and
lending are simulated. This demonstrates how tokenised asset interests
could support financing workflows."

Clearly display the simulated-service label.

## 16. Act 9 — Rental Income Distribution

**Persona:** Aarav — Investor

### Actions

1. Open Rental Distributions.
2. Select TechPark One.
3. Review the distribution period and record date.
4. Calculate investor entitlements.
5. Review Aarav's eligible holdings.
6. Simulate distribution payment.

### Expected result

- Distribution calculation uses record-date ownership.
- Eligible ANSH quantity is displayed.
- Calculation inputs and results are retained.
- Payment status is labelled simulated.

Pledged units remain investor-owned and are included in distribution
eligibility unless the demonstration's explicitly defined contractual
rules state otherwise.

### Presenter talking point

"Ownership is not only about trading. TokANSH also demonstrates how income
can be allocated based on eligible holdings at a defined record date."

## 17. Act 10 — Repayment and Collateral Release

**Persona:** Aarav — Investor

### Actions

1. Open Loan Details.
2. Review outstanding simulated loan balance.
3. Record full simulated repayment.
4. Confirm that the loan is fully repaid.
5. Open Collateral Management.
6. Initiate full pledge release.
7. Submit the release through DRUNIX.
8. Verify commitment.
9. Refresh the portfolio.

### Expected result

- Loan is marked repaid in the simulated lending workflow.
- DRUNIX release transaction is committed.
- Pledge status is updated.
- Previously pledged 200 ANSH become available.
- Aarav still owns all 500 ANSH.

### Presenter talking point

"The lifecycle does not end with a pledge. Once the simulated financing
obligation is repaid, the collateral release is executed on DRUNIX and the
investor's available balance is restored."

## 18. Act 11 — Final Portfolio and Lifecycle Review

Show Aarav's final portfolio.

Expected state:

| Attribute | Final value |
|---|---:|
| Total owned ANSH | 500 |
| Pledged ANSH | 0 |
| Available ANSH | 500 |

Show:

- Purchase transaction.
- Pledge transaction.
- Rejected transfer attempt.
- Collateral release transaction.
- Rental distribution record.
- Application and asset lifecycle history.

Explain which events are actual ledger transactions and which are
application-level or simulated records.

## 19. Evidence Checklist

The following evidence should be prepared before the presentation.

### DRUNIX evidence

- Network is running.
- Chaincode is deployed.
- Property/asset records where supported.
- ANSH issuance transaction.
- ANSH transfer transaction.
- Pledge transaction.
- Rejected invalid transfer.
- Collateral release transaction.
- Ledger query results.
- Actual transaction identifiers.
- Confirmed commit statuses.

### Application evidence

- Dashboard.
- Property details.
- Issuance details.
- Purchase confirmation.
- Portfolio before and after pledge.
- Rejected transfer screen.
- Simulated lending details.
- Rental distribution calculation.
- Collateral release result.
- Final lifecycle history.

### Deployment evidence

- Public application URL.
- HTTPS access.
- System status screen.
- DRUNIX connectivity.
- Persistent data after restart.
- No publicly exposed administrative interfaces.

## 20. Pre-Demonstration Checklist

### Infrastructure

- [ ] Complete application is deployed in the public-cloud environment.
- [ ] DRUNIX network is deployed and operational in that environment.
- [ ] HTTPS works.
- [ ] FastAPI is healthy.
- [ ] Application database is accessible.
- [ ] Go gateway is operational and connected to the deployed DRUNIX network.
- [ ] Chaincode is deployed on the cloud DRUNIX network.
- [ ] Required identities and permissions work.
- [ ] Actual cloud DRUNIX transactions have been tested and committed.
- [ ] Transaction identifiers and commit evidence are available for
      the demonstration.

### Business data

- [ ] TechPark One is available.
- [ ] Property approval is recorded in the TokANSH application.
- [ ] Approved property reference and issuance constraints are registered
      and committed on DRUNIX.
- [ ] 100,000 ANSH issuance is committed on DRUNIX.
- [ ] Actual transaction identifiers and commit evidence are available.
- [ ] Marketplace listing is available.
- [ ] Aarav's demonstration account is ready.
- [ ] Financing parameters are documented.
- [ ] Distribution parameters are documented.

### Functional

- [ ] Purchase workflow works.
- [ ] Payment simulation works.
- [ ] Transfer commitment is verified.
- [ ] Pledge works.
- [ ] Pledged-unit transfer is rejected.
- [ ] Loan simulation works.
- [ ] Distribution calculation works.
- [ ] Repayment simulation works.
- [ ] Collateral release works.
- [ ] Final portfolio balances are correct.

### Presentation

- [ ] Presentation timing rehearsed.
- [ ] Screens and navigation rehearsed.
- [ ] Transaction evidence prepared.
- [ ] Simulated services labelled.
- [ ] Backup screenshots and evidence available.
- [ ] Recovery procedure documented.

## 21. Failure and Recovery Plan

The demonstration must not hide real technical failures.

### DRUNIX unavailable

- Stop core ANSH ledger operations.
- Show the integration failure clearly.
- Do not silently use a simulator.
- Use previously captured evidence only if explicitly labelled as historical
  evidence, not as a live transaction.

### Transaction submission timeout

- Display UNKNOWN or RECONCILIATION_REQUIRED.
- Check transaction status.
- Do not blindly resubmit.

### Transaction committed but UI not refreshed

- Query the authoritative ledger state.
- Rebuild or refresh the application projection.
- Preserve the actual transaction identifier.

### Simulated payment failure

- Show payment failure.
- Do not submit the corresponding ANSH transfer.

### Simulated lending failure after pledge

- Preserve the committed pledge.
- Show the loan workflow failure.
- Execute a separate release only through the approved release process.

### Cloud failure

- Use the local development environment for technical recovery if permitted.
- Clearly disclose that the demonstration has moved to a local environment.

## 22. Closing Statement

Suggested closing:

"TokANSH demonstrates a lifecycle-oriented approach to real estate
tokenisation.

By combining DRUNIX-backed ANSH issuance, ownership, transfers and
collateral management with supporting financing and income workflows,
we demonstrate how tokenised real estate interests can become part of a
broader digital financial ecosystem.

Our focus is not just creating a token. It is enabling the lifecycle
around the asset."

## 23. Claims and Limitations

During the demonstration:

- Do not claim registered legal property ownership.
- Do not claim actual bank lending.
- Do not claim actual payment-gateway integration.
- Do not claim atomic delivery-versus-payment.
- Do not claim production-grade decentralisation based solely on a
  self-hosted test network.
- Do not claim production scalability or regulatory certification.
- Do not describe simulated income as guaranteed investment returns.
- Do not claim a transaction is committed without evidence.

The demonstration should be technically honest and distinguish implemented
capabilities from illustrative workflows.

---

**End of Demonstration Script**
