// Package contract implements the approved-property registry and ANSH issuance.
package contract

import (
	"bytes"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"io"
	"reflect"
	"regexp"
	"strconv"
	"strings"
	"time"
	"unicode/utf8"

	"github.com/hyperledger/fabric-contract-api-go/v2/contractapi"
)

const (
	maxSupply               int64 = 9007199254740991
	maxPrice                int64 = 9999999999999999
	maxCommandBytes               = 4096
	registrationMSP               = "Org1MSP"
	registrationDN                = "x509::CN=User1@org1.example.com,OU=client,L=San Francisco,ST=California,C=US::CN=ca.org1.example.com,O=org1.example.com,L=San Francisco,ST=California,C=US"
	registrationFingerprint       = "54690b215edf0e4065332b7b3bd6387dad86f6a36de54b2c49b945309abac59c"
)

var (
	uuidPattern   = regexp.MustCompile(`^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$`)
	digestPattern = regexp.MustCompile(`^[0-9a-f]{64}$`)
	moneyPattern  = regexp.MustCompile(`^[1-9][0-9]{0,15}$`)
)

type SmartContract struct{ contractapi.Contract }

type Command struct {
	CommandVersion    int    `json:"command_version"`
	OperationID       string `json:"operation_id"`
	PropertyID        string `json:"property_id"`
	IssuerID          string `json:"issuer_id"`
	ApprovalReference string `json:"approval_reference"`
	ApprovalDigest    string `json:"approval_digest"`
	ApprovedSupply    int64  `json:"approved_supply"`
	IssuePriceMinor   string `json:"issue_price_minor"`
	Currency          string `json:"currency"`
}

type Property struct {
	SchemaVersion             int    `json:"schema_version"`
	PropertyID                string `json:"property_id"`
	IssuerID                  string `json:"issuer_id"`
	ApprovalReference         string `json:"approval_reference"`
	ApprovalDigest            string `json:"approval_digest"`
	ApprovedSupply            int64  `json:"approved_supply"`
	IssuePriceMinor           string `json:"issue_price_minor"`
	Currency                  string `json:"currency"`
	RegisteredByMSP           string `json:"registered_by_msp"`
	RegisteredByPrincipal     string `json:"registered_by_principal"`
	RegistrationOperationID   string `json:"registration_operation_id"`
	RegistrationTransactionID string `json:"registration_transaction_id"`
	ProposalTimestamp         string `json:"proposal_timestamp"`
}

type RegistrationResult struct {
	PropertyID    string `json:"property_id"`
	OperationID   string `json:"operation_id"`
	TransactionID string `json:"transaction_id"`
}

type Operation struct {
	SchemaVersion         int                `json:"schema_version"`
	OperationID           string             `json:"operation_id"`
	AuthorizingMSP        string             `json:"authorizing_msp"`
	AuthorizingPrincipal  string             `json:"authorizing_principal"`
	Function              string             `json:"function"`
	RequestDigest         string             `json:"request_digest"`
	PropertyID            string             `json:"property_id"`
	OriginalTransactionID string             `json:"original_transaction_id"`
	Result                RegistrationResult `json:"result"`
}

type ContractInfo struct {
	Contract             string   `json:"contract"`
	SchemaVersion        int      `json:"schema_version"`
	Functions            []string `json:"functions"`
	SupplyInterpretation string   `json:"supply_interpretation"`
}

type contractError struct {
	Code    string `json:"code"`
	Message string `json:"message"`
}

func (e contractError) Error() string {
	b, err := json.Marshal(e)
	if err != nil {
		return `{"code":"LEDGER_STATE_ERROR","message":"Ledger state could not be processed."}`
	}
	return string(b)
}
func failure(code string) error {
	messages := map[string]string{
		"INVALID_ARGUMENT":                            "Command or identifier is invalid.",
		"UNSUPPORTED_SCHEMA_VERSION":                  "Command version is unsupported.",
		"UNAUTHORIZED":                                "Identity is not authorized.",
		"PROPERTY_NOT_FOUND":                          "Registered property was not found.",
		"OPERATION_NOT_FOUND":                         "Operation was not found.",
		"PROPERTY_ALREADY_REGISTERED":                 "Property registration is immutable.",
		"IDEMPOTENCY_CONFLICT":                        "Operation was already used with different parameters.",
		"LEDGER_STATE_ERROR":                          "Ledger state could not be processed.",
		"ISSUANCE_LIMIT_EXCEEDED":                     "Requested issuance exceeds approved supply.",
		"INITIAL_ISSUANCE_MUST_MATCH_APPROVED_SUPPLY": "Initial issuance must equal approved supply.",
		"ISSUANCE_ALREADY_COMPLETED":                  "This property has already completed issuance.",
		"INSUFFICIENT_BALANCE":                        "Sender has insufficient ANSH.",
	}
	return contractError{code, messages[code]}
}

