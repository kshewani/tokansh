package registration

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"testing"

	common "github.com/hyperledger/fabric-protos-go-apiv2/common"
	gp "github.com/hyperledger/fabric-protos-go-apiv2/gateway"
	"github.com/hyperledger/fabric-protos-go-apiv2/peer"
	"google.golang.org/protobuf/proto"
)

type transferMock struct {
	mockLedger
	prepares int
}

func (m *transferMock) PrepareTransfer(context.Context, TransferCommand) (string, []byte, []byte, error) {
	m.prepares++
	return "test-only-id", m.tx, m.creator, m.err
}
func transferCommand() TransferCommand {
	return TransferCommand{1, command().OperationID, command().PropertyID, command().IssuerID, "60000000-0000-4000-8000-000000000001", 4}
}
func transferPrepared(t *testing.T) ([]byte, []byte) {
	t.Helper()
	b, creator := issuancePrepared(t)
	var p gp.PreparedTransaction
	var payload common.Payload
	var tx peer.Transaction
	var action peer.ChaincodeActionPayload
	var proposal peer.ChaincodeProposalPayload
	decode := func(b []byte, v proto.Message) {
		t.Helper()
		if e := proto.Unmarshal(b, v); e != nil {
			t.Fatal(e)
		}
	}
	decode(b, &p)
	decode(p.Envelope.Payload, &payload)
	decode(payload.Data, &tx)
	decode(tx.Actions[0].Payload, &action)
	decode(action.ChaincodeProposalPayload, &proposal)
	command, e := json.Marshal(transferCommand())
	if e != nil {
		t.Fatal(e)
	}
	proposal.Input = marshal(&peer.ChaincodeInvocationSpec{ChaincodeSpec: &peer.ChaincodeSpec{ChaincodeId: &peer.ChaincodeID{Name: "tokansh"}, Input: &peer.ChaincodeInput{Args: [][]byte{[]byte("TransferANSH"), command}}}})
	action.ChaincodeProposalPayload = marshal(&proposal)
	tx.Actions[0].Payload = marshal(&action)
	payload.Data = marshal(&tx)
	p.Envelope.Payload = marshal(&payload)
	return marshal(&p), creator
}
func TestTransferPrepareAndSharedSubmission(t *testing.T) {
	tx, creator := transferPrepared(t)
	m := &transferMock{mockLedger: mockLedger{tx: tx, creator: creator}}
	s := &Service{Ledger: m, Key: bytes.Repeat([]byte{1}, 32)}
	body, _ := json.Marshal(transferCommand())
	for _, path := range []string{"transfers/prepare", "transfers/submit", "transfers/commit-status"} {
		for _, auth := range []struct {
			bearer, operator bool
			status           int
		}{{false, false, 401}, {true, false, 403}} {
			w := issuanceRequest(s, path, body, auth.bearer, auth.operator)
			if w.Code != auth.status {
				t.Fatal(w.Code, w.Body.String())
			}
		}
	}
	w := issuanceRequest(s, "transfers/prepare", body, true, true)
	if w.Code != 200 || m.prepares != 1 {
		t.Fatal(w.Code, w.Body.String())
	}
	var frame struct {
		Data TransferArtifact `json:"data"`
	}
	if json.Unmarshal(w.Body.Bytes(), &frame) != nil {
		t.Fatal("artifact")
	}
	artifact := frame.Data
	if artifact.Function != "TransferANSH" || artifact.Command != transferCommand() || s.CheckTransfer(artifact) != nil {
		t.Fatal("wrong artifact")
	}
	raw, _ := json.Marshal(artifact)
	var recovered TransferArtifact
	if strict(raw, &recovered) != nil || (&Service{Key: s.Key}).CheckTransfer(recovered) != nil {
		t.Fatal("restart reconstruction")
	}
	for _, path := range []string{"transfers/submit", "transfers/commit-status"} {
		before := m.calls
		w = issuanceRequest(s, path, raw, true, true)
		if w.Code != 200 || m.calls != before+1 || bytes.Contains(w.Body.Bytes(), []byte("COMMITTED_VALID")) {
			t.Fatal(w.Code, w.Body.String())
		}
	}
	if w = issuanceRequest(s, "issuances/submit", raw, true, true); w.Code != 400 {
		t.Fatal("cross-function artifact accepted")
	}
	artifact.Command.Quantity++
	if s.CheckTransfer(artifact) == nil {
		t.Fatal("tamper accepted")
	}
	artifact = frame.Data
	artifact.Function = "IssueANSH"
	artifact.MAC = commandMAC(s.Key, artifact)
	if s.CheckTransfer(artifact) == nil {
		t.Fatal("wrong function")
	}
	m.err = context.DeadlineExceeded
	before := m.calls
	w = issuanceRequest(s, "transfers/submit", raw, true, true)
	if w.Code != 503 || m.calls != before+1 || !bytes.Contains(w.Body.Bytes(), []byte("UNKNOWN")) {
		t.Fatal("unsafe retry/commit", w.Body.String())
	}
}
func TestMalformedTransferNeverEndorses(t *testing.T) {
	good, _ := json.Marshal(transferCommand())
	for _, raw := range [][]byte{[]byte(`{}`), []byte(`null`), bytes.Replace(good, []byte(`"quantity":4`), []byte(`"quantity":0`), 1), bytes.Replace(good, []byte(`"quantity":4`), []byte(`"quantity":-1`), 1), bytes.Replace(good, []byte(`"quantity":4`), []byte(`"quantity":1.5`), 1), bytes.Replace(good, []byte(`"quantity":4`), []byte(`"quantity":9007199254740992`), 1), bytes.Replace(good, []byte(`"quantity":4`), []byte(`"quantity":4,"quantity":4`), 1), bytes.Replace(good, []byte(`"quantity"`), []byte(`"Quantity"`), 1), bytes.Replace(good, []byte(`"command_version":1`), []byte(`"command_version":2`), 1), bytes.Replace(good, []byte(`"to_holder_id":"60000000-0000-4000-8000-000000000001"`), []byte(`"to_holder_id":"`+command().IssuerID+`"`), 1)} {
		m := &transferMock{}
		w := issuanceRequest(&Service{Ledger: m, Key: bytes.Repeat([]byte{1}, 32)}, "transfers/prepare", raw, true, true)
		if w.Code != 400 || m.prepares != 0 {
			t.Fatal("bad command reached endorsement", w.Code)
		}
	}
}
func TestTransferPreparationErrors(t *testing.T) {
	const insufficient = `chaincode response 500, {"code":"INSUFFICIENT_BALANCE","message":"Sender has insufficient ANSH."}`
	body, _ := json.Marshal(transferCommand())
	for _, tc := range []struct {
		messages []string
		status   int
		code     string
	}{
		{[]string{insufficient, insufficient}, 409, "INSUFFICIENT_BALANCE"},
		{[]string{operationConflict}, 409, "IDEMPOTENCY_CONFLICT"},
		{[]string{propertyMissing}, 404, "PROPERTY_NOT_FOUND"},
		{[]string{insufficient, propertyMissing}, 503, "LEDGER_UNAVAILABLE"},
		{[]string{"not found private host"}, 503, "LEDGER_UNAVAILABLE"},
		{[]string{supplyExceeded}, 503, "LEDGER_UNAVAILABLE"},
	} {
		m := &transferMock{mockLedger: mockLedger{err: preparationError(tc.messages...)}}
		w := issuanceRequest(&Service{Ledger: m, Key: bytes.Repeat([]byte{1}, 32)}, "transfers/prepare", body, true, true)
		if w.Code != tc.status || !bytes.Contains(w.Body.Bytes(), []byte(tc.code)) || bytes.Contains(w.Body.Bytes(), []byte("private")) {
			t.Fatal(w.Code, w.Body.String())
		}
	}
	if err := classifyIssuancePreparation(preparationError(insufficient)); err == nil || err.(*readFailure).httpStatus != 503 {
		t.Fatal("issuance accepted transfer error")
	}
}
func TestIssuanceArtifactEncodingUnchanged(t *testing.T) {
	a := IssuanceArtifact{1, "mychannel", "tokansh", Signer, "IssueANSH", issuanceCommand(), "digest", "tx", []byte{1}, []byte{2}, ""}
	// Explicit old struct layout guards the existing JSON/HMAC recovery contract.
	old := struct {
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
	}{a.Version, a.Channel, a.Chaincode, a.Signer, a.Function, a.Command, a.RequestDigest, a.TransactionID, a.Transaction, a.Creator, a.MAC}
	b, _ := json.Marshal(a)
	want, _ := json.Marshal(old)
	if !bytes.Equal(b, want) {
		t.Fatal("issuance artifact encoding changed")
	}
}

