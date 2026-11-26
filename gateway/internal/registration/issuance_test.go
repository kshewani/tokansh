package registration

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	common "github.com/hyperledger/fabric-protos-go-apiv2/common"
	gp "github.com/hyperledger/fabric-protos-go-apiv2/gateway"
	"github.com/hyperledger/fabric-protos-go-apiv2/peer"
	"google.golang.org/grpc/codes"
	"google.golang.org/protobuf/proto"
	"net/http/httptest"
	"testing"
)

type issuanceMock struct {
	mockLedger
	body     []byte
	function string
	args     []string
	prepares int
}

func (m *issuanceMock) Read(_ context.Context, f string, args ...string) ([]byte, error) {
	m.function = f
	m.args = args
	if f == "GetContractInfo" && m.body == nil {
		return []byte(`{"contract":"tokansh","schema_version":1,"functions":["GetContractInfo","GetRegisteredProperty","GetOperation","RegisterApprovedProperty","IssueANSH","GetIssuanceState","GetBalance","GetIssuanceOperation","TransferANSH"],"supply_interpretation":"ONE_TIME_FULL_SUPPLY_ISSUANCE"}`), nil
	}
	return m.body, m.err
}
func (m *issuanceMock) PrepareIssuance(context.Context, IssuanceCommand) (string, []byte, []byte, error) {
	m.prepares++
	return "test-only-id", m.tx, m.creator, m.err
}
func issuanceCommand() IssuanceCommand {
	return IssuanceCommand{1, command().OperationID, command().PropertyID, 40}
}
func issuancePrepared(t *testing.T) ([]byte, []byte) {
	b, creator := prepared(t, command())
	var p gp.PreparedTransaction
	var pl common.Payload
	var tx peer.Transaction
	var a peer.ChaincodeActionPayload
	var cp peer.ChaincodeProposalPayload
	for _, v := range []struct {
		b []byte
		m proto.Message
	}{{b, &p}} {
		if proto.Unmarshal(v.b, v.m) != nil {
			t.Fatal("fixture")
		}
	}
	proto.Unmarshal(p.Envelope.Payload, &pl)
	proto.Unmarshal(pl.Data, &tx)
	proto.Unmarshal(tx.Actions[0].Payload, &a)
	proto.Unmarshal(a.ChaincodeProposalPayload, &cp)
	c, _ := json.Marshal(issuanceCommand())
	cp.Input = marshal(&peer.ChaincodeInvocationSpec{ChaincodeSpec: &peer.ChaincodeSpec{ChaincodeId: &peer.ChaincodeID{Name: "tokansh"}, Input: &peer.ChaincodeInput{Args: [][]byte{[]byte("IssueANSH"), c}}}})
	a.ChaincodeProposalPayload = marshal(&cp)
	tx.Actions[0].Payload = marshal(&a)
	pl.Data = marshal(&tx)
	p.Envelope.Payload = marshal(&pl)
	return marshal(&p), creator
}
func issuanceRequest(s *Service, path string, body []byte, auth, operator bool) *httptest.ResponseRecorder {
	r := httptest.NewRequest("POST", "/v1/tokansh/"+path, bytes.NewReader(body))
	if auth {
		r.Header.Set("Authorization", "Bearer "+hex.EncodeToString(s.Key))
	}
	if operator {
		r.Header.Set("X-Operator-Capability", hex.EncodeToString(bytes.Repeat([]byte{2}, 32)))
	}
	w := httptest.NewRecorder()
	Handler(s, bytes.Repeat([]byte{2}, 32)).ServeHTTP(w, r)
	return w
}
func TestIssuanceCommandValidation(t *testing.T) {
	b, _ := json.Marshal(issuanceCommand())
	if _, e := DecodeIssuanceCommand(b); e != nil {
		t.Fatal(e)
	}
	for _, raw := range []string{`{}`, `{"command_version":1,"operation_id":"bad","property_id":"bad","quantity":1}`, string(bytes.Replace(b, []byte(`40`), []byte(`0`), 1)), string(bytes.Replace(b, []byte(`40`), []byte(`-1`), 1)), string(bytes.Replace(b, []byte(`40`), []byte(`1.5`), 1)), string(bytes.Replace(b, []byte(`40`), []byte(`9007199254740992`), 1)), string(bytes.Replace(b, []byte(`40`), []byte(`9223372036854775808`), 1)), string(bytes.Replace(b, []byte(`"quantity":40`), []byte(`"quantity":40,"quantity":40`), 1)), string(bytes.Replace(b, []byte(`"quantity"`), []byte(`"Quantity"`), 1)), string(b[:len(b)-1]) + `,"issuer_id":"fake"}`} {
		if _, e := DecodeIssuanceCommand([]byte(raw)); e == nil {
			t.Fatalf("accepted %s", raw)
		}
	}
	c := issuanceCommand()
	c.Quantity = maxIssuance
	b, _ = json.Marshal(c)
	if _, e := DecodeIssuanceCommand(b); e != nil {
		t.Fatal("precision boundary rejected")
	}
}
func TestIssuancePrepareAuthorizationIntegrityAndUnknown(t *testing.T) {
	tx, creator := issuancePrepared(t)
	m := &issuanceMock{mockLedger: mockLedger{tx: tx, creator: creator}}
	s := &Service{Ledger: m, Key: bytes.Repeat([]byte{1}, 32)}
	c, _ := json.Marshal(issuanceCommand())
	for _, tc := range []struct {
		auth, op bool
		status   int
	}{{false, false, 401}, {true, false, 403}, {true, true, 200}} {
		w := issuanceRequest(s, "issuances/prepare", c, tc.auth, tc.op)
		if w.Code != tc.status {
			t.Fatal(w.Code, w.Body.String())
		}
	}
	if m.prepares != 1 {
		t.Fatal("unauthorized preparation")
	}
	a, e := s.PrepareIssuance(context.Background(), issuanceCommand())
	if e != nil {
		t.Fatal(e)
	}
	original := a
	a.Command.Quantity++
	if s.CheckIssuance(a) == nil {
		t.Fatal("tamper")
	}
	a = original
	a.Function = "RegisterApprovedProperty"
	a.MAC = s.issuanceMAC(a)
	if s.CheckIssuance(a) == nil {
		t.Fatal("function confusion")
	}
	a = original
	a.Transaction, _ = prepared(t, command())
	a.MAC = s.issuanceMAC(a)
	if s.CheckIssuance(a) == nil {
		t.Fatal("registration bytes accepted")
	}
	a = original
	encoded, _ := json.Marshal(a)
	// Serialization/reconstruction remains valid across service restarts with the same key.
	var recovered IssuanceArtifact
	if strict(encoded, &recovered) != nil || (&Service{Key: s.Key}).CheckIssuance(recovered) != nil {
		t.Fatal("recovery")
	}
	w := issuanceRequest(s, "issuances/submit", encoded, true, true)
	if w.Code != 200 || bytes.Contains(w.Body.Bytes(), []byte("COMMITTED_VALID")) {
		t.Fatal(w.Body.String())
	}
	for _, failure := range []error{context.DeadlineExceeded, errors.New("private-peer secret detail")} {
		m.err = failure
		before := m.calls
		w = issuanceRequest(s, "issuances/submit", encoded, true, true)
		if w.Code != 503 || !bytes.Contains(w.Body.Bytes(), []byte("UNKNOWN")) || bytes.Contains(w.Body.Bytes(), []byte("private-peer")) || m.calls != before+1 {
			t.Fatal("unsafe ambiguous outcome", w.Body.String())
		}
	}
	m.err = nil
	w = issuanceRequest(s, "issuances/commit-status", encoded, true, true)
	if w.Code != 200 {
		t.Fatal(w.Body.String())
	}
	m.err = context.DeadlineExceeded
	w = issuanceRequest(s, "issuances/commit-status", encoded, true, true)
	if w.Code != 503 || !bytes.Contains(w.Body.Bytes(), []byte("UNKNOWN")) {
		t.Fatal(w.Body.String())
	}
}
func TestIssuanceTypedReads(t *testing.T) {
	c := issuanceCommand()
	issuer := command().IssuerID
	principal := "test-only-principal"
	result := IssuanceResult{c.PropertyID, issuer, c.OperationID, "test-only-id", 40, 40, 60, 40}
	b, _ := json.Marshal(struct {
		Function  string          `json:"function"`
		MSP       string          `json:"msp"`
		Principal string          `json:"principal"`
		Command   IssuanceCommand `json:"command"`
	}{"IssueANSH", "Org1MSP", principal, c})
	hash := sha256.Sum256(b)
	op := IssuanceOperation{1, c.OperationID, "Org1MSP", principal, "IssueANSH", hex.EncodeToString(hash[:]), c.PropertyID, issuer, 40, "test-only-id", result}
	for _, tc := range []struct {
		function, path string
		ids            []string
		value          any
	}{
		{"GetIssuanceState", "issuance-state/" + c.PropertyID, []string{c.PropertyID}, IssuanceState{1, c.PropertyID, issuer, 100, 0, 100}},
		{"GetBalance", "balances/" + c.PropertyID + "/" + issuer, []string{c.PropertyID, issuer}, Balance{1, c.PropertyID, issuer, 0}},
		{"GetIssuanceOperation", "issuance-operations/" + c.OperationID, []string{c.OperationID}, op},
	} {
		t.Run(tc.function, func(t *testing.T) {
			body, _ := json.Marshal(tc.value)
			m := &issuanceMock{body: body}
			s := &Service{Ledger: m, Key: bytes.Repeat([]byte{1}, 32)}
			if _, e := s.ReadIssuance(context.Background(), tc.function, tc.ids...); e != nil {
				t.Fatal(e)
			}
			if m.function != tc.function || len(m.args) != len(tc.ids) {
				t.Fatal("argument routing")
			}
			for i, v := range m.args {
				if v != tc.ids[i] {
					t.Fatal("argument order")
				}
			}
			r := httptest.NewRequest("GET", "/v1/tokansh/"+tc.path, nil)
			r.Header.Set("Authorization", "Bearer "+hex.EncodeToString(s.Key))
			w := httptest.NewRecorder()
			Handler(s, bytes.Repeat([]byte{2}, 32)).ServeHTTP(w, r)
			if w.Code != 200 {
				t.Fatal(w.Body.String())
			}
			for _, bad := range [][]byte{[]byte(`{}`), bytes.Replace(body, []byte(`"schema_version":1`), []byte(`"schema_version":2`), 1), bytes.Replace(body, []byte(`"property_id":"`+c.PropertyID+`"`), []byte(`"property_id":"wrong"`), 1)} {
				m.body = bad
				if _, e := s.ReadIssuance(context.Background(), tc.function, tc.ids...); e == nil {
					t.Fatal("bad ledger state accepted")
				}
			}
			if _, e := s.ReadIssuance(context.Background(), tc.function, "bad"); e == nil {
				t.Fatal("bad arguments")
			}
		})
	}
}
func TestIssuanceChaincodeErrors(t *testing.T) {
	for _, tc := range []struct {
		function, message, code string
		http                    int
	}{
		{"GetIssuanceState", propertyMissing, "PROPERTY_NOT_FOUND", 404},
		{"GetBalance", propertyMissing, "PROPERTY_NOT_FOUND", 404},
		{"GetIssuanceOperation", operationMissing, "OPERATION_NOT_FOUND", 404},
		{"IssueANSH", `chaincode response 500, {"code":"IDEMPOTENCY_CONFLICT","message":"Operation was already used with different parameters."}`, "IDEMPOTENCY_CONFLICT", 409},
		{"IssueANSH", `chaincode response 500, {"code":"ISSUANCE_LIMIT_EXCEEDED","message":"Requested issuance exceeds approved supply."}`, "ISSUANCE_LIMIT_EXCEEDED", 422},
		{"GetIssuanceState", operationMissing, "LEDGER_UNAVAILABLE", 503},
	} {
		var e *readFailure
		if !errors.As(classifyEvaluation(detailed(codes.Unknown, tc.message), tc.function), &e) || e.code != tc.code || e.httpStatus != tc.http {
			t.Fatal(tc, e)
		}
	}
}

