#!/usr/bin/env bash
# REVIEW ONLY. Every phase needs separate explicit human authorization.
# Syntax: bash deployment-proposed.sh PHASE --authorize-PHASE [ORG]
# install/approve require ORG 1 or 2; readiness/commit/verify accept no ORG.
# Authorization flags are operator acknowledgements, not access control.
# Never run phases concurrently. A failed/timeout mutation is UNCERTAIN:
# inspect state and logs first; do not rerun approve/commit automatically.
# No init, registration, policy update, network reset or approval chaining.
set -Eeuo pipefail
umask 077
PHASE=${1:-}
case "$PHASE" in install|approve|readiness|commit|verify) ;; *) echo 'Choose exactly one phase: install, approve, readiness, commit, verify' >&2; exit 2;; esac
[[ ${2:-} == "--authorize-$PHASE" ]] || { echo 'Explicit phase authorization flag required' >&2; exit 2; }
ORG=${3:-}
if [[ "$PHASE" == install || "$PHASE" == approve ]]; then
    [[ $# == 3 && ( "$ORG" == 1 || "$ORG" == 2 ) ]] || exit 2
else
    [[ $# == 2 ]] || exit 2
fi
HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# No implicit package, baseline or environment selection. Validate offline first.
: "${TOKANSH_DEPLOYMENT_MANIFEST:?Select an external reviewed manifest}"
: "${TOKANSH_DEPLOYMENT_MANIFEST_SHA256:?Acknowledge its reviewed SHA-256}"
: "${TOKANSH_DEPLOYMENT_ID:?Acknowledge the deployment/environment ID}"
CONFIG=$(python3 "$HERE/deployment-context.py" "$TOKANSH_DEPLOYMENT_MANIFEST" "$TOKANSH_DEPLOYMENT_MANIFEST_SHA256" "$TOKANSH_DEPLOYMENT_ID")
mapfile -t SETTINGS <<< "$CONFIG"
DRUNIX=${SETTINGS[0]}
PACKAGE=${SETTINGS[1]}
BASELINE=${SETTINGS[2]}
SHA=${SETTINGS[3]}
PACKAGE_ID=${SETTINGS[4]}
EVIDENCE_ROOT=${SETTINGS[5]}
NETWORK="$DRUNIX/drunix-network/test-network"
PEER="$DRUNIX/build/bin/peer"
TRANSLATOR="$DRUNIX/build/bin/configtxlator"
export DRUNIX_CONFIGTXLATOR="$TRANSLATOR"
CHECK="$HERE/deployment-checks.py"
INSPECT="$HERE/lifecycle-inspect.py"
POLICY="AND('Org1MSP.peer','Org2MSP.peer')"
export FABRIC_CFG_PATH="$DRUNIX/drunix-network/config"
export CORE_PEER_TLS_ENABLED=true
export FABRIC_LOGGING_SPEC=info
ORDERER_CA="$NETWORK/organizations/ordererOrganizations/example.com/orderers/orderer.example.com/tls/ca.crt"
ORG1_CA="$NETWORK/organizations/peerOrganizations/org1.example.com/peers/peer0.org1.example.com/tls/ca.crt"
ORG2_CA="$NETWORK/organizations/peerOrganizations/org2.example.com/peers/peer0.org2.example.com/tls/ca.crt"
ORDERER=(-o localhost:7050 --ordererTLSHostnameOverride orderer.example.com --tls --cafile "$ORDERER_CA")
DEFINITION=(--channelID mychannel --name tokansh --version 1.0 --sequence 1 --signature-policy "$POLICY" --init-required=false)
for file in "$PACKAGE" "$BASELINE" "$CHECK" "$INSPECT" "$PEER" "$TRANSLATOR" "$ORDERER_CA" "$ORG1_CA" "$ORG2_CA"; do [[ -r "$file" ]] || { echo "Missing precondition: $file" >&2; exit 1; }; done
printf '%s  %s\n' "$SHA" "$PACKAGE" | sha256sum --check --status
[[ $("$PEER" lifecycle chaincode calculatepackageid "$PACKAGE") == "$PACKAGE_ID" ]]
# Local-only certificate checks. A shared override is NOT safe for multi-peer CLI.
# ClientConnections uses one viper serverhostoverride for all peer connections.
# Each CP certificate must independently validate the destination name localhost.
for org in 1 2; do
    cert="$NETWORK/organizations/peerOrganizations/org${org}.example.com/peers/peer1.org${org}.example.com/tls/server.crt"
    openssl x509 -in "$cert" -noout -checkhost localhost >/dev/null
    openssl x509 -in "$cert" -noout -checkend 0 >/dev/null
    openssl verify -CAfile "$NETWORK/organizations/peerOrganizations/org${org}.example.com/peers/peer0.org${org}.example.com/tls/ca.crt" "$cert" >/dev/null
 done
EVIDENCE=$(mktemp -d "$EVIDENCE_ROOT/evidence-${PHASE}-XXXXXX")
echo "Phase=$PHASE; evidence=$EVIDENCE"
trap 'rc=$?; echo "STOP: phase failed (exit $rc). Inspect evidence; mutation outcome may be uncertain. No automatic retry." >&2; exit "$rc"' ERR
set_peer() {
    local org=$1 role=$2 port=$3
    export CORE_PEER_LOCALMSPID="Org${org}MSP"
    export CORE_PEER_MSPCONFIGPATH="$NETWORK/organizations/peerOrganizations/org${org}.example.com/users/Admin@org${org}.example.com/msp"
    export CORE_PEER_TLS_ROOTCERT_FILE="$NETWORK/organizations/peerOrganizations/org${org}.example.com/peers/peer0.org${org}.example.com/tls/ca.crt"
    export CORE_PEER_ADDRESS="localhost:${port}"
    export CORE_PEER_TLS_SERVERHOSTOVERRIDE="peer${role}.org${org}.example.com"
    [[ -d "$CORE_PEER_MSPCONFIGPATH" ]]
}
installed() {
    local org=$1; local port=7051; [[ "$org" == 1 ]] || port=9051
    set_peer "$org" 0 "$port" || return 1
    "$PEER" lifecycle chaincode queryinstalled --output json > "$EVIDENCE/installed-$org.json" || return 1
    python3 "$INSPECT" installed "$EVIDENCE/installed-$org.json" "$PACKAGE_ID"
}
readiness() {
    local org port
    for org in 1 2; do
        port=7061; [[ "$org" == 1 ]] || port=9061
        set_peer "$org" 1 "$port"
        "$PEER" lifecycle chaincode checkcommitreadiness "${DEFINITION[@]}" --output json > "$EVIDENCE/readiness-$org.json"
        python3 "$CHECK" readiness "$BASELINE" "$EVIDENCE/readiness-$org.json"
    done
}
preservation() {
    local tag=$1 org cp lp
    for org in 1 2; do
        cp=7061; lp=7051; [[ "$org" == 1 ]] || { cp=9061; lp=9051; }
        set_peer "$org" 1 "$cp"
        "$PEER" channel getinfo -c mychannel > "$EVIDENCE/$tag-channel-$org.txt"
        "$PEER" lifecycle chaincode querycommitted -C mychannel --output json > "$EVIDENCE/$tag-basic-def-$org.json"
        set_peer "$org" 0 "$lp"
        "$PEER" chaincode query -C mychannel -n basic -c '{"Args":["GetAllAssets"]}' > "$EVIDENCE/$tag-assets-$org.json"
        python3 "$CHECK" basic "$BASELINE" "$org" "$EVIDENCE/$tag-basic-def-$org.json" "$EVIDENCE/$tag-assets-$org.json"
    done
    # Approvals/definition commits advance height; compare both peers, not height==8.
    python3 "$CHECK" channels "$BASELINE" "$EVIDENCE/$tag-channel-1.txt" "$EVIDENCE/$tag-channel-2.txt"
}
case "$PHASE" in
install)
    # Inspection is idempotent. Only explicit absence allows one install attempt.
    if installed "$ORG"; then echo 'Reviewed package already installed; no mutation.'
    else
        rc=$?; [[ $rc == 3 ]] || exit "$rc"
        "$PEER" lifecycle chaincode install "$PACKAGE" > "$EVIDENCE/install.txt" 2>&1
        installed "$ORG"
    fi
    ;;
approve)
    installed "$ORG"
    port=7061; [[ "$ORG" == 1 ]] || port=9061
    set_peer "$ORG" 1 "$port"
    # No CLI error, including the known ambiguous missing-approval error, proves
    # absence. Query the exact reviewed sequence and retain private diagnostics.
    "$PEER" lifecycle chaincode queryapproved -C mychannel --name tokansh --sequence 1 --output json > "$EVIDENCE/approved-$ORG.json" 2> "$EVIDENCE/approved-$ORG.stderr"
    if python3 "$INSPECT" approved "$EVIDENCE/approved-$ORG.json" "$PACKAGE_ID"; then
        echo 'Exact expected approval already exists; no mutation.'
    else
        rc=$?
        # There is currently no source-verified unambiguous ABSENT approval response.
        # All non-matching results stop; do not add a stderr-string absence fallback.
        echo 'Approval inspection did not establish a matching approval. STOP; operator review required.' >&2
        exit "$rc"
    fi
    ;;
readiness) readiness ;;
commit)
    installed 1; installed 2
    readiness
    preservation before
    # Stop before mutation if any tokansh definition already exists, even matching.
    for org in 1 2; do
        port=7061; [[ "$org" == 1 ]] || port=9061
        set_peer "$org" 1 "$port"
        "$PEER" lifecycle chaincode querycommitted -C mychannel --output json > "$EVIDENCE/definitions-$org.json"
        if python3 "$INSPECT" committed "$EVIDENCE/definitions-$org.json" "$PACKAGE_ID"; then
            echo 'TokANSH already committed; use separately authorized verification.' >&2
            exit 4
        else
            rc=$?; [[ $rc == 3 ]] || exit "$rc"
        fi
    done
    set_peer 1 1 7061
    unset CORE_PEER_TLS_SERVERHOSTOVERRIDE
    "$PEER" lifecycle chaincode commit "${ORDERER[@]}" "${DEFINITION[@]}" \
        --peerAddresses localhost:7061 --tlsRootCertFiles "$ORG1_CA" \
        --peerAddresses localhost:9061 --tlsRootCertFiles "$ORG2_CA" --waitForEvent > "$EVIDENCE/commit.txt" 2>&1
    # Verification is intentionally a separate authorized invocation, never chained.
    echo 'Commit command returned; this does not replace post-deployment verification.'
    ;;
