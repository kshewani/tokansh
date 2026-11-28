# TokANSH — API Contracts

**Version:** 1.0
**Status:** Proposed MVP contract
**Last updated:** 2026-11-16

---

## 1. Purpose

This document defines the application programming interfaces between:

- React frontend
- Python FastAPI backend
- Go DRUNIX gateway adapter
- TokANSH application database
- Supporting simulation services

The purpose is to establish consistent API boundaries before implementation.

The contracts in this document are proposed TokANSH application interfaces.
They are not claims about existing DRUNIX native APIs.

Actual DRUNIX gateway methods, transaction lifecycle behaviour, identity
configuration and network interfaces must be verified against the deployed
DRUNIX version and its supported client libraries.

## 2. API Design Principles

1. Use REST APIs over HTTP/JSON for frontend-to-backend communication.
2. Use versioned application routes under `/api/v1`.
3. Use Pydantic models for request and response validation.
4. Use explicit resource identifiers.
5. Use consistent error responses.
6. Use decimal-safe financial representations.
7. Use idempotency controls for financial and ledger-changing operations.
8. Never expose private keys, certificates or signing material through APIs.
9. Never treat a submitted transaction as a committed transaction.
10. Never silently simulate a core ANSH ledger operation.
11. Keep DRUNIX-specific protocol details behind the Go gateway adapter.
12. Return clear operation states so the UI can distinguish pending, committed
    and failed transactions.

## 3. Application Components and Responsibilities

### 3.1 React frontend

Responsible for:

- User interaction
- Input validation for usability
- Displaying portfolio and asset information
- Displaying operation status
- Displaying ledger transaction references
- Showing simulated-service labels
- Presenting errors and reconciliation states

The frontend must not connect directly to DRUNIX.

### 3.2 FastAPI backend

Responsible for:

- Application API
- Business validation
- Workflow orchestration
- Application persistence
- Financial calculations
- Simulated payment and lending services
- Calling the Go DRUNIX gateway
- Reconciling application projections with ledger outcomes
- Application-level authorization

### 3.3 Go DRUNIX gateway adapter

Responsible for:

- DRUNIX network connectivity
- Client identity and signing
- TLS and gateway configuration
- Chaincode invocation
- Ledger queries
- Transaction submission
- Commit-status verification
- Mapping DRUNIX responses into a stable internal response format

The gateway adapter must not independently implement TokANSH business rules
that belong in FastAPI or chaincode.

### 3.4 Application database

Responsible for:

- Users and application roles
- Marketplace listings and orders
- Payment simulation records
- Loan simulation records
- Distribution workflows
- Application audit events
- Ledger operation metadata
- Read models and portfolio projections

The application database is not authoritative for core ANSH ownership.

## 4. API Conventions

### 4.1 Base path

All application endpoints use:

`/api/v1`

### 4.2 Content type

Requests and responses use:

`application/json`

### 4.3 Identifiers

Use UUIDs for application-generated resource identifiers unless a specific
external identifier must be preserved.

DRUNIX transaction identifiers must be stored and returned exactly as
provided by DRUNIX.

### 4.4 Financial values

Financial amounts must use decimal-safe representations.

Example:

- `amount`: `"5000000.00"`
- `currency`: `"INR"`

Do not serialize financial calculations using imprecise binary floating
point.

ANSH quantities must use integer values for the MVP.

### 4.5 Timestamps

Use ISO 8601 timestamps in UTC.

Example:

`2026-11-16T12:30:00Z`

### 4.6 Pagination

List endpoints should support:

- `page`
- `page_size`

Defaults:

- `page = 1`
- `page_size = 20`

Maximum page size: 100.

A standard paginated response contains:

- `items`
- `page`
- `page_size`
- `total_items`
- `total_pages`

### 4.7 Correlation and idempotency

Support:

- `X-Correlation-ID` for request tracing.
- `Idempotency-Key` for operations that may create financial or ledger state.

A repeated request with the same idempotency key must not create a duplicate
business operation.

The backend must detect conflicting reuse of an idempotency key with
different request parameters.

## 5. Standard Response and Error Contracts

### 5.1 Successful response

Example:

```json
{
  "data": {
    "id": "resource-identifier",
    "status": "success"
  },
  "meta": {
    "correlation_id": "correlation-identifier"
  }
}
```

### 5.2 Error response

Example:

