package contract

import (
	"crypto/sha256"
	"crypto/x509"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"encoding/pem"
	"errors"
	"os"
	"reflect"
	"strings"
	"testing"

	"github.com/hyperledger/fabric-chaincode-go/v2/pkg/cid"
	"github.com/hyperledger/fabric-chaincode-go/v2/shim"
	"github.com/hyperledger/fabric-contract-api-go/v2/contractapi"
	"google.golang.org/protobuf/types/known/timestamppb"
)

// All ledger/identity doubles below are isolated tests, never runtime adapters.
type testIdentity struct {
	cid.ClientIdentity
	msp, id string
	cert    *x509.Certificate
	err     error
}

func (i *testIdentity) GetMSPID() (string, error)                      { return i.msp, i.err }
func (i *testIdentity) GetID() (string, error)                         { return i.id, i.err }
func (i *testIdentity) GetX509Certificate() (*x509.Certificate, error) { return i.cert, i.err }

type testStub struct {
	shim.ChaincodeStubInterface
	state, pending               map[string][]byte
	failRead, failWrite, failKey int
	reads, writes, keys          int
	txID                         string
	timestamp                    *timestamppb.Timestamp
	timestampErr                 error
}

func (s *testStub) CreateCompositeKey(object string, attrs []string) (string, error) {
	s.keys++
	if s.keys == s.failKey {
		return "", errors.New("secret key failure")
	}
	return shim.CreateCompositeKey(object, attrs)
}
func (s *testStub) GetState(k string) ([]byte, error) {
	s.reads++
	if s.reads == s.failRead {
		return nil, errors.New("secret read failure")
	}
	return s.state[k], nil
}
func (s *testStub) PutState(k string, v []byte) error {
	s.writes++
	if s.writes == s.failWrite {
		return errors.New("secret write failure")
	}
	s.pending[k] = append([]byte(nil), v...)
	return nil
}
func (s *testStub) GetTxID() string { return s.txID }
func (s *testStub) GetTxTimestamp() (*timestamppb.Timestamp, error) {
	return s.timestamp, s.timestampErr
}
func setup(t *testing.T) (*SmartContract, *contractapi.TransactionContext, *testStub, *testIdentity) {
	t.Helper()
	b, err := os.ReadFile("testdata/org1-user1-public.pem")
	if err != nil {
		t.Fatal(err)
	}
	block, _ := pem.Decode(b)
	if block == nil {
		t.Fatal("invalid public fixture")
	}
	cert, err := x509.ParseCertificate(block.Bytes)
	if err != nil {
		t.Fatal(err)
	}
	i := &testIdentity{msp: registrationMSP, id: registrationPrincipal(), cert: cert}
	s := &testStub{state: map[string][]byte{}, pending: map[string][]byte{}, txID: "test-only-tx-1", timestamp: &timestamppb.Timestamp{Seconds: 1700000000, Nanos: 123}}
	c := new(contractapi.TransactionContext)
	c.SetStub(s)
	c.SetClientIdentity(i)
	return &SmartContract{}, c, s, i
}
func command() Command {
	return Command{1, "10000000-0000-4000-8000-000000000001", "20000000-0000-4000-8000-000000000001", "30000000-0000-4000-8000-000000000001", "40000000-0000-4000-8000-000000000001", strings.Repeat("a", 64), 100000, "1000000", "INR"}
}
func raw(c Command) string { b, _ := json.Marshal(c); return string(b) }
func assertCode(t *testing.T, err error, code string) {
	t.Helper()
	if err == nil {
		t.Fatalf("expected %s", code)
	}
	var e contractError
	if !errors.As(err, &e) || e.Code != code {
		t.Fatalf("unexpected error %v", err)
	}
	if !json.Valid([]byte(err.Error())) || strings.Contains(err.Error(), "secret") {
		t.Fatalf("unsafe error %v", err)
	}
}

