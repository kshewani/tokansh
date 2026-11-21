# DRUNIX deployment operator instructions

M3.3c deployed TokANSH 1.0 sequence 1 and verified at height 11. M3.3c.1 verified reads on both Lite Peers. No live property registration has occurred. Consolidation executes no phases. Obtain explicit human authorization for each phase and organization before using an acknowledgement flag. Flags do not grant authorization themselves. Do not execute commands concurrently or concatenate phases into unattended automation. Keep the reviewed package, manifest and baseline unchanged. This procedure targets initial v1 deployment and verification only; it is not an upgrade script. Fresh approvals are currently blocked by an ambiguous upstream absence signal (see remediation section below).

Examples, each a separate operator action after authorization:

```
bash deployment-proposed.sh install --authorize-install 1
bash deployment-proposed.sh install --authorize-install 2
bash deployment-proposed.sh approve --authorize-approve 1 # inspect existing approval only
bash deployment-proposed.sh approve --authorize-approve 2 # inspect existing approval only
bash deployment-proposed.sh readiness --authorize-readiness
bash deployment-proposed.sh commit --authorize-commit
bash deployment-proposed.sh verify --authorize-verify
```

Inspect each phase's private evidence directory before requesting authorization for the next. Install skips only when the exact package ID is already reported installed. Approval inspection is non-mutating; commit has one attempt, no retry or implicit following phase. A timeout/failure is not proof of no effect: inspect queryinstalled/queryapproved/querycommitted and peer/orderer evidence under the correct organization before deciding on any new action. Do not rerun an uncertain approval or commit automatically. A commit invocation stops if either organization already reports any tokansh definition; use verification and operator review instead.

Commit performs fresh both-org readiness, channel agreement and saved basic definition/full six-asset comparisons before its mutation. Approvals normally advance channel height, so agreement and non-regression are checked rather than insisting height remains 8. This is not historical block-hash anchoring at the original height after the channel advances. The non-atomic interval between checks and commit remains a race with external actors; use an exclusive operator window and stop on unexpected changes.

Post-deployment verification is a separate authorization. It asserts both CPs' channel agreement, unchanged basic definition/assets, tokansh 1.0 sequence 1, escc/vscc, no init or collections, and the decoded two-distinct-peer AND policy on both CPs/LPs; then reads GetContractInfo on both LPs. It does not register a property or verify the application's submit/recovery path. A failed verification never triggers rollback or another mutation. Eventual propagation can require a later explicitly authorized verification; there are no polling retries.

The certificate checks are local static checks, not proof of a live successful multi-peer TLS session. The two actual CP certificates have DNS:localhost. The DRUNIX CLI uses a shared peer TLS override; commit clears it and verifies each localhost endpoint against its organization CA. Orderer TLS name remains orderer.example.com. Staged credential paths point to existing organization Admin MSP directories; no keys are copied or printed.

Do not use the archived monolithic script from the original temporary directory. Retain package, manifest, baseline and evidence securely outside both repositories and beyond temporary-directory cleanup. Do not edit/regenerate the package or replace the saved baseline to make a failed check pass.


## External context: mandatory before any phase

The repository stores reusable tooling and synthetic offline test fixtures only.
`accepted-local-deployment.json` is a sanitized historical identity, not a runnable
profile. It preserves the exact accepted SHA/package ID and source revision.
The original package, baseline and evidence remain external; do not copy them into Git.
The historical manifest's validation statements describe package preparation time,
not current deployment state.

1. Create a private durable release directory outside TokANSH and DRUNIX. Archive
   the reviewed package, baseline and evidence there without changing their bytes.
2. Copy `deployment-context.example.json` there and replace every placeholder.
   `network_root` points to the existing DRUNIX repository, not test-network.
   Create `evidence_directory` with owner-only permissions. Restrict the manifest,
   baseline and archive to the operator. All paths must be absolute.