```json
{
  "error": {
    "code": "INSUFFICIENT_AVAILABLE_ANSH",
    "message": "The requested quantity exceeds available ANSH.",
    "details": {
      "requested_quantity": 500,
      "available_quantity": 300
    }
  },
  "meta": {
    "correlation_id": "correlation-identifier"
  }
}
```

### 5.3 Standard HTTP status usage

| HTTP status | Meaning |
|---|---|
| 200 | Successful retrieval or operation |
| 201 | Resource created |
| 202 | Operation accepted and still processing |
| 400 | Invalid request |
| 401 | Authentication required |
| 403 | Insufficient permissions |
| 404 | Resource not found |
| 409 | Business conflict or idempotency conflict |
| 422 | Request validation failure |
| 500 | Unexpected application failure |
| 502 | Upstream integration failure |
| 503 | Required service unavailable |
| 504 | Upstream timeout |

An HTTP success response must not be interpreted as proof of DRUNIX
commitment unless the returned operation state explicitly confirms it.

## 6. Authentication and Roles

The MVP supports three demonstration roles:

- ADMIN / ISSUER
- INVESTOR
- LENDER

The UI may provide a demonstration role switcher.

This is not production authentication.

Backend authorization must still enforce role permissions. Hiding a button
in React is not sufficient access control.

Production-grade identity-provider integration is outside the MVP scope.

## 7. API Endpoint Catalogue

### 7.1 System and health

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/health` | Application liveness |
| GET | `/ready` | Application readiness and required dependency status |
| GET | `/api/v1/system/status` | Component and integration status |
| GET | `/api/v1/system/configuration` | Safe, non-secret runtime configuration |

The configuration endpoint must never expose credentials, private keys,
certificates or secret values.

The system status response should distinguish:

- FastAPI availability
- Application database availability
- Go gateway availability
- DRUNIX network connectivity
- DRUNIX transaction capability

A successful application health check does not imply DRUNIX is operational.

### 7.2 Demonstration users and roles

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/v1/users` | List demonstration users |
| GET | `/api/v1/users/{user_id}` | Get user details |
| GET | `/api/v1/roles` | List available demonstration roles |
| POST | `/api/v1/demo/active-role` | Change demonstration role |

Role switching is restricted to demonstration mode.

### 7.3 Dashboard

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/v1/dashboard/summary` | Dashboard summary |
| GET | `/api/v1/dashboard/recent-activity` | Recent application and asset activity |
| GET | `/api/v1/dashboard/portfolio-overview` | Portfolio overview |
| GET | `/api/v1/dashboard/market-overview` | Marketplace statistics |

Dashboard data may combine ledger-derived information with application
workflows and simulated analytics.

The response must identify data that is simulated where relevant.

### 7.4 Property registry

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/v1/properties` | List properties |
| POST | `/api/v1/properties` | Create property |
| GET | `/api/v1/properties/{property_id}` | Get property details |
| PUT | `/api/v1/properties/{property_id}` | Update editable property details |
| POST | `/api/v1/properties/{property_id}/submit` | Submit property for approval |
| POST | `/api/v1/properties/{property_id}/approve` | Approve property |
| GET | `/api/v1/properties/{property_id}/history` | Property lifecycle history |

Property approval is an application workflow decision. The
`POST /api/v1/properties/{property_id}/approve` endpoint records the
authorised review decision in the TokANSH application database.

After approval, the backend must register the approved property reference
and its approved issuance constraints on DRUNIX through the Go gateway
adapter. This registration is a ledger operation, not a property approval
decision.

The backend must confirm the DRUNIX commit before allowing ANSH issuance.
If registration fails or its outcome is unknown, issuance must remain
blocked or pending reconciliation. The application must not represent an
unconfirmed registration as successful.