// Emulate Fabric's transaction boundary, discarding simulation writes on any error.
func invoke(cc *SmartContract, ctx *contractapi.TransactionContext, s *testStub, c string) (*RegistrationResult, error) {
	s.pending = map[string][]byte{}
	r, e := cc.RegisterApprovedProperty(ctx, c)
	if e == nil {
		for k, v := range s.pending {
			s.state[k] = v
		}
	}
	s.pending = map[string][]byte{}
	return r, e
}
func TestRegistrationReadsReplayAndSupplyCeiling(t *testing.T) {
	cc, ctx, s, i := setup(t)
	cmd := command()
	r, err := invoke(cc, ctx, s, raw(cmd))
	if err != nil {
		t.Fatal(err)
	}
	if r.TransactionID != s.txID || len(s.state) != 2 {
		t.Fatal("missing reference or extra state")
	}
	p, err := cc.GetRegisteredProperty(ctx, cmd.PropertyID)
	if err != nil {
		t.Fatal(err)
	}
	if p.ApprovedSupply != 100000 || p.RegistrationTransactionID != r.TransactionID {
		t.Fatal("incorrect constraints")
	}
	for k, v := range s.state {
		parts := strings.Split(k, "\x00")
		if len(parts) < 3 {
			t.Fatal("not a composite key")
		}
		object := parts[1]
		if object != "property" && object != "operation" {
			t.Fatal("financial state created")
		}
		if strings.Contains(string(v), "issued_supply") || strings.Contains(string(v), "owned") {
			t.Fatal("minted supply")
		}
	}
	op, err := cc.GetOperation(ctx, registrationMSP, cmd.OperationID)
	if err != nil {
		t.Fatal(err)
	}
	if op.Result != *r || !digestPattern.MatchString(op.RequestDigest) {
		t.Fatal("wrong receipt")
	}
	snapshot := map[string][]byte{}
	for k, v := range s.state {
		snapshot[k] = append([]byte(nil), v...)
	}
	writes := s.writes
	s.txID = "test-only-tx-2"
	s.timestamp.Seconds++
	replay, err := invoke(cc, ctx, s, " \n"+raw(cmd))
	if err != nil || *replay != *r || s.writes != writes || !reflect.DeepEqual(snapshot, s.state) {
		t.Fatal("replay changed state/result")
	}
	i.msp = "Org2MSP"
	if _, err := cc.GetRegisteredProperty(ctx, cmd.PropertyID); err != nil {
		t.Fatal(err)
	}
	_, err = cc.GetOperation(ctx, registrationMSP, cmd.OperationID)
	assertCode(t, err, "UNAUTHORIZED")
}
func TestConflictAndDuplicateProperty(t *testing.T) {
	cc, ctx, s, _ := setup(t)
	cmd := command()
	if _, err := invoke(cc, ctx, s, raw(cmd)); err != nil {
		t.Fatal(err)
	}
	writes := s.writes
	cmd.ApprovedSupply++
	_, err := invoke(cc, ctx, s, raw(cmd))
	assertCode(t, err, "IDEMPOTENCY_CONFLICT")
	cmd.OperationID = "10000000-0000-4000-8000-000000000002"
	_, err = invoke(cc, ctx, s, raw(cmd))
	assertCode(t, err, "PROPERTY_ALREADY_REGISTERED")
	if s.writes != writes {
		t.Fatal("conflict wrote state")
	}
}
func TestStrictCommands(t *testing.T) {
	cases := []struct{ name, body, code string }{{"unknown", strings.TrimSuffix(raw(command()), "}") + `,"extra":1}`, "INVALID_ARGUMENT"}, {"duplicate", strings.TrimSuffix(raw(command()), "}") + `,"currency":"INR"}`, "INVALID_ARGUMENT"}, {"escaped duplicate", strings.TrimSuffix(raw(command()), "}") + `,"currenc\u0079":"INR"}`, "INVALID_ARGUMENT"}, {"case", strings.Replace(raw(command()), "command_version", "Command_Version", 1), "INVALID_ARGUMENT"}, {"null", "null", "INVALID_ARGUMENT"}, {"array", "[]", "INVALID_ARGUMENT"}, {"trailing", raw(command()) + " {}", "INVALID_ARGUMENT"}, {"huge", strings.Repeat(" ", maxCommandBytes+1), "INVALID_ARGUMENT"}, {"missing", "{}", "INVALID_ARGUMENT"}, {"field null", strings.Replace(raw(command()), `"approved_supply":100000`, `"approved_supply":null`, 1), "INVALID_ARGUMENT"}, {"decimal quantity", strings.Replace(raw(command()), `"approved_supply":100000`, `"approved_supply":1.0`, 1), "INVALID_ARGUMENT"}, {"exponent quantity", strings.Replace(raw(command()), `"approved_supply":100000`, `"approved_supply":1e5`, 1), "INVALID_ARGUMENT"}}
	for _, mut := range []struct {
		name  string
		apply func(*Command)
		code  string
	}{
		{"version", func(c *Command) { c.CommandVersion = 2 }, "UNSUPPORTED_SCHEMA_VERSION"}, {"UUID", func(c *Command) { c.PropertyID = "TechPark One" }, "INVALID_ARGUMENT"}, {"operation UUID", func(c *Command) { c.OperationID = "invalid" }, "INVALID_ARGUMENT"}, {"issuer UUID", func(c *Command) { c.IssuerID = "invalid" }, "INVALID_ARGUMENT"}, {"approval UUID", func(c *Command) { c.ApprovalReference = "invalid" }, "INVALID_ARGUMENT"}, {"digest", func(c *Command) { c.ApprovalDigest = "AA" }, "INVALID_ARGUMENT"}, {"zero", func(c *Command) { c.ApprovedSupply = 0 }, "INVALID_ARGUMENT"}, {"negative", func(c *Command) { c.ApprovedSupply = -1 }, "INVALID_ARGUMENT"}, {"overflow", func(c *Command) { c.ApprovedSupply = maxSupply + 1 }, "INVALID_ARGUMENT"}, {"currency", func(c *Command) { c.Currency = "USD" }, "INVALID_ARGUMENT"}, {"price zero", func(c *Command) { c.IssuePriceMinor = "0" }, "INVALID_ARGUMENT"}, {"price leading zero", func(c *Command) { c.IssuePriceMinor = "01" }, "INVALID_ARGUMENT"}, {"price decimal", func(c *Command) { c.IssuePriceMinor = "1.00" }, "INVALID_ARGUMENT"}, {"price overflow", func(c *Command) { c.IssuePriceMinor = "10000000000000000" }, "INVALID_ARGUMENT"}, {"price exponent", func(c *Command) { c.IssuePriceMinor = "1e3" }, "INVALID_ARGUMENT"}} {
		c := command()
		mut.apply(&c)
		cases = append(cases, struct{ name, body, code string }{mut.name, raw(c), mut.code})
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			cc, ctx, s, _ := setup(t)
			_, err := invoke(cc, ctx, s, tc.body)
			assertCode(t, err, tc.code)
			if s.writes != 0 {
				t.Fatal("invalid command wrote state")
			}
		})
	}
	for _, supply := range []int64{1, maxSupply} {
		c := command()
		c.ApprovedSupply = supply
		c.IssuePriceMinor = "9999999999999999"
		if _, err := decodeCommand(raw(c)); err != nil {
			t.Fatal(err)
		}
	}
}
func TestAuthorization(t *testing.T) {
	for _, kind := range []string{"msp", "principal", "certificate", "nil certificate", "identity error"} {
		t.Run(kind, func(t *testing.T) {
			cc, ctx, s, i := setup(t)
			switch kind {
			case "msp":
				i.msp = "Org2MSP"
			case "principal":
				i.id = "wrong"
			case "certificate":
				i.cert = &x509.Certificate{Raw: []byte("test-only wrong certificate")}
			case "nil certificate":
				i.cert = nil
			case "identity error":
				i.err = errors.New("secret identity error")
			}
			_, err := invoke(cc, ctx, s, raw(command()))
			assertCode(t, err, "UNAUTHORIZED")
			if s.reads != 0 || s.writes != 0 {
				t.Fatal("unauthorized ledger access")
			}
		})
	}
}
func TestFailuresAndMissingReads(t *testing.T) {
	for _, kind := range []string{"read operation", "read property", "write property", "write operation", "key operation", "key property", "timestamp", "transaction ID"} {
		t.Run(kind, func(t *testing.T) {
			cc, ctx, s, _ := setup(t)
			switch kind {
			case "read operation":
				s.failRead = 1
			case "read property":
				s.failRead = 2
			case "write property":
				s.failWrite = 1
			case "write operation":
				s.failWrite = 2
			case "key operation":
				s.failKey = 1
			case "key property":
				s.failKey = 2
			case "timestamp":
				s.timestampErr = errors.New("secret timestamp error")
			case "transaction ID":
				s.txID = ""
			}
			_, err := invoke(cc, ctx, s, raw(command()))
			assertCode(t, err, "LEDGER_STATE_ERROR")
			if len(s.state) != 0 {
				t.Fatal("failed transaction applied state")
			}
		})
	}
	cc, ctx, s, _ := setup(t)
	_, err := cc.GetRegisteredProperty(ctx, command().PropertyID)
	assertCode(t, err, "PROPERTY_NOT_FOUND")
	_, err = cc.GetOperation(ctx, registrationMSP, command().OperationID)
	assertCode(t, err, "OPERATION_NOT_FOUND")
	s.failRead = s.reads + 1
	_, err = cc.GetRegisteredProperty(ctx, command().PropertyID)
	assertCode(t, err, "LEDGER_STATE_ERROR")
}
func TestDeterminismAndContractMetadata(t *testing.T) {
	a, ctxA, sA, _ := setup(t)
	b, ctxB, sB, _ := setup(t)
	_, err := invoke(a, ctxA, sA, raw(command()))
	if err != nil {
		t.Fatal(err)
	}
	_, err = invoke(b, ctxB, sB, raw(command()))
	if err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(sA.state, sB.state) {
		t.Fatal("nondeterministic state")
	}
	info, err := a.GetContractInfo(ctxA)
	if err != nil || !reflect.DeepEqual(info.Functions, []string{"GetContractInfo", "GetRegisteredProperty", "GetOperation", "RegisterApprovedProperty", "IssueANSH", "GetIssuanceState", "GetBalance", "GetIssuanceOperation", "TransferANSH"}) || info.SupplyInterpretation != "LIFETIME_CUMULATIVE_ISSUANCE_CEILING" {
		t.Fatal("bad metadata")
	}
	if _, err := contractapi.NewChaincode(&SmartContract{}); err != nil {
		t.Fatal(err)
	}
	if failure("UNAUTHORIZED").Error() != `{"code":"UNAUTHORIZED","message":"Identity is not authorized."}` {
		t.Fatal("unstable error")
	}
	// Verify the public certificate fixture is exactly the reviewed identity, without keys.
	cert := ctxA.GetClientIdentity()
	x, _ := cert.GetX509Certificate()
	sum := sha256.Sum256(x.Raw)
	if hex.EncodeToString(sum[:]) != registrationFingerprint {
		t.Fatal("wrong pin")
	}
	expected := base64.StdEncoding.EncodeToString([]byte("x509::" + x.Subject.String() + "::" + x.Issuer.String()))
	if expected != registrationPrincipal() {
		t.Fatal("wrong principal")
	}
}

