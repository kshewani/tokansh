package contract

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"strings"

	"github.com/hyperledger/fabric-contract-api-go/v2/contractapi"
)

type TransferCommand struct {
	CommandVersion int    `json:"command_version"`
	OperationID    string `json:"operation_id"`
	PropertyID     string `json:"property_id"`
	FromHolderID   string `json:"from_holder_id"`
	ToHolderID     string `json:"to_holder_id"`
	Quantity       int64  `json:"quantity"`
}

type TransferResult struct {
	PropertyID    string `json:"property_id"`
	FromHolderID  string `json:"from_holder_id"`
	ToHolderID    string `json:"to_holder_id"`
	Quantity      int64  `json:"quantity"`
	OperationID   string `json:"operation_id"`
	TransactionID string `json:"transaction_id"`
	FromBalance   int64  `json:"from_balance"`
	ToBalance     int64  `json:"to_balance"`
}

type TransferOperation struct {
	SchemaVersion        int             `json:"schema_version"`
	AuthorizingMSP       string          `json:"authorizing_msp"`
	AuthorizingPrincipal string          `json:"authorizing_principal"`
	Function             string          `json:"function"`
	RequestDigest        string          `json:"request_digest"`
	Command              TransferCommand `json:"command"`
	Result               TransferResult  `json:"result"`
}

// Local MVP: the existing platform authority orchestrates transfers on behalf of
// holder accounts. A from_holder_id is attribution, never caller authentication.
func authorizeTransfer(ctx contractapi.TransactionContextInterface) (string, error) {
	return authorizeRegistration(ctx)
}
func decodeTransferCommand(raw string) (TransferCommand, error) {
	var c TransferCommand
	if len(raw) > maxCommandBytes || strictRecord([]byte(raw), &c) != nil {
		return c, failure("INVALID_ARGUMENT")
	}
	if c.CommandVersion != 1 {
		return c, failure("UNSUPPORTED_SCHEMA_VERSION")
	}
	if !uuidPattern.MatchString(c.OperationID) || !uuidPattern.MatchString(c.PropertyID) || !uuidPattern.MatchString(c.FromHolderID) || !uuidPattern.MatchString(c.ToHolderID) || c.FromHolderID == c.ToHolderID || c.Quantity < 1 || c.Quantity > maxSupply {
		return c, failure("INVALID_ARGUMENT")
	}
	return c, nil
}
func transferDigest(c TransferCommand, principal string) (string, error) {
	b, err := json.Marshal(struct {
		Function  string          `json:"function"`
		MSP       string          `json:"msp"`
		Principal string          `json:"principal"`
		Command   TransferCommand `json:"command"`
	}{"TransferANSH", registrationMSP, principal, c})
	if err != nil {
		return "", failure("LEDGER_STATE_ERROR")
	}
	sum := sha256.Sum256(b)
	return hex.EncodeToString(sum[:]), nil
}

func (s *SmartContract) TransferANSH(ctx contractapi.TransactionContextInterface, commandJSON string) (*TransferResult, error) {
	principal, err := authorizeTransfer(ctx)
	if err != nil {
		return nil, err
	}
	c, err := decodeTransferCommand(commandJSON)
	if err != nil {
		return nil, err
	}
	digest, err := transferDigest(c, principal)
	if err != nil {
		return nil, err
	}
	p, err := s.GetRegisteredProperty(ctx, c.PropertyID)
	if err != nil {
		return nil, err
	}
	state, _, err := issuanceRecords(ctx, p)
	if err != nil {
		return nil, err
	}
	opKey, err := key(ctx, "transfer_operation", registrationMSP, c.OperationID)
	if err != nil {
		return nil, err
	}
	b, err := read(ctx, opKey)
	if err != nil {
		return nil, err
	}
	if b != nil {
		var op TransferOperation
		if strictRecord(b, &op) != nil || op.SchemaVersion != 1 || op.AuthorizingMSP != registrationMSP || op.AuthorizingPrincipal != principal || op.Function != "TransferANSH" {
			return nil, failure("LEDGER_STATE_ERROR")
		}
		encoded, e := json.Marshal(op.Command)
		if e != nil {
			return nil, failure("LEDGER_STATE_ERROR")
		}
		previous, e := decodeTransferCommand(string(encoded))
		if e != nil || previous.OperationID != c.OperationID {
			return nil, failure("LEDGER_STATE_ERROR")
		}
		previousDigest, e := transferDigest(previous, principal)
		if e != nil || previousDigest != op.RequestDigest {
			return nil, failure("LEDGER_STATE_ERROR")
		}
		r := op.Result
		if r.PropertyID != previous.PropertyID || r.FromHolderID != previous.FromHolderID || r.ToHolderID != previous.ToHolderID || r.Quantity != previous.Quantity || r.OperationID != previous.OperationID || strings.TrimSpace(r.TransactionID) == "" || r.FromBalance < 0 || r.ToBalance < previous.Quantity || r.ToBalance > state.CumulativeIssuedSupply || r.FromBalance > state.CumulativeIssuedSupply-r.ToBalance {
			return nil, failure("LEDGER_STATE_ERROR")
		}
		if op.RequestDigest != digest {
			return nil, failure("IDEMPOTENCY_CONFLICT")
		}
		return &op.Result, nil
	}
	from, err := s.GetBalance(ctx, c.PropertyID, c.FromHolderID)
	if err != nil {
		return nil, err
	}
	to, err := s.GetBalance(ctx, c.PropertyID, c.ToHolderID)
	if err != nil {
		return nil, err
	}
	if from.Quantity < c.Quantity {
		return nil, failure("INSUFFICIENT_BALANCE")
	}
	// Both balances are bounded by issued supply. Check their sum by subtraction
	// before adding; the pair is conserved and issuance state is never written.
	if from.Quantity > state.CumulativeIssuedSupply-to.Quantity {
		return nil, failure("LEDGER_STATE_ERROR")
	}
	total, err := addQuantity(to.Quantity, c.Quantity)
	if err != nil {
		return nil, err
	}
	from.Quantity -= c.Quantity
	to.Quantity = total
	txID := ctx.GetStub().GetTxID()
	if strings.TrimSpace(txID) == "" {
		return nil, failure("LEDGER_STATE_ERROR")
	}
	result := TransferResult{c.PropertyID, c.FromHolderID, c.ToHolderID, c.Quantity, c.OperationID, txID, from.Quantity, to.Quantity}
	op := TransferOperation{1, registrationMSP, principal, "TransferANSH", digest, c, result}
	fromKey, err := key(ctx, "balance", c.PropertyID, c.FromHolderID)
	if err != nil {
		return nil, err
	}
	toKey, err := key(ctx, "balance", c.PropertyID, c.ToHolderID)
	if err != nil {
		return nil, err
	}
	// Marshal everything first. Fabric atomically commits or discards all three writes.
	writes := []struct {
		key   string
		value any
	}{{fromKey, from}, {toKey, to}, {opKey, op}}
	values := make([][]byte, len(writes))
	for i, w := range writes {
		values[i], err = json.Marshal(w.value)
		if err != nil {
			return nil, failure("LEDGER_STATE_ERROR")
		}
	}
	for i, w := range writes {
		if err = ctx.GetStub().PutState(w.key, values[i]); err != nil {
			return nil, failure("LEDGER_STATE_ERROR")
		}
	}
	return &result, nil
}
