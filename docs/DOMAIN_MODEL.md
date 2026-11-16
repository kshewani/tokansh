# TokANSH — Domain Model

## 1. Domain Modelling Principles

The domain model represents fractional economic interests in real
estate through ANSH units.

Core principles:

1. Property assets and ANSH units are separate entities.
2. Legal property title and ANSH ownership are not equivalent.
3. ANSH issuance must be associated with an approved property.
4. Committed DRUNIX ledger state is authoritative for ANSH ownership and restrictions.
5. Pledged ANSH remains owned but is restricted from transfer.
6. REIT holdings are a separate asset class.
7. Financial values use fixed-precision decimal or integer units.
8. Application workflows and ledger transactions are distinct.

## 2. Core Entity Overview

### 2.1 User

Represents a participant interacting with TokANSH.

Attributes:
- user_id
- full_name
- email
- role
- status
- created_at
- updated_at

Demo roles:
- ADMIN
- ISSUER
- INVESTOR
- LENDER

The MVP may use predefined demonstration users and role switching.
This is not production authentication.

### 2.2 Property

Represents a real estate asset registered on TokANSH.

Attributes:
- property_id
- property_name
- property_type
- description
- address
- city
- country
- illustrative_valuation
- valuation_currency
- issuer_id
- verification_status
- approval_status
- approved_property_ref
- drunix_registration_transaction_id
- created_at
- updated_at

Property status:
- DRAFT
- SUBMITTED
- UNDER_REVIEW
- APPROVED
- REJECTED
- SUSPENDED

Relationships:
- One issuer may submit multiple properties.
- A property may have multiple supporting documents.
- A property may have one or more issuance records, subject to
  approved supply constraints.
- A property may have marketplace listings associated with its ANSH.

Property ownership/title information must not be inferred from
ANSH ownership.

### 2.3 Property Document

Represents a supporting document associated with a property.

Attributes:
- document_id
- property_id
- document_type
- document_name
- document_reference
- verification_status
- uploaded_at

Documents may be synthetic references in the MVP.

Do not claim external legal or government verification unless
an actual verification integration exists.

### 2.4 ANSH Issuance

Represents an authorized issuance of ANSH units against a property.

Attributes:
- issuance_id
- property_id
- approved_property_ref
- ansh_asset_id
- issuer_id
- approved_supply
- issued_quantity
- issue_price
- currency
- issuance_status
- ledger_transaction_id
- created_at
- confirmed_at

Issuance status:
- DRAFT
- PENDING_APPROVAL
- APPROVED
- SUBMITTED
- CONFIRMED
- FAILED

Rules:
- Property must be approved before issuance.
- Issued quantity must not exceed approved supply.
- Confirmed issuance requires actual DRUNIX commit confirmation.
- Application projections must not independently create ledger supply.

### 2.5 ANSH Unit

ANSH is the digitally represented fractional economic interest
associated with an approved real estate issuance.

The prototype uses fungible units.

Important:
ANSH is not automatically equivalent to registered legal title
or direct legal ownership of the underlying property.

Attributes:
- ansh_asset_id
- issuance_id
- property_id
- issue_price
- currency
- created_at

`ansh_asset_id` is the single application-level identifier for
the fungible ANSH asset/issuance class. Keep any actual DRUNIX
chaincode key or asset identifier separately if required by the
verified platform design.

Do not create an individual database row for every fungible unit.

### 2.6 Ownership Position

Represents an investor's ANSH balance for a property/issuance.

Attributes:
- position_id
- investor_id
- issuance_id
- owned_quantity
- pledged_quantity
- observed_at
- ledger_reference
- reconciliation_status

Derived quantity:

Available ANSH = Owned ANSH - Pledged ANSH

Rules:
- Owned quantity cannot be negative.
- Pledged quantity cannot exceed owned quantity.
- Available quantity cannot be negative.
- Committed DRUNIX ledger state is authoritative for ownership.
- Cached application positions must be traceable to ledger state.

Ownership status:
- ACTIVE
- RESTRICTED
- RECONCILIATION_REQUIRED

Do not treat an application snapshot as an independent ownership
authority.

### 2.7 Marketplace Listing

Represents an offer to sell ANSH units.

Attributes:
- listing_id
- seller_id
- issuance_id
- quantity
- unit_price
- currency
- listing_status
- created_at
- expires_at

Listing status:
- DRAFT
- ACTIVE
- PARTIALLY_FILLED
- FILLED
- CANCELLED
- EXPIRED

Rules:
- Seller must have sufficient available ANSH.
- Pledged units cannot be listed for transfer.
- Listing quantity cannot exceed available eligible holdings.
- Listing availability must be revalidated during purchase.