func TestReadValidationAndCorruptState(t *testing.T) {
	cc, ctx, s, i := setup(t)
	_, err := cc.GetRegisteredProperty(ctx, "bad")
	assertCode(t, err, "INVALID_ARGUMENT")
	_, err = cc.GetOperation(ctx, registrationMSP, "bad")
	assertCode(t, err, "INVALID_ARGUMENT")
	_, err = cc.GetOperation(ctx, "Org2MSP", command().OperationID)
	assertCode(t, err, "UNAUTHORIZED")
	i.msp = "UnknownMSP"
	_, err = cc.GetContractInfo(ctx)
	assertCode(t, err, "UNAUTHORIZED")
	_, err = cc.GetRegisteredProperty(ctx, command().PropertyID)
	assertCode(t, err, "UNAUTHORIZED")
	i.msp = registrationMSP
	if _, err = invoke(cc, ctx, s, raw(command())); err != nil {
		t.Fatal(err)
	}
	pk, _ := shim.CreateCompositeKey("property", []string{command().PropertyID})
	s.state[pk] = []byte(`{broken`)
	_, err = cc.GetRegisteredProperty(ctx, command().PropertyID)
	assertCode(t, err, "LEDGER_STATE_ERROR")
	ok, _ := shim.CreateCompositeKey("operation", []string{registrationMSP, command().OperationID})
	s.state[ok] = []byte(`{broken`)
	_, err = cc.GetOperation(ctx, registrationMSP, command().OperationID)
	assertCode(t, err, "LEDGER_STATE_ERROR")
	_, err = invoke(cc, ctx, s, raw(command()))
	assertCode(t, err, "LEDGER_STATE_ERROR")
}

