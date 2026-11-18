# DRUNIX Integration Specification

**Project:** TokANSH
**Status:** Research baseline with M3.2 local read-only verification below; write/commit capabilities remain unverified
**Last researched:** 16 November 2026
**Primary upstream:** https://github.com/npci/drunix

> This document distinguishes (1) facts visible in NPCI's public DRUNIX repository, (2) proposed TokANSH design, and (3) questions that require confirmation. Do not treat proposed operations or unverified interfaces as existing DRUNIX APIs.

## 1. Executive summary

DRUNIX is an NPCI open-source distributed-ledger platform developed as an enhanced fork of Hyperledger Fabric. The upstream repository documents separation of endorsement and commitment roles, a stateless validation service, SQL state-database support, and a shared transient store for private data.

The public repository also contains:
- A local two-organisation test network.
- Go, Java, JavaScript and TypeScript application-gateway samples.
- Go, Java, JavaScript and TypeScript chaincode samples.
- A sample Go REST application that wraps gateway operations.

**TokANSH integration recommendation:** implement Go chaincode for ANSH lifecycle and use a backend-owned DRUNIX adapter. Start by reproducing NPCI's sample-network workflow and one basic asset transaction before implementing TokANSH domain operations. Keep the adapter behind a stable application interface, but use the self-hosted DRUNIX development network for all local runtime ledger operations. Missing credentials, endpoints or network availability must produce explicit configuration or operational failures; they must never trigger a simulator fallback.

## 2. Evidence classification

| Classification | Meaning |
|---|---|
| Verified upstream fact | Explicitly documented or demonstrated in NPCI's public repository/package documentation inspected for this research |
| TokANSH design proposal | Recommended application design; not a claim about DRUNIX platform functionality |
| NPCI confirmation required | Cannot safely be determined from public material or must be confirmed for the target network/version |

The upstream `main` branch is mutable. Pin the actual DRUNIX Git commit/tag used by the team before implementation and record it in `DECISIONS.md`.

## 3. DRUNIX platform architecture

### 3.1 Platform characteristics

**Verified upstream facts**
- DRUNIX is described by NPCI as an enhanced fork of Hyperledger Fabric.
- The README states backward compatibility with Hyperledger Fabric v2.5.x; this should not be interpreted as proof that every Fabric SDK, deployment recipe or operational assumption is compatible.
- Peer responsibilities are separated into Lite Peer (LP) and Committing Peer (CP).
- DRUNIX introduces a stateless Validation Service (VS).
- The architecture documentation describes YugabyteDB support in addition to LevelDB and CouchDB.
- KeyDB is used as a transient store shared by LP and CP within an organisation to reduce private-data network exchanges.

### 3.2 Component responsibilities

| Component | Documented responsibility | TokANSH implication |
|---|---|---|
| Lite Peer (LP) | Executes chaincode proposals, simulates transactions and produces endorsements/read-write sets; does not maintain the committed ledger | Client proposal/endorsement endpoint is expected to be an LP in the sample topology |
| Committing Peer (CP) | Receives ordered blocks, performs block checks, coordinates validation, performs MVCC checks and commits valid writes to ledger/state DB | Commit outcome must be observed; an endorsement response alone is not final ownership evidence |
| Validation Service (VS) | Stateless validation of endorsements/policies/signatures; can be scaled horizontally | Treat as network infrastructure, not a TokANSH business service |
| Ordering service | Orders submitted transactions into blocks | Transaction ordering does not itself mean a transaction is valid |
| KeyDB | Transient private-data storage shared by LP and CP in an organisation | Do not use it as application persistence |
| State database | Stores current ledger state; supported choices described include YugabyteDB, LevelDB and CouchDB | Never query or update DRUNIX's internal state DB directly from TokANSH |
| Channel | Fabric-derived logical ledger/network partition used by the application and chaincode | Exact channel membership, policies and names are environment configuration |

### 3.3 Public test-network topology

The NPCI test-network README describes:
- Two peer organisations.
- One Lite Peer and one Committing Peer per organisation.
- One validation server per organisation in the documented sample topology.
- A single-node Raft ordering service.
- Default channel name `mychannel`.
- Default state database `yugabyte`.
- Default chaincode language `go`.
- Peer indices in the sample scripts: `0 = Lite Peer`, `1 = Committing Peer`.

This is a development/test topology, not a production high-availability design. The exact network provided to TokANSH may differ.

## 4. Transaction lifecycle