### 7.5 ANSH issuance

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/api/v1/ansh/issuances` | Initiate ANSH issuance |
| GET | `/api/v1/ansh/issuances` | List issuances |
| GET | `/api/v1/ansh/issuances/{issuance_id}` | Get issuance details |
| GET | `/api/v1/ansh/issuances/{issuance_id}/status` | Get issuance operation status |

Example issuance request:

```json
{
  "property_id": "property-uuid",
  "total_quantity": 100000,
  "issue_price": "10000.00",
  "currency": "INR"
}
```

Example response:

```json
{
  "data": {
    "issuance_id": "issuance-uuid",
    "operation_id": "operation-uuid",
    "status": "COMMITTED",
    "total_quantity": 100000,
    "ledger_transaction_id": "actual-drunix-transaction-id"
  }
}
```

The transaction identifier above is illustrative. A real response must contain
the identifier returned by DRUNIX.

Issuance must not be reported as successful until ledger commitment has
been confirmed.

### 7.6 Marketplace

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/v1/marketplace/listings` | List available ANSH listings |
| POST | `/api/v1/marketplace/listings` | Create listing |
| GET | `/api/v1/marketplace/listings/{listing_id}` | Get listing |
| POST | `/api/v1/marketplace/listings/{listing_id}/cancel` | Cancel listing |
| POST | `/api/v1/marketplace/orders` | Create purchase order |
| GET | `/api/v1/marketplace/orders/{order_id}` | Get order details |
| GET | `/api/v1/marketplace/orders/{order_id}/status` | Get order and settlement status |

Example purchase request:

```json
{
  "listing_id": "listing-uuid",
  "buyer_id": "investor-uuid",
  "quantity": 500
}
```

A purchase order must pass business validation before settlement begins.

### 7.7 Payment simulation

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/api/v1/payments/simulate` | Execute simulated payment |
| GET | `/api/v1/payments/{payment_id}` | Get payment status |

Payment simulation must return an explicit simulation indicator.

Example:

```json
{
  "data": {
    "payment_id": "payment-uuid",
    "status": "SUCCESS",
    "simulation": true,
    "amount": "5000000.00",
    "currency": "INR"
  }
}
```

Payment success is not proof of ANSH ownership transfer.

### 7.8 ANSH transfers

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/api/v1/ansh/transfers` | Initiate ANSH transfer |
| GET | `/api/v1/ansh/transfers/{transfer_id}` | Get transfer details |
| GET | `/api/v1/ansh/transfers/{transfer_id}/status` | Get ledger operation status |

Example request:

```json
{
  "asset_id": "ansh-asset-uuid",
  "from_user_id": "seller-uuid",
  "to_user_id": "buyer-uuid",
  "quantity": 500
}
```

The backend must validate the available balance and then invoke the
appropriate DRUNIX chaincode operation.

Only confirmed ledger commitment can establish the new ownership projection.

### 7.9 Portfolio

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/v1/portfolios/{user_id}` | Get consolidated portfolio |
| GET | `/api/v1/portfolios/{user_id}/ansh` | Get ANSH holdings |
| GET | `/api/v1/portfolios/{user_id}/reits` | Get REIT holdings |
| GET | `/api/v1/portfolios/{user_id}/transactions` | Get transaction history |
| GET | `/api/v1/portfolios/{user_id}/summary` | Get portfolio summary |

ANSH and REIT holdings must remain distinct asset classes.

ANSH ownership must be derived from DRUNIX or a verified ledger projection,
not from an unverified application database balance.

Portfolio responses should identify the source and freshness of ledger-derived
information.

### 7.10 Collateral and financing

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/api/v1/collateral/pledges` | Initiate ANSH pledge |
| GET | `/api/v1/collateral/pledges/{pledge_id}` | Get pledge details |
| GET | `/api/v1/collateral/pledges/{pledge_id}/status` | Get pledge ledger status |
| POST | `/api/v1/loans/applications` | Create simulated loan application |
| GET | `/api/v1/loans/{loan_id}` | Get loan details |
| POST | `/api/v1/loans/{loan_id}/assess` | Run simulated credit assessment |
| POST | `/api/v1/loans/{loan_id}/approve` | Simulate lender approval |
| POST | `/api/v1/loans/{loan_id}/disburse` | Simulate loan disbursement |
| POST | `/api/v1/loans/{loan_id}/repayments` | Record simulated repayment |
| POST | `/api/v1/collateral/pledges/{pledge_id}/release` | Initiate full collateral release |

Pledge and release operations must be committed on DRUNIX.

Loan approval, disbursement and repayment are simulated workflows.

A successful simulated repayment does not itself release collateral.

Collateral becomes available only after DRUNIX confirms the release operation.

Partial collateral release is outside MVP scope.

