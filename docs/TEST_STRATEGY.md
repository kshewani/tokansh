# TokANSH — Test Strategy

**Version:** 1.0
**Status:** Proposed MVP test specification
**Last updated:** 2026-11-16

---

## 1. Purpose

Define the testing approach, test levels, coverage expectations, acceptance
criteria and validation procedures for the TokANSH MVP.

Testing must establish that:

- Core ANSH operations execute against an actual DRUNIX network.
- Business invariants are enforced.
- Financial calculations are deterministic.
- Application projections remain consistent with ledger state.
- Simulated supporting workflows are clearly separated from ledger operations.
- The complete demonstration works locally and can be deployed to public cloud.

A successful UI interaction alone is not evidence of a successful ledger
operation.

## 2. Testing Principles

1. Test business rules independently of the UI.
2. Test DRUNIX integration against an actual running network.
3. Never treat isolated mock tests as proof of DRUNIX integration.
4. Verify ledger commitment, not merely transaction submission.
5. Test both successful and unsuccessful paths.
6. Test duplicate requests and ambiguous transaction outcomes.
7. Use deterministic synthetic test data.
8. Keep test credentials and private keys out of Git.
9. Make tests reproducible through scripts and documented setup.
10. Separate local development tests from cloud deployment tests.

## 3. Testing Levels

| Level | Scope | Primary objective |
|---|---|---|
| Unit | Individual functions and modules | Validate isolated business logic |
| Component | Backend modules and UI components | Validate component behaviour |
| API | FastAPI endpoints | Validate request/response contracts |
| Contract | FastAPI-to-Go adapter | Validate integration interface |
| Chaincode | TokANSH chaincode | Validate ledger business rules |
| DRUNIX integration | Actual DRUNIX network | Validate real ledger execution |
| End-to-end | Complete user journeys | Validate application workflows |
| Deployment | Docker and cloud | Validate operational readiness |
| Security | Application and network boundaries | Validate access and secret handling |

## 4. Test Environments

### 4.1 Local development

Environment:

- Windows 11
- WSL2 Ubuntu 22.04
- Docker Desktop
- Docker Compose
- TokANSH application containers
- Self-hosted DRUNIX test network

This is the primary development and integration-test environment.

### 4.2 Test network

Use the official DRUNIX test-network implementation as the starting point.

Validate:

- Network startup
- Organisation configuration
- Peer availability
- Ordering service availability
- Validation service availability
- Channel configuration
- Chaincode deployment
- Application gateway connectivity

The exact topology and startup requirements must be verified against the
selected DRUNIX repository version.

### 4.3 Public-cloud demonstration

Deploy the complete application and DRUNIX network to the selected public
cloud environment.

Validate:

- Container startup
- Network connectivity
- Persistent storage
- Gateway and ledger operations
- HTTPS access
- Secret configuration
- Application health
- Restart and recovery behaviour

Cloud deployment tests must use the same application code and container
images as local testing.

## 5. Testing Technology

Recommended tools:

| Component | Testing tools |
|---|---|
| Python backend | Pytest |
| API | FastAPI TestClient / HTTPX |
| Python coverage | pytest-cov |
| Go gateway | Go testing package |
| Go coverage | go test -cover |
| Go HTTP contract | httptest where applicable |
| React | Vitest |
| UI components | React Testing Library |
| Browser end-to-end | Playwright |
| Chaincode | Go testing package and supported DRUNIX test environment |
| Containers | Docker Compose health checks |
| API documentation | OpenAPI validation |

Do not introduce a test dependency unless it provides a clear benefit.

## 6. Test Data

Use controlled synthetic data.

### 6.1 Primary demonstration property

| Attribute | Value |
|---|---|
| Property | TechPark One |
| Illustrative valuation | ₹100 crore |
| Total ANSH supply | 100,000 |
| Issue price | ₹10,000 |
| Currency | INR |

### 6.2 Demonstration investors

| Investor | Purpose |
|---|---|
| Meera | Property owner / issuer |
| Aarav | Investor |

### 6.3 Primary transaction

| Attribute | Value |
|---|---|
| Purchase quantity | 500 ANSH |
| Purchase value | ₹50,00,000 |
| Pledged quantity | 200 ANSH |
| Available after pledge | 300 ANSH |

All test data must be synthetic.

Tests must not rely on real customer information or real financial accounts.

## 7. Domain and Business Rule Tests

### 7.1 Property validation

Test:

- Property creation with valid information.
- Missing mandatory fields.
- Invalid property valuation.
- Invalid currency.
- Duplicate property identifiers.
- Approval of eligible property in the TokANSH application.
- Rejection of ineligible property in the application.
- Registration of an approved property reference and its issuance
  constraints on DRUNIX.
- Issuance attempted before application approval.
- Issuance attempted before confirmed DRUNIX property registration.