func TestCanonicalFieldOrderAndResponse(t *testing.T) {
	cc, ctx, s, _ := setup(t)
	r, err := invoke(cc, ctx, s, raw(command()))
	if err != nil {
		t.Fatal(err)
	}
	b, _ := json.Marshal(r)
	want := `{"property_id":"20000000-0000-4000-8000-000000000001","operation_id":"10000000-0000-4000-8000-000000000001","transaction_id":"test-only-tx-1"}`
	if string(b) != want {
		t.Fatalf("unexpected response %s", b)
	}
	var fields map[string]any
	json.Unmarshal([]byte(raw(command())), &fields)
	reordered, _ := json.Marshal(fields)
	writes := s.writes
	s.txID = "another-test-only-tx"
	replay, err := invoke(cc, ctx, s, string(reordered))
	if err != nil || *replay != *r || s.writes != writes {
		t.Fatal("field order changed replay")
	}
}

func TestPersistedRecordHardening(t *testing.T) {
	cases := []struct {
		object, field string
		value         any
	}{
		{"property", "schema_version", 2}, {"property", "issuer_id", "invalid"}, {"property", "approval_reference", "invalid"}, {"property", "approval_digest", "bad"}, {"property", "approved_supply", 0}, {"property", "approved_supply", maxSupply + 1}, {"property", "issue_price_minor", "01"}, {"property", "currency", "USD"}, {"property", "registered_by_msp", "Org2MSP"}, {"property", "registered_by_principal", "wrong"}, {"property", "registration_operation_id", "invalid"}, {"property", "registration_transaction_id", ""}, {"property", "proposal_timestamp", "invalid"}, {"property", "extra", true}, {"property", "Currency", "INR"},
		{"operation", "schema_version", 2}, {"operation", "request_digest", "bad"}, {"operation", "request_digest", strings.Repeat("0", 64)}, {"operation", "property_id", "invalid"}, {"operation", "original_transaction_id", ""}, {"operation", "function", "other"}, {"operation", "authorizing_principal", "wrong"}, {"operation", "extra", true}, {"operation", "Request_Digest", "bad"},
	}
	for _, tc := range cases {
		t.Run(tc.object+tc.field, func(t *testing.T) {
			cc, ctx, s, _ := setup(t)
			c := command()
			if _, err := invoke(cc, ctx, s, raw(c)); err != nil {
				t.Fatal(err)
			}
			attrs := []string{c.PropertyID}
			if tc.object == "operation" {
				attrs = []string{registrationMSP, c.OperationID}
			}
			k, _ := shim.CreateCompositeKey(tc.object, attrs)
			var m map[string]any
			if err := json.Unmarshal(s.state[k], &m); err != nil {
				t.Fatal(err)
			}
			m[tc.field] = tc.value
			b, err := json.Marshal(m)
			if err != nil {
				t.Fatal(err)
			}
			s.state[k] = b
			writes := s.writes
			if tc.object == "property" {
				_, err = cc.GetRegisteredProperty(ctx, c.PropertyID)
			} else {
				_, err = cc.GetOperation(ctx, registrationMSP, c.OperationID)
			}
			assertCode(t, err, "LEDGER_STATE_ERROR")
			_, err = invoke(cc, ctx, s, raw(c))
			assertCode(t, err, "LEDGER_STATE_ERROR")
			if writes != s.writes {
				t.Fatal("corruption caused writes")
			}
		})
	}
}

