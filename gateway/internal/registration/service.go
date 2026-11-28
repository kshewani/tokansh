package registration

import (
	"bytes"
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"reflect"
	"regexp"
)

var uuid = regexp.MustCompile(`^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$`)
var digestPattern = regexp.MustCompile(`^[0-9a-f]{64}$`)
var money = regexp.MustCompile(`^[1-9][0-9]{0,15}$`)
var invalid = errors.New("INVALID_REQUEST")

const (
	LifetimeCumulativeIssuanceCeiling = "LIFETIME_CUMULATIVE_ISSUANCE_CEILING"
	OneTimeFullSupplyIssuance         = "ONE_TIME_FULL_SUPPLY_ISSUANCE"
)

// Exact reviewed interfaces: M3, M4.1 and M4.2. Metadata has
// no lifecycle version field; do not accept arbitrary supersets or subsets.
func supportedContractFunctions(functions []string) bool {
	return reflect.DeepEqual(functions, []string{"GetContractInfo", "GetRegisteredProperty", "GetOperation", "RegisterApprovedProperty"}) ||
		reflect.DeepEqual(functions, []string{"GetContractInfo", "GetRegisteredProperty", "GetOperation", "RegisterApprovedProperty", "IssueANSH", "GetIssuanceState", "GetBalance", "GetIssuanceOperation"}) ||
		reflect.DeepEqual(functions, []string{"GetContractInfo", "GetRegisteredProperty", "GetOperation", "RegisterApprovedProperty", "IssueANSH", "GetIssuanceState", "GetBalance", "GetIssuanceOperation", "TransferANSH"})
}

// Exact field names, duplicates, nulls and nested unknown fields fail closed.
func strict(data []byte, target any) error {
	t := reflect.TypeOf(target).Elem()
	d := json.NewDecoder(bytes.NewReader(data))
	tok, e := d.Token()
	if e != nil || tok != json.Delim('{') {
		return invalid
	}
	seen := map[string]bool{}
	for d.More() {
		tok, e = d.Token()
		if e != nil {
			return invalid
		}
		name, ok := tok.(string)
		if !ok || seen[name] {
			return invalid
		}
		seen[name] = true
		var raw json.RawMessage
		if d.Decode(&raw) != nil || bytes.Equal(bytes.TrimSpace(raw), []byte("null")) {
			return invalid
		}
		found := false
		for i := 0; i < t.NumField(); i++ {
			f := t.Field(i)
			if f.Tag.Get("json") == name {
				found = true
				if f.Type.Kind() == reflect.Struct {
					if strict(raw, reflect.New(f.Type).Interface()) != nil {
						return invalid
					}
				}
				break
			}
		}
		if !found {
			return invalid
		}
	}
	if _, e = d.Token(); e != nil {
		return invalid
	}
	if d.Decode(new(any)) != io.EOF || len(seen) != t.NumField() {
		return invalid
	}
	if json.Unmarshal(data, target) != nil {
		return invalid
	}
	return nil
}
func validate(c Command) error {
	if c.CommandVersion != 1 || !uuid.MatchString(c.OperationID) || !uuid.MatchString(c.PropertyID) || !uuid.MatchString(c.IssuerID) || !uuid.MatchString(c.ApprovalReference) || !digestPattern.MatchString(c.ApprovalDigest) || c.ApprovedSupply < 1 || c.ApprovedSupply > 9007199254740991 || !money.MatchString(c.IssuePriceMinor) || c.Currency != "INR" {
		return invalid
	}
	return nil
}
func DecodeCommand(data []byte) (Command, error) {
	var c Command
	if len(data) > 4096 || strict(data, &c) != nil {
		return c, invalid
	}
	return c, validate(c)
}
func commandDigest(c Command) string {
	b, _ := json.Marshal(c)
	s := sha256.Sum256(b)
	return hex.EncodeToString(s[:])
}

type Artifact struct {
	Version       int     `json:"version"`
	Channel       string  `json:"channel"`
	Chaincode     string  `json:"chaincode"`
	Signer        string  `json:"signer"`
	Command       Command `json:"command"`
	RequestDigest string  `json:"request_digest"`
	TransactionID string  `json:"transaction_id"`
	Transaction   []byte  `json:"transaction"`
	Creator       []byte  `json:"creator"`
	MAC           string  `json:"mac"`
}
type Status struct {
	TransactionID string `json:"transaction_id"`
	Code          int32  `json:"code"`
	BlockNumber   uint64 `json:"block_number"`
	Successful    bool   `json:"successful"`
}

