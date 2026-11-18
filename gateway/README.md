# Private DRUNIX Gateway — M3 current state

This isolated Go module implements the approved FastAPI → Go → DRUNIX boundary. Its M3.2 diagnostic routes only query `basic` on `mychannel`. The M3.3b authenticated private extension implements TokANSH preparation, submission and status recovery; live business transactions remain unverified. No runtime mock/fallback is available. The DRUNIX repository and running network must remain unchanged.

## Configuration and execution

Go 1.24+ is required. The public SDK versions match the inspected DRUNIX sample at `drunix-network/asset-transfer-basic/application-gateway-go/go.mod`: Fabric Gateway **v1.10.0**, gRPC **v1.76.0**, fabric-protos-go-apiv2 **v0.3.7**. Validation used Go 1.26.11.

Export the variables documented in [.env.example](.env.example). The Go programs do not auto-load `.env`. Keep credentials outside TokANSH; provide file paths, never certificate/key contents in environment values. For the existing Org1 network under `~/projects/drunix/drunix-network/test-network/organizations/peerOrganizations/org1.example.com`:

| Variable | Existing material / value |
|---|---|
| `DRUNIX_MSP_ID` | `Org1MSP` |
| `DRUNIX_CERT_PATH` | `users/User1@org1.example.com/msp/signcerts/User1@org1.example.com-cert.pem` under that directory |
| `DRUNIX_KEY_PATH` | Explicit existing file in that user's `msp/keystore`; do not copy or print it |
| `DRUNIX_TLS_CA_PATH` | `peers/peer0.org1.example.com/tls/ca.crt` under that directory |
| `DRUNIX_PEER_ENDPOINT` | `dns:///127.0.0.1:7051` (Org1 LP gateway, recommended for local WSL) |
| `DRUNIX_TLS_SERVER_NAME` | `peer0.org1.example.com` |

Certificate and key must match, use ECDSA P-256 and be currently valid. TLS verifies the peer against its CA and server name; signed evaluation proposals use User1's MSP identity. This is not a claim of mutual TLS client-certificate authentication. Connection construction is lazy: only a successful evaluation establishes actual connectivity.

For local WSL deployment, the literal-IP endpoint avoids unnecessary local DNS resolution while preserving TLS server-name verification through `DRUNIX_TLS_SERVER_NAME=peer0.org1.example.com`. The endpoint remains environment-driven; Go source does not hardcode the IP. Keep the five-second evaluation deadline and do not add retries. For other deployments, configure the actual network endpoint and matching TLS server name.

From `gateway/`, after exporting the paths above:

```bash
go build -mod=readonly -o bin/probe ./cmd/probe
go build -mod=readonly -o bin/gateway ./cmd/gateway
./bin/probe
./bin/gateway
```

The probe calls exactly `EvaluateTransaction("GetAllAssets")`. HTTP reads use cancellation-aware evaluation with bounded contexts and reuse the SDK connection. Defaults: loopback `127.0.0.1:8001`, evaluation deadline 5 seconds (allowed 100ms–10s), channel `mychannel`, chaincode `basic`. Other channels/chaincodes and non-loopback listening addresses are rejected. Server header/read/write timeouts are 2/3/15 seconds. A request has one overall evaluation deadline even when ReadAsset first checks existence. Responses are limited to 1 MiB (gRPC receive ceiling 2 MiB).

## M3.2 basic diagnostic HTTP contract

For the M3.2 basic diagnostic routes, only GET requests are accepted; query parameters and request bodies are rejected. These diagnostic routes have no generic invocation endpoint, CORS configuration, transaction submission or automatic retry.

| Route | Meaning |
|---|---|
| `/health` | Process liveness only; data is `{status:"UP",mode:"READ_ONLY"}` |
| `/v1/basic/assets` | GetAllAssets |
| `/v1/basic/assets/{id}` | ReadAsset; missing asset returns 404 |
| `/v1/basic/assets/{id}/exists` | AssetExists; missing asset returns false |

Asset IDs match `[A-Za-z0-9][A-Za-z0-9._:-]{0,127}`. Successful evaluations return:

```json
{"data":{"source":"DRUNIX_EVALUATE","channel":"mychannel","chaincode":"basic","function":"AssetExists","observed_at":"2026-11-18T00:00:00Z","result":true},"meta":{"correlation_id":"application-reference"}}
```

Timestamp above illustrates the format only. Real responses use the actual observation time. Assets retain the chaincode's `ID`, `Color`, `Size`, `Owner`, `AppraisedValue` fields. GetAllAssets normalizes the chaincode's valid empty-range `null` to `[]`; malformed data and evaluation failures never become empty results. An evaluation is not a committed transaction and exposes no transaction ID or commit evidence.