3. For the existing deployment, retain the exact identity in
   `accepted-local-deployment.json`; retain the original baseline hash
   `2d9d8d0a51c159125f2ccca2cf8e7bbe3e3aed996889ff4d9dd45f2cbed2deca`.
   Do not turn the synthetic fixture into a baseline.
4. Bind both CP TLS certificates by SHA-256 of DER certificate bytes (not PEM text):
   `openssl x509 -in /path/to/peer1/tls/server.crt -outform DER | sha256sum`.
   Review actual network paths, certificates, baseline provenance and package
   together. This is local file inspection, not a live connectivity check.
5. Review the complete manifest, compute its SHA-256, and separately acknowledge
   that digest and unique deployment ID. The script does not source shell files:

```bash
export TOKANSH_DEPLOYMENT_MANIFEST=/absolute/path/to/private-release/context.json
export TOKANSH_DEPLOYMENT_MANIFEST_SHA256=REVIEWED_MANIFEST_SHA256
export TOKANSH_DEPLOYMENT_ID=REVIEWED_UNIQUE_DEPLOYMENT_ID
# Offline only; validates package/baseline hashes and local CP certificate pins:
python3 scripts/drunix/deployment-context.py "$TOKANSH_DEPLOYMENT_MANIFEST" \
  "$TOKANSH_DEPLOYMENT_MANIFEST_SHA256" "$TOKANSH_DEPLOYMENT_ID"
```

Run phase examples above from `scripts/drunix/` only after separate authorization.
No context is selected by default. Missing, mismatched or incomplete context fails
before any peer command. Evidence is generated only in the external evidence directory.
`DRUNIX_CONFIGTXLATOR` is set by the shell wrapper from the selected network root;
standalone policy checks with encoded MSP principals require this explicit path.

## Preparing a future package identity

Never edit the historical identity record to select a new release. Create a new
release directory, deployment ID and manifest; stage reviewed source outside both
repositories, vendor dependencies there as needed, run tests/race/vet/build, then
package twice and compare bytes. Record source revision/file hashes, package SHA,
`peer lifecycle chaincode calculatepackageid` result, label and size. These local
artifact commands are not network deployment authorization.

Obtain a fresh independently reviewed baseline for the target environment under
separate read-only authorization: both CP channel states/definitions and both LP
full six-asset payloads. Preserve the original `Org1_channel`, `Org2_channel`,
`Org1_definitions`, `Org2_definitions`, `Org1_basic`, `Org2_basic` objects with
`observed` values. Hash its exact bytes. Never reuse another environment's baseline.
Pin the target CP certificates and review the new manifest digest/ID before use.

A different reviewed package hash is supported for a new initial-v1 environment;
version/sequence/channel/policy changes and upgrades require design/script/test
review. The commit phase intentionally refuses any existing TokANSH definition.
Certificate/path binding catches accidental environment swaps, not a malicious
operator or a ledger reset retaining identical certificates. Fresh baseline review
is mandatory; no claim of genesis-block anchoring is made. Explicitly acknowledging
an old manifest cannot mechanically prove its freshness.

## Local-only policy exception and transaction acceptance boundary

The observed Org2 Writers policy anomaly was explicitly accepted only for this
isolated local hackathon network. It is not approved for shared, cloud or production
environments. Do not modify policies using this tooling. A broader deployment needs
separate policy review/remediation and fresh endorsement/authorization acceptance.
The chaincode policy remains exactly AND('Org1MSP.peer','Org2MSP.peer'); both endorsers
must be available. Lifecycle administrators are distinct from the pinned Org1 User1
application signer.

Before M3.3c.2, review a separate transaction checkpoint: approval attestation and
exact UUID command, migration 0002 readiness, secure database/artifact backup and
stable signing/HMAC secrets, exclusive operator window, before/after ledger/basic
baseline, and expected operation/property receipt comparisons. Permit one explicit
submission through RegistrationService, confirm VALID status before claiming success,
and reconcile UNKNOWN/PENDING after restart without resubmission. Live endorsement,
ordering, MVCC and LP-to-CP status forwarding remain unverified. This deployment
script never prepares/submits business transactions or tests recovery on the ledger.

