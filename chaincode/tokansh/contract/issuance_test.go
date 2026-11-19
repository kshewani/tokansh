package contract

import (
	"bytes"
	"crypto/x509"
	"encoding/json"
	"errors"
	"math"
	"reflect"
	"strings"
	"testing"

	"github.com/hyperledger/fabric-chaincode-go/v2/shim"
	"github.com/hyperledger/fabric-contract-api-go/v2/contractapi"
)

func issuanceCommand() IssuanceCommand {
	return IssuanceCommand{1, "50000000-0000-4000-8000-000000000001", command().PropertyID, 40}
}
func issuanceJSON(t *testing.T, c IssuanceCommand) string {
	t.Helper()
	b, err := json.Marshal(c)
	if err != nil {
		t.Fatal(err)
	}
	return string(b)
}
func issuanceSetup(t *testing.T, supply int64) (*SmartContract, *contractapi.TransactionContext, *testStub, *testIdentity) {
	t.Helper()
	cc, ctx, stub, id := setup(t)
	c := command()
	c.ApprovedSupply = supply
	if _, err := invoke(cc, ctx, stub, raw(c)); err != nil {
		t.Fatal(err)
	}
	stub.txID = "test-only-issuance-tx-1"
	return cc, ctx, stub, id
}

// Same commit/discard boundary as the existing registration test helper.
func invokeIssuance(cc *SmartContract, ctx *contractapi.TransactionContext, stub *testStub, body string) (*IssuanceResult, error) {
	stub.pending = map[string][]byte{}
	result, err := cc.IssueANSH(ctx, body)
	if err == nil {
		for k, v := range stub.pending {
			stub.state[k] = v
		}
	}
	stub.pending = map[string][]byte{}
	return result, err
}
func issuanceKey(t *testing.T, object string, attrs ...string) string {
	t.Helper()
	k, err := shim.CreateCompositeKey(object, attrs)
	if err != nil {
		t.Fatal(err)
	}
	return k
}
func ledgerSnapshot(stub *testStub) map[string][]byte {
	snapshot := map[string][]byte{}
	for k, v := range stub.state {
		snapshot[k] = append([]byte(nil), v...)
	}
	return snapshot
}
func mustIssue(t *testing.T, cc *SmartContract, ctx *contractapi.TransactionContext, stub *testStub, c IssuanceCommand) *IssuanceResult {
	t.Helper()
	result, err := invokeIssuance(cc, ctx, stub, issuanceJSON(t, c))
	if err != nil {
		t.Fatal(err)
	}
	return result
}