func TestV12IssuanceReceiptWithDistributedHoldings(t *testing.T) {
	c := issuanceCommand()
	principal := "test-only-principal"
	encoded, e := json.Marshal(struct {
		Function  string          `json:"function"`
		MSP       string          `json:"msp"`
		Principal string          `json:"principal"`
		Command   IssuanceCommand `json:"command"`
	}{"IssueANSH", "Org1MSP", principal, c})
	if e != nil {
		t.Fatal(e)
	}
	sum := sha256.Sum256(encoded)
	result := IssuanceResult{c.PropertyID, command().IssuerID, c.OperationID, "test-only-id", 40, 60, 40, 40}
	op := IssuanceOperation{1, c.OperationID, "Org1MSP", principal, "IssueANSH", hex.EncodeToString(sum[:]), c.PropertyID, command().IssuerID, 40, "test-only-id", result}
	body, _ := json.Marshal(op)
	ledger := &readLedger{body: body}
	s := &Service{Ledger: ledger}
	if _, e := s.ReadIssuance(context.Background(), "GetIssuanceOperation", c.OperationID); e != nil {
		t.Fatal("v1.2 receipt rejected", e)
	}
	for _, amount := range []int64{39, 61} {
		op.Result.IssuerBalance = amount
		ledger.body, _ = json.Marshal(op)
		if _, e := s.ReadIssuance(context.Background(), "GetIssuanceOperation", c.OperationID); e == nil {
			t.Fatal("invalid inventory accepted")
		}
	}
}