Errors use `{error:{code,message},meta:{correlation_id}}`. Codes include `INVALID_ARGUMENT` (400), `REQUEST_CANCELLED` (408), `ASSET_NOT_FOUND`/`RESOURCE_NOT_FOUND` (404), `METHOD_NOT_ALLOWED` (405), `MALFORMED_LEDGER_RESPONSE` (502), `LEDGER_UNAVAILABLE` (503), `LEDGER_TIMEOUT` (504). Unexpected failures return sanitized `INTERNAL_ERROR` (500). SDK exception contents, identity material and certificate contents are not returned. `X-Correlation-ID` is propagated or generated as an application reference; responses disable caching.

Loopback is the local MVP trust boundary, not authentication against other local processes. Production requires a separately reviewed authenticated private transport, dedicated least-privilege identity and credential lifecycle.

## Validation

```bash
go test -mod=readonly ./...
go test -mod=readonly -race ./...
go vet ./...
```

Tests generate ephemeral identities only inside temporary test directories. Real reads are opt-in and require the existing network and exported configuration:

```bash
RUN_DRUNIX_INTEGRATION=1 go test -mod=readonly -count=1 -run TestDRUNIXReadOnlyIntegration -v ./internal/readonly
python3 scripts/verify_readonly.py
```

The Python verifier additionally needs existing `../backend/.venv`, built `bin/probe` and `bin/gateway`, and the existing DRUNIX peer CLI. It defaults to `~/projects/drunix` (override `DRUNIX_REPOSITORY`). It compares the full decoded SDK and HTTP results against peer CLI GetAllAssets, runs live Go reads and FastAPI tests, and checks channel height before/after through Org1 CP `localhost:7061`. It starts/stops only its own temporary TokANSH gateway child. It does not manage containers, deploy chaincode or invoke writes. Tests assume the previously observed six diagnostic assets; an externally changed baseline fails explicitly.

Historical M3.2 verification results: asset1–asset6, complete payload equality with peer CLI, real FastAPI adapter reads, missing-asset handling and rejection of incorrect TLS server name. Channel height remained 8. An initial probe failed, then a fresh probe and the full verifier succeeded without SDK/dependency/network changes. Final verification and a subsequent standalone SDK probe both returned `LEDGER_TIMEOUT` at the unchanged 5-second deadline (standalone duration 5.026 seconds), while a contemporaneous peer CLI GetAllAssets succeeded in 0.087 seconds with all six assets. The SDK timeout cause is unresolved; repeatable gateway connectivity is an open M3.2 acceptance issue. No retry, deadline increase, alternate SDK or transport workaround was added. Live testing also caught and corrected Python 3.10 rejection of Go nanosecond timestamps.

Read connectivity does not prove endorsement, ordering, validation, submission, commit status or reconciliation. FastAPI `/ready` remains 503, transaction capability UNAVAILABLE, last ledger operation null, and Connected Mode business screens remain unavailable.

M3.2c follow-up: with the unchanged five-second deadline, `dns:///localhost:7051` succeeded in 9/10 fresh reads (one timeout); `dns:///127.0.0.1:7051` succeeded in 10/10 fresh reads and 10/10 reads on one reused connection. All successful full asset payloads matched peer CLI, and channel height and block hashes were unchanged. This bounded evidence supports the literal-IP recommendation; it does not establish long-term reliability or confirm the historical timeout's exact cause. The M3.2 timeout observations above remain historical evidence.

Verifier CLI peer selection is independent of the SDK endpoint: `DRUNIX_CLI_COMMITTING_PEER_ADDRESS` defaults to `localhost:7061` for channel height and block hashes, while `DRUNIX_CLI_LITE_PEER_ADDRESS` defaults to `localhost:7051` for basic chaincode queries. Each command receives its own environment copy. Before/after checks compare height, current block hash and previous block hash. CLI failures include bounded, sanitized stderr.

M3.3b adds [authenticated private transaction integration](TRANSACTIONS.md), disabled unless both dedicated secrets are configured. Existing basic diagnostic routes and their read-only semantics are preserved. No live write capability has been verified on DRUNIX.


## Current M3 acceptance boundary

TokANSH v1.0 sequence 1 is deployed on mychannel with the two-org AND policy.
Deployment preservation checks and dual-org Lite Peer read acceptance passed at
height 11: contract metadata 200, absent property/operation 404, basic six assets
preserved. Both peer endpoints were tested with the pinned Org1 User1 signer;
this does not establish an Org2 application signer authorization.
No live property registration has occurred. Endorsement, submission, commit-status
forwarding and restart reconciliation still require M3.3c.2 live acceptance.
Earlier M3.2 timeout observations above are historical; literal-IP selection
improved bounded read reliability without confirming the original root cause.

[Deployment instructions](../scripts/drunix/OPERATOR-INSTRUCTIONS.md) preserve the
phase-gated procedure and local-only Org2 Writers exception. Private secrets,
packages, baselines and raw evidence stay outside Git. See [transaction limitations](TRANSACTIONS.md)
for the SQLite preparation write lock, trusted single-submission gate (no global
exactly-once guarantee) and cold namespace initialization latency risk. The evaluation
deadline stays five seconds, with no retry. `/ready` remains unavailable until business
readiness is established; deployment or successful reads alone do not enable it.