func TestIssuanceInventoryCeilingAndHistoricalReplay(t *testing.T) {
	cc, ctx, stub, _ := issuanceSetup(t, 100)
	original := ledgerSnapshot(stub)
	c := issuanceCommand()
	writes := stub.writes
	state, err := cc.GetIssuanceState(ctx, c.PropertyID)
	if err != nil || state.ApprovedSupply != 100 || state.CumulativeIssuedSupply != 0 || state.RemainingIssuanceCapacity != 100 {
		t.Fatal(state, err)
	}
	for _, holder := range []string{command().IssuerID, "60000000-0000-4000-8000-000000000001"} {
		b, err := cc.GetBalance(ctx, c.PropertyID, holder)
		if err != nil || b.Quantity != 0 || b.HolderID != holder {
			t.Fatal(b, err)
		}
	}
	if stub.writes != writes {
		t.Fatal("reads initialized ledger state")
	}
	first := mustIssue(t, cc, ctx, stub, c)
	if first.Quantity != 40 || first.IssuerBalance != 40 || first.CumulativeIssuedSupply != 40 || first.RemainingIssuanceCapacity != 60 || first.IssuerID != command().IssuerID || first.TransactionID != stub.txID || stub.writes-writes != 3 || len(stub.state) != 5 {
		t.Fatal(first)
	}
	op, err := cc.GetIssuanceOperation(ctx, c.OperationID)
	if err != nil || op.Result != *first || op.Function != "IssueANSH" || op.AuthorizingMSP != registrationMSP || op.AuthorizingPrincipal != registrationPrincipal() || !digestPattern.MatchString(op.RequestDigest) {
		t.Fatal(op, err)
	}
	c.OperationID = "50000000-0000-4000-8000-000000000002"
	c.Quantity = 60
	stub.txID = "test-only-issuance-tx-2"
	second := mustIssue(t, cc, ctx, stub, c)
	state, err = cc.GetIssuanceState(ctx, c.PropertyID)
	if err != nil || second.IssuerBalance != 100 || state.CumulativeIssuedSupply != 100 || state.RemainingIssuanceCapacity != 0 {
		t.Fatal(second, state, err)
	}
	inventory, err := cc.GetBalance(ctx, c.PropertyID, command().IssuerID)
	if err != nil || inventory.Quantity != 100 {
		t.Fatal(inventory, err)
	}
	before := ledgerSnapshot(stub)
	writes = stub.writes
	// Replaying an earlier operation after later issuance returns its original snapshot.
	replay := mustIssue(t, cc, ctx, stub, issuanceCommand())
	if *replay != *first || stub.writes != writes || !reflect.DeepEqual(before, stub.state) {
		t.Fatal("replay minted units or changed original result")
	}
	c.OperationID = "50000000-0000-4000-8000-000000000003"
	c.Quantity = 1
	_, err = invokeIssuance(cc, ctx, stub, issuanceJSON(t, c))
	assertCode(t, err, "ISSUANCE_LIMIT_EXCEEDED")
	if stub.writes != writes || !reflect.DeepEqual(before, stub.state) {
		t.Fatal("excess issuance wrote state")
	}
	for k, v := range original {
		if !bytes.Equal(stub.state[k], v) {
			t.Fatal("M3 registration record changed")
		}
	}
	// M3 reads and idempotency remain valid after issuance.
	if _, err := cc.GetOperation(ctx, registrationMSP, command().OperationID); err != nil {
		t.Fatal(err)
	}
	registration := command()
	registration.ApprovedSupply = 100
	if _, err := invoke(cc, ctx, stub, raw(registration)); err != nil {
		t.Fatal(err)
	}
}

