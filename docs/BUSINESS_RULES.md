# TokANSH — Business Rules and Financial Invariants

## 1. Purpose

This document defines the business rules governing ANSH issuance,
ownership, marketplace transactions, settlement, collateral financing,
loan repayment and rental income distributions.

These rules must be consistently enforced by:
- Backend domain services.
- Blockchain chaincode where ledger enforcement is required.
- Application workflows.
- Frontend validation and presentation.

Frontend validation is supplementary. The backend and ledger must
enforce their respective authoritative rules.

## 2. Financial Representation

### 2.1 Currency

- Use an explicit currency code for every monetary amount.
- INR is the default demonstration currency.
- Do not mix currencies in calculations without an explicit
  conversion mechanism.

### 2.2 Precision

- Use Python Decimal or integer minor currency units.
- Never use binary floating-point for financial calculations.
- Define rounding rules explicitly.
- Preserve calculation inputs and outputs for auditability.

### 2.3 ANSH Quantity

For the MVP:
- ANSH quantities are whole units.
- Quantity must be a positive integer for issuance, purchase,
  transfer and pledge operations.
- Fractional ANSH units are not supported unless separately approved.

## 3. Property Approval and ANSH Issuance

### Rule 3.1 — Property Eligibility

ANSH issuance is permitted only against an approved property.

### Rule 3.2 — Supply Constraint

Issued supply must never exceed approved supply.

Issued Quantity <= Approved Supply

Remaining Supply = Approved Supply - Issued Quantity

### Rule 3.3 — Issuance Price

Every issuance must have a defined unit price and currency.

Illustrative issuance:

Property: TechPark One
Property valuation: INR 100 crore
Approved supply: 100,000 ANSH
Issue price: INR 10,000 per ANSH
Illustrative issuance value: INR 100 crore

### Rule 3.4 — Issuance Confirmation

- Issuance requests must have unique operation identifiers.
- A submitted issuance is not a confirmed issuance.
- Issued supply is recognized only after the DRUNIX transaction is committed and its outcome is confirmed.
- Failed or ambiguous operations must not be treated as successful.

## 4. Ownership and Available Balance

### Rule 4.1 — Ownership

ANSH ownership represents the economic interest recorded by the
platform under the defined ANSH model. It does not automatically
represent registered legal property title.

### Rule 4.2 — Available Balance

Available ANSH = Owned ANSH - Pledged ANSH

Example:

Owned ANSH: 500
Pledged ANSH: 200
Available ANSH: 300

### Rule 4.3 — Balance Constraints

- Owned quantity cannot be negative.
- Pledged quantity cannot exceed owned quantity.
- Available quantity cannot be negative.
- Confirmed transfers must reconcile between sender and recipient.
- Total ownership must reconcile with confirmed issued supply.

### Rule 4.4 — Source of Ownership

- Committed DRUNIX ledger state is the sole authority for ANSH ownership.
- SQLite may maintain ownership projections and cached read models for application queries and display.
- Application projections must never silently override ledger state.
- A projection must be reconciled against DRUNIX and must not be treated as proof of ownership.
- Test mocks may be used only in isolated automated tests; they are never authoritative in a running application or demo.

## 5. Marketplace and Purchase Rules

### Rule 5.1 — Listing Eligibility

A seller may list only units that are available for transfer.

Listing Quantity <= Available ANSH

### Rule 5.2 — Purchase Eligibility

A purchase is valid only when:

- Listing is active.
- Listing has sufficient remaining quantity.
- Buyer and seller are valid participants.
- Purchase quantity is positive.
- Seller has sufficient available ANSH.
- Unit price and currency are valid.

All conditions must be revalidated immediately before execution.

### Rule 5.3 — Purchase Calculation

Purchase Amount = Quantity * Unit Price

Example:

Quantity: 500 ANSH
Unit Price: INR 10,000
Purchase Amount: INR 50,00,000

The backend calculates the amount. The frontend must not be
the authority for the transaction amount.

### Rule 5.4 — Listing Updates

After a confirmed transfer:
- Reduce remaining listing quantity.
- Mark listing PARTIALLY_FILLED if units remain.
- Mark listing FILLED if no units remain.

Do not reduce listing quantity based on an unconfirmed transfer.

### Rule 5.5 — Duplicate Purchase Protection

Every consequential purchase operation must have a unique
idempotency key.

Repeated requests with the same key must not create duplicate
payments or transfers.

## 6. Payment and Settlement Rules

### Rule 6.1 — Payment Before Transfer

The MVP sequence is:

1. Validate purchase.
2. Initiate payment simulation.
3. Receive payment result.
4. If payment fails, stop the transfer workflow.
5. If payment succeeds, submit ownership transfer.
6. Wait for ledger commit confirmation.
7. Update application read models.
8. Mark purchase COMPLETED.

### Rule 6.2 — Payment Failure

