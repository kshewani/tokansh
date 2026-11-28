package contract

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"math"
	"strings"

	"github.com/hyperledger/fabric-contract-api-go/v2/contractapi"
)

type IssuanceCommand struct {
	CommandVersion int    `json:"command_version"`
	OperationID    string `json:"operation_id"`
	PropertyID     string `json:"property_id"`
	Quantity       int64  `json:"quantity"`
}

type IssuanceState struct {
	SchemaVersion             int    `json:"schema_version"`
	PropertyID                string `json:"property_id"`
	IssuerID                  string `json:"issuer_id"`
	ApprovedSupply            int64  `json:"approved_supply"`
	CumulativeIssuedSupply    int64  `json:"cumulative_issued_supply"`
	RemainingIssuanceCapacity int64  `json:"remaining_issuance_capacity"`
}

type Balance struct {
	SchemaVersion int    `json:"schema_version"`
	PropertyID    string `json:"property_id"`
	HolderID      string `json:"holder_id"`
	Quantity      int64  `json:"quantity"`
}

type IssuanceResult struct {
	PropertyID                string `json:"property_id"`
	IssuerID                  string `json:"issuer_id"`
	OperationID               string `json:"operation_id"`
	TransactionID             string `json:"transaction_id"`
	Quantity                  int64  `json:"quantity"`
	CumulativeIssuedSupply    int64  `json:"cumulative_issued_supply"`
	RemainingIssuanceCapacity int64  `json:"remaining_issuance_capacity"`
	IssuerBalance             int64  `json:"issuer_balance"`
}

type IssuanceOperation struct {
	SchemaVersion         int            `json:"schema_version"`
	OperationID           string         `json:"operation_id"`
	AuthorizingMSP        string         `json:"authorizing_msp"`
	AuthorizingPrincipal  string         `json:"authorizing_principal"`
	Function              string         `json:"function"`
	RequestDigest         string         `json:"request_digest"`
	PropertyID            string         `json:"property_id"`
	IssuerID              string         `json:"issuer_id"`
	Quantity              int64          `json:"quantity"`
	OriginalTransactionID string         `json:"original_transaction_id"`
	Result                IssuanceResult `json:"result"`
}

// Kept separate so future issuance policies cannot silently change registration.
func authorizeIssuance(ctx contractapi.TransactionContextInterface) (string, error) {
	return authorizeRegistration(ctx)
}

func decodeIssuanceCommand(raw string) (IssuanceCommand, error) {
	var c IssuanceCommand
	// Reuse exact, recursive field validation (including duplicates and case).
	if len(raw) > maxCommandBytes || strictRecord([]byte(raw), &c) != nil {
		return c, failure("INVALID_ARGUMENT")
	}
	if c.CommandVersion != 1 {
		return c, failure("UNSUPPORTED_SCHEMA_VERSION")
	}
	if !uuidPattern.MatchString(c.OperationID) || !uuidPattern.MatchString(c.PropertyID) || c.Quantity < 1 || c.Quantity > maxSupply {
		return c, failure("INVALID_ARGUMENT")
	}
	return c, nil
}

func issuanceDigest(c IssuanceCommand, principal string) (string, error) {
	b, err := json.Marshal(struct {
		Function  string          `json:"function"`
		MSP       string          `json:"msp"`
		Principal string          `json:"principal"`
		Command   IssuanceCommand `json:"command"`
	}{"IssueANSH", registrationMSP, principal, c})
	if err != nil {
		return "", failure("LEDGER_STATE_ERROR")
	}
	sum := sha256.Sum256(b)
	return hex.EncodeToString(sum[:]), nil
}

// Both counters are bounded before addition, independently of the supply check.
func addQuantity(current, quantity int64) (int64, error) {
	if current < 0 || quantity < 1 || current > math.MaxInt64-quantity {
		return 0, failure("LEDGER_STATE_ERROR")
	}
	return current + quantity, nil
}