func TestIssuanceStrictCommandValidation(t *testing.T) {
	good := issuanceJSON(t, issuanceCommand())
	cases := []struct{ name, body, code string }{
		{"zero", strings.Replace(good, `"quantity":40`, `"quantity":0`, 1), "INVALID_ARGUMENT"},
		{"negative", strings.Replace(good, `"quantity":40`, `"quantity":-1`, 1), "INVALID_ARGUMENT"},
		{"fraction", strings.Replace(good, `"quantity":40`, `"quantity":1.5`, 1), "INVALID_ARGUMENT"},
		{"decimal", strings.Replace(good, `"quantity":40`, `"quantity":40.0`, 1), "INVALID_ARGUMENT"},
		{"exponent", strings.Replace(good, `"quantity":40`, `"quantity":4e1`, 1), "INVALID_ARGUMENT"},
		{"string", strings.Replace(good, `"quantity":40`, `"quantity":"40"`, 1), "INVALID_ARGUMENT"},
		{"boolean", strings.Replace(good, `"quantity":40`, `"quantity":true`, 1), "INVALID_ARGUMENT"},
		{"null", strings.Replace(good, `"quantity":40`, `"quantity":null`, 1), "INVALID_ARGUMENT"},
		{"outside domain", strings.Replace(good, `"quantity":40`, `"quantity":9007199254740992`, 1), "INVALID_ARGUMENT"},
		{"int64 overflow", strings.Replace(good, `"quantity":40`, `"quantity":9223372036854775808`, 1), "INVALID_ARGUMENT"},
		{"int64 underflow", strings.Replace(good, `"quantity":40`, `"quantity":-9223372036854775809`, 1), "INVALID_ARGUMENT"},
		{"unknown", strings.TrimSuffix(good, "}") + `,"extra":1}`, "INVALID_ARGUMENT"},
		{"spoof issuer", strings.TrimSuffix(good, "}") + `,"issuer_id":"30000000-0000-4000-8000-000000000002"}`, "INVALID_ARGUMENT"},
		{"duplicate", strings.TrimSuffix(good, "}") + `,"quantity":40}`, "INVALID_ARGUMENT"},
		{"escaped duplicate", strings.TrimSuffix(good, "}") + `,"quantit\u0079":40}`, "INVALID_ARGUMENT"},
		{"case", strings.Replace(good, "quantity", "Quantity", 1), "INVALID_ARGUMENT"},
		{"missing", strings.Replace(good, `,"quantity":40`, "", 1), "INVALID_ARGUMENT"},
		{"trailing", good + " {}", "INVALID_ARGUMENT"},
		{"array", "[]", "INVALID_ARGUMENT"}, {"empty", "{}", "INVALID_ARGUMENT"}, {"root null", "null", "INVALID_ARGUMENT"},
		{"invalid UTF8", good + string([]byte{0xff}), "INVALID_ARGUMENT"},
		{"oversized", strings.Repeat(" ", maxCommandBytes+1), "INVALID_ARGUMENT"},
		{"version", strings.Replace(good, `"command_version":1`, `"command_version":2`, 1), "UNSUPPORTED_SCHEMA_VERSION"},
		{"operation UUID", strings.Replace(good, issuanceCommand().OperationID, "bad", 1), "INVALID_ARGUMENT"},
		{"property UUID", strings.Replace(good, issuanceCommand().PropertyID, "bad", 1), "INVALID_ARGUMENT"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			cc, ctx, stub, _ := issuanceSetup(t, 100)
			before, reads, writes := ledgerSnapshot(stub), stub.reads, stub.writes
			_, err := invokeIssuance(cc, ctx, stub, tc.body)
			assertCode(t, err, tc.code)
			if stub.reads != reads || stub.writes != writes || !reflect.DeepEqual(before, stub.state) {
				t.Fatal("invalid input accessed ledger")
			}
		})
	}
}

func TestIssuanceConflictsAndCanonicalReplay(t *testing.T) {
	cc, ctx, stub, _ := issuanceSetup(t, 100)
	c := issuanceCommand()
	first := mustIssue(t, cc, ctx, stub, c)
	before, writes := ledgerSnapshot(stub), stub.writes
	reordered := ` { "quantity":40, "property_id":"` + c.PropertyID + `", "operation_id":"` + c.OperationID + `", "command_version":1 } `
	result, err := invokeIssuance(cc, ctx, stub, reordered)
	if err != nil || *result != *first || stub.writes != writes {
		t.Fatal(result, err)
	}
	c.Quantity++
	_, err = invokeIssuance(cc, ctx, stub, issuanceJSON(t, c))
	assertCode(t, err, "IDEMPOTENCY_CONFLICT")
	c = issuanceCommand()
	c.PropertyID = "20000000-0000-4000-8000-000000000002"
	_, err = invokeIssuance(cc, ctx, stub, issuanceJSON(t, c))
	assertCode(t, err, "IDEMPOTENCY_CONFLICT")
	if stub.writes != writes || !reflect.DeepEqual(before, stub.state) {
		t.Fatal("conflict changed ledger")
	}
}

func TestIssuanceUnknownPropertyAndReadValidation(t *testing.T) {
	cc, ctx, stub, _ := setup(t)
	c := issuanceCommand()
	_, err := invokeIssuance(cc, ctx, stub, issuanceJSON(t, c))
	assertCode(t, err, "PROPERTY_NOT_FOUND")
	_, err = cc.GetIssuanceState(ctx, c.PropertyID)
	assertCode(t, err, "PROPERTY_NOT_FOUND")
	_, err = cc.GetBalance(ctx, c.PropertyID, command().IssuerID)
	assertCode(t, err, "PROPERTY_NOT_FOUND")
	_, err = cc.GetIssuanceOperation(ctx, c.OperationID)
	assertCode(t, err, "OPERATION_NOT_FOUND")
	_, err = cc.GetIssuanceState(ctx, "bad")
	assertCode(t, err, "INVALID_ARGUMENT")
	_, err = cc.GetBalance(ctx, c.PropertyID, "bad")
	assertCode(t, err, "INVALID_ARGUMENT")
	_, err = cc.GetIssuanceOperation(ctx, "bad")
	assertCode(t, err, "INVALID_ARGUMENT")
	if stub.writes != 0 {
		t.Fatal("missing reads wrote state")
	}
}