func registrationPrincipal() string { return base64.StdEncoding.EncodeToString([]byte(registrationDN)) }
func authorizeRead(ctx contractapi.TransactionContextInterface) error {
	msp, err := ctx.GetClientIdentity().GetMSPID()
	if err != nil || (msp != "Org1MSP" && msp != "Org2MSP") {
		return failure("UNAUTHORIZED")
	}
	return nil
}
func authorizeRegistration(ctx contractapi.TransactionContextInterface) (string, error) {
	id := ctx.GetClientIdentity()
	msp, err := id.GetMSPID()
	if err != nil || msp != registrationMSP {
		return "", failure("UNAUTHORIZED")
	}
	principal, err := id.GetID()
	if err != nil || principal != registrationPrincipal() {
		return "", failure("UNAUTHORIZED")
	}
	cert, err := id.GetX509Certificate()
	if err != nil || cert == nil {
		return "", failure("UNAUTHORIZED")
	}
	sum := sha256.Sum256(cert.Raw)
	if hex.EncodeToString(sum[:]) != registrationFingerprint {
		return "", failure("UNAUTHORIZED")
	}
	return principal, nil
}

// decodeCommand requires exact field spelling and rejects duplicates, nulls and trailing data.
func decodeCommand(raw string) (Command, error) {
	var c Command
	if len(raw) > maxCommandBytes || !utf8.ValidString(raw) {
		return c, failure("INVALID_ARGUMENT")
	}
	d := json.NewDecoder(bytes.NewBufferString(raw))
	token, err := d.Token()
	if err != nil || token != json.Delim('{') {
		return c, failure("INVALID_ARGUMENT")
	}
	fields := map[string]json.RawMessage{}
	for d.More() {
		token, err := d.Token()
		if err != nil {
			return c, failure("INVALID_ARGUMENT")
		}
		name, ok := token.(string)
		if !ok {
			return c, failure("INVALID_ARGUMENT")
		}
		if _, exists := fields[name]; exists {
			return c, failure("INVALID_ARGUMENT")
		}
		var value json.RawMessage
		if err := d.Decode(&value); err != nil || bytes.Equal(bytes.TrimSpace(value), []byte("null")) {
			return c, failure("INVALID_ARGUMENT")
		}
		fields[name] = value
	}
	if _, err := d.Token(); err != nil {
		return c, failure("INVALID_ARGUMENT")
	}
	if err := d.Decode(new(any)); err != io.EOF {
		return c, failure("INVALID_ARGUMENT")
	}
	expected := []string{"command_version", "operation_id", "property_id", "issuer_id", "approval_reference", "approval_digest", "approved_supply", "issue_price_minor", "currency"}
	if len(fields) != len(expected) {
		return c, failure("INVALID_ARGUMENT")
	}
	for _, name := range expected {
		if _, ok := fields[name]; !ok {
			return c, failure("INVALID_ARGUMENT")
		}
	}
	if err := json.Unmarshal([]byte(raw), &c); err != nil {
		return c, failure("INVALID_ARGUMENT")
	}
	if c.CommandVersion != 1 {
		return c, failure("UNSUPPORTED_SCHEMA_VERSION")
	}
	if !uuidPattern.MatchString(c.OperationID) || !uuidPattern.MatchString(c.PropertyID) || !uuidPattern.MatchString(c.IssuerID) || !uuidPattern.MatchString(c.ApprovalReference) || !digestPattern.MatchString(c.ApprovalDigest) || c.ApprovedSupply < 1 || c.ApprovedSupply > maxSupply || c.Currency != "INR" || !moneyPattern.MatchString(c.IssuePriceMinor) {
		return c, failure("INVALID_ARGUMENT")
	}
	amount, err := strconv.ParseInt(c.IssuePriceMinor, 10, 64)
	if err != nil || amount > maxPrice {
		return c, failure("INVALID_ARGUMENT")
	}
	return c, nil
}

