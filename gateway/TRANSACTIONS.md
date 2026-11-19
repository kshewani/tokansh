# M3.3b private registration integration

Current status: `tokansh` v1.0 sequence 1 is deployed on mychannel; deployment and dual-org read-only acceptance passed at height 11. No live property registration has occurred. M3.3b transaction integration is implemented and tested in isolation; live transaction acceptance remains pending. Existing `basic` endpoints remain read-only and unchanged. Transaction readiness remains unavailable and connected business screens remain disabled.

FastAPI SQLite is the sole durable transaction-state owner. The Go process shares the existing TLS SDK connection and contains no transaction database. Set distinct, independently random 32-byte secrets (64 hex characters) in both processes: TOKANSH_GATEWAY_SECRET and TOKANSH_OPERATOR_SECRET. Missing/invalid/identical credentials disable TokANSH routes. No actual secret values belong in examples or Git. Persist the secrets securely across restarts: changing the backend secret invalidates existing artifact HMACs and requires operator review, not re-preparation/resubmission.

All endpoints below live under `/v1/tokansh/`, return `{data:...}` or a sanitized `{error:{code,message}}`, and require `Authorization: Bearer <TOKANSH_GATEWAY_SECRET>`. All POSTs additionally require `X-Operator-Capability: <TOKANSH_OPERATOR_SECRET>`. Origin/Sec-Fetch requests are rejected and CORS is not enabled. The existing loopback-only server address validation remains mandatory. The static bearer mechanism is a local MVP boundary, not remote production authentication.

| Method | Path | Input/output |
|---|---|---|
| GET | contract-info | GetContractInfo typed result |
| GET | properties/{UUID} | GetRegisteredProperty typed result |
| GET | operations/{UUID} | GetOperation for configured Org1 authority |
| POST | property-registrations/prepare | Exact M3.3a Command → versioned Artifact |
| POST | property-registrations/submit | Artifact → SUBMITTED and transaction ID, never commitment |
| POST | commit-status | Artifact → transaction ID, numeric validation code, block number, successful flag |

Only Org1 User1's reviewed certificate pin can enable the adapter; private key loading/matching and TLS verification continue through the original SDK connection. Prepare explicitly requests Org1MSP and Org2MSP endorsements. Read, endorsement, submission and commit-status calls each use a bounded five-second context. There are no application retries or automatic re-endorsement/resubmission. DRUNIX's own internal orderer selection is outside the application retry policy.

Artifacts include version 1, command, canonical command digest, channel mychannel, chaincode tokansh, pinned signer reference, genuine SDK transaction ID, endorsed PreparedTransaction bytes, serialized creator, and an HMAC covering all fields. Validation checks HMAC, creator certificate, transaction/header IDs, channel, target chaincode/function and exact command encoded inside the endorsed bytes. No arbitrary chaincode invocation is exposed. Bytes and metadata are private recovery material; do not publish them in API logs or UI.

FastAPI is the only authorized submission orchestrator. Its committed compare-and-set prevents concurrent callers/processes from authorizing a second submission. The stateless Go endpoint trusts this authenticated owner to enforce that gate; it cannot independently prove SQLite persistence. Do not hand backend credentials to another submission client. The separate operator secret prevents demo-role headers alone from initiating a command. There is no public FastAPI registration route.

SQLite states: CREATED → PREPARED → SUBMISSION_PENDING → SUBMITTED → COMMITTED_VALID / COMMITTED_INVALID / UNKNOWN. CREATED and a canonical command are saved before preparation. The preparation result, transaction ID, signer, channel/chaincode and artifact are committed before submission. A SQLite write-lock spans the remote preparation call to serialize duplicate preparations; no DB transaction spans submission. A durable CAS from PREPARED to SUBMISSION_PENDING must commit before any submission call. Every other submission attempt through RegistrationService is refused or returns its already persisted terminal outcome.

A preparation failure leaves CREATED and can be explicitly prepared again (endorsement has no ledger effect). A submission timeout, lost response or crash leaves UNKNOWN or SUBMISSION_PENDING. Those states can only reconcile status, never automatically submit. SUBMITTED means orderer acknowledgement only. Only a matching status result with validation code 0 produces COMMITTED_VALID; invalid codes produce COMMITTED_INVALID. Neither terminal state changes property drafts or ownership projections in M3.3b. A new command for the same property is blocked for operator review, including after invalidity.

Restart recovery reconstructs the public Gateway CommitStatusRequest from persisted transaction ID, channel and original serialized creator, wraps it as SignedCommitStatusRequest, calls SDK NewCommit and StatusWithContext. The persisted creator must exactly match both the adapter creator and Gateway.Identity before any status RPC. The wrapper starts unsigned: SDK v1.10.0 StatusWithContext signs its SHA-256 request digest with the existing configured signer before sending it. No additional key or signing configuration is loaded for recovery. Offline tests verify that signature cryptographically, along with the channel, transaction ID and creator, using an isolated in-memory gRPC server. It does not require Submit to have returned a Commit. Credentials and artifacts must remain consistent. Missing status/receipt is never proof that submission did not happen. Persistent pending states require explicit operator reconciliation; no background resubmission worker exists.

Run the operator from backend after applying migrations:

```
.venv/bin/python -m alembic upgrade head
.venv/bin/python -m app.registration_operator prepare /path/to/approved-command.json
.venv/bin/python -m app.registration_operator submit OPERATION_UUID
.venv/bin/python -m app.registration_operator reconcile OPERATION_UUID
```