The architecture documentation and sample gateway illustrate a Fabric-derived execute/order/validate/commit lifecycle:

1. **Evaluate (read):** client evaluates a chaincode function through the gateway; the proposal is executed for a read result and is not committed as a state-changing transaction.
2. **Endorse:** client sends a transaction proposal to an LP. LP executes chaincode simulation and returns an endorsed proposal response/read-write set.
3. **Submit:** client submits the endorsed transaction to the ordering service.
4. **Order:** ordering service sequences transactions and creates blocks.
5. **Validate:** CP coordinates with VS for endorsement/policy validation and performs MVCC checks against current state.
6. **Commit:** CP commits the block and applies valid write sets to the ledger/state database. Invalid transactions may be recorded in a block but their writes are not applied.
7. **Observe commit status:** client waits for or queries the transaction's commit status and checks whether it was successful.

**Critical TokANSH rule:** a successful proposal/endorsement or a returned transaction identifier is not proof that state was committed. Treat a state-changing operation as successful only after a successful commit status is obtained. If the outcome is unknown because of timeout/disconnection, reconcile by transaction ID/status before retrying.

## 5. Integration surfaces evidenced by NPCI's repository

### 5.1 Application Gateway samples

The upstream `drunix-network/asset-transfer-basic` sample includes application gateway projects for Go, Java, JavaScript and TypeScript. The TypeScript sample:
- Uses `@hyperledger/fabric-gateway` and `@grpc/grpc-js`.
- Configures channel, chaincode name and MSP ID.
- Loads an organisation user certificate, private signing key and peer TLS CA certificate.
- Connects to a peer endpoint over gRPC.
- Creates a Gateway connection with an identity and signer.
- Uses `evaluateTransaction()` for queries.
- Uses `submitTransaction()` for synchronous submission/commit.
- Uses `submitAsync()` and then `getStatus()` for explicit asynchronous commit-status handling.
- Configures separate evaluate, endorse, submit and commit-status timeouts.

This is concrete evidence that the public sample network can be accessed through a Fabric Gateway-compatible client pattern. It does **not** prove that the hackathon network has the same hostnames, ports, MSPs, channel, TLS configuration, certificate lifecycle, gateway availability or SDK versions.

### 5.2 Go REST sample

The upstream `rest-api-go` sample is a small Go HTTP server with invoke/query endpoints. Its README shows form-encoded invoke/query requests; its `main.go` configures an organisation identity, certificate, private key, TLS certificate and peer endpoint before starting the server.

**Interpretation:** this is a sample application wrapper that calls the gateway. It is not evidence of a built-in DRUNIX REST endpoint. TokANSH should not assume that a REST server is deployed or supported by NPCI's network.

### 5.3 Recommended TokANSH integration choice

**Proposal**
- Keep the TokANSH business backend in Python/FastAPI.
- Implement a narrow `DRUNIXAdapter` boundary.
- For the first real-network integration spike, prefer a small Go integration service/client using the upstream Go gateway sample as the reference, if the current Go client API and network configuration are confirmed.
- Alternatively, use the TypeScript gateway only if the team chooses to run a Node/TypeScript adapter. Avoid introducing a separate TypeScript service solely because the frontend uses TypeScript.
- FastAPI communicates with the adapter through a private local interface (for example, an internal HTTP API) only after that interface is designed and secured. The internal interface is TokANSH-owned, not a DRUNIX API.
- Do not place DRUNIX private keys in the React frontend or browser.

The choice between a Go adapter and direct Python integration is **not settled**. Public examples inspected demonstrate Go and Node/TypeScript gateway clients; Python gateway support was not established by the evidence reviewed. Do not invent a Python SDK.

## 6. Chaincode strategy for TokANSH

### 6.1 Scope

Chaincode should hold the minimum authoritative asset state that requires shared, permissioned-ledger integrity. It should not attempt to reproduce the whole application database or analytics layer.

**Proposed on-ledger records**
- Approved property reference: stable application property reference, authorised issuer identity reference, approved ANSH supply constraint and optional metadata hash/reference. Registration on DRUNIX records that the property has passed TokANSH's off-chain approval workflow.
- ANSH asset/issuance record: asset identifier, registered property reference, approved supply, issued supply, unit denomination and lifecycle status.
- Ownership position: asset ID, owner identity reference and quantity.
- Pledge/restriction state: quantity encumbered, pledge reference and status.
- Lifecycle events: issuance, transfer, pledge, release, distribution declaration and other material state transitions.

