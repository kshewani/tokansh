# TokANSH chaincode — registration and ANSH issuance

An isolated Go module using the existing DRUNIX basic sample's chaincode libraries: fabric-chaincode-go/v2 v2.0.0 and fabric-contract-api-go/v2 v2.2.0. M3.3a registration is extended by locally tested M4.1 issuance. Nothing here deploys chaincode or initializes a ledger; this extension has not been deployed or validated on DRUNIX.

## Public contract

All functions take `contractapi.TransactionContextInterface` first:

- `GetContractInfo(ctx) (*ContractInfo, error)`
- `GetRegisteredProperty(ctx, propertyID string) (*Property, error)`
- `GetOperation(ctx, authorizingMSP, operationID string) (*Operation, error)`
- `RegisterApprovedProperty(ctx, commandJSON string) (*RegistrationResult, error)`
- `IssueANSH(ctx, commandJSON string) (*IssuanceResult, error)`
- `GetIssuanceState(ctx, propertyID string) (*IssuanceState, error)`
- `GetBalance(ctx, propertyID, holderID string) (*Balance, error)`
- `GetIssuanceOperation(ctx, operationID string) (*IssuanceOperation, error)`

Read info/properties requires Org1MSP or Org2MSP membership. Registration and receipt reads require the approved Org1 User1 MSP, exact Fabric principal and SHA-256 certificate fingerprint. Pins are public, deterministic package policy, not environment-dependent. The sole local-MVP service signer attests application approval; issuer UUID is attribution, not the issuer's personal signature. Fabric validates the signed creator identity; chaincode adds its narrower allowlist. No backend/demo header is trusted or accepted by this contract.

The public User1 certificate in `contract/testdata` is an explicitly allowlisted unit-test fixture, contains no private key, and is not a runtime credential-loading mechanism. Tests fake the already-authenticated client context; they do not test Fabric signature verification. Key custody, private gateway authentication and operator authorization belong to application/Gateway integration, not this module. Replacing the pinned certificate requires a reviewed policy/package update.

## Command and state

Registration accepts exactly these JSON fields: `command_version` (1), `operation_id`, `property_id`, `issuer_id`, `approval_reference`, `approval_digest`, `approved_supply`, `issue_price_minor`, `currency` (INR). UUIDs must be canonical lowercase RFC variant UUIDs of versions 1–5; property UUID is reused from the application. Approval digest is lowercase SHA-256 hex. No documents, names, addresses or external URLs are accepted.

Commands are limited to 4096 UTF-8 bytes. Unknown, duplicate (including escaped duplicate), missing, null and incorrectly cased fields are rejected, as is trailing data. Quantity must be an integer JSON number from 1 through 9007199254740991; decimal/exponent encodings are rejected. Price is a canonical integer minor-unit string from "1" through "9999999999999999", preserving the backend monetary limit. No floating-point calculations occur.

Fabric composite keys:

- `CreateCompositeKey("property", []string{property_id})`
- `CreateCompositeKey("operation", []string{"Org1MSP", operation_id})`

Version-1 property state stores immutable approved constraints, issuer/approval references, derived registering MSP/principal, registration operation/transaction IDs and proposal timestamp. `approved_supply` is a **lifetime cumulative issuance ceiling**, not minted supply. Registration itself creates no holdings or issuance state. M4.1 tracks the lifetime ceiling in separate supply and inventory keys, without changing existing property or registration receipt schemas.

Version-1 receipts store authorizing identity, function, canonical request digest, property ID, original transaction ID and original registration result. The digest covers typed command fields, function and derived MSP/principal; whitespace/field order do not change it. Identical replay returns the original result without writes or new timestamps. Conflicting operation reuse and registration under a different operation are rejected. Receipts are not deleted.

Errors are deterministic JSON strings with `code` and fixed `message`: INVALID_ARGUMENT, UNSUPPORTED_SCHEMA_VERSION, UNAUTHORIZED, PROPERTY_NOT_FOUND, OPERATION_NOT_FOUND, PROPERTY_ALREADY_REGISTERED, IDEMPOTENCY_CONFLICT, LEDGER_STATE_ERROR, ISSUANCE_LIMIT_EXCEEDED. Underlying errors are not returned. Application/gateway HTTP envelopes remain separate.