If payment fails:
- Ownership must not change.
- No ledger transfer must be submitted.
- Purchase status becomes PAYMENT_FAILED.
- Failure reason must be recorded.

### Rule 6.3 — Transfer Failure After Payment Success

If payment succeeds but ledger transfer fails:
- Preserve the successful payment record.
- Do not update ownership.
- Mark the purchase RECONCILIATION_REQUIRED or equivalent.
- Do not mark the order COMPLETED.
- Initiate an explicit compensation or refund workflow.
  For the MVP, this may be simulated.
- Record the outcome and references.

### Rule 6.4 — Ambiguous Ledger Outcome

If ledger submission succeeds but commit status is unknown:
- Do not blindly resubmit.
- Query transaction status and ownership.
- Reconcile the outcome.
- Update application state only after the result is established.

### Rule 6.5 — Settlement Integrity

Payment success is not proof of ownership transfer.

Ownership transfer success is not proof of payment unless the
payment record independently confirms it.

Do not claim atomic delivery versus payment.

## 7. ANSH Transfer Rules

### Rule 7.1 — Transfer Eligibility

Transfer Quantity <= Available ANSH

### Rule 7.2 — Pledged Unit Restriction

Pledged ANSH cannot be transferred.

### Rule 7.3 — Transfer State Change

After confirmed transfer:

Sender Owned ANSH = Sender Owned ANSH - Transfer Quantity

Recipient Owned ANSH = Recipient Owned ANSH + Transfer Quantity

Sender Pledged ANSH remains unchanged.

### Rule 7.4 — Transfer Validation

Every transfer must validate:
- Sender identity.
- Recipient identity.
- Issuance identity.
- Sufficient available balance.
- Applicable transfer restrictions.
- Unique operation identifier.

### Rule 7.5 — Concurrency

Two concurrent transactions must not transfer the same units.

DRUNIX chaincode must enforce the balance constraint against ledger state at transaction execution time, not only during an earlier UI or backend query.

## 8. Collateral Financing Rules

### Rule 8.1 — Collateral Eligibility

Only eligible ANSH units may be pledged.

REIT holdings are excluded from collateral in the current MVP.

### Rule 8.2 — Pledge Quantity

Pledge Quantity <= Available ANSH

### Rule 8.3 — Collateral Valuation

Collateral Value = Pledged Quantity * Approved Collateral Unit Value

Use an explicitly defined valuation source and observation time.

The illustrative market value must not automatically be treated
as an approved collateral value.

### Rule 8.4 — Loan-to-Value Ratio

LTV (%) = Outstanding Loan / Collateral Value * 100

Example:

Pledged ANSH: 200
Illustrative collateral unit value: INR 10,000
Collateral value: INR 20,00,000
Illustrative loan: INR 12,00,000

LTV = 60%

### Rule 8.5 — LTV Validation

- Collateral value must be greater than zero.
- Loan amount must be greater than zero.
- LTV must not exceed the configured demonstration threshold.
- The threshold must be configurable, not hardcoded into UI logic.
- The prototype must label the result as indicative.

### Rule 8.6 — Pledge State

After confirmed pledge:
- Pledged quantity increases.
- Available quantity decreases.
- Owned quantity remains unchanged.
- Pledged units become non-transferable.

### Rule 8.7 — Transfer Restriction

An investor cannot transfer pledged ANSH.

An attempted transfer exceeding available quantity must be rejected by backend validation and DRUNIX chaincode. The ledger must independently enforce the restriction against committed state.

## 9. Loan Repayment and Collateral Release

### Rule 9.1 — Repayment Amount

Repayment must be positive and cannot exceed the applicable
outstanding amount.

### Rule 9.2 — Outstanding Balance

New Outstanding Balance =
Previous Outstanding Balance - Confirmed Repayment

The MVP may use a simplified principal-only loan model.
If interest is introduced, it must be separately modelled and
calculated deterministically.

### Rule 9.3 — Full Repayment

When outstanding balance reaches zero:
- Loan status becomes REPAID.
- Collateral becomes eligible for release, subject to the
  configured release workflow.

### Rule 9.4 — Collateral Release

After confirmed release:
- Pledged quantity decreases.
- Available quantity increases.
- Owned quantity remains unchanged.
- Released units become transferable again.

### Rule 9.5 — Partial Repayment

Partial repayment does not automatically release all collateral.

The MVP must define whether partial release is supported.
Until implemented and tested, collateral release requires
full repayment.

## 10. Rental Income Distribution Rules

### Rule 10.1 — Distribution Declaration

A distribution must have:
- Property.
- Associated issuance.
- Total distribution amount.
- Currency.
- Record date.
- Distribution date.
- Declaring administrator.

### Rule 10.2 — Eligible Holdings

Investor eligibility is determined by holdings at the declared
record date.

Current holdings must not be substituted for historical holdings.

### Rule 10.3 — Entitlement Calculation

Investor Entitlement =
Investor Eligible ANSH / Total Eligible ANSH
* Total Distribution Amount