// The production adapter and isolated mocks share only this typed surface.
type Ledger interface {
	Read(context.Context, string, ...string) ([]byte, error)
	Prepare(context.Context, Command) (string, []byte, []byte, error)
	Submit(context.Context, Artifact) error
	Status(context.Context, Artifact) (Status, error)
}
type Service struct {
	Ledger  Ledger
	Key     []byte
	Signer  string
}

func (s *Service) mac(a Artifact) string {
	a.MAC = ""
	b, _ := json.Marshal(a)
	m := hmac.New(sha256.New, s.Key)
	m.Write(b)
	return hex.EncodeToString(m.Sum(nil))
}
func (s *Service) Check(a Artifact) error {
	if len(s.Key) < 32 || a.Version != 1 || a.Channel != "mychannel" || a.Chaincode != "tokansh" || (s.Signer != "" && a.Signer != s.Signer) || validate(a.Command) != nil || a.RequestDigest != commandDigest(a.Command) || a.TransactionID == "" || len(a.Transaction) == 0 || len(a.Creator) == 0 || !hmac.Equal([]byte(a.MAC), []byte(s.mac(a))) {
		return invalid
	}
	return validatePrepared(a)
}
func (s *Service) Prepare(ctx context.Context, c Command) (Artifact, error) {
	if validate(c) != nil || len(s.Key) < 32 {
		return Artifact{}, invalid
	}
	id, tx, creator, e := s.Ledger.Prepare(ctx, c)
	if e != nil {
		return Artifact{}, e
	}
	a := Artifact{1, "mychannel", "tokansh", s.Signer, c, commandDigest(c), id, tx, creator, ""}
	a.MAC = s.mac(a)
	if e = s.Check(a); e != nil {
		return Artifact{}, e
	}
	return a, nil
}
func (s *Service) Read(ctx context.Context, function, id string) (any, error) {
	args := []string{}
	switch function {
	case "GetContractInfo":
		if id != "" {
			return nil, invalid
		}
	case "GetRegisteredProperty":
		if !uuid.MatchString(id) {
			return nil, invalid
		}
		args = []string{id}
	case "GetOperation":
		if !uuid.MatchString(id) {
			return nil, invalid
		}
		args = []string{"Org1MSP", id}
	default:
		return nil, invalid
	}
	b, e := s.Ledger.Read(ctx, function, args...)
	if e != nil {
		return nil, classifyEvaluation(e, function)
	}
	switch function {
	case "GetContractInfo":
		var v ContractInfo
		e = strict(b, &v)
		if e != nil || v.Contract != "tokansh" || v.SchemaVersion != 1 || (v.SupplyInterpretation != LifetimeCumulativeIssuanceCeiling && v.SupplyInterpretation != OneTimeFullSupplyIssuance) || !supportedContractFunctions(v.Functions) {
			return nil, invalid
		}
		return v, nil
	case "GetRegisteredProperty":
		var v Property
		e = strict(b, &v)
		if e != nil || v.PropertyID != id || v.SchemaVersion != 1 || validate(Command{1, v.RegistrationOperationID, v.PropertyID, v.IssuerID, v.ApprovalReference, v.ApprovalDigest, v.ApprovedSupply, v.IssuePriceMinor, v.Currency}) != nil || v.RegisteredByMSP != "Org1MSP" || v.RegisteredByPrincipal == "" || v.RegistrationTransactionID == "" || v.ProposalTimestamp == "" {
			return nil, invalid
		}
		return v, nil
	default:
		var v Operation
		e = strict(b, &v)
		if e != nil || v.OperationID != id || v.SchemaVersion != 1 || v.AuthorizingMSP != "Org1MSP" || v.AuthorizingPrincipal == "" || v.Function != "RegisterApprovedProperty" || !digestPattern.MatchString(v.RequestDigest) || !uuid.MatchString(v.PropertyID) || v.OriginalTransactionID == "" || v.Result != (RegistrationResult{v.PropertyID, v.OperationID, v.OriginalTransactionID}) {
			return nil, invalid
		}
		return v, nil
	}
}