## Offline validation

```bash
bash -n scripts/drunix/deployment-proposed.sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s scripts/drunix -p 'test_*.py'
```

Tests use synthetic CLI-shaped objects, temporary files and decoded policy principals;
they do not call peers, deploy chaincode, or prove runtime compatibility. They retain
the all-definitions/name-required checks (named CLI responses omit the name).

## Strict lifecycle inspection (M3.3c.3 review remediation)

`lifecycle-inspect.py` is the single offline parser for installation, committed
TokANSH definitions and existing approvals. It rejects duplicate JSON keys, missing
arrays, invalid entries/types and duplicate/ambiguous package identities or names.
Exit codes are 0 MATCH, 3 validated ABSENT, 4 CONFLICT, 1 invalid/ambiguous. A CLI
failure is never passed off as absence. The expected package ID comes from the
reviewed external context, not the historical deployment record.

- Install: MATCH skips mutation; only ABSENT permits one install attempt. A matching
  label with a different package ID is a conflict. A failed query/parser stops.
- Commit: only ABSENT on both CPs permits one commit attempt after readiness and
  preservation checks. MATCH stops and directs the operator to separate verification;
  CONFLICT and malformed/ambiguous responses stop. No automatic retries occur.
- Approval: query the requested organization's CP for `tokansh`, `mychannel`,
  sequence 1. MATCH requires the exact package source, version, sequence, plugins,
  no init/collections, and reviewed serialized two-org AND policy; it skips mutation.
  Conflicting or malformed output and every failed query stop. A semantically
  equivalent policy with different protobuf bytes is conservatively a conflict.

### Fresh approval is blocked pending a safe absence signal

Source inspection, not a live query, establishes the current DRUNIX behavior:
`internal/peer/lifecycle/chaincode/queryapproved.go:136–141` returns a nonzero CLI
error `query failed with status: ...` on unsuccessful proposal responses. In
`core/chaincode/lifecycle/lifecycle.go:551–552` (missing parameter metadata) and
`:570–571` (parameters exist but package-source metadata is missing), the same
message is returned:

```
could not fetch approved chaincode definition (name: 'tokansh', sequence: '1') on channel 'mychannel'
```

It is therefore **ambiguous**, even with exact text matching. No current approval
response can be classified as verified ABSENT by this tooling. The approve phase
is now inspection-only: it skips exact existing approval or stops; it cannot create
an approval on a fresh environment. Do not interpret an error string, empty object,
or operator flag as absence authorization. Before restoring a fresh-approval path,
review a supported way to distinguish genuine absence from inconsistent state.
This is an explicit unresolved dependency, not silently weakened validation.

The success JSON schema is verified from the pinned CLI's `common.go:122–138`
(`encoding/json` of the protobuf), lifecycle SCC result construction and
fabric-protos-go-apiv2 v0.3.7. Approval JSON is a named-query result without `name`;
its oneof source is `{"Type":{"LocalPackage":{"package_id":"..."}}}`. The
name/channel/sequence are fixed query arguments. These source findings do not
constitute live approval acceptance. Policy bytes match the reviewed deployed
ApplicationPolicy; future policies need explicit review.

Environment binding relies on trusted local configuration and certificate files,
not cryptographic channel identity or a live endpoint certificate fingerprint pin.
The network's CLI still verifies TLS CA and hostname. Baseline freshness, directory
permissions, filesystem integrity and an exclusive operator window remain operator
responsibilities; files must not change between review, validation and phase use.

Offline shell tests run this script against temporary fake peer/openssl executables
and synthetic context files only. They exercise exit behavior, mutation gates and
single-attempt failures without reaching any DRUNIX service.