Expected result:

ANSH issuance must not proceed unless property approval is recorded
in the application and the approved property reference and issuance
constraints have been committed to DRUNIX.

### 7.2 ANSH issuance

Test:

- Valid issuance.
- Issuance at approved supply.
- Issuance exceeding approved supply.
- Zero quantity.
- Negative quantity.
- Duplicate issuance request.
- Issuance against unapproved property.
- DRUNIX submission failure.
- DRUNIX commit failure.
- Ambiguous commit outcome.

Expected invariants:

- Issued supply must not exceed approved supply.
- Issuance success requires confirmed DRUNIX commitment.
- Duplicate requests must not create duplicate issuance.

### 7.3 Ownership and transfer

Test:

- Transfer between valid accounts.
- Transfer of available ANSH.
- Transfer of zero quantity.
- Transfer of negative quantity.
- Transfer exceeding available holdings.
- Transfer by a non-owner.
- Transfer to an invalid recipient.
- Duplicate transfer request.
- Transfer while DRUNIX is unavailable.
- Transfer with unknown commit outcome.

Expected invariants:

- Ownership changes only after confirmed DRUNIX commitment.
- Transfer quantity cannot exceed available holdings.
- Failed transactions must not create an application ownership update.

### 7.4 Collateral pledge

Test:

- Pledge of available ANSH.
- Pledge exceeding available quantity.
- Pledge of units not owned by the investor.
- Duplicate pledge request.
- Pledge while DRUNIX is unavailable.
- Pledge submission failure.
- Pledge commit failure.
- Ambiguous pledge outcome.

Expected invariants:

- Pledged quantity cannot exceed owned, unpledged quantity.
- Pledged units remain owned.
- Pledged units cannot be transferred.
- Application pledge state must reflect confirmed ledger state.

### 7.5 Collateral release

Test:

- Full repayment followed by release.
- Release before full repayment.
- Release of unknown pledge.
- Duplicate release request.
- Release submission failure.
- Release commit failure.
- Ambiguous release outcome.

Expected invariants:

- Full loan repayment is required for MVP collateral release.
- Units remain restricted until release commitment is confirmed.
- Partial collateral release is not supported.

### 7.6 Financial calculations

Test:

- Purchase value.
- Collateral value.
- LTV.
- Outstanding loan balance.
- Repayment balance.
- Rental entitlement.
- Distribution rounding.
- Currency consistency.

Expected invariants:

- No binary floating-point financial arithmetic.
- Rounding is deterministic.
- Currency is explicit.
- Calculations can be reproduced from stored inputs.

## 8. Chaincode Testing

Chaincode tests must validate the actual business rules enforced at the
ledger boundary.

Required operations, subject to the verified chaincode design:

- RegisterApprovedProperty
- IssueANSH
- TransferANSH
- PledgeANSH
- UpdateCollateralStatus
- ReleasePledge
- DeclareDistribution, if included in the implemented ledger design
- GetAssetHistory or equivalent supported query

For each operation, test:

1. Valid invocation.
2. Invalid arguments.
3. Unauthorized caller.
4. Invalid business state.
5. Duplicate operation.
6. Conflicting state.
7. Expected state changes.
8. Expected rejection behaviour.

Important:

A passing chaincode unit test does not prove that the application is
successfully integrated with a running DRUNIX network.

That requires separate integration tests.

## 9. Go Gateway Tests

Test the Go gateway independently.

Required test areas:

- Client configuration validation.
- Certificate loading.
- Private-key loading.
- TLS configuration.
- Gateway connection.
- Query/evaluate operations.
- Transaction submission.
- Commit-status verification.
- Error translation.
- Timeout handling.
- Connection failure.
- Invalid identity.
- Invalid chaincode response.
- Unknown transaction outcome.

Verify that:

- Actual DRUNIX transaction identifiers are preserved.
- Endorsement and submission are not treated as commitment.
- Unknown outcomes are not mapped to successful outcomes.
- Secrets never appear in logs or error responses.

Use mocks for isolated gateway unit tests, but do not substitute mocks for
actual DRUNIX integration tests.

## 10. DRUNIX Integration Tests

These tests must run against the self-hosted DRUNIX test network.

### 10.1 Network readiness

Verify:

- Required network processes are running.
- Channel is available.
- Required organisations are operational.
- Required peers are available.
- Chaincode is deployed and accessible.
- Go gateway can connect.

### 10.2 Real issuance test

1. Register a test property.
2. Approve it using the implemented workflow.
3. Issue ANSH through the application.
4. Capture the actual DRUNIX transaction identifier.
5. Verify commit status.
6. Query ledger state.
7. Confirm issued supply.

Acceptance criterion:

The issued supply must be visible through an authoritative DRUNIX query
after confirmed commitment.