### 2.8 Purchase Order

Represents an investor's intention to purchase ANSH.

Attributes:
- order_id
- buyer_id
- seller_id
- listing_id
- issuance_id
- quantity
- unit_price
- total_amount
- currency
- order_status
- idempotency_key
- created_at
- updated_at

Order status:
- CREATED
- VALIDATED
- PAYMENT_PENDING
- PAYMENT_FAILED
- PAYMENT_SUCCEEDED
- TRANSFER_PENDING
- RECONCILIATION_REQUIRED
- COMPLETED
- CANCELLED
- FAILED

Rules:
- Buyer and seller must be valid participants.
- Quantity must be positive.
- Listing must be active.
- Seller must have sufficient available units.
- Total amount must be calculated by the backend.
- Duplicate order submissions must be protected.
- Ownership transfer must not occur after payment failure.

### 2.9 Payment Record

Represents a payment attempt associated with a purchase order.

Attributes:
- payment_id
- order_id
- payment_reference
- amount
- currency
- payment_status
- simulation_flag
- created_at
- completed_at

Payment status:
- INITIATED
- AUTHORIZED
- SUCCESS
- FAILED
- REVERSED
- UNKNOWN

For the MVP, payment is simulated.

Payment success does not itself establish ANSH ownership.

### 2.10 Blockchain Operation

Represents an operation submitted to the blockchain adapter.

Attributes:
- operation_id
- operation_type
- entity_id
- idempotency_key
- transaction_id
- drunix_network_reference
- submission_status
- commit_status
- error_code
- created_at
- confirmed_at

Operation types:
- APPROVED_PROPERTY_REGISTRATION
- ANSH_ISSUANCE
- ANSH_TRANSFER
- ANSH_PLEDGE
- ANSH_RELEASE

Operation status:
- CREATED
- SUBMITTED
- COMMITTED
- FAILED
- UNKNOWN
- RECONCILIATION_REQUIRED

Rules:
- Simulator references must be clearly identifiable as simulated.
- DRUNIX transaction identifiers must be genuine.
- Submission must not be confused with commit.
- An unknown outcome must be reconciled before retrying.

### 2.11 Collateral Pledge

Represents ANSH units restricted as collateral.

Attributes:
- pledge_id
- investor_id
- issuance_id
- quantity
- collateral_value
- currency
- pledge_status
- blockchain_operation_id
- created_at
- released_at

Pledge status:
- REQUESTED
- APPROVED
- SUBMITTED
- ACTIVE
- RELEASE_PENDING
- RELEASED
- FAILED

Rules:
- Investor must own sufficient eligible units.
- Available units must cover the pledge quantity.
- Pledged units remain owned by the investor.
- Pledged units cannot be transferred.
- Release requires the applicable loan and collateral conditions.
- Ledger confirmation requires actual DRUNIX commit confirmation.

### 2.12 Loan

Represents a financing arrangement backed by pledged ANSH.

Attributes:
- loan_id
- borrower_id
- lender_id
- pledge_id
- principal_amount
- outstanding_amount
- interest_rate
- currency
- collateral_value
- ltv_ratio
- loan_status
- created_at
- maturity_date

Loan status:
- REQUESTED
- UNDER_REVIEW
- APPROVED
- DISBURSED
- ACTIVE
- PARTIALLY_REPAID
- REPAID
- DEFAULTED
- REJECTED

The MVP lender and disbursement workflows are simulated.

A loan record does not imply that a real financial institution
has approved or disbursed funds.

### 2.13 Loan Repayment

Represents a repayment against a loan.

Attributes:
- repayment_id
- loan_id
- amount
- currency
- repayment_reference
- repayment_status
- simulation_flag
- created_at

Repayment status:
- INITIATED
- SUCCESS
- FAILED

Rules:
- Repayment cannot exceed the applicable outstanding balance.
- Outstanding balance must be recalculated deterministically.
- Collateral release must follow the defined loan settlement rules.

### 2.14 Distribution

Represents a rental income distribution declared for a property.

Attributes:
- distribution_id
- property_id
- issuance_id
- declared_by
- total_amount
- currency
- record_date
- distribution_date
- distribution_status
- created_at

Distribution status:
- DRAFT
- DECLARED
- PROCESSING
- COMPLETED
- FAILED

### 2.15 Distribution Entitlement

Represents an investor's entitlement to a declared distribution.

Attributes:
- entitlement_id
- distribution_id
- investor_id
- eligible_quantity
- total_eligible_quantity
- entitlement_amount
- currency
- calculation_reference
- entitlement_status