func TestIssuanceAuthorization(t *testing.T) {
	for _, kind := range []string{"msp", "principal", "certificate", "nil certificate", "identity error"} {
		t.Run(kind, func(t *testing.T) {
			cc, ctx, stub, id := issuanceSetup(t, 100)
			switch kind {
			case "msp":
				id.msp = "Org2MSP"
			case "principal":
				id.id = "issuer supplied by request"
			case "certificate":
				id.cert = &x509.Certificate{Raw: []byte("test-only wrong certificate")}
			case "nil certificate":
				id.cert = nil
			case "identity error":
				id.err = errors.New("secret identity error")
			}
			reads, writes := stub.reads, stub.writes
			_, err := invokeIssuance(cc, ctx, stub, issuanceJSON(t, issuanceCommand()))
			assertCode(t, err, "UNAUTHORIZED")
			_, err = cc.GetIssuanceOperation(ctx, issuanceCommand().OperationID)
			assertCode(t, err, "UNAUTHORIZED")
			if stub.reads != reads || stub.writes != writes {
				t.Fatal("unauthorized state access")
			}
		})
	}
	cc, ctx, stub, id := issuanceSetup(t, 100)
	mustIssue(t, cc, ctx, stub, issuanceCommand())
	id.msp = "Org2MSP"
	if _, err := cc.GetIssuanceState(ctx, command().PropertyID); err != nil {
		t.Fatal(err)
	}
	if _, err := cc.GetBalance(ctx, command().PropertyID, command().IssuerID); err != nil {
		t.Fatal(err)
	}
	id.msp = "UnknownMSP"
	_, err := cc.GetIssuanceState(ctx, command().PropertyID)
	assertCode(t, err, "UNAUTHORIZED")
	_, err = cc.GetBalance(ctx, command().PropertyID, command().IssuerID)
	assertCode(t, err, "UNAUTHORIZED")
}

func TestIssuanceCorruptSupplyAndBalances(t *testing.T) {
	cases := []struct {
		object, field string
		value         any
	}{
		{"issuance", "schema_version", 2}, {"issuance", "property_id", "bad"}, {"issuance", "issuer_id", "bad"},
		{"issuance", "approved_supply", 101}, {"issuance", "cumulative_issued_supply", -1}, {"issuance", "cumulative_issued_supply", 0},
		{"issuance", "cumulative_issued_supply", 101}, {"issuance", "cumulative_issued_supply", int64(math.MaxInt64)},
		{"issuance", "remaining_issuance_capacity", 59}, {"issuance", "remaining_issuance_capacity", -1},
		{"balance", "schema_version", 2}, {"balance", "property_id", "bad"}, {"balance", "holder_id", "bad"},
		{"balance", "quantity", -1}, {"balance", "quantity", 39}, {"balance", "quantity", 101}, {"balance", "quantity", int64(math.MaxInt64)},
	}
	for _, tc := range cases {
		t.Run(tc.object+tc.field+reflect.TypeOf(tc.value).String(), func(t *testing.T) {
			cc, ctx, stub, _ := issuanceSetup(t, 100)
			mustIssue(t, cc, ctx, stub, issuanceCommand())
			attrs := []string{command().PropertyID}
			if tc.object == "balance" {
				attrs = append(attrs, command().IssuerID)
			}
			k := issuanceKey(t, tc.object, attrs...)
			var record map[string]json.RawMessage
			if err := json.Unmarshal(stub.state[k], &record); err != nil {
				t.Fatal(err)
			}
			value, err := json.Marshal(tc.value)
			if err != nil {
				t.Fatal(err)
			}
			record[tc.field] = value
			stub.state[k], err = json.Marshal(record)
			if err != nil {
				t.Fatal(err)
			}
			before, writes := ledgerSnapshot(stub), stub.writes
			_, err = cc.GetIssuanceState(ctx, command().PropertyID)
			assertCode(t, err, "LEDGER_STATE_ERROR")
			_, err = cc.GetBalance(ctx, command().PropertyID, command().IssuerID)
			assertCode(t, err, "LEDGER_STATE_ERROR")
			next := issuanceCommand()
			next.OperationID = "50000000-0000-4000-8000-000000000002"
			_, err = invokeIssuance(cc, ctx, stub, issuanceJSON(t, next))
			assertCode(t, err, "LEDGER_STATE_ERROR")
			_, err = invokeIssuance(cc, ctx, stub, issuanceJSON(t, issuanceCommand()))
			assertCode(t, err, "LEDGER_STATE_ERROR")
			if stub.writes != writes || !reflect.DeepEqual(before, stub.state) {
				t.Fatal("corruption caused writes")
			}
		})
	}
}