func TestIssuanceInvalidCommandsNeverPrepare(t *testing.T) {
	good, _ := json.Marshal(issuanceCommand())
	for _, body := range []string{`{}`, `null`, string(bytes.Replace(good, []byte(`"quantity":40`), []byte(`"quantity":0`), 1)), string(bytes.Replace(good, []byte(`"quantity":40`), []byte(`"quantity":-1`), 1)), string(bytes.Replace(good, []byte(`"quantity":40`), []byte(`"quantity":1.5`), 1)), string(bytes.Replace(good, []byte(`"quantity":40`), []byte(`"quantity":9007199254740992`), 1)), string(bytes.Replace(good, []byte(`"command_version":1`), []byte(`"command_version":2`), 1)), string(bytes.Replace(good, []byte(`"quantity":40`), []byte(`"quantity":40,"quantity":40`), 1)), string(bytes.Replace(good, []byte(`"quantity":40`), []byte(`"quantity":40,"issuer_id":"spoof"`), 1)), string(bytes.Replace(good, []byte(`"quantity"`), []byte(`"Quantity"`), 1))} {
		m := &issuanceMock{}
		s := &Service{Ledger: m, Key: bytes.Repeat([]byte{1}, 32)}
		w := issuanceRequest(s, "issuances/prepare", []byte(body), true, true)
		if w.Code != 400 || m.prepares != 0 {
			t.Fatal("invalid command reached endorsement", body, w.Code)
		}
	}
}
