# TokANSH chaincode foundation (M3.3a)

An isolated Go module using the existing DRUNIX basic sample's chaincode libraries: fabric-chaincode-go/v2 v2.0.0 and fabric-contract-api-go/v2 v2.2.0. Nothing here deploys chaincode, initializes a ledger or implements issuance.

## Public contract

All functions take `contractapi.TransactionContextInterface` first:

- `GetContractInfo(ctx) (*ContractInfo, error)`
- `GetRegisteredProperty(ctx, propertyID string) (*Property, error)`
- `GetOperation(ctx, authorizingMSP, operationID string) (*Operation, error)`
- `RegisterApprovedProperty(ctx, commandJSON string) (*RegistrationResult, error)`

Read info/properties requires Org1MSP or Org2MSP membership. Registration and receipt reads require the approved Org1 User1 MSP, exact Fabric principal and SHA-256 certificate fingerprint. Pins are public, deterministic package policy, not environment-dependent. The sole local-MVP service signer attests application approval; issuer UUID is attribution, not the issuer's personal signature. Fabric validates the signed creator identity; chaincode adds its narrower allowlist. No backend/demo header is trusted or accepted by this contract.

The public User1 certificate in `contract/testdata` is an explicitly allowlisted unit-test fixture, contains no private key, and is not a runtime credential-loading mechanism. Tests fake the already-authenticated client context; they do not test Fabric signature verification. Key custody, private gateway authentication and operator authorization belong to later integration, not this module. Replacing the pinned certificate requires a reviewed policy/package update.

## Command and state

Registration accepts exactly these JSON fields: `command_version` (1), `operation_id`, `property_id`, `issuer_id`, `approval_reference`, `approval_digest`, `approved_supply`, `issue_price_minor`, `currency` (INR). UUIDs must be canonical lowercase RFC variant UUIDs of versions 1–5; property UUID is reused from the application. Approval digest is lowercase SHA-256 hex. No documents, names, addresses or external URLs are accepted.

Commands are limited to 4096 UTF-8 bytes. Unknown, duplicate (including escaped duplicate), missing, null and incorrectly cased fields are rejected, as is trailing data. Quantity must be an integer JSON number from 1 through 9007199254740991; decimal/exponent encodings are rejected. Price is a canonical integer minor-unit string from "1" through "9999999999999999", preserving the backend monetary limit. No floating-point calculations occur.

Fabric composite keys:

- `CreateCompositeKey("property", []string{property_id})`
- `CreateCompositeKey("operation", []string{"Org1MSP", operation_id})`

Version-1 property state stores immutable approved constraints, issuer/approval references, derived registering MSP/principal, registration operation/transaction IDs and proposal timestamp. `approved_supply` is a **lifetime cumulative issuance ceiling**, not minted supply. No holdings, issuance records or supply-utilization records exist yet. M4 must enforce the ceiling across all issuances using an atomically updated supply-utilization key, with MVCC contention.

Version-1 receipts store authorizing identity, function, canonical request digest, property ID, original transaction ID and original registration result. The digest covers typed command fields, function and derived MSP/principal; whitespace/field order do not change it. Identical replay returns the original result without writes or new timestamps. Conflicting operation reuse and registration under a different operation are rejected. Receipts are not deleted.

Errors are deterministic JSON strings with `code` and fixed `message`: INVALID_ARGUMENT, UNSUPPORTED_SCHEMA_VERSION, UNAUTHORIZED, PROPERTY_NOT_FOUND, OPERATION_NOT_FOUND, PROPERTY_ALREADY_REGISTERED, IDEMPOTENCY_CONFLICT, LEDGER_STATE_ERROR. Underlying errors are not returned. Application/gateway HTTP envelopes remain separate.

The result's transaction ID comes from Fabric transaction context. Execution/endorsement results **do not prove commitment**. A proposal timestamp is not trusted wall-clock time. Both writes are in one simulation; an error causes the transaction's write set to be discarded by Fabric. No manual rollback writes occur.

## Validation

Run from this directory:

```sh
go test -mod=readonly ./...
go test -mod=readonly -race ./...
go vet -mod=readonly ./...
```

Tests cover deterministic state and errors, authorization, strict command boundaries, replay/conflict, reads, immutable registration and state-access failures. The isolated stub models Fabric's commit/discard boundary. These tests cannot establish real MVCC, endorsement-policy enforcement, atomic commit or DRUNIX finality. No live network tests, deployment, initialization or ledger writes are part of M3.3a. Await independent review before M3.3b.