Avoid putting sensitive KYC documents, bank details, personal data, full property documents or private loan data directly on a broadly replicated ledger. Store approved off-chain documents securely and anchor hashes/references only where justified.

### 6.2 Proposed chaincode operations

These are TokANSH contract design proposals, not pre-existing DRUNIX functions.

| Proposed operation | Purpose | Key validation |
|---|---|---|
| `RegisterApprovedProperty` | Register a property reference that has already completed TokANSH's off-chain approval workflow | Unique property reference; authorised issuer; valid approved supply constraint |
| `IssueANSH` | Mint ANSH against a registered approved property reference | Property reference exists on DRUNIX; issuance does not exceed registered supply constraint; issuer authority |
| `TransferANSH` | Transfer units between owners | Seller owns units; quantity positive; sufficient unencumbered balance; authorisation |
| `PledgeANSH` | Mark units as encumbered | Owner authority; sufficient available units; unique pledge reference |
| `ReleasePledge` | Release encumbered units | Valid pledge; authorised release condition |
| `DeclareDistribution` | Record distribution and record-date parameters | Valid asset; authorised declarant; immutable record date and amount |
| `RecordDistribution` | Record a distribution outcome/reference if required | Idempotent reference; deterministic entitlement basis |
| `GetApprovedProperty` / `GetANSHAsset` | Read registered approved property reference and issuance state | Access control as required |
| `GetPosition` | Read owner position and restrictions | Access control; correct asset/owner |
| `GetAssetHistory` | Read lifecycle history | Use supported history/event mechanism; exact query support to verify |

Do not implement every operation as an independent write if the same business invariant can be enforced in one atomic chaincode transaction. The chaincode must validate the ledger state at execution time; frontend and backend checks are not substitutes.

### 6.3 Core ledger invariants

- `issuedSupply <= approvedSupply`.
- Ownership quantity cannot become negative.
- `availableQuantity = ownedQuantity - pledgedQuantity`.
- A transfer cannot exceed available quantity.
- Pledged units cannot be transferred.
- A pledge cannot exceed available units.
- Release cannot exceed the active pledged quantity.
- Every state-changing request must be authorised by a valid ledger identity/role.
- Operation references must support duplicate detection/idempotency.
- Amounts and quantities must use deterministic integer/fixed-precision representations; never binary floating-point arithmetic.
- State changes must emit or otherwise expose enough evidence for application reconciliation, subject to supported DRUNIX event/query APIs.

**Distribution note:** distribution eligibility is based on the record-date position. Pledged units remain owned by the investor and should remain eligible unless the governing contractual model says otherwise. If the platform cannot provide a historical state snapshot, the design needs a reliable event-reconstruction method or an explicitly labelled simulator snapshot.

## 7. Source-of-truth boundaries

| Data | Authoritative source |
|---|---|
| ANSH issuance and issued supply | DRUNIX ledger |
| ANSH ownership and transfer result | DRUNIX ledger |
| Pledge/encumbrance and available quantity | DRUNIX ledger, if implemented in chaincode |
| Commit status and ledger transaction reference | DRUNIX gateway/network |
| Marketplace listings and order workflow | TokANSH application database |
| Payment simulation status | TokANSH payment simulator |
| Loan workflow and simulated lender decision | TokANSH application database/simulator, unless a later on-ledger design is approved |
| Property documents and KYC evidence | Secure off-chain storage; only approved references/hashes on ledger |
| Portfolio read model and analytics | TokANSH application database, reconciled from ledger state/events |
| REIT holdings | Separate simulated/external REIT source; not ANSH ledger balances |

TokANSH must never connect directly to DRUNIX's internal YugabyteDB or other peer state database. It must use the supported application/gateway interfaces.

## 8. TokANSH adapter contract

The application should depend on a domain-level interface rather than DRUNIX SDK types. Illustrative operations:

```text
interface LedgerPort:
    create_property(command) -> SubmissionResult
    approve_property(command) -> SubmissionResult
    issue_ansh(command) -> SubmissionResult
    transfer_ansh(command) -> SubmissionResult
    pledge_ansh(command) -> SubmissionResult
    release_pledge(command) -> SubmissionResult
    declare_distribution(command) -> SubmissionResult
    evaluate(query) -> QueryResult
    get_transaction_status(transaction_id) -> CommitStatus
```