Example:

Total Eligible ANSH: 100,000
Investor Eligible ANSH: 500
Total Distribution: INR 10,00,000

Investor Entitlement =
500 / 100,000 * 10,00,000
= INR 5,000

### Rule 10.4 — Pledged Holdings

For the MVP, pledged units remain part of the investor's ownership
and are included in distribution eligibility unless a separately
defined contractual rule specifies otherwise.

Pledging alone does not transfer ownership.

### Rule 10.5 — Distribution Reconciliation

- Sum of investor entitlements must reconcile with the declared
  distribution amount.
- Any rounding residual must be handled deterministically.
- The allocation method must be documented.
- Distribution records must not be duplicated.
- Payment execution is simulated in the MVP.

### Rule 10.6 — Historical Ownership

Historical ownership must be obtained from:
- A verified ledger snapshot; or
- A deterministic reconstruction from confirmed ledger events.

If neither is available, the application must not present a
historical ownership-based distribution calculation as verified.
The calculation must remain pending or unavailable until a reliable
DRUNIX snapshot or confirmed-event reconstruction can be obtained.

## 11. Asset Valuation and Portfolio Rules

### Rule 11.1 — Portfolio Valuation

Illustrative ANSH Value =
Owned ANSH * Current Illustrative Unit Value

Display pledged units separately from available units.

### Rule 11.2 — Cost and Market Value

Acquisition cost and illustrative market value must be displayed
as different measures.

Do not present unrealized gains as realized profit.

### Rule 11.3 — Portfolio Allocation

ANSH and REIT holdings must be reported separately.

A consolidated portfolio may show both asset classes, but must
preserve their separate classifications.

### Rule 11.4 — Synthetic Valuations

Synthetic valuations must be clearly labelled.

A simulated valuation must not be presented as an independently
verified market valuation.

## 12. Audit and Lifecycle Rules

Every consequential operation must record:
- Operation identifier.
- Entity identifier.
- Actor.
- Operation type.
- Timestamp.
- Previous state where relevant.
- New state where relevant.
- Source system.
- Simulation indicator.
- Ledger transaction reference, where applicable.
- Outcome.

Event source must distinguish:
- DRUNIX_LEDGER
- APPLICATION
- PAYMENT_SIMULATOR
- LENDER_SIMULATOR
- EXTERNAL_SIMULATOR

Do not label application events as blockchain-confirmed events.

## 13. Core State Transition Rules

### Purchase

CREATED
  -> VALIDATED
  -> PAYMENT_PENDING
  -> PAYMENT_SUCCEEDED
  -> TRANSFER_PENDING
  -> COMPLETED

Alternative outcomes:

PAYMENT_PENDING -> PAYMENT_FAILED

TRANSFER_PENDING -> RECONCILIATION_REQUIRED

TRANSFER_PENDING -> FAILED

### Pledge

REQUESTED
  -> APPROVED
  -> SUBMITTED
  -> ACTIVE

Failure outcomes must be recorded without incorrectly increasing
pledged quantity.

### Loan

REQUESTED
  -> UNDER_REVIEW
  -> APPROVED
  -> DISBURSED
  -> ACTIVE
  -> PARTIALLY_REPAID
  -> REPAID

### Distribution

DRAFT
  -> DECLARED
  -> PROCESSING
  -> COMPLETED

Failed processing must not silently create duplicate entitlements.

## 14. Demonstration Data and Expected Results

Property:
TechPark One

Illustrative property valuation:
INR 100 crore

Approved and issued ANSH:
100,000

Issue price:
INR 10,000 per ANSH

Investor:
Aarav

Purchase:
500 ANSH

Purchase amount:
INR 50,00,000

After successful transfer:

Owned ANSH: 500
Pledged ANSH: 0
Available ANSH: 500

After pledging 200 ANSH:

Owned ANSH: 500
Pledged ANSH: 200
Available ANSH: 300

Attempted transfer of 350 ANSH:
REJECTED

After full repayment and confirmed collateral release:

Owned ANSH: 500
Pledged ANSH: 0
Available ANSH: 500

All these outcomes must be reflected consistently across the
portfolio, financing and audit modules.

## 15. Business Rule Acceptance Criteria

The implementation is acceptable when:

1. Issuance cannot exceed approved supply.
2. Ownership balances reconcile with confirmed issuance.
3. Available balance excludes pledged units.
4. Failed payment never triggers ownership transfer.
5. Ownership changes only after confirmed DRUNIX ledger commit.
6. Duplicate operations do not execute twice.
7. Concurrent transfers cannot overspend a balance.
8. Pledged units cannot be transferred.
9. Loan balances cannot become negative.
10. Full repayment enables collateral release.
11. Distribution uses record-date holdings.
12. Distribution totals reconcile deterministically.
13. REIT holdings remain separate from ANSH.
14. Simulated operations are explicitly labelled.
15. Audit history accurately reflects every consequential transition.