// A registered M3 property needs no migration: two absent keys mean zero issued.
// A partially missing pair is corruption, never a reason to initialize again.
func issuanceRecords(ctx contractapi.TransactionContextInterface, p *Property) (*IssuanceState, *Balance, error) {
	sk, err := key(ctx, "issuance", p.PropertyID)
	if err != nil {
		return nil, nil, err
	}
	bk, err := key(ctx, "balance", p.PropertyID, p.IssuerID)
	if err != nil {
		return nil, nil, err
	}
	sb, err := read(ctx, sk)
	if err != nil {
		return nil, nil, err
	}
	bb, err := read(ctx, bk)
	if err != nil {
		return nil, nil, err
	}
	state := &IssuanceState{SchemaVersion: 1, PropertyID: p.PropertyID, IssuerID: p.IssuerID, ApprovedSupply: p.ApprovedSupply, RemainingIssuanceCapacity: p.ApprovedSupply}
	balance := &Balance{SchemaVersion: 1, PropertyID: p.PropertyID, HolderID: p.IssuerID}
	if sb == nil && bb == nil {
		return state, balance, nil
	}
	if sb == nil || bb == nil || strictRecord(sb, state) != nil || strictRecord(bb, balance) != nil {
		return nil, nil, failure("LEDGER_STATE_ERROR")
	}
	if state.SchemaVersion != 1 || state.PropertyID != p.PropertyID || state.IssuerID != p.IssuerID || state.ApprovedSupply != p.ApprovedSupply || state.CumulativeIssuedSupply < 1 || state.CumulativeIssuedSupply > p.ApprovedSupply || state.RemainingIssuanceCapacity != p.ApprovedSupply-state.CumulativeIssuedSupply {
		return nil, nil, failure("LEDGER_STATE_ERROR")
	}
	// Transfers can reduce issuer inventory; no holder can exceed lifetime issuance.
	if balance.SchemaVersion != 1 || balance.PropertyID != p.PropertyID || balance.HolderID != p.IssuerID || (balance.Quantity < 0 || balance.Quantity > state.CumulativeIssuedSupply) {
		return nil, nil, failure("LEDGER_STATE_ERROR")
	}
	return state, balance, nil
}

func (s *SmartContract) GetIssuanceState(ctx contractapi.TransactionContextInterface, propertyID string) (*IssuanceState, error) {
	p, err := s.GetRegisteredProperty(ctx, propertyID)
	if err != nil {
		return nil, err
	}
	state, _, err := issuanceRecords(ctx, p)
	return state, err
}

func (s *SmartContract) GetBalance(ctx contractapi.TransactionContextInterface, propertyID, holderID string) (*Balance, error) {
	if err := authorizeRead(ctx); err != nil {
		return nil, err
	}
	if !uuidPattern.MatchString(holderID) {
		return nil, failure("INVALID_ARGUMENT")
	}
	p, err := s.GetRegisteredProperty(ctx, propertyID)
	if err != nil {
		return nil, err
	}
	state, issuer, err := issuanceRecords(ctx, p)
	if err != nil {
		return nil, err
	}
	if holderID == p.IssuerID {
		return issuer, nil
	}
	k, err := key(ctx, "balance", propertyID, holderID)
	if err != nil {
		return nil, err
	}
	b, err := read(ctx, k)
	if err != nil {
		return nil, err
	}
	balance := &Balance{SchemaVersion: 1, PropertyID: propertyID, HolderID: holderID}
	// An absent holder account has zero units; persisted balances stay bounded.
	if b != nil && (strictRecord(b, balance) != nil || balance.SchemaVersion != 1 || balance.PropertyID != propertyID || balance.HolderID != holderID || (balance.Quantity < 0 || balance.Quantity > state.CumulativeIssuedSupply)) {
		return nil, failure("LEDGER_STATE_ERROR")
	}
	return balance, nil
}

func (s *SmartContract) GetIssuanceOperation(ctx contractapi.TransactionContextInterface, operationID string) (*IssuanceOperation, error) {
	principal, err := authorizeIssuance(ctx)
	if err != nil {
		return nil, err
	}
	if !uuidPattern.MatchString(operationID) {
		return nil, failure("INVALID_ARGUMENT")
	}
	k, err := key(ctx, "issuance_operation", registrationMSP, operationID)
	if err != nil {
		return nil, err
	}
	b, err := read(ctx, k)
	if err != nil {
		return nil, err
	}
	if b == nil {
		return nil, failure("OPERATION_NOT_FOUND")
	}
	var op IssuanceOperation
	if strictRecord(b, &op) != nil || op.SchemaVersion != 1 || op.OperationID != operationID || op.AuthorizingMSP != registrationMSP || op.AuthorizingPrincipal != principal || op.Function != "IssueANSH" || !digestPattern.MatchString(op.RequestDigest) || strings.TrimSpace(op.OriginalTransactionID) == "" {
		return nil, failure("LEDGER_STATE_ERROR")
	}
	c := IssuanceCommand{1, op.OperationID, op.PropertyID, op.Quantity}
	encoded, err := json.Marshal(c)
	if err != nil {
		return nil, failure("LEDGER_STATE_ERROR")
	}
	if _, err := decodeIssuanceCommand(string(encoded)); err != nil {
		return nil, failure("LEDGER_STATE_ERROR")
	}
	digest, err := issuanceDigest(c, principal)
	if err != nil || digest != op.RequestDigest {
		return nil, failure("LEDGER_STATE_ERROR")
	}
	p, err := s.GetRegisteredProperty(ctx, op.PropertyID)
	if err != nil {
		return nil, failure("LEDGER_STATE_ERROR")
	}
	r := op.Result
	if op.IssuerID != p.IssuerID || r.PropertyID != op.PropertyID || r.IssuerID != op.IssuerID || r.OperationID != operationID || r.TransactionID != op.OriginalTransactionID || r.Quantity != op.Quantity || r.CumulativeIssuedSupply < op.Quantity || r.CumulativeIssuedSupply > p.ApprovedSupply || r.RemainingIssuanceCapacity != p.ApprovedSupply-r.CumulativeIssuedSupply || (r.IssuerBalance < r.Quantity || r.IssuerBalance > r.CumulativeIssuedSupply) {
		return nil, failure("LEDGER_STATE_ERROR")
	}
	state, _, err := issuanceRecords(ctx, p)
	if err != nil || state.CumulativeIssuedSupply < r.CumulativeIssuedSupply {
		return nil, failure("LEDGER_STATE_ERROR")
	}
	return &op, nil
}