// strictRecord validates exact keys recursively, including nested result objects.
// encoding/json alone accepts duplicate keys and case-insensitive field matches.
func strictRecord(data []byte, target any) error {
	if !utf8.Valid(data) {
		return failure("LEDGER_STATE_ERROR")
	}
	if err := recordShape(data, reflect.TypeOf(target).Elem()); err != nil {
		return failure("LEDGER_STATE_ERROR")
	}
	if err := json.Unmarshal(data, target); err != nil {
		return failure("LEDGER_STATE_ERROR")
	}
	return nil
}
func recordShape(data []byte, typ reflect.Type) error {
	d := json.NewDecoder(bytes.NewReader(data))
	token, err := d.Token()
	if err != nil || token != json.Delim('{') {
		return failure("LEDGER_STATE_ERROR")
	}
	seen := map[string]bool{}
	for d.More() {
		token, err := d.Token()
		if err != nil {
			return err
		}
		name, ok := token.(string)
		if !ok || seen[name] {
			return failure("LEDGER_STATE_ERROR")
		}
		seen[name] = true
		var value json.RawMessage
		if err := d.Decode(&value); err != nil {
			return err
		}
		if bytes.Equal(bytes.TrimSpace(value), []byte("null")) {
			return failure("LEDGER_STATE_ERROR")
		}
		found := false
		for i := 0; i < typ.NumField(); i++ {
			field := typ.Field(i)
			if field.Tag.Get("json") == name {
				found = true
				if field.Type.Kind() == reflect.Struct {
					if err := recordShape(value, field.Type); err != nil {
						return err
					}
				}
				break
			}
		}
		if !found {
			return failure("LEDGER_STATE_ERROR")
		}
	}
	if _, err := d.Token(); err != nil {
		return err
	}
	if len(seen) != typ.NumField() {
		return failure("LEDGER_STATE_ERROR")
	}
	if err := d.Decode(new(any)); err != io.EOF {
		return failure("LEDGER_STATE_ERROR")
	}
	return nil
}
func propertyCommand(p Property) Command {
	return Command{1, p.RegistrationOperationID, p.PropertyID, p.IssuerID, p.ApprovalReference, p.ApprovalDigest, p.ApprovedSupply, p.IssuePriceMinor, p.Currency}
}
func requestDigest(c Command, principal string) (string, error) {
	normalized, err := json.Marshal(struct {
		Function  string  `json:"function"`
		MSP       string  `json:"msp"`
		Principal string  `json:"principal"`
		Command   Command `json:"command"`
	}{"RegisterApprovedProperty", registrationMSP, principal, c})
	if err != nil {
		return "", failure("LEDGER_STATE_ERROR")
	}
	sum := sha256.Sum256(normalized)
	return hex.EncodeToString(sum[:]), nil
}
func validProperty(p Property) bool {
	command, err := json.Marshal(propertyCommand(p))
	if err != nil {
		return false
	}
	if _, err := decodeCommand(string(command)); err != nil {
		return false
	}
	timestamp, err := time.Parse(time.RFC3339Nano, p.ProposalTimestamp)
	return p.SchemaVersion == 1 && p.RegisteredByMSP == registrationMSP && p.RegisteredByPrincipal == registrationPrincipal() && strings.TrimSpace(p.RegistrationTransactionID) != "" && err == nil && timestamp.UTC().Format(time.RFC3339Nano) == p.ProposalTimestamp
}

func key(ctx contractapi.TransactionContextInterface, object string, attrs ...string) (string, error) {
	k, err := ctx.GetStub().CreateCompositeKey(object, attrs)
	if err != nil {
		return "", failure("LEDGER_STATE_ERROR")
	}
	return k, nil
}
func read(ctx contractapi.TransactionContextInterface, k string) ([]byte, error) {
	b, err := ctx.GetStub().GetState(k)
	if err != nil {
		return nil, failure("LEDGER_STATE_ERROR")
	}
	return b, nil
}

