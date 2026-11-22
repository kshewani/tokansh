package registration

import (
	"bytes"
	"context"
	"encoding/hex"
	"encoding/json"
	"errors"
	common "github.com/hyperledger/fabric-protos-go-apiv2/common"
	gp "github.com/hyperledger/fabric-protos-go-apiv2/gateway"
	"github.com/hyperledger/fabric-protos-go-apiv2/msp"
	"github.com/hyperledger/fabric-protos-go-apiv2/peer"
	"google.golang.org/protobuf/proto"
	"net/http"
	"net/http/httptest"
	"os"
	"testing"
)

func marshal(v proto.Message) []byte {
	b, e := proto.Marshal(v)
	if e != nil {
		panic(e)
	}
	return b
}
func command() Command {
	return Command{1, "10000000-0000-4000-8000-000000000001", "20000000-0000-4000-8000-000000000001", "30000000-0000-4000-8000-000000000001", "40000000-0000-4000-8000-000000000001", string(bytes.Repeat([]byte("a"), 64)), 100000, "1000000", "INR"}
}
func prepared(t *testing.T, c Command) ([]byte, []byte) {
	t.Helper()
	cert, e := os.ReadFile("../../../chaincode/tokansh/contract/testdata/org1-user1-public.pem")
	if e != nil {
		t.Fatal(e)
	}
	creator := marshal(&msp.SerializedIdentity{Mspid: "Org1MSP", IdBytes: cert})
	args, _ := json.Marshal(c)
	input := marshal(&peer.ChaincodeInvocationSpec{ChaincodeSpec: &peer.ChaincodeSpec{ChaincodeId: &peer.ChaincodeID{Name: "tokansh"}, Input: &peer.ChaincodeInput{Args: [][]byte{[]byte("RegisterApprovedProperty"), args}}}})
	tx := marshal(&peer.Transaction{Actions: []*peer.TransactionAction{{Payload: marshal(&peer.ChaincodeActionPayload{ChaincodeProposalPayload: marshal(&peer.ChaincodeProposalPayload{Input: input})})}}})
	return marshal(&gp.PreparedTransaction{TransactionId: "test-only-id", Envelope: &common.Envelope{Payload: marshal(&common.Payload{Header: &common.Header{ChannelHeader: marshal(&common.ChannelHeader{ChannelId: "mychannel", TxId: "test-only-id"}), SignatureHeader: marshal(&common.SignatureHeader{Creator: creator})}, Data: tx})}}), creator
}

type mockLedger struct {
	tx, creator []byte
	err         error
	calls       int
}

func (m *mockLedger) Read(context.Context, string, ...string) ([]byte, error) {
	m.calls++
	return []byte(`{"contract":"tokansh","schema_version":1,"functions":["GetContractInfo","GetRegisteredProperty","GetOperation","RegisterApprovedProperty"],"supply_interpretation":"LIFETIME_CUMULATIVE_ISSUANCE_CEILING"}`), m.err
}
func (m *mockLedger) Prepare(context.Context, Command) (string, []byte, []byte, error) {
	m.calls++
	return "test-only-id", m.tx, m.creator, m.err
}
func (m *mockLedger) Submit(context.Context, Artifact) error { m.calls++; return m.err }
func (m *mockLedger) Status(context.Context, Artifact) (Status, error) {
	m.calls++
	return Status{"test-only-id", 0, 4, true}, m.err
}
func TestArtifactIntegrityAndTypedAllowlist(t *testing.T) {
	tx, creator := prepared(t, command())
	m := &mockLedger{tx: tx, creator: creator}
	s := &Service{Ledger: m, Key: bytes.Repeat([]byte{1}, 32)}
	a, e := s.Prepare(context.Background(), command())
	if e != nil {
		t.Fatal(e)
	}
	b, _ := json.Marshal(a)
	var recovered Artifact
	if strict(b, &recovered) != nil || s.Check(recovered) != nil {
		t.Fatal("restart artifact failed")
	}
	a.Channel = "wrong"
	a.MAC = s.mac(a)
	if s.Check(a) == nil {
		t.Fatal("wrong channel accepted")
	}
	a = recovered
	a.Transaction = []byte("corrupted")
	a.MAC = s.mac(a)
	if s.Check(a) == nil {
		t.Fatal("malformed endorsed bytes accepted")
	}
	a = recovered
	a.Command.ApprovedSupply++
	if s.Check(a) == nil {
		t.Fatal("tampered command accepted")
	}
	if _, e = s.Read(context.Background(), "CreateAsset", ""); e == nil {
		t.Fatal("arbitrary function allowed")
	}
}
func TestAuthenticationAndSanitization(t *testing.T) {
	tx, c := prepared(t, command())
	m := &mockLedger{tx: tx, creator: c}
	key := bytes.Repeat([]byte{1}, 32)
	op := bytes.Repeat([]byte{2}, 32)
	handler := Handler(&Service{Ledger: m, Key: key}, op)
	for _, tc := range []struct {
		token, operator, origin string
		status                  int
	}{{"", "", "", 401}, {hex.EncodeToString(key), "", "", 403}, {hex.EncodeToString(key), hex.EncodeToString(op), "http://localhost:5173", 403}} {
		r := httptest.NewRequest("POST", "/v1/tokansh/property-registrations/prepare", bytes.NewBufferString(`{}`))
		r.Header.Set("Authorization", "Bearer "+tc.token)
		r.Header.Set("X-Operator-Capability", tc.operator)
		r.Header.Set("Origin", tc.origin)
		w := httptest.NewRecorder()
		handler.ServeHTTP(w, r)
		if w.Code != tc.status {
			t.Fatal(w.Code)
		}
		if m.calls != 0 {
			t.Fatal("unauthorized SDK interaction")
		}
	}
	m.err = errors.New("secret internal topology")
	r := httptest.NewRequest(http.MethodGet, "/v1/tokansh/contract-info", nil)
	r.Header.Set("Authorization", "Bearer "+hex.EncodeToString(key))
	w := httptest.NewRecorder()
	handler.ServeHTTP(w, r)
	if w.Code != 503 || bytes.Contains(w.Body.Bytes(), []byte("secret")) {
		t.Fatal("error leak")
	}
	w = httptest.NewRecorder()
	Handler(&Service{}, nil).ServeHTTP(w, r)
	if w.Code != 503 {
		t.Fatal("missing configuration accepted")
	}
}
func TestCommandStrictness(t *testing.T) {
	b, _ := json.Marshal(command())
	if _, e := DecodeCommand(b); e != nil {
		t.Fatal(e)
	}
	for _, bad := range []string{string(b[:len(b)-1]) + `,"currency":"INR"}`, string(b[:len(b)-1]) + `,"extra":1}`, string(bytes.Replace(b, []byte("command_version"), []byte("Command_Version"), 1))} {
		if _, e := DecodeCommand([]byte(bad)); e == nil {
			t.Fatal("invalid schema accepted")
		}
	}
}