Illustrative result fields:
- `operation_id`: TokANSH-generated idempotency/correlation identifier.
- `transaction_id`: network transaction ID, only when actually returned by the client.
- `submission_state`: `NOT_SUBMITTED`, `SUBMITTED`, `COMMIT_CONFIRMED`, `COMMIT_FAILED`, `UNKNOWN`.
- `validation_code`: raw or mapped network commit validation result, where available.
- `result_payload`: chaincode result, if any.
- `observed_at`: application observation timestamp.

These names are TokANSH internal contract proposals. They are not DRUNIX wire-format fields.

### 8.1 Runtime integration

- All running application environments use the real DRUNIX adapter for core ANSH ledger operations.
- Local development uses the self-hosted DRUNIX development network.
- The cloud demonstration uses the deployed DRUNIX network.
- There is no runtime `BLOCKCHAIN_MODE` setting and no simulator ledger implementation or fallback.
- Automated tests may use isolated mocks for unit testing, but these must not be available as a runtime ledger mode.
- Never fabricate transaction IDs, block numbers, endorsements or commit proofs.
- Startup and operation handling must report missing DRUNIX configuration, credentials, connectivity or commit confirmation explicitly. A failed or unknown outcome must not be reported as successful.

## 9. Purchase and transfer orchestration

TokANSH purchase flow includes a simulated payment provider and a ledger transfer. These are separate systems; do not claim atomic delivery-versus-payment unless the network and payment rails explicitly provide it.

Recommended workflow:
1. Validate order and listing in TokANSH.
2. Create an idempotent purchase/settlement operation.
3. Execute payment simulation.
4. If payment fails, do not invoke `TransferANSH`.
5. If payment succeeds, submit `TransferANSH` to DRUNIX.
6. Wait for commit status.
7. Only after successful commit, mark the order as completed and refresh the ownership read model.
8. If the ledger transaction is invalid, mark settlement for exception handling; do not report ownership transfer.
9. If commit status is unknown due to timeout/network interruption, retain `UNKNOWN`/`RECONCILIATION_REQUIRED`, query status by transaction ID, and do not blindly resubmit.
10. If payment succeeded but ledger transfer definitively failed, record a compensation/refund workflow. Do not rewrite history to imply payment never occurred.

Use an outbox/reconciliation pattern if needed to make workflow recovery deterministic. Ensure repeated client requests cannot cause duplicate payment or duplicate transfer.

## 10. Identity, signing and access control

**Verified sample behaviour:** public gateway sample loads an organisation MSP ID, user certificate, private signing key, peer TLS CA certificate and peer endpoint. It constructs a Gateway identity and signer and connects over gRPC/TLS.

**TokANSH proposal**
- Backend/adapter uses a dedicated application identity with the minimum required network permissions.
- Do not use an individual developer's certificate/key as a production service identity.
- Keep signing keys outside source control and outside the frontend; use environment-specific secret injection or a managed secret store.
- Keep TLS trust material distinct from transaction-signing identity material.
- Chaincode must enforce role/organisation permissions using the identity attributes and APIs actually supported by the selected chaincode runtime.
- Map TokANSH users to ledger identities through an explicit, auditable identity mapping. Do not equate a UI role switcher with ledger authorisation.
- Confirm certificate issuance, renewal, revocation, MSP setup, attribute support and private-key custody with NPCI/network administrators.

## 11. Events, queries and history

The public gateway package documentation exposes gateway operations including `Evaluate`, `Endorse`, `Submit`, `CommitStatus` and `ChaincodeEvents`. This supports the existence of gateway-level evaluation, transaction submission/status and chaincode-event concepts in the published code.

However, exact event payloads, event replay/retention, block-history APIs, pagination, query limits and supported history semantics must be validated against the pinned DRUNIX version and target network.

TokANSH should:
- Persist each submitted operation and returned transaction ID in its own database.
- Consume events only as a reconciliation/read-model mechanism, not as the sole proof of a successful transaction unless event semantics are verified.
- Periodically reconcile important balances/positions against authoritative ledger queries.
- Treat event consumer restarts and duplicate delivery as normal; use transaction/event identifiers for deduplication.
- Avoid depending on internal peer databases or direct SQL access to YugabyteDB.

## 12. Deployment and developer workflow

The NPCI test-network README documents Linux prerequisites including Git, Docker, Go and `jq`. It provides `network.sh` commands to install prerequisites, start the network, create a channel, deploy chaincode, invoke and query chaincode, and shut down the network.

The repository's test network defaults to YugabyteDB and Go chaincode. Its sample deploy command is structurally:

```bash
./network.sh up createChannel -c mychannel -ca -s yugabyte

./network.sh deployCC \
  -ccn basic \
  -ccp ../asset-transfer-basic/chaincode-go \
  -ccl go

./network.sh cc invoke \
  -c mychannel \
  -ccn basic \
  -ccic '{"Args":["InitLedger"]}'

./network.sh cc query \
  -c mychannel \
  -ccn basic \
  -ccqc '{"Args":["GetAllAssets"]}'
```

Run these only from the correct directory in a clone of the pinned NPCI repository, after checking the current README and prerequisites. They are upstream sample-network commands, not TokANSH deployment scripts. The test network's `down` command removes its nodes and ledger data; do not use it against any persistent environment.

The upstream `go.mod` at the time inspected declares Go `1.26.1`. The team's installed WSL Go version should be checked against the exact pinned source version before building DRUNIX. Chaincode language and runtime compatibility must also be verified.

## 13. Implementation sequence

### Phase 0 — Pin and inspect upstream
1. Clone NPCI's official repository.
2. Record commit SHA/tag and Go version.
3. Read the current test-network README and sample application READMEs.
4. Inspect the gateway sample and chaincode sample.
5. Record the selected test-network configuration.

### Phase 1 — Prove the platform path
1. Start the local DRUNIX test network.
2. Create channel.
3. Deploy the upstream basic Go chaincode.
4. Run one query.
5. Run one state-changing invoke.
6. Confirm commit status and inspect the resulting state.
7. Capture actual endpoint, TLS, identity, MSP, channel and chaincode configuration.

### Phase 2 — Build TokANSH chaincode
1. Fork/adapt the basic Go chaincode structure.
2. Implement `RegisterApprovedProperty` to record the approved property reference and its issuance constraints, followed by ANSH issuance. Property onboarding, document review and approval remain application workflows and are not chaincode operations.
3. Add transfer and available-balance/pledge restrictions.
4. Add tests for invariants and negative cases.
5. Deploy and test against the local DRUNIX network.

### Phase 3 — Connect TokANSH backend
1. Implement the Go DRUNIX gateway adapter based on the proven sample client.
3. Add idempotency, commit-status handling and reconciliation.
4. Add ledger-derived read models and audit display.
5. Run end-to-end purchase, pledge, blocked transfer, release and distribution scenarios.

Do not begin the TokANSH real adapter before Phase 1 has produced a successful, reproducible sample transaction.

## 14. Risks and design decisions

| Risk | Consequence | Mitigation |
|---|---|---|
| Assuming generic Fabric compatibility | Wrong SDK/API assumptions or runtime failures | Use NPCI's own sample gateway and pin versions |
| Treating endorsement as commit | UI reports ownership before ledger state is final | Require successful commit status |
| Assuming REST is a DRUNIX platform API | Integration depends on a demo wrapper | Treat REST sample as optional TokANSH-owned wrapper |
| Direct SQL access to peer YugabyteDB | Bypasses ledger validation/consensus and breaks support boundary | Use gateway/chaincode interfaces only |
| Payment success + ledger failure | Cash/payment and ownership states diverge | Reconciliation and compensation workflow |
| Timeout after submission | Duplicate transaction risk | Query commit status before retry |
| Misconfigured identities/policies | Endorsement/validation failures or excessive privilege | Dedicated service identity and least privilege |
| Unverified history/event semantics | Incorrect record-date entitlement or incomplete audit trail | Test event replay/history and use explicit snapshots where needed |
| Test-network assumptions copied to production | False HA/security claims | Label local network as development-only |

## 15. Questions for NPCI / DRUNIX developer

### Network and access
1. Which DRUNIX release/commit is used for the hackathon environment?
2. Is a local test network expected, or will a shared remote network be provided?
3. What are the peer/gateway endpoints, ports, TLS roots and host aliases?
4. Which organisations/MSPs and channel(s) should TokANSH use?
5. How are application identities/certificates issued, renewed and revoked?
6. Are there restrictions on storing signing keys in a local developer environment?

### Client integration
7. Is the Fabric Gateway API the recommended supported application interface for this DRUNIX release?
8. Which SDK versions/languages are tested and supported (Go, Java, Node/TypeScript)?
9. Is there a supported Python client path, or should TokANSH use a Go/Node adapter?
10. Is a gateway endpoint exposed by the shared network, and is it attached to an LP?
11. What are the recommended evaluate, endorse, submit and commit-status timeout/retry settings?
12. Are there network-specific differences from the upstream sample gateway?

