package registration

import (
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"strings"
)

const maxIssuance int64 = 9007199254740991

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

// Separate artifact type prevents registration/issuance command confusion.
type IssuanceArtifact struct {
	Version       int             `json:"version"`
	Channel       string          `json:"channel"`
	Chaincode     string          `json:"chaincode"`
	Signer        string          `json:"signer"`
	Function      string          `json:"function"`
	Command       IssuanceCommand `json:"command"`
	RequestDigest string          `json:"request_digest"`
	TransactionID string          `json:"transaction_id"`
	Transaction   []byte          `json:"transaction"`
	Creator       []byte          `json:"creator"`
	MAC           string          `json:"mac"`
}

type IssuanceLedger interface {
	PrepareIssuance(context.Context, IssuanceCommand) (string, []byte, []byte, error)
}

func validateIssuance(c IssuanceCommand) error {
	if c.CommandVersion != 1 || !uuid.MatchString(c.OperationID) || !uuid.MatchString(c.PropertyID) || c.Quantity < 1 || c.Quantity > maxIssuance {
		return invalid
	}
	return nil
}
func DecodeIssuanceCommand(b []byte) (IssuanceCommand, error) {
	var c IssuanceCommand
	if len(b) > 4096 || strict(b, &c) != nil {
		return c, invalid
	}
	return c, validateIssuance(c)
}
func issuanceCommandDigest(c IssuanceCommand) string {
	b, _ := json.Marshal(c)
	h := sha256.Sum256(b)
	return hex.EncodeToString(h[:])
}
func (s *Service) issuanceMAC(a IssuanceArtifact) string {
	a.MAC = ""
	b, _ := json.Marshal(a)
	m := hmac.New(sha256.New, s.Key)
	m.Write(b)
	return hex.EncodeToString(m.Sum(nil))
}
func issuanceEnvelope(a IssuanceArtifact) Artifact {
	return Artifact{Channel: a.Channel, Chaincode: a.Chaincode, Signer: a.Signer, TransactionID: a.TransactionID, Transaction: a.Transaction, Creator: a.Creator}
}
func (s *Service) CheckIssuance(a IssuanceArtifact) error {
	if len(s.Key) != 32 || a.Version != 1 || a.Channel != "mychannel" || a.Chaincode != "tokansh" || a.Signer != Signer || a.Function != "IssueANSH" || validateIssuance(a.Command) != nil || a.RequestDigest != issuanceCommandDigest(a.Command) || strings.TrimSpace(a.TransactionID) == "" || len(a.Transaction) == 0 || len(a.Creator) == 0 || !hmac.Equal([]byte(a.MAC), []byte(s.issuanceMAC(a))) {
		return invalid
	}
	b, e := json.Marshal(a.Command)
	if e != nil {
		return invalid
	}
	return validatePreparedCommand(issuanceEnvelope(a), "IssueANSH", b)
}
func (s *Service) PrepareIssuance(ctx context.Context, c IssuanceCommand) (IssuanceArtifact, error) {
	if validateIssuance(c) != nil || len(s.Key) != 32 {
		return IssuanceArtifact{}, invalid
	}
	ledger, ok := s.Ledger.(IssuanceLedger)
	if !ok {
		return IssuanceArtifact{}, invalid
	}
	id, tx, creator, e := ledger.PrepareIssuance(ctx, c)
	if e != nil {
		return IssuanceArtifact{}, classifyIssuancePreparation(e)
	}
	a := IssuanceArtifact{1, "mychannel", "tokansh", Signer, "IssueANSH", c, issuanceCommandDigest(c), id, tx, creator, ""}
	a.MAC = s.issuanceMAC(a)
	if e = s.CheckIssuance(a); e != nil {
		return IssuanceArtifact{}, e
	}
	return a, nil
}

func (s *Service) ReadIssuance(ctx context.Context, function string, ids ...string) (any, error) {
	expected := 1
	if function == "GetBalance" {
		expected = 2
	}
	if function != "GetBalance" && function != "GetIssuanceState" && function != "GetIssuanceOperation" {
		return nil, invalid
	}
	if len(ids) != expected {
		return nil, invalid
	}
	for _, id := range ids {
		if !uuid.MatchString(id) {
			return nil, invalid
		}
	}
	b, e := s.Ledger.Read(ctx, function, ids...)
	if e != nil {
		return nil, classifyEvaluation(e, function)
	}
	switch function {
	case "GetIssuanceState":
		var v IssuanceState
		if strict(b, &v) != nil || v.SchemaVersion != 1 || v.PropertyID != ids[0] || !uuid.MatchString(v.IssuerID) || v.ApprovedSupply < 1 || v.ApprovedSupply > maxIssuance || v.CumulativeIssuedSupply < 0 || v.CumulativeIssuedSupply > v.ApprovedSupply || v.RemainingIssuanceCapacity != v.ApprovedSupply-v.CumulativeIssuedSupply {
			return nil, invalid
		}
		return v, nil
	case "GetBalance":
		var v Balance
		if strict(b, &v) != nil || v.SchemaVersion != 1 || v.PropertyID != ids[0] || v.HolderID != ids[1] || v.Quantity < 0 || v.Quantity > maxIssuance {
			return nil, invalid
		}
		return v, nil
	default:
		var v IssuanceOperation
		if strict(b, &v) != nil || v.SchemaVersion != 1 || v.OperationID != ids[0] || v.AuthorizingMSP != "Org1MSP" || strings.TrimSpace(v.AuthorizingPrincipal) == "" || v.Function != "IssueANSH" || !digestPattern.MatchString(v.RequestDigest) || !uuid.MatchString(v.IssuerID) || strings.TrimSpace(v.OriginalTransactionID) == "" || validateIssuance(IssuanceCommand{1, v.OperationID, v.PropertyID, v.Quantity}) != nil {
			return nil, invalid
		}
		r := v.Result
		if r.PropertyID != v.PropertyID || r.OperationID != v.OperationID || r.IssuerID != v.IssuerID || r.TransactionID != v.OriginalTransactionID || r.Quantity != v.Quantity || r.CumulativeIssuedSupply < v.Quantity || r.CumulativeIssuedSupply > maxIssuance || r.RemainingIssuanceCapacity < 0 || r.RemainingIssuanceCapacity > maxIssuance-r.CumulativeIssuedSupply || r.IssuerBalance != r.CumulativeIssuedSupply {
			return nil, invalid
		}
		// Match chaincode's function/MSP/principal-bound operation digest.
		encoded, e := json.Marshal(struct {
			Function  string          `json:"function"`
			MSP       string          `json:"msp"`
			Principal string          `json:"principal"`
			Command   IssuanceCommand `json:"command"`
		}{"IssueANSH", "Org1MSP", v.AuthorizingPrincipal, IssuanceCommand{1, v.OperationID, v.PropertyID, v.Quantity}})
		if e != nil {
			return nil, invalid
		}
		hash := sha256.Sum256(encoded)
		if hex.EncodeToString(hash[:]) != v.RequestDigest {
			return nil, invalid
		}
		return v, nil
	}
}