func TestIssuanceCorruptRecordShapes(t *testing.T) {
	for _, object := range []string{"issuance", "balance", "issuance_operation"} {
		for _, kind := range []string{"missing record", "malformed", "unknown", "duplicate", "missing field", "null", "case"} {
			t.Run(object+"/"+kind, func(t *testing.T) {
				cc, ctx, stub, _ := issuanceSetup(t, 100)
				mustIssue(t, cc, ctx, stub, issuanceCommand())
				attrs := []string{command().PropertyID}
				if object == "balance" {
					attrs = append(attrs, command().IssuerID)
				}
				if object == "issuance_operation" {
					attrs = []string{registrationMSP, issuanceCommand().OperationID}
				}
				k := issuanceKey(t, object, attrs...)
				b := string(stub.state[k])
				switch kind {
				case "missing record":
					delete(stub.state, k)
				case "malformed":
					stub.state[k] = []byte(`{broken`)
				case "unknown":
					stub.state[k] = []byte(strings.TrimSuffix(b, "}") + `,"extra":true}`)
				case "duplicate":
					stub.state[k] = []byte(strings.TrimSuffix(b, "}") + `,"schema_version":1}`)
				case "missing field":
					stub.state[k] = []byte(strings.Replace(b, `"schema_version":1,`, "", 1))
				case "null":
					stub.state[k] = []byte(strings.Replace(b, `"schema_version":1`, `"schema_version":null`, 1))
				case "case":
					stub.state[k] = []byte(strings.Replace(b, "schema_version", "Schema_Version", 1))
				}
				writes := stub.writes
				if object == "issuance_operation" {
					_, err := cc.GetIssuanceOperation(ctx, issuanceCommand().OperationID)
					if kind == "missing record" {
						assertCode(t, err, "OPERATION_NOT_FOUND")
					} else {
						assertCode(t, err, "LEDGER_STATE_ERROR")
					}
				} else {
					_, err := cc.GetIssuanceState(ctx, command().PropertyID)
					assertCode(t, err, "LEDGER_STATE_ERROR")
					_, err = invokeIssuance(cc, ctx, stub, issuanceJSON(t, issuanceCommand()))
					assertCode(t, err, "LEDGER_STATE_ERROR")
				}
				if stub.writes != writes {
					t.Fatal("malformed state wrote ledger")
				}
			})
		}
	}
}

