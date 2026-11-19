# Offline prepared registration verification

Run from the repository root with the existing backend virtual environment:

```bash
backend/.venv/bin/python -B scripts/verify_prepared_registration.py \
  --operation-id edaeabd1-78e9-4e9d-a808-92affc2a81af \
  --transaction-id 205f60daf6790d1d2a9cc2077026691e6bdef754810c1451c6791f0e892b984f \
  --command "$HOME/.local/share/tokansh/evidence/m33c4-20261119T090531Z/command.json"
```

This is a local read, not Gateway prepare/submit/status. It never loads a signing
private key. The existing SQLite file is opened with mode=ro and query_only, and
only the selected PREPARED row is queried. The selected file must match DATABASE_URL
from ~/.config/tokansh/local.env (owner-only file and directory). No migration,
backup restore, row update, evidence export or network operation is performed.
Read-only WAL opening still relies on SQLite's normal existing sidecar requirements.

The existing gateway secret is used only to authenticate the artifact HMAC, over a
private stdin pipe, never argv/output or a temporary artifact file. The Go verifier
is built in a private temporary directory using the existing gateway module/pins,
GOPROXY=off, GOSUMDB=off and GOTOOLCHAIN=local. Missing cached tooling/dependencies
fail closed. Temporary compiled code is removed; no source modules are changed.

Checks include exact JSON keys, malformed/unknown protobuf fields and duplicate
singular fields; local row/frozen-command/artifact agreement; existing production
artifact HMAC/creator pin checks; nonce-derived transaction ID; one transaction
action with matching signature header; exact channel/chaincode/function/command;
proposal hash; successful registration result; expected property and receipt writes;
and exactly two endorsements, one each Org1MSP and Org2MSP. Both signatures verify
SHA256(ProposalResponsePayload || original serialized Endorser), using canonical
ASN.1 low-S ECDSA P-256 as in DRUNIX bccsp/sw/ecdsa.go. The signed shared response
payload is bound to the prepared proposal by the Fabric proposal hash algorithm
(protoutil/txutils.go:GetProposalHash2). No separate per-endorser response is invented.

Trust scope is explicitly **offline local MSP**. --msp-root defaults to the existing
DRUNIX test-network organizations/peerOrganizations directory. It must be the
operator-reviewed enrollment MSP configuration, not TLS roots or a caller-supplied
self-declared MSP label. The supported profile is the inspected exact NodeOUs config,
one enrollment root per org, direct root issuance, enabled peer/client OU identities,
current certificate validity and digital-signature usage. The pinned Org1 User1
creator is also chain-validated. A different profile, intermediate CA, or nonempty CRL
requires a separately reviewed implementation; it returns BLOCKED_MSP_TRUST_INCOMPLETE.
No CRL is configured in the inspected profile: this does not assert external live
revocation status. Certificates/configuration must be retained securely and unchanged
during verification; root-file selection is a trusted local operator boundary.

PASS means cryptographic signatures and the selected local MSP trust profile pass.
It does NOT establish current channel configuration freshness, package deployment,
MVCC validity, ordering, submission, final commit, on-chain registration or authorization
to submit. A later signed channel-config snapshot/revocation policy is required if
current channel trust, rather than the accepted local MSP profile, is the acceptance
criterion. In that case treat submission clearance as BLOCKED until independently
reviewed; do not promote the local PASS into full Fabric channel validation.

Tests generate isolated root/peer certificates and low-S endorsements in memory.
The lower-level endorsed-evidence parser has a full synthetic positive fixture;
creator trust and the outer production pin/HMAC gate are tested separately. Tests
cannot substitute a generated identity for the production-pinned User1. Existing
registration tests cover production artifact MAC construction/validation. A real
stored-artifact run is separate evidence, never a test fixture committed to Git.

```bash
cd gateway
GOPROXY=off GOTOOLCHAIN=local go test -mod=readonly -race ./...
GOPROXY=off GOTOOLCHAIN=local go vet -mod=readonly ./...
```

Only a sanitized status and validated public operation/transaction IDs are printed.
Never redirect stdin, enable process tracing or publish DB/artifact/certificate bytes.
FAIL is terminal for this invocation; there are no automatic retries or fallbacks.