These are future write-capable operator commands, **not commands executed during M3.3b validation**. Capability is entered with getpass, never supplied in argv. `prepare-created` explicitly resumes a CREATED operation. The operator must independently verify the approval attestation: M4 approval workflows do not exist yet. Draft data or a demo role is not approval evidence.

Migration 0002_registration adds a separate ledger_operations table. Do not downgrade/drop it while operations need reconciliation. Go tests use isolated mocks and an in-memory gRPC server; SDK recovery is tested without a submission object. Network deployment and read-only acceptance are complete. Actual business two-org endorsement, ordering, MVCC, LP→CP status forwarding and true restart recovery against DRUNIX remain future runtime acceptance gates. M3.2 read connectivity alone does not establish them.

## M3.3b.1 hardening and deferred contention optimization

RegistrationClient validates its raw destination before sending credentials: only HTTP with literal `127.0.0.1` or `[::1]`, an explicit port 1–65535, and an optional trailing slash is accepted. DNS names (including localhost), credentials in URLs, query/fragment delimiters and other paths are rejected. Injected HTTP clients must have environment proxy trust and redirects disabled; each request also explicitly disables redirects. This protects the credentialed registration path independently of settings validation and leaves existing basic diagnostics unchanged.

The SQLite compare-and-set authorizes a single submission attempt **through the trusted RegistrationService**. It is not an independently enforced single-use guarantee in the stateless Go Gateway. Another caller possessing both gateway credentials and a valid artifact can bypass the service and call submit again. There is no global exactly-once delivery guarantee. Keep those credentials restricted to this orchestrator; chaincode operation receipts provide a separate committed business-effect deduplication boundary, not transport exactly-once delivery.

Preparation-lock optimization is deliberately deferred. Releasing BEGIN IMMEDIATE before remote preparation while retaining crash recovery and exclusive preparation requires durable claim ownership, fencing, expiry/takeover rules and a schema migration. An expiring lease alone could let a delayed original caller overwrite a replacement artifact. Adding that machinery exceeds this targeted pass. The current transaction preserves CREATED on failure/process exit and atomically persists the complete artifact with PREPARED on success; only an explicit operator call can resume CREATED. No submission occurs under this lock, and submission still requires the persisted artifact and committed CAS. Concurrent preparations are serialized and the second caller observes the saved artifact/state without issuing a second prepare.

Trade-off: unrelated SQLite writers can be blocked for the duration of preparation (including connection/response time and local validation), and can reach the configured SQLite busy timeout. The seven-second client deadline is not a strict total wall-clock guarantee for every transport stall. Do not describe this as a short lock or a contention optimization. A future measured optimization must test fenced takeover and stale-result rejection before replacing it.

## M3.3c.1 read-only error classification

Only TokANSH GET evaluation errors are classified here; submission/status paths and basic diagnostics are unchanged. PROPERTY_NOT_FOUND and OPERATION_NOT_FOUND become HTTP 404 only for the matching read function and the exact reviewed code/message JSON in DRUNIX's `chaincode response 500, ...` framing. SDK gRPC Unknown status carries `gateway.ErrorDetail` records; all provided details must agree. When details are absent, only the exact documented outer Evaluate framing is accepted. Unknown fields, duplicate keys, mismatched functions and arbitrary "not found" strings are not classified as business absence. Actual context/gRPC DeadlineExceeded takes precedence and returns 504 LEDGER_TIMEOUT. Other SDK failures return sanitized 503 LEDGER_UNAVAILABLE. No peer address, upstream message or credential is forwarded.

Runtime verification after deployment returned GetContractInfo 200, missing property/operation 404, and preserved the complete basic payload. Both organizations stayed at height 11 with unchanged hashes. Only GET evaluations and channel-info reads were performed; no transaction workflow was exercised. Five-second timeouts, RPC unavailability and disconnected transports are also tested through the pinned SDK against an isolated in-memory gRPC server.

Timeout investigation: previous peer logs at 2026-11-18 16:11:26–31 UTC show `Creating table mychannel.tokansh`, followed by Gateway Evaluate DeadlineExceeded (5.002 seconds) and chaincode execution lasting 5003 ms. DRUNIX `sql_client.go` routes GetState through GetTable; GetTable calls tableCache.CreateIfNotExists, whose implementation can AutoMigrate the namespace table. This confirms that the timed-out request reached the peer/endorser, rather than stalling at client DNS or TLS. Cold namespace-table initialization is strongly supported by source/log correlation and subsequent fast missing-key reads, but the exact SQL timing was not instrumented and is not conclusively isolated. No DRUNIX modification, cache reset, schema creation command, retry or timeout increase was used. Any future cold-start reproduction needs separate authorization in an isolated environment; do not force a cold state on the existing network.


## M3.3c.3 operational consolidation

The [deployment runbook](../scripts/drunix/OPERATOR-INSTRUCTIONS.md) and offline
assertions are repository deliverables. The historical package identity is retained
as sanitized metadata; packages, signed recovery artifacts, SQLite databases,
secrets and raw evidence remain external. Each future environment/package needs
its own reviewed manifest, certificate binding, baseline, digest and deployment ID.
The Org2 Writers policy anomaly is an accepted isolated-local-hackathon exception
only, not approval for shared, cloud or production use. No channel policy is changed.

The cold namespace initialization correlation above is a latency risk, not a proven
SQL timing root cause. Preserve the five-second evaluation deadline and fail honestly
on expiry; do not add retries. `/ready` remains 503 until business readiness is
established. A valid business commit must be independently observed during live
transaction acceptance before claiming that transaction integration works on DRUNIX.