func TestIssuanceReceiptConsistency(t *testing.T) {
	for _, kind := range []string{"digest", "function", "principal", "msp", "issuer", "operation", "property", "quantity", "tx", "result quantity", "result balance", "result supply", "result capacity", "result tx", "nested unknown", "nested duplicate", "ahead of state"} {
		t.Run(kind, func(t *testing.T) {
			cc, ctx, stub, _ := issuanceSetup(t, 100)
			mustIssue(t, cc, ctx, stub, issuanceCommand())
			k := issuanceKey(t, "issuance_operation", registrationMSP, issuanceCommand().OperationID)
			var op IssuanceOperation
			if err := json.Unmarshal(stub.state[k], &op); err != nil {
				t.Fatal(err)
			}
			switch kind {
			case "digest":
				op.RequestDigest = strings.Repeat("0", 64)
			case "function":
				op.Function = "RegisterApprovedProperty"
			case "principal":
				op.AuthorizingPrincipal = "other"
			case "msp":
				op.AuthorizingMSP = "Org2MSP"
			case "issuer":
				op.IssuerID = "30000000-0000-4000-8000-000000000002"
			case "operation":
				op.OperationID = "50000000-0000-4000-8000-000000000002"
			case "property":
				op.PropertyID = "20000000-0000-4000-8000-000000000002"
			case "quantity":
				op.Quantity++
			case "tx":
				op.OriginalTransactionID = ""
			case "result quantity":
				op.Result.Quantity++
			case "result balance":
				op.Result.IssuerBalance++
			case "result supply":
				op.Result.CumulativeIssuedSupply = 101
			case "result capacity":
				op.Result.RemainingIssuanceCapacity++
			case "result tx":
				op.Result.TransactionID = "other"
			case "ahead of state":
				op.Result.CumulativeIssuedSupply = 41
				op.Result.IssuerBalance = 41
				op.Result.RemainingIssuanceCapacity = 59
			}
			b, err := json.Marshal(op)
			if err != nil {
				t.Fatal(err)
			}
			if kind == "nested unknown" {
				b = []byte(strings.Replace(string(b), `"result":{`, `"result":{"extra":true,`, 1))
			}
			if kind == "nested duplicate" {
				b = []byte(strings.Replace(string(b), `"result":{`, `"result":{"quantity":40,`, 1))
			}
			stub.state[k] = b
			writes := stub.writes
			_, err = cc.GetIssuanceOperation(ctx, issuanceCommand().OperationID)
			assertCode(t, err, "LEDGER_STATE_ERROR")
			_, err = invokeIssuance(cc, ctx, stub, issuanceJSON(t, issuanceCommand()))
			assertCode(t, err, "LEDGER_STATE_ERROR")
			if stub.writes != writes {
				t.Fatal("corrupt receipt wrote ledger")
			}
		})
	}
}

func TestIssuanceAtomicFailures(t *testing.T) {
	// Counted key/read failures cover every access on the fresh-issuance path.
	for _, kind := range []string{"read", "key", "write", "tx"} {
		count := 1
		switch kind {
		case "read":
			count = 4
		case "key":
			count = 6
		case "write":
			count = 3
		}
		for offset := 1; offset <= count; offset++ {
			t.Run(kind+string(rune('0'+offset)), func(t *testing.T) {
				for _, prior := range []bool{false, true} {
					cc, ctx, stub, _ := issuanceSetup(t, 100)
					c := issuanceCommand()
					if prior {
						mustIssue(t, cc, ctx, stub, c)
						c.OperationID = "50000000-0000-4000-8000-000000000002"
					}
					before := ledgerSnapshot(stub)
					switch kind {
					case "read":
						stub.failRead = stub.reads + offset
					case "key":
						stub.failKey = stub.keys + offset
					case "write":
						stub.failWrite = stub.writes + offset
					case "tx":
						stub.txID = ""
					}
					result, err := invokeIssuance(cc, ctx, stub, issuanceJSON(t, c))
					assertCode(t, err, "LEDGER_STATE_ERROR")
					if result != nil || !reflect.DeepEqual(before, stub.state) || len(stub.pending) != 0 {
						t.Fatal("failed transaction partially applied")
					}
				}
			})
		}
	}
}