### 7.11 Distributions

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/api/v1/distributions` | Create distribution declaration |
| GET | `/api/v1/distributions` | List distributions |
| GET | `/api/v1/distributions/{distribution_id}` | Get distribution details |
| POST | `/api/v1/distributions/{distribution_id}/calculate` | Calculate entitlements |
| GET | `/api/v1/distributions/{distribution_id}/entitlements` | List investor entitlements |
| POST | `/api/v1/distributions/{distribution_id}/simulate-payment` | Simulate distribution payments |

Entitlement calculations must use record-date eligible ownership.

The ownership snapshot or reference used in the calculation must be retained.

Distribution payments are simulated and must be labelled as such.

### 7.12 Asset intelligence

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/v1/assets/{asset_id}/valuation` | Get illustrative valuation |
| GET | `/api/v1/assets/{asset_id}/analytics` | Get asset analytics |
| GET | `/api/v1/assets/{asset_id}/performance` | Get illustrative performance |
| GET | `/api/v1/assets/{asset_id}/lifecycle` | Get asset lifecycle information |

Valuation and performance information must identify whether the data is
simulated or externally sourced.

### 7.13 Audit and history

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/v1/audit/events` | Query application audit events |
| GET | `/api/v1/assets/{asset_id}/history` | Get asset lifecycle history |
| GET | `/api/v1/ledger/operations/{operation_id}` | Get ledger operation metadata |
| GET | `/api/v1/ledger/transactions/{transaction_id}` | Get transaction status/details where supported |

Distinguish:

- Application audit events
- Asset lifecycle events
- DRUNIX ledger transactions

Do not claim that application audit records are immutable blockchain records.

## 8. Ledger Operation State Model

The backend must maintain a consistent operation lifecycle.

Recommended application states:

| State | Meaning |
|---|---|
| CREATED | Operation created |
| VALIDATING | Business validation in progress |
| SUBMITTED | Submitted to DRUNIX |
| COMMITTED | DRUNIX commitment confirmed |
| FAILED | Definitive failure established |
| UNKNOWN | Outcome cannot currently be established |
| RECONCILIATION_REQUIRED | Further status reconciliation is required |

The exact mapping of DRUNIX responses into these states must be validated
against actual gateway behaviour.

An operation in UNKNOWN or RECONCILIATION_REQUIRED must not be presented as
committed.

## 9. Go Gateway Adapter Contract

The following describes the logical interface expected by FastAPI.

It is not a specification of native DRUNIX endpoints or SDK method names.

The adapter must expose equivalent capabilities for:

### 9.1 Submit transaction

Input:

- Channel identifier
- Chaincode identifier
- Function name
- Function arguments
- Request correlation identifier
- Idempotency/business operation identifier

Output:

- Transaction identifier, when supplied by DRUNIX
- Submission result
- Current known operation state
- Error information, if any

### 9.2 Evaluate/query transaction

Input:

- Channel identifier
- Chaincode identifier
- Query function
- Query arguments

Output:

- Query result
- Relevant ledger metadata, where available

### 9.3 Check commit status

Input:

- DRUNIX transaction identifier

Output:

- Transaction status
- Validity or failure information, where available
- Block or commit metadata, where supported

### 9.4 Query ledger history

Input:

- Asset or ownership identifier
- Relevant query parameters

Output:

- Ledger-derived records or events
- Pagination or continuation information, if supported

History capabilities and event-retention semantics must be verified before
they are relied upon by application workflows.

### 9.5 Adapter error mapping

The adapter must distinguish:

- Invalid request
- Authentication or identity failure
- TLS/connectivity failure
- Endorsement failure
- Submission failure
- Commit validation failure
- Commit timeout
- Unknown transaction outcome
- Unsupported operation

Do not convert an unknown outcome into a definitive failure.

## 10. Critical Workflow Contracts

### 10.1 Purchase and transfer

1. Create purchase order.
2. Validate listing, quantity and buyer.
3. Verify seller's available ANSH through the authoritative ledger interface.
4. Execute simulated payment.
5. If payment fails, do not invoke the transfer.
6. If payment succeeds, submit the DRUNIX transfer.
7. Check transaction commitment.
8. Update ownership projections only after confirmed commitment.
9. If commitment fails or is ambiguous, initiate reconciliation.
10. Preserve both payment and ledger operation records.

### 10.2 Pledge

1. Validate investor and requested quantity.
2. Verify current ledger ownership.
3. Verify available, unpledged quantity.
4. Submit pledge to DRUNIX.
5. Confirm commitment.
6. Update application projections.
7. Permit simulated loan processing after the required pledge state is
   confirmed.

If loan processing fails after pledge commitment, do not silently remove
the pledge. A separate release operation is required.

### 10.3 Collateral release

1. Verify simulated loan repayment conditions.
2. Confirm that the loan is fully repaid.
3. Submit release operation to DRUNIX.
4. Confirm commitment.
5. Update application collateral projections.
6. Make the units available again only after confirmed commitment.

### 10.4 Rental distribution

1. Create distribution declaration.
2. Determine the record date.
3. Obtain the applicable ledger ownership snapshot or verified reconstruction.
4. Calculate investor entitlements.
5. Persist calculation inputs and results.
6. Simulate payment.
7. Record simulated payment outcome.

## 11. Error Codes

Recommended application error codes:

| Error code | Meaning |
|---|---|
| INVALID_REQUEST | Invalid request data |
| RESOURCE_NOT_FOUND | Requested resource does not exist |
| INSUFFICIENT_AVAILABLE_ANSH | Available quantity is insufficient |
| PROPERTY_NOT_APPROVED | Property is not eligible for issuance |
| ISSUANCE_LIMIT_EXCEEDED | Requested issuance exceeds approved supply |
| PLEDGED_UNITS_RESTRICTED | Pledged units cannot be transferred |
| PAYMENT_FAILED | Simulated payment failed |
| LEDGER_UNAVAILABLE | DRUNIX is unavailable |
| LEDGER_SUBMISSION_FAILED | Transaction submission failed |
| LEDGER_COMMIT_FAILED | Transaction was definitively invalidated or failed |
| LEDGER_OUTCOME_UNKNOWN | Commitment outcome is unknown |
| RECONCILIATION_REQUIRED | Operation requires reconciliation |
| IDEMPOTENCY_CONFLICT | Idempotency key reused with conflicting request |
| INVALID_OPERATION_STATE | Operation is not valid in the current state |
| INSUFFICIENT_PERMISSIONS | User lacks required role or permission |

Error responses must not expose private keys, credentials, certificate
contents or sensitive internal stack traces.

## 12. Security Requirements

- Validate all inputs on the backend.
- Enforce role-based permissions in FastAPI.
- Do not trust client-supplied ownership balances.
- Never accept private signing keys from frontend requests.
- Keep gateway credentials outside source control.
- Restrict access to administrative and ledger-management operations.
- Validate resource ownership before investor-specific operations.
- Record security-relevant application actions.
- Avoid exposing internal network addresses and secrets through status APIs.
- Use HTTPS in public-cloud deployment.
- Restrict DRUNIX management interfaces from public access.

## 13. API Documentation and Testing

FastAPI should generate OpenAPI documentation.

Development endpoints:

- `/docs`
- `/redoc`
- `/openapi.json`

The API implementation must include:

- Request schema tests
- Response schema tests
- Business validation tests
- Authorization tests
- Idempotency tests
- Error mapping tests
- Ledger adapter contract tests
- Integration tests against the self-hosted DRUNIX network

Unit tests may use isolated mocks for testing application behaviour
and adapter contracts. These mocks must never be used as a runtime ledger
implementation or treated as evidence of DRUNIX integration.

Integration tests must execute against the self-hosted DRUNIX network and
verify actual transaction submission, commit status and resulting ledger
state.

## 14. Implementation Rules

1. Implement only the API contracts required by the approved MVP.
2. Keep endpoint naming and response conventions consistent.
3. Do not implement all endpoints before their underlying business modules
   are ready.
4. Keep API schemas separate from database models.
5. Do not expose database entities directly as public API contracts.
6. Keep ledger transaction metadata separate from application resource IDs.
7. Document any deliberate deviation from this contract.
8. Update this document whenever an approved API contract changes.

## 15. Implementation Notes and Deviations

Recorded as required by rule 14.7. Implemented in `backend/app/modules/`.

1. **Demo identity.** `POST /auth/login` (any non-empty password) issues an in-memory bearer session; requests send `Authorization: Bearer`. `GET /auth/me`, `POST /auth/logout`. Not authentication; roles are enforced per operation. Missing token -> 401 `AUTHENTICATION_REQUIRED`, unknown or ended session -> 401 `INVALID_SESSION`, unknown username -> 401 `INVALID_CREDENTIALS`. Refused in production. The earlier `X-Demo-User-Id` header and `/demo/active-role` are removed.
2. **Idempotency-Key is mandatory** (400 if absent) on: approve, register, issuances, listings, orders, payments, transfers, pledges, release, repayments, distribution payout. Business-error responses are stored and replayed too.
3. **Two-step purchase.** `POST /marketplace/orders` creates the order (`PAYMENT_PENDING`); `POST /payments/simulate` with `simulated_outcome: SUCCESS | FAILED` runs the simulated payment and, on success, the DRUNIX transfer. A failed payment returns 409 `PAYMENT_FAILED`.
4. **Ledger outcomes.** 200/201 only after `COMMITTED`; 202 when pending or reconciliation is required; 503 `LEDGER_UNAVAILABLE`, 502 `LEDGER_COMMIT_FAILED` / `LEDGER_SUBMISSION_FAILED`, or 409 with the chaincode's business code when it failed. The body includes the operation and its DRUNIX transaction id when one exists.
5. **Approval returns 202** when approval succeeded but DRUNIX registration did not commit. `POST /properties/{id}/register` (new) retries only after a definitive failure.
6. **Added endpoints:** `POST /properties/{id}/documents`, `POST /properties/{id}/register`, `GET /marketplace/orders`, `GET /collateral/pledges`, `GET /loans`, `POST /loans/{id}/reject`, `GET /assets/events`, `GET /ledger/operations`, `POST /ledger/operations/{id}/reconcile`, `GET /reconciliation/cases`.
7. **New error codes:** `AUTHENTICATION_REQUIRED`, `INVALID_SESSION`, `INVALID_CREDENTIALS`, `AUTH_NOT_CONFIGURED`, `LTV_LIMIT_EXCEEDED`, `REPAYMENT_EXCEEDS_OUTSTANDING`, `INVALID_LENDER`, `INVALID_OFFER`, `INSUFFICIENT_DEMO_CASH`, `INITIAL_ISSUANCE_MUST_MATCH_APPROVED_SUPPLY`, `ISSUANCE_ALREADY_COMPLETED`, `LEDGER_FUNCTION_UNAVAILABLE`, `LEDGER_NOT_SUBMITTED`, `INTERNAL_ERROR`.
12. **Simulated financing additions:** `GET /financing/lenders` (fictional lender catalogue with offers), loan applications take `lender_id`, `offer_id`, `interest_rate_bps`, `term_months` (must match the offer; fixed-term simple interest, repaid interest-first), and a simulated demo cash wallet (`GET /wallet`, `POST /wallet/fund`, `POST /wallet/withdraw`) credited by disbursement and debited by repayment.
8. **One-time full-supply issuance** (chaincode policy `ONE_TIME_FULL_SUPPLY_ISSUANCE`, adopted from main): `quantity` must equal the approved supply (422 `INITIAL_ISSUANCE_MUST_MATCH_APPROVED_SUPPLY`, checked before DRUNIX and again by the chaincode); a second issuance returns 409 `ISSUANCE_ALREADY_COMPLETED`. A definitively failed issuance can be retried on the same record. A gateway that cannot prove the policy on the deployed chaincode returns 503 `LEDGER_FUNCTION_UNAVAILABLE`.
9. **Record date.** Entitlements use holdings committed up to the end of the record date (UTC), reconstructed from committed ledger operations and verified against the confirmed issued supply. Calculation is refused before the record date; on the record date itself the cut-off is the calculation time, which is recorded. Pending team confirmation.
10. **Who approves.** ADMIN or ISSUER may approve a property, matching the demo script ("Issuer approves"). Segregating issuer and approver is a team decision.
13. **Purchases are paid from the simulated demo wallet** (adopted from main). A successful simulated payment debits the buyer (`PURCHASE_PAYMENT`, 409 `INSUFFICIENT_DEMO_CASH` before anything else happens); the seller is credited (`SALE_PROCEEDS`) only after the DRUNIX transfer commits; a failed transfer refunds the buyer (`PURCHASE_REFUND`); an ambiguous outcome keeps the cash held until reconciliation resolves it. The seed gives Aarav INR 1 crore of opening demo cash. Still simulated cash: no bank, no atomic DvP.
14. **Friendly ANSH symbols** (`ansh_symbol`, e.g. `ANSH-TECHPARK`) on properties, listings, orders and holdings. Presentation only: the ledger, the API paths and every command keep using the property UUID.
11. **Not implemented yet (Priority 2):** `/dashboard/*` beyond `summary`, `/assets/{id}/valuation|analytics|performance|lifecycle`.

---

**End of API Contracts**
