package contract

import (
	"encoding/json"
	"reflect"
	"strings"
	"testing"

	"github.com/hyperledger/fabric-contract-api-go/v2/contractapi"
)

const investorA = "60000000-0000-4000-8000-000000000001"
const investorB = "60000000-0000-4000-8000-000000000002"

func transferCommand() TransferCommand {
	return TransferCommand{1, "70000000-0000-4000-8000-000000000001", command().PropertyID, command().IssuerID, investorA, 4}
}
func transferSetup(t *testing.T) (*SmartContract, *contractapi.TransactionContext, *testStub, *testIdentity) {
	cc, ctx, stub, id := issuanceSetup(t, 100)
	c := issuanceCommand()
	c.Quantity = 10
	mustIssue(t, cc, ctx, stub, c)
	stub.txID = "test-only-transfer-1"
	return cc, ctx, stub, id
}
func transferJSON(t *testing.T, c TransferCommand) string {
	t.Helper()
	b, e := json.Marshal(c)
	if e != nil {
		t.Fatal(e)
	}
	return string(b)
}
func invokeTransfer(cc *SmartContract, ctx *contractapi.TransactionContext, stub *testStub, raw string) (*TransferResult, error) {
	stub.pending = map[string][]byte{}
	r, e := cc.TransferANSH(ctx, raw)
	if e == nil {
		for k, v := range stub.pending {
			stub.state[k] = v
		}
	}
	stub.pending = map[string][]byte{}
	return r, e
}
func move(t *testing.T, cc *SmartContract, ctx *contractapi.TransactionContext, stub *testStub, c TransferCommand) *TransferResult {
	t.Helper()
	r, e := invokeTransfer(cc, ctx, stub, transferJSON(t, c))
	if e != nil {
		t.Fatal(e)
	}
	return r
}
func quantity(t *testing.T, cc *SmartContract, ctx *contractapi.TransactionContext, holder string) int64 {
	t.Helper()
	b, e := cc.GetBalance(ctx, command().PropertyID, holder)
	if e != nil {
		t.Fatal(e)
	}
	return b.Quantity
}