func (s *SmartContract) GetContractInfo(ctx contractapi.TransactionContextInterface) (*ContractInfo, error) {
	if err := authorizeRead(ctx); err != nil {
		return nil, err
	}
	return &ContractInfo{"tokansh", 1, []string{"GetContractInfo", "GetRegisteredProperty", "GetOperation", "RegisterApprovedProperty", "IssueANSH", "GetIssuanceState", "GetBalance", "GetIssuanceOperation", "TransferANSH"}, "ONE_TIME_FULL_SUPPLY_ISSUANCE"}, nil
}
func (s *SmartContract) GetRegisteredProperty(ctx contractapi.TransactionContextInterface, propertyID string) (*Property, error) {
	if err := authorizeRead(ctx); err != nil {
		return nil, err
	}
	if !uuidPattern.MatchString(propertyID) {
		return nil, failure("INVALID_ARGUMENT")
	}
	k, err := key(ctx, "property", propertyID)
	if err != nil {
		return nil, err
	}
	b, err := read(ctx, k)
	if err != nil {
		return nil, err
	}
	if b == nil {
		return nil, failure("PROPERTY_NOT_FOUND")
	}
	var p Property
	if err := strictRecord(b, &p); err != nil || !validProperty(p) || p.PropertyID != propertyID {
		return nil, failure("LEDGER_STATE_ERROR")
	}
	return &p, nil
}
func (s *SmartContract) GetOperation(ctx contractapi.TransactionContextInterface, authorizingMSP, operationID string) (*Operation, error) {
	principal, err := authorizeRegistration(ctx)
	if err != nil {
		return nil, err
	}
	if authorizingMSP != registrationMSP {
		return nil, failure("UNAUTHORIZED")
	}
	if !uuidPattern.MatchString(operationID) {
		return nil, failure("INVALID_ARGUMENT")
	}
	k, err := key(ctx, "operation", authorizingMSP, operationID)
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
	var op Operation
	if err := strictRecord(b, &op); err != nil || !digestPattern.MatchString(op.RequestDigest) || !uuidPattern.MatchString(op.PropertyID) || strings.TrimSpace(op.OriginalTransactionID) == "" || op.SchemaVersion != 1 || op.OperationID != operationID || op.AuthorizingMSP != authorizingMSP || op.AuthorizingPrincipal != principal || op.Function != "RegisterApprovedProperty" || op.Result.OperationID != operationID || op.Result.PropertyID != op.PropertyID || op.Result.TransactionID != op.OriginalTransactionID {
		return nil, failure("LEDGER_STATE_ERROR")
	}
	p, err := s.GetRegisteredProperty(ctx, op.PropertyID)
	if err != nil || p.RegistrationOperationID != operationID || p.RegistrationTransactionID != op.OriginalTransactionID {
		return nil, failure("LEDGER_STATE_ERROR")
	}
	digest, err := requestDigest(propertyCommand(*p), principal)
	if err != nil || digest != op.RequestDigest {
		return nil, failure("LEDGER_STATE_ERROR")
	}
	return &op, nil
}
func (s *SmartContract) RegisterApprovedProperty(ctx contractapi.TransactionContextInterface, commandJSON string) (*RegistrationResult, error) {
	principal, err := authorizeRegistration(ctx)
	if err != nil {
		return nil, err
	}
	c, err := decodeCommand(commandJSON)
	if err != nil {
		return nil, err
	}
	digest, err := requestDigest(c, principal)
	if err != nil {
		return nil, err
	}
	operationKey, err := key(ctx, "operation", registrationMSP, c.OperationID)
	if err != nil {
		return nil, err
	}
	existing, err := read(ctx, operationKey)
	if err != nil {
		return nil, err
	}
	if existing != nil {
		op, err := s.GetOperation(ctx, registrationMSP, c.OperationID)
		if err != nil {
			return nil, err
		}
		if op.RequestDigest != digest {
			return nil, failure("IDEMPOTENCY_CONFLICT")
		}
		return &op.Result, nil
	}
	propertyKey, err := key(ctx, "property", c.PropertyID)
	if err != nil {
		return nil, err
	}
	existing, err = read(ctx, propertyKey)
	if err != nil {
		return nil, err
	}
	if existing != nil {
		return nil, failure("PROPERTY_ALREADY_REGISTERED")
	}
	timestamp, err := ctx.GetStub().GetTxTimestamp()
	if err != nil || timestamp == nil || timestamp.CheckValid() != nil || ctx.GetStub().GetTxID() == "" {
		return nil, failure("LEDGER_STATE_ERROR")
	}
	result := RegistrationResult{c.PropertyID, c.OperationID, ctx.GetStub().GetTxID()}
	p := Property{1, c.PropertyID, c.IssuerID, c.ApprovalReference, c.ApprovalDigest, c.ApprovedSupply, c.IssuePriceMinor, c.Currency, registrationMSP, principal, c.OperationID, result.TransactionID, timestamp.AsTime().UTC().Format(time.RFC3339Nano)}
	op := Operation{1, c.OperationID, registrationMSP, principal, "RegisterApprovedProperty", digest, c.PropertyID, result.TransactionID, result}
	propertyBytes, err := json.Marshal(p)
	if err != nil {
		return nil, failure("LEDGER_STATE_ERROR")
	}
	operationBytes, err := json.Marshal(op)
	if err != nil {
		return nil, failure("LEDGER_STATE_ERROR")
	}
	// Both writes belong to one Fabric simulation. An error invalidates the whole transaction;
	// chaincode must not attempt manual compensating writes or claim commit success.
	if err := ctx.GetStub().PutState(propertyKey, propertyBytes); err != nil {
		return nil, failure("LEDGER_STATE_ERROR")
	}
	if err := ctx.GetStub().PutState(operationKey, operationBytes); err != nil {
		return nil, failure("LEDGER_STATE_ERROR")
	}
	return &result, nil
}