func TestIssuanceIntegerBoundaries(t *testing.T) {
	cc, ctx, stub, _ := issuanceSetup(t, maxSupply)
	c := issuanceCommand()
	c.Quantity = maxSupply - 1
	mustIssue(t, cc, ctx, stub, c)
	c.OperationID = "50000000-0000-4000-8000-000000000002"
	c.Quantity = 1
	result := mustIssue(t, cc, ctx, stub, c)
	if result.CumulativeIssuedSupply != maxSupply || result.IssuerBalance != maxSupply || result.RemainingIssuanceCapacity != 0 {
		t.Fatal(result)
	}
	for _, pair := range [][2]int64{{math.MaxInt64, 1}, {math.MaxInt64 - 1, 2}, {-1, 1}, {0, 0}, {0, -1}, {math.MaxInt64, math.MaxInt64}} {
		_, err := addQuantity(pair[0], pair[1])
		assertCode(t, err, "LEDGER_STATE_ERROR")
	}
	if sum, err := addQuantity(math.MaxInt64-1, 1); err != nil || sum != math.MaxInt64 {
		t.Fatal(sum, err)
	}
	for _, quantity := range []int64{1, maxSupply} {
		c.Quantity = quantity
		if _, err := decodeIssuanceCommand(issuanceJSON(t, c)); err != nil {
			t.Fatal(err)
		}
	}
}

func TestIssuancePropertyIsolationAndDeterminism(t *testing.T) {
	a, ctxA, stubA, _ := issuanceSetup(t, 100)
	b, ctxB, stubB, _ := issuanceSetup(t, 100)
	ra := mustIssue(t, a, ctxA, stubA, issuanceCommand())
	rb := mustIssue(t, b, ctxB, stubB, issuanceCommand())
	if *ra != *rb || !reflect.DeepEqual(stubA.state, stubB.state) {
		t.Fatal("nondeterministic issuance")
	}
	c := command()
	c.OperationID = "10000000-0000-4000-8000-000000000002"
	c.PropertyID = "20000000-0000-4000-8000-000000000002"
	c.IssuerID = "30000000-0000-4000-8000-000000000002"
	c.ApprovedSupply = 50
	if _, err := invoke(a, ctxA, stubA, raw(c)); err != nil {
		t.Fatal(err)
	}
	issue := issuanceCommand()
	issue.OperationID = "50000000-0000-4000-8000-000000000002"
	issue.PropertyID = c.PropertyID
	result := mustIssue(t, a, ctxA, stubA, issue)
	if result.IssuerID != c.IssuerID || result.IssuerBalance != 40 || result.RemainingIssuanceCapacity != 10 {
		t.Fatal(result)
	}
	first, err := a.GetBalance(ctxA, command().PropertyID, command().IssuerID)
	if err != nil || first.Quantity != 40 {
		t.Fatal(first, err)
	}
	if failure("ISSUANCE_LIMIT_EXCEEDED").Error() != `{"code":"ISSUANCE_LIMIT_EXCEEDED","message":"Requested issuance exceeds approved supply."}` {
		t.Fatal("nondeterministic error")
	}
}

func TestIssuanceNonIssuerInventoryValidation(t *testing.T) {
	cc, ctx, stub, _ := issuanceSetup(t, 1)
	c := issuanceCommand()
	c.Quantity = 1
	mustIssue(t, cc, ctx, stub, c)
	holder := "60000000-0000-4000-8000-000000000001"
	k := issuanceKey(t, "balance", c.PropertyID, holder)
	for _, quantity := range []int64{0, 1, -1} {
		record, err := json.Marshal(Balance{1, c.PropertyID, holder, quantity})
		if err != nil {
			t.Fatal(err)
		}
		stub.state[k] = record
		before, writes := ledgerSnapshot(stub), stub.writes
		balance, err := cc.GetBalance(ctx, c.PropertyID, holder)
		if quantity == 0 {
			if err != nil || balance.Quantity != 0 {
				t.Fatal(balance, err)
			}
		} else {
			assertCode(t, err, "LEDGER_STATE_ERROR")
		}
		if stub.writes != writes || !reflect.DeepEqual(before, stub.state) {
			t.Fatal("balance read mutated ledger")
		}
	}
}