### 10.3 Real transfer test

1. Query seller ownership.
2. Transfer a defined ANSH quantity.
3. Obtain the DRUNIX transaction identifier.
4. Verify commitment.
5. Query both seller and buyer balances.
6. Verify the resulting ownership.

Acceptance criterion:

The ledger must reflect the expected ownership change.

### 10.4 Real pledge test

1. Query investor ownership.
2. Pledge 200 available ANSH.
3. Verify commitment.
4. Query pledge and available balance.
5. Attempt a transfer involving pledged units.

Acceptance criteria:

- Pledge is visible in authoritative ledger state.
- Pledged units remain owned.
- Pledged units cannot be transferred.

### 10.5 Real release test

1. Complete the simulated loan repayment workflow.
2. Submit full collateral release.
3. Verify DRUNIX commitment.
4. Query updated collateral and available balance.

Acceptance criterion:

Released units become available only after confirmed ledger commitment.

### 10.6 Transaction history

Verify that the implemented history/query mechanism returns the required
asset operations.

Do not assume that event replay, retention or historical-state queries are
available until verified against DRUNIX.

## 11. API Contract Tests

Validate every implemented FastAPI endpoint against its documented schema.

Test:

- Required fields
- Optional fields
- Invalid values
- Response structure
- HTTP status codes
- Error codes
- Authorization
- Pagination
- Idempotency
- Correlation identifiers

The generated OpenAPI specification must match the implemented endpoints.

Test FastAPI-to-Go adapter requests and responses independently.

## 12. Application Database Tests

Test:

- Database initialisation.
- Alembic migrations.
- Entity relationships.
- Constraints.
- Duplicate prevention.
- Transaction boundaries.
- Rollback behaviour.
- Data consistency after failed workflows.
- Restart persistence.

For application projections, verify that a failed or uncommitted ledger
operation does not produce a false ownership update.

## 13. Purchase Workflow End-to-End Tests

### Scenario A: Successful purchase

1. Seller has sufficient ANSH.
2. Buyer creates order.
3. Order passes validation.
4. Simulated payment succeeds.
5. DRUNIX transfer is submitted.
6. DRUNIX confirms commitment.
7. Application updates ownership projection.

Expected result:

Purchase is completed and the ledger reflects the ownership transfer.

### Scenario B: Payment failure

1. Buyer creates order.
2. Simulated payment fails.

Expected result:

No DRUNIX transfer is submitted.

### Scenario C: Ledger failure after payment success

1. Buyer creates order.
2. Simulated payment succeeds.
3. DRUNIX transfer fails definitively.

Expected result:

- Payment record remains successful.
- Ownership does not change.
- Order enters the appropriate failure/reconciliation state.
- The application does not falsely report a completed purchase.

### Scenario D: Ambiguous ledger outcome

1. Payment succeeds.
2. Transfer is submitted.
3. Connection fails before commit status is established.

Expected result:

- Operation is marked UNKNOWN or RECONCILIATION_REQUIRED.
- No false ownership update occurs.
- The system reconciles before retrying.
- Duplicate transfer is prevented.

## 14. Lending and Distribution Simulation Tests

### Lending

Test:

- Loan application.
- Credit assessment.
- Lender approval.
- Disbursement simulation.
- Repayment.
- Outstanding balance calculation.
- Rejection.
- Loan processing failure after a committed pledge.

All lending results must be identified as simulated.

A loan failure after a confirmed pledge must not silently release the
collateral.

### Rental distributions

Test:

- Record-date ownership snapshot.
- Entitlement calculation.
- Pledged units included in ownership where contractual rules permit.
- Distribution rounding.
- Simulated payment success.
- Simulated payment failure.
- Duplicate payment simulation.
- Historical entitlement reproducibility.

## 15. Frontend Testing

Test the following UI behaviour:

- Navigation.
- Role-based presentation.
- Form validation.
- Dashboard loading.
- Property onboarding.
- ANSH issuance.
- Marketplace purchase.
- Payment and transfer stages.
- Portfolio refresh after committed transfer.
- Pledge and available balance.
- Transfer rejection for pledged units.
- Loan simulation.
- Repayment and collateral release.
- Distribution calculation.
- Transaction history.
- DRUNIX connectivity indicator.
- Error and reconciliation states.

Verify that frontend components do not fabricate successful transaction
responses.

## 16. Full Demonstration Acceptance Test

The complete demonstration must execute the following journey:

1. Meera registers TechPark One and submits its documents.
2. The application reviewer verifies the evidence and approves the property.
3. The backend registers the approved property reference and issuance
   constraints through `RegisterApprovedProperty` on DRUNIX.