func (s *SmartContract) IssueANSH(ctx contractapi.TransactionContextInterface, commandJSON string) (*IssuanceResult, error) {
	principal, err := authorizeIssuance(ctx)
	if err != nil {
		return nil, err
	}
	c, err := decodeIssuanceCommand(commandJSON)
	if err != nil {
		return nil, err
	}
	digest, err := issuanceDigest(c, principal)
	if err != nil {
		return nil, err
	}
	ok, err := key(ctx, "issuance_operation", registrationMSP, c.OperationID)
	if err != nil {
		return nil, err
	}
	b, err := read(ctx, ok)
	if err != nil {
		return nil, err
	}
	if b != nil {
		op, err := s.GetIssuanceOperation(ctx, c.OperationID)
		if err != nil {
			return nil, err
		}
		if op.RequestDigest != digest {
			return nil, failure("IDEMPOTENCY_CONFLICT")
		}
		return &op.Result, nil
	}
	p, err := s.GetRegisteredProperty(ctx, c.PropertyID)
	if err != nil {
		return nil, err
	}
	state, balance, err := issuanceRecords(ctx, p)
	if err != nil {
		return nil, err
	}
	// Idempotency was resolved before loading issuance state. A new operation
	// cannot mint against a property that already has persisted issuance.
	if state.CumulativeIssuedSupply != 0 {
		return nil, failure("ISSUANCE_ALREADY_COMPLETED")
	}
	if c.Quantity > p.ApprovedSupply {
		return nil, failure("ISSUANCE_LIMIT_EXCEEDED")
	}
	if c.Quantity != p.ApprovedSupply {
		return nil, failure("INITIAL_ISSUANCE_MUST_MATCH_APPROVED_SUPPLY")
	}
	if c.Quantity > state.RemainingIssuanceCapacity {
		return nil, failure("ISSUANCE_LIMIT_EXCEEDED")
	}
	issued, err := addQuantity(state.CumulativeIssuedSupply, c.Quantity)
	if err != nil {
		return nil, err
	}
	owned, err := addQuantity(balance.Quantity, c.Quantity)
	if err != nil {
		return nil, err
	}
	txID := ctx.GetStub().GetTxID()
	if strings.TrimSpace(txID) == "" {
		return nil, failure("LEDGER_STATE_ERROR")
	}
	state.CumulativeIssuedSupply = issued
	state.RemainingIssuanceCapacity = p.ApprovedSupply - issued
	balance.Quantity = owned
	result := IssuanceResult{p.PropertyID, p.IssuerID, c.OperationID, txID, c.Quantity, issued, state.RemainingIssuanceCapacity, owned}
	op := IssuanceOperation{1, c.OperationID, registrationMSP, principal, "IssueANSH", digest, p.PropertyID, p.IssuerID, c.Quantity, txID, result}
	sk, err := key(ctx, "issuance", p.PropertyID)
	if err != nil {
		return nil, err
	}
	bk, err := key(ctx, "balance", p.PropertyID, p.IssuerID)
	if err != nil {
		return nil, err
	}
	// Marshal every record before the first write. All writes share one Fabric
	// simulation; errors discard its write set, without compensating mutations.
	records := []struct {
		key   string
		value any
	}{{sk, state}, {bk, balance}, {ok, op}}
	values := make([][]byte, len(records))
	for i, record := range records {
		values[i], err = json.Marshal(record.value)
		if err != nil {
			return nil, failure("LEDGER_STATE_ERROR")
		}
	}
	for i, record := range records {
		if err := ctx.GetStub().PutState(record.key, values[i]); err != nil {
			return nil, failure("LEDGER_STATE_ERROR")
		}
	}
	return &result, nil
}