The result's transaction ID comes from Fabric transaction context. Execution/endorsement results **do not prove commitment**. A proposal timestamp is not trusted wall-clock time. Both writes are in one simulation; an error causes the transaction's write set to be discarded by Fabric. No manual rollback writes occur.

## Validation

Run from this directory:

```sh
go test -mod=readonly ./...
go test -mod=readonly -race ./...
go vet -mod=readonly ./...
```

Tests cover deterministic state and errors, authorization, strict command boundaries, replay/conflict, reads, immutable registration, cumulative issuance ceilings, inventory consistency, overflow, corrupt records and state-access/write failures. The isolated stub models Fabric's commit/discard boundary. These tests cannot establish real MVCC, endorsement-policy enforcement, atomic commit or DRUNIX finality. No live network tests, deployment, initialization or ledger writes are part of local validation. Independent review and explicit authorization are required before deploying this extension. Gateway/backend/frontend integration is unchanged and does not yet expose issuance.


## M4.1 — Issuer inventory only

The command is exactly:

```json
{
  "command_version": 1,
  "operation_id": "50000000-0000-4000-8000-000000000001",
  "property_id": "20000000-0000-4000-8000-000000000001",
  "quantity": 40
}
```

The same strict spelling, duplicate/unknown/null rejection, UUID rules, 4096-byte
limit and integer range apply as for registration. Zero, negative, decimal,
exponent, string and out-of-range quantities are invalid. Quantities use `int64`;
both additions explicitly check overflow. Price and currency remain the immutable
registered property's values; an issuance command cannot override them.

`authorizeIssuance` delegates to the unchanged registration authority check for the
local MVP. Issuance and issuance-receipt reads require that authenticated MSP,
principal and certificate pin. The issuer UUID always comes from the validated
registered property. It is an inventory attribution, not a personal signing
identity. Supply and balance reads allow the same Org1/Org2 membership as property
reads. No demo role or request-supplied issuer can authorize issuance.

New composite keys (all records use `schema_version: 1`):

- `issuance / property_id`: property/issuer IDs, immutable `approved_supply`,
  `cumulative_issued_supply`, `remaining_issuance_capacity`.
- `balance / property_id / holder_id`: property/holder IDs and integer `quantity`.
- `issuance_operation / Org1MSP / operation_id`: operation/property/issuer IDs,
  derived MSP/principal, function, canonical request digest, quantity, original
  transaction ID and original result.

Issuance operation IDs are unique across properties within the separate issuance
namespace. The existing registration `operation` namespace is unchanged. A digest
binds the typed command, `IssueANSH`, MSP and authenticated principal; JSON ordering
and whitespace do not change it. An identical operation returns its original
transaction ID and issuance snapshot, even after later issuances; a changed
property or quantity under that operation returns `IDEMPOTENCY_CONFLICT`.

A registered property with both new supply/inventory keys absent reads as zero
issued with its full approved capacity, without writing keys. A partially missing
pair, invalid schema, inconsistent receipt or balance/counter mismatch fails with
`LEDGER_STATE_ERROR`. There are no transfers or burns in M4.1: issuer inventory must
equal cumulative issuance, and other holders have zero balances. These checks
must be reviewed together with conservation rules before adding transfer/burn
functions; do not simply weaken them when extending the lifecycle.

One `IssueANSH` simulation reads the property, receipt, shared supply key and issuer
balance; it writes exactly the supply, issuer balance and receipt. A failed write
invalidates the simulation. Reads of the shared supply key and operation key
participate in Fabric MVCC: competing proposals may endorse successfully, but
conflicting stale writes must not both commit. Unit tests model commit/discard,
not DRUNIX MVCC validation. The response includes property/issuer/operation IDs,
transaction ID, quantity, cumulative supply, remaining capacity and issuer balance
as of that issuance. An endorsement response is never evidence of valid commit;
the caller must observe actual commit status before reporting issuance success.