func TestPrepareAndStatusHTTP(t *testing.T) {
	tx, c := prepared(t, command())
	m := &mockLedger{tx: tx, creator: c}
	key := bytes.Repeat([]byte{1}, 32)
	op := bytes.Repeat([]byte{2}, 32)
	service := &Service{Ledger: m, Key: key}
	handler := Handler(service, op)
	request := func(path string, body []byte) *httptest.ResponseRecorder {
		r := httptest.NewRequest("POST", "/v1/tokansh/"+path, bytes.NewReader(body))
		r.Header.Set("Authorization", "Bearer "+hex.EncodeToString(key))
		r.Header.Set("X-Operator-Capability", hex.EncodeToString(op))
		w := httptest.NewRecorder()
		handler.ServeHTTP(w, r)
		return w
	}
	b, _ := json.Marshal(command())
	w := request("property-registrations/prepare", b)
	if w.Code != 200 {
		t.Fatal(w.Body.String())
	}
	var frame struct {
		Data Artifact `json:"data"`
	}
	if json.Unmarshal(w.Body.Bytes(), &frame) != nil {
		t.Fatal("bad frame")
	}
	encoded, _ := json.Marshal(frame.Data)
	w = request("commit-status", encoded)
	if w.Code != 200 {
		t.Fatal(w.Body.String())
	}
	w = request("property-registrations/submit", encoded)
	if w.Code != 200 || bytes.Contains(w.Body.Bytes(), []byte("COMMITTED_VALID")) {
		t.Fatal("premature commitment")
	}
	for _, name := range []string{"Org2 endorser", "Lite Peer", "Committing Peer"} {
		t.Run(name, func(t *testing.T) {
			m.err = errors.New("private network detail")
			w := request("commit-status", encoded)
			if w.Code != 503 || bytes.Contains(w.Body.Bytes(), []byte("private network detail")) {
				t.Fatal("unsafe failure")
			}
		})
	}
}

type readLedger struct {
	mockLedger
	body []byte
}

func (m *readLedger) Read(context.Context, string, ...string) ([]byte, error) { return m.body, nil }
func TestTypedPropertyAndOperationReads(t *testing.T) {
	c := command()
	p := Property{1, c.PropertyID, c.IssuerID, c.ApprovalReference, c.ApprovalDigest, c.ApprovedSupply, c.IssuePriceMinor, c.Currency, "Org1MSP", "test-only-principal", c.OperationID, "test-only-id", "2026-11-18T00:00:00Z"}
	op := Operation{1, c.OperationID, "Org1MSP", "test-only-principal", "RegisterApprovedProperty", commandDigest(c), c.PropertyID, "test-only-id", RegistrationResult{c.PropertyID, c.OperationID, "test-only-id"}}
	for _, tc := range []struct {
		function, id string
		body         any
	}{{"GetRegisteredProperty", c.PropertyID, p}, {"GetOperation", c.OperationID, op}} {
		t.Run(tc.function, func(t *testing.T) {
			b, _ := json.Marshal(tc.body)
			ledger := &readLedger{body: b}
			s := &Service{Ledger: ledger}
			if _, e := s.Read(context.Background(), tc.function, tc.id); e != nil {
				t.Fatal(e)
			}
			ledger.body = []byte(`{"schema_version":1}`)
			if _, e := s.Read(context.Background(), tc.function, tc.id); e == nil {
				t.Fatal("malformed upstream accepted")
			}
		})
	}
}
