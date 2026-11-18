# M3.3b private registration integration

Implementation/testing only: `tokansh` has not been deployed and no live submissions were made. Existing `basic` endpoints remain read-only and unchanged. Transaction readiness remains unavailable and connected business screens remain disabled.

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

SQLite states: CREATED → PREPARED → SUBMISSION_PENDING → SUBMITTED → COMMITTED_VALID / COMMITTED_INVALID / UNKNOWN. CREATED and a canonical command are saved before preparation. The preparation result, transaction ID, signer, channel/chaincode and artifact are committed before submission. A short SQLite write-lock spans preparation to serialize duplicate preparations; no DB transaction spans submission. A durable CAS from PREPARED to SUBMISSION_PENDING must commit before any submission call. Every other submission attempt is refused.

A preparation failure leaves CREATED and can be explicitly prepared again (endorsement has no ledger effect). A submission timeout, lost response or crash leaves UNKNOWN or SUBMISSION_PENDING. Those states can only reconcile status, never automatically submit. SUBMITTED means orderer acknowledgement only. Only a matching status result with validation code 0 produces COMMITTED_VALID; invalid codes produce COMMITTED_INVALID. Neither terminal state changes property drafts or ownership projections in M3.3b. A new command for the same property is blocked for operator review, including after invalidity.

Restart recovery reconstructs the public Gateway CommitStatusRequest from persisted transaction ID, channel and original serialized creator, wraps it as SignedCommitStatusRequest, calls SDK NewCommit and StatusWithContext. It does not require Submit to have returned a Commit. Credentials and artifacts must remain consistent. Missing status/receipt is never proof that submission did not happen. Persistent pending states require explicit operator reconciliation; no background resubmission worker exists.

Run the operator from backend after applying migrations:

```
.venv/bin/python -m alembic upgrade head
.venv/bin/python -m app.registration_operator prepare /path/to/approved-command.json
.venv/bin/python -m app.registration_operator submit OPERATION_UUID
.venv/bin/python -m app.registration_operator reconcile OPERATION_UUID
```

These are future write-capable operator commands, **not commands executed during M3.3b validation**. Capability is entered with getpass, never supplied in argv. `prepare-created` explicitly resumes a CREATED operation. The operator must independently verify the approval attestation: M4 approval workflows do not exist yet. Draft data or a demo role is not approval evidence.

Migration 0002_registration adds a separate ledger_operations table. Do not downgrade/drop it while operations need reconciliation. Go tests use isolated mocks and an in-memory gRPC server; SDK recovery is tested without a submission object. Network deployment, actual two-org endorsement, ordering, MVCC, LP→CP status forwarding and true restart recovery against DRUNIX remain future runtime acceptance gates. M3.2 read connectivity alone does not establish them.