4. The test verifies that property registration has committed on DRUNIX.
5. 100,000 ANSH are issued through DRUNIX.
6. Aarav purchases 500 ANSH.
7. Simulated payment succeeds.
8. DRUNIX transfer commits.
9. Portfolio shows 500 ANSH.
10. Aarav pledges 200 ANSH through DRUNIX.
11. Portfolio shows 300 available and 200 pledged.
12. Attempt to transfer pledged units.
13. DRUNIX/chaincode rejects the invalid transfer.
14. Rental entitlement is calculated from verified record-date DRUNIX
    ownership.
15. Rental payment is simulated.
16. Aarav repays the simulated loan.
17. Collateral release commits through DRUNIX.
18. Portfolio shows the released units as available.
19. Asset history reflects the committed ledger operations.

The demonstration must not rely on hardcoded success responses.

## 17. Security Tests

Test:

- Unauthorized operations.
- Role enforcement.
- Input validation.
- Sensitive information in logs.
- Private-key protection.
- Certificate permissions.
- Environment configuration.
- API exposure.
- CORS configuration.
- Public endpoint restrictions.
- Dependency vulnerabilities where practical.

Never expose DRUNIX peer, orderer, database or administrative management
interfaces publicly without an explicit and justified requirement.

## 18. Deployment Tests

### 18.1 Local deployment

Verify:

- All required containers start.
- Health checks pass.
- Application can connect to its database.
- Go gateway can connect to DRUNIX.
- Chaincode is accessible.
- Ledger operations work.
- Persistent data survives container restarts.
- Runtime state is not stored in the Git repository.

### 18.2 Cloud deployment

Verify:

- Containers start from the documented deployment configuration.
- Persistent volumes are correctly configured.
- Secrets are injected securely.
- HTTPS works.
- Application entry point is publicly accessible.
- Internal DRUNIX services are not unnecessarily exposed.
- Ledger transactions work remotely.
- Data survives container restarts.
- Recovery procedures are documented.

### 18.3 Recovery tests

Test:

- Application container restart.
- Go gateway restart.
- DRUNIX peer restart.
- Temporary network interruption.
- Application database restart.
- Unknown transaction outcome followed by reconciliation.

Do not assume that restarting a container resets or restores ledger state.

## 19. Test Execution Strategy

Recommended execution sequence:

1. Static analysis and formatting.
2. Backend unit tests.
3. Chaincode unit tests.
4. Go gateway unit tests.
5. Frontend component tests.
6. API contract tests.
7. Database tests.
8. Start local DRUNIX network.
9. Deploy chaincode.
10. Execute real DRUNIX integration tests.
11. Execute end-to-end workflows.
12. Execute deployment and recovery tests.

A failed prerequisite should prevent dependent tests from being reported as
passed.

## 20. Test Reporting

Test reports should distinguish:

- Passed
- Failed
- Skipped
- Blocked
- Not executed

Also distinguish:

- Isolated mock/unit tests
- Actual local DRUNIX network integration tests
- Cloud DRUNIX deployment and integration tests

Do not report a mocked operation as a successful DRUNIX integration test.

For ledger integration tests, retain where appropriate:

- Test case identifier
- Environment
- Chaincode version
- DRUNIX network configuration reference
- Actual transaction identifier
- Commit result
- Expected state
- Observed state

Never include private keys, credentials or sensitive certificate material
in test reports.

## 21. MVP Quality Gates

The MVP is not ready for demonstration until:

- Core chaincode business rules pass.
- Actual DRUNIX issuance succeeds.
- Actual DRUNIX transfer succeeds.
- Actual DRUNIX pledge succeeds.
- Actual DRUNIX collateral release succeeds.
- Pledged-unit transfer is rejected.
- Commit status is verified.
- Ambiguous transaction outcomes are handled safely.
- Purchase workflow handles payment and ledger failures.
- Portfolio projections match authoritative ledger state.
- Simulated workflows are clearly identified.
- The complete end-to-end demonstration passes.
- The public-cloud deployment has been validated.

## 22. Known Testing Limitations

The MVP does not establish:

- Production-grade high availability.
- Independent multi-organisation governance.
- Production disaster recovery.
- Regulatory certification.
- Real-world lending or payment integration.
- Legal enforceability of ANSH rights.
- Production-scale transaction throughput.

These limitations must be communicated accurately during the hackathon
demonstration.

## 23. AI Coding Agent Instructions

1. Read this document before implementing tests.
2. Test business invariants before UI workflows.
3. Keep unit tests independent of live network dependencies.
4. Provide separate integration tests for the real DRUNIX network.
5. Never replace mandatory DRUNIX tests with mocks.
6. Never fabricate ledger transaction identifiers.
7. Verify transaction commitment.
8. Test ambiguous outcomes and reconciliation.
9. Keep test data deterministic.
10. Update test cases when business rules or API contracts change.

---

**End of Test Strategy**