Rules:
- Eligibility is determined using ownership at the record date.
- Current holdings must not replace historical holdings.
- Total entitlements must reconcile to the declared distribution,
  subject to documented rounding treatment.
- Distribution payments are simulated in the MVP.

### 2.16 REIT Holding

Represents an investor's holding in a Real Estate Investment Trust.

Attributes:
- holding_id
- investor_id
- reit_identifier
- reit_name
- quantity
- purchase_value
- illustrative_market_value
- currency
- data_source
- observed_at

Rules:
- REIT holdings remain separate from ANSH holdings.
- REIT data is synthetic unless connected to a verified external feed.
- Do not apply ANSH ownership or collateral rules to REIT holdings
  without a separate approved design.

### 2.17 Asset Event

Represents an event in the lifecycle of a property or its ANSH.

Attributes:
- event_id
- property_id
- issuance_id
- event_type
- event_description
- event_source
- reference_id
- occurred_at

Event source:
- DRUNIX_LEDGER
- APPLICATION
- PAYMENT_SIMULATOR
- LENDER_SIMULATOR
- EXTERNAL_SIMULATOR

This distinction must be visible in audit views.

## 3. Entity Relationships

```text
User
 |
 +---- Property (Issuer)
 |        |
 |        +---- Property Documents
 |        |
 |        +---- ANSH Issuance
 |                 |
 |                 +---- Ownership Positions
 |                 |         |
 |                 |         +---- Marketplace Listings
 |                 |         |          |
 |                 |         |          +---- Purchase Orders
 |                 |         |                    |
 |                 |         |                    +---- Payment Records
 |                 |         |                    |
 |                 |         |                    +---- Blockchain Operations
 |                 |         |
 |                 |         +---- Collateral Pledges
 |                 |                    |
 |                 |                    +---- Loans
 |                 |                              |
 |                 |                              +---- Repayments
 |                 |
 |                 +---- Distributions
 |                           |
 |                           +---- Distribution Entitlements
 |
 +---- REIT Holdings
 |
 +---- Audit Events

Property
 |
 +---- Asset Events
```

This is a conceptual relationship diagram. Final database
cardinality and implementation details must be reviewed before
creating ORM models.

## 4. Important Domain Invariants

1. Issued quantity cannot exceed approved supply.
2. Total ownership must reconcile with confirmed issued supply.
3. Available quantity = owned quantity - pledged quantity.
4. Pledged quantity cannot exceed owned quantity.
5. Transfers cannot exceed available quantity.
6. Failed payment cannot result in ownership transfer.
7. Ownership updates require confirmed DRUNIX ledger commit.
8. Duplicate operations must not execute twice.
9. Loan outstanding balance cannot become negative.
10. Distribution entitlement uses record-date holdings.
11. ANSH and REIT holdings remain separate.
12. Application projections must not override authoritative ledger state.
13. Simulated events must never be presented as genuine ledger events.

## 5. Financial Data Representation

Use fixed-precision decimal arithmetic or integer minor units.

Recommended conventions:
- Currency: explicit ISO currency code, such as INR.
- Monetary amounts: Decimal or integer minor units.
- ANSH quantity: integer units for the MVP.
- Unit price: fixed-precision decimal.
- LTV: fixed-precision percentage.

Never use binary floating-point for financial calculations.

## 6. Identifier Strategy

Use stable unique identifiers for application entities.

Examples:
- property_id
- issuance_id
- order_id
- payment_id
- operation_id
- pledge_id
- loan_id
- distribution_id

Maintain a separate field for genuine DRUNIX transaction identifiers.

Do not use a simulated transaction reference in a field or UI
that implies a genuine blockchain transaction hash.

## 7. Open Domain Questions

Resolve these before finalizing production-oriented domain semantics:

1. Does DRUNIX support fungible ANSH token balances natively,
   or must chaincode maintain ownership quantities?
2. What exact ledger state is required to represent a pledge?
3. Can a pledge be partially released?
4. How can historical ownership be queried at a record date?
5. What are the supported identity and authorization mechanisms?
6. What are the legal and contractual rights represented by ANSH?
7. How are property valuation changes approved and recorded?
8. What transfer restrictions apply beyond collateral pledges?

Do not invent answers to unresolved questions.

## 8. Domain Model Acceptance Criteria

The domain model is acceptable when:

- Property and ANSH are distinct entities.
- Legal title is distinct from ANSH economic interests.
- Issuance, ownership and transfer are clearly represented.
- Available and pledged quantities are distinct.
- Purchase, payment and ledger operations have separate lifecycles.
- Collateral and loans are related but separate entities.
- Distribution entitlements use record-date holdings.
- REIT holdings remain a separate asset class.
- Audit events identify their source.
- Financial calculations use deterministic precision.