func TestTransferOwnerToInvestor(t *testing.T) {
	cc, ctx, stub, _ := transferSetup(t)
	before := ledgerSnapshot(stub)
	writes := stub.writes
	c := transferCommand()
	r := move(t, cc, ctx, stub, c)
	if r.PropertyID != c.PropertyID || r.FromHolderID != c.FromHolderID || r.ToHolderID != c.ToHolderID || r.Quantity != 4 || r.TransactionID != stub.txID || r.OperationID != c.OperationID || r.FromBalance != 6 || r.ToBalance != 4 || stub.writes-writes != 3 {
		t.Fatal(r)
	}
	if quantity(t, cc, ctx, c.FromHolderID) != 6 || quantity(t, cc, ctx, c.ToHolderID) != 4 {
		t.Fatal("wrong balances")
	}
	for k, v := range before {
		if strings.HasPrefix(k, "\x00balance\x00") {
			continue
		}
		if !reflect.DeepEqual(stub.state[k], v) {
			t.Fatal("registration/supply/issuance receipt changed")
		}
	}
	var receipt TransferOperation
	if json.Unmarshal(stub.state[issuanceKey(t, "transfer_operation", registrationMSP, c.OperationID)], &receipt) != nil || receipt.Result != *r || receipt.Command != c {
		t.Fatal("missing receipt")
	}
	if _, e := cc.GetIssuanceOperation(ctx, issuanceCommand().OperationID); e != nil {
		t.Fatal("historical issuance receipt unreadable", e)
	}
}
func TestTransferInvestorToInvestor(t *testing.T) {
	cc, ctx, stub, _ := transferSetup(t)
	c := transferCommand()
	move(t, cc, ctx, stub, c)
	c.OperationID = "70000000-0000-4000-8000-000000000002"
	c.FromHolderID = investorA
	c.ToHolderID = investorB
	c.Quantity = 3
	stub.txID = "test-only-transfer-2"
	r := move(t, cc, ctx, stub, c)
	if r.FromBalance != 1 || r.ToBalance != 3 || quantity(t, cc, ctx, investorA) != 1 || quantity(t, cc, ctx, investorB) != 3 {
		t.Fatal(r)
	}
}
func TestTransferInsufficientBalance(t *testing.T) {
	cc, ctx, stub, _ := transferSetup(t)
	before := ledgerSnapshot(stub)
	c := transferCommand()
	c.Quantity = 11
	_, e := invokeTransfer(cc, ctx, stub, transferJSON(t, c))
	assertCode(t, e, "INSUFFICIENT_BALANCE")
	c.FromHolderID = investorB
	c.Quantity = 1
	_, e = invokeTransfer(cc, ctx, stub, transferJSON(t, c))
	assertCode(t, e, "INSUFFICIENT_BALANCE")
	if !reflect.DeepEqual(before, stub.state) {
		t.Fatal("failed transfer changed state")
	}
}
func TestTransferIdenticalAndConflictingReplay(t *testing.T) {
	cc, ctx, stub, _ := transferSetup(t)
	c := transferCommand()
	original := move(t, cc, ctx, stub, c)
	next := c
	next.OperationID = "70000000-0000-4000-8000-000000000002"
	next.FromHolderID = investorA
	next.ToHolderID = investorB
	next.Quantity = 4
	stub.txID = "test-only-transfer-2"
	move(t, cc, ctx, stub, next)
	before := ledgerSnapshot(stub)
	writes := stub.writes
	stub.txID = "test-only-replay"
	replay := move(t, cc, ctx, stub, c)
	if *replay != *original || stub.writes != writes || !reflect.DeepEqual(before, stub.state) {
		t.Fatal("replay transferred again or altered historical result")
	}
	for _, mutate := range []func(*TransferCommand){func(c *TransferCommand) { c.Quantity++ }, func(c *TransferCommand) { c.ToHolderID = investorB }, func(c *TransferCommand) { c.FromHolderID = investorB }} {
		changed := c
		mutate(&changed)
		_, e := invokeTransfer(cc, ctx, stub, transferJSON(t, changed))
		assertCode(t, e, "IDEMPOTENCY_CONFLICT")
	}
	if stub.writes != writes || !reflect.DeepEqual(before, stub.state) {
		t.Fatal("conflict wrote state")
	}
}
func TestTransferConservationAndSubsequentIssuance(t *testing.T) {
	cc, ctx, stub, _ := transferSetup(t)
	before := append([]byte(nil), stub.state[issuanceKey(t, "issuance", command().PropertyID)]...)
	c := transferCommand()
	c.Quantity = 10
	move(t, cc, ctx, stub, c)
	c.OperationID = "70000000-0000-4000-8000-000000000002"
	c.FromHolderID = investorA
	c.ToHolderID = investorB
	c.Quantity = 6
	move(t, cc, ctx, stub, c)
	if quantity(t, cc, ctx, command().IssuerID) != 0 || quantity(t, cc, ctx, investorA)+quantity(t, cc, ctx, investorB) != 10 || !reflect.DeepEqual(before, stub.state[issuanceKey(t, "issuance", command().PropertyID)]) {
		t.Fatal("supply not conserved")
	}
	// Further issuance goes into current inventory, not the cumulative counter.
	issued := issuanceCommand()
	issued.OperationID = "50000000-0000-4000-8000-000000000002"
	issued.Quantity = 5
	stub.txID = "test-only-later-issuance"
	r := mustIssue(t, cc, ctx, stub, issued)
	if r.CumulativeIssuedSupply != 15 || r.RemainingIssuanceCapacity != 85 || r.IssuerBalance != 5 {
		t.Fatal(r)
	}
	if _, e := cc.GetIssuanceOperation(ctx, issued.OperationID); e != nil {
		t.Fatal(e)
	}
	if quantity(t, cc, ctx, command().IssuerID)+quantity(t, cc, ctx, investorA)+quantity(t, cc, ctx, investorB) != 15 {
		t.Fatal("issuance after transfer lost units")
	}
}
func TestTransferInputAuthorizationAndAtomicFailure(t *testing.T) {
	cc, ctx, stub, id := transferSetup(t)
	c := transferCommand()
	original := ledgerSnapshot(stub)
	for _, q := range []int64{0, -1, maxSupply + 1} {
		bad := c
		bad.Quantity = q
		_, e := invokeTransfer(cc, ctx, stub, transferJSON(t, bad))
		assertCode(t, e, "INVALID_ARGUMENT")
	}
	bad := c
	bad.ToHolderID = bad.FromHolderID
	_, e := invokeTransfer(cc, ctx, stub, transferJSON(t, bad))
	assertCode(t, e, "INVALID_ARGUMENT")
	bad = c
	bad.PropertyID = "20000000-0000-4000-8000-000000000002"
	_, e = invokeTransfer(cc, ctx, stub, transferJSON(t, bad))
	assertCode(t, e, "PROPERTY_NOT_FOUND")
	id.msp = "Org2MSP"
	_, e = invokeTransfer(cc, ctx, stub, transferJSON(t, c))
	assertCode(t, e, "UNAUTHORIZED")
	id.msp = registrationMSP
	for i := 1; i <= 3; i++ {
		stub.failWrite = stub.writes + i
		_, e = invokeTransfer(cc, ctx, stub, transferJSON(t, c))
		assertCode(t, e, "LEDGER_STATE_ERROR")
		if !reflect.DeepEqual(original, stub.state) {
			t.Fatal("partial transfer")
		}
	}
}