### Chaincode and policy
13. Which chaincode languages/runtimes are supported in the target environment?
14. Which endorsement policies should TokANSH use across organisations?
15. Which identity attributes/ACL mechanisms are available to chaincode?
16. Are private data collections required or recommended for this use case?
17. What are the chaincode deployment/approval/upgrade steps and required permissions?

### Events, history and operations
18. Which chaincode event API and replay/checkpoint mechanism are supported?
19. Is historical state or block/event retrieval available to application clients?
20. What is the retention and query model for committed transactions?
21. How should applications resolve a transaction whose submit succeeded but commit-status response timed out?
22. Are there known limits for transaction payload size, query size, throughput or concurrent submissions?

## 16. Public references inspected

1. NPCI DRUNIX repository README: https://github.com/npci/drunix
2. DRUNIX architecture changes: https://github.com/npci/drunix/blob/main/docs/drunix-arch.md
3. DRUNIX test-network README: https://github.com/npci/drunix/blob/main/drunix-network/test-network/README.md
4. DRUNIX asset-transfer-basic sample: https://github.com/npci/drunix/tree/main/drunix-network/asset-transfer-basic
5. TypeScript gateway sample: https://github.com/npci/drunix/tree/main/drunix-network/asset-transfer-basic/application-gateway-typescript
6. Go REST wrapper sample: https://github.com/npci/drunix/tree/main/drunix-network/asset-transfer-basic/rest-api-go
7. DRUNIX gateway package documentation: https://pkg.go.dev/github.com/npci/drunix/internal/pkg/gateway
8. DRUNIX module definition (`go.mod`): https://github.com/npci/drunix/blob/main/go.mod

**Research limitation:** public repository documentation and samples establish a useful integration path, but they do not establish the configuration, operational guarantees or support commitments of the specific hackathon network. Revalidate every version- and environment-sensitive detail before implementation.

## 17. M3.2 local implementation and evidence

The approved React → FastAPI → private Go gateway → DRUNIX boundary is implemented for diagnostic reads only. [Gateway README](../gateway/README.md) documents configuration, private endpoints, constraints and repeatable verification. Existing research/deployment examples above are not instructions to reset or redeploy the running network.

The public Fabric Gateway Go SDK v1.10.0 with gRPC v1.76.0 (matching the local DRUNIX Go sample) successfully evaluated GetAllAssets against existing `basic` on `mychannel` using Org1 User1, TLS CA verification and peer hostname verification. DRUNIX source was inspected at `8090e0ce58802c8a0f13d23a6abe5a2d35456cc5`. The SDK result matched the full decoded peer CLI result: asset1 through asset6. Go HTTP and FastAPI diagnostic reads were also verified; channel height was 8 before and after verification. These observations establish compatibility for these reads on this local network only, not general Fabric compatibility, write support or production guarantees.

Only GetAllAssets, ReadAsset and AssetExists are exposed privately. No submission or commit implementation exists. System Status preserves its existing schema and reports actual read observations without transaction evidence; readiness stays unavailable. Diagnostic evaluation results never populate ANSH business state. Production credentials, distributed deployment, service authentication and transaction lifecycle/reconciliation remain future work.

**Final verification limitation:** later Gateway SDK probes timed out at the unchanged five-second deadline, despite a contemporaneous successful peer CLI read (0.087 seconds). Earlier full-stack verification remains valid evidence of successful reads, but repeatability is unresolved. No workaround or network modification was attempted; the runtime reliability gate is not fully satisfied.

### M3.2c/d local WSL endpoint recommendation

Use environment configuration `DRUNIX_PEER_ENDPOINT=dns:///127.0.0.1:7051` with `DRUNIX_TLS_SERVER_NAME=peer0.org1.example.com` and `DRUNIX_EVALUATE_TIMEOUT=5s` for the existing local Org1 LP gateway. The literal IP avoids unnecessary local DNS resolution; the configured CA and TLS server-name verification remain enabled. This is a local deployment recommendation, not an IP hardcoded in Go source or a change to application business behavior.

In M3.2c's bounded comparison, the hostname endpoint completed 9/10 fresh SDK reads, with one five-second timeout. The literal-IP endpoint completed 10/10 fresh reads and 10/10 sequential reads on a reused connection. All successful full asset payloads matched native peer CLI results; channel height and block hashes were unchanged. These results support adopting the literal IP locally without retries or deadline increases. They do not confirm the historical timeout's exact cause or guarantee long-term reliability. The preceding M3.2 limitation describes the earlier hostname-endpoint verification.