verify)
    [[ -r "$HERE/extract-definition.py" ]]
    preservation after
    for target in '1 1 7061' '2 1 9061' '1 0 7051' '2 0 9051'; do
        read -r org role port <<< "$target"
        set_peer "$org" "$role" "$port"
        file="$EVIDENCE/tokansh-$org-$role"
        # Named-query JSON omits Name. Preserve the full response, then select
        # exactly one explicit tokansh record before existing strict checks.
        "$PEER" lifecycle chaincode querycommitted -C mychannel --output json > "$file.all.json"
        python3 "$HERE/extract-definition.py" "$file.all.json" "$file.json"
        python3 -c 'import base64,json,sys; d=json.load(open(sys.argv[1])); open(sys.argv[2],"wb").write(base64.b64decode(d["validation_parameter"],validate=True))' "$file.json" "$file.policy.pb"
        "$TRANSLATOR" proto_decode --input "$file.policy.pb" --type protos.ApplicationPolicy --output "$file.policy.json"
        python3 "$CHECK" definition "$BASELINE" "$file.json" "$file.policy.json"
    done
    for org in 1 2; do
        port=7051; [[ "$org" == 1 ]] || port=9051
        set_peer "$org" 0 "$port"
        "$PEER" chaincode query -C mychannel -n tokansh -c '{"Args":["GetContractInfo"]}' > "$EVIDENCE/info-$org.json"
        python3 "$CHECK" info "$BASELINE" "$EVIDENCE/info-$org.json"
    done
    ;;
esac
echo "Phase $PHASE completed. STOP. No subsequent phase is authorized implicitly."