func TestPersistedShapeAndReceiptConsistency(t *testing.T) {
	for _, kind := range []string{"duplicate", "missing", "null", "case replacement", "nested extra", "nested case", "nested duplicate", "result mismatch", "transaction mismatch", "missing property"} {
		t.Run(kind, func(t *testing.T) {
			cc, ctx, s, _ := setup(t)
			c := command()
			if _, err := invoke(cc, ctx, s, raw(c)); err != nil {
				t.Fatal(err)
			}
			k, _ := shim.CreateCompositeKey("operation", []string{registrationMSP, c.OperationID})
			var m map[string]any
			json.Unmarshal(s.state[k], &m)
			r := m["result"].(map[string]any)
			switch kind {
			case "missing":
				delete(m, "request_digest")
			case "null":
				m["request_digest"] = nil
			case "case replacement":
				m["Request_Digest"] = m["request_digest"]
				delete(m, "request_digest")
			case "nested extra":
				r["extra"] = true
			case "nested case":
				r["Property_ID"] = r["property_id"]
				delete(r, "property_id")
			case "result mismatch":
				r["property_id"] = "invalid"
			case "transaction mismatch":
				r["transaction_id"] = "another"
				m["original_transaction_id"] = "another"
			case "missing property":
				pk, _ := shim.CreateCompositeKey("property", []string{c.PropertyID})
				delete(s.state, pk)
			}
			b, err := json.Marshal(m)
			if err != nil {
				t.Fatal(err)
			}
			if kind == "duplicate" {
				b = []byte(strings.TrimSuffix(string(b), "}") + `,"schema_version":1}`)
			}
			if kind == "nested duplicate" {
				b = []byte(strings.Replace(string(b), `"result":{`, `"result":{"property_id":"invalid",`, 1))
			}
			s.state[k] = b
			_, err = cc.GetOperation(ctx, registrationMSP, c.OperationID)
			assertCode(t, err, "LEDGER_STATE_ERROR")
		})
	}
}
