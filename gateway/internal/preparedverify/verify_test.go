package preparedverify

import (
	"bytes"
	"crypto/ecdsa"
	"crypto/elliptic"

	"crypto/rand"

	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/asn1"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"encoding/pem"
	"math/big"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	common "github.com/hyperledger/fabric-protos-go-apiv2/common"
	gp "github.com/hyperledger/fabric-protos-go-apiv2/gateway"
	"github.com/hyperledger/fabric-protos-go-apiv2/ledger/rwset"
	"github.com/hyperledger/fabric-protos-go-apiv2/ledger/rwset/kvrwset"
	"github.com/hyperledger/fabric-protos-go-apiv2/msp"
	"github.com/hyperledger/fabric-protos-go-apiv2/peer"
	"google.golang.org/protobuf/proto"
	"tokansh/gateway/internal/registration"
)

func marshal(t *testing.T, m proto.Message) []byte {
	t.Helper()
	b, e := proto.Marshal(m)
	if e != nil {
		t.Fatal(e)
	}
	return b
}
func certificate(t *testing.T, root *x509.Certificate, key *ecdsa.PrivateKey, role string) (*x509.Certificate, *ecdsa.PrivateKey) {
	t.Helper()
	k, e := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if e != nil {
		t.Fatal(e)
	}
	c := &x509.Certificate{SerialNumber: big.NewInt(time.Now().UnixNano()), Subject: pkix.Name{CommonName: "test-only", OrganizationalUnit: []string{role}}, NotBefore: time.Now().Add(-time.Hour), NotAfter: time.Now().Add(time.Hour), KeyUsage: x509.KeyUsageDigitalSignature, BasicConstraintsValid: true}
	if root == nil {
		c.IsCA = true
		c.KeyUsage |= x509.KeyUsageCertSign
		root = c
		key = k
	}
	der, e := x509.CreateCertificate(rand.Reader, c, root, &k.PublicKey, key)
	if e != nil {
		t.Fatal(e)
	}
	parsed, e := x509.ParseCertificate(der)
	if e != nil {
		t.Fatal(e)
	}
	return parsed, k
}
func sign(t *testing.T, k *ecdsa.PrivateKey, b []byte) []byte {
	t.Helper()
	r, s, e := ecdsa.Sign(rand.Reader, k, hash(b))
	if e != nil {
		t.Fatal(e)
	}
	half := new(big.Int).Rsh(new(big.Int).Set(k.Params().N), 1)
	if s.Cmp(half) > 0 {
		s.Sub(k.Params().N, s)
	}
	v, e := asn1.Marshal(struct{ R, S *big.Int }{r, s})
	if e != nil {
		t.Fatal(e)
	}
	return v
}
func fixture(t *testing.T) (Input, map[string]*x509.Certificate, *peer.ChaincodeActionPayload) {
	c := registration.Command{CommandVersion: 1, OperationID: "edaeabd1-78e9-4e9d-a808-92affc2a81af", PropertyID: "10000000-0000-4000-8000-000000000001", IssuerID: "20000000-0000-4000-8000-000000000001", ApprovalReference: "30000000-0000-4000-8000-000000000001", ApprovalDigest: strings.Repeat("a", 64), ApprovedSupply: 100, IssuePriceMinor: "1000", Currency: "INR"}
	b, e := json.Marshal(c)
	if e != nil {
		t.Fatal(e)
	}
	creator := marshal(t, &msp.SerializedIdentity{Mspid: "Org1MSP", IdBytes: []byte("test-only creator; evidence parser is tested below full pinned-creator gate")})
	sh := marshal(t, &common.SignatureHeader{Creator: creator, Nonce: bytes.Repeat([]byte{1}, 24)})
	txid := hex.EncodeToString(hash(bytes.Repeat([]byte{1}, 24), creator))
	ch := marshal(t, &common.ChannelHeader{Type: int32(common.HeaderType_ENDORSER_TRANSACTION), ChannelId: "mychannel", TxId: txid, Extension: marshal(t, &peer.ChaincodeHeaderExtension{ChaincodeId: &peer.ChaincodeID{Name: "tokansh"}})})
	inv := marshal(t, &peer.ChaincodeInvocationSpec{ChaincodeSpec: &peer.ChaincodeSpec{ChaincodeId: &peer.ChaincodeID{Name: "tokansh"}, Input: &peer.ChaincodeInput{Args: [][]byte{[]byte("RegisterApprovedProperty"), b}}}})
	proposal := marshal(t, &peer.ChaincodeProposalPayload{Input: inv})
	result, e := json.Marshal(registration.RegistrationResult{PropertyID: c.PropertyID, OperationID: c.OperationID, TransactionID: txid})
	if e != nil {
		t.Fatal(e)
	}
	principal := base64.StdEncoding.EncodeToString([]byte("x509::CN=User1@org1.example.com,OU=client,L=San Francisco,ST=California,C=US::CN=ca.org1.example.com,O=org1.example.com,L=San Francisco,ST=California,C=US"))
	digestBytes, _ := json.Marshal(struct {
		Function  string               `json:"function"`
		MSP       string               `json:"msp"`
		Principal string               `json:"principal"`
		Command   registration.Command `json:"command"`
	}{"RegisterApprovedProperty", "Org1MSP", principal, c})
	property := registration.Property{SchemaVersion: 1, PropertyID: c.PropertyID, IssuerID: c.IssuerID, ApprovalReference: c.ApprovalReference, ApprovalDigest: c.ApprovalDigest, ApprovedSupply: c.ApprovedSupply, IssuePriceMinor: c.IssuePriceMinor, Currency: c.Currency, RegisteredByMSP: "Org1MSP", RegisteredByPrincipal: principal, RegistrationOperationID: c.OperationID, RegistrationTransactionID: txid, ProposalTimestamp: time.Now().UTC().Format(time.RFC3339Nano)}
	operation := registration.Operation{SchemaVersion: 1, OperationID: c.OperationID, PropertyID: c.PropertyID, AuthorizingMSP: "Org1MSP", AuthorizingPrincipal: principal, RequestDigest: hex.EncodeToString(hash(digestBytes)), Function: "RegisterApprovedProperty", OriginalTransactionID: txid, Result: registration.RegistrationResult{PropertyID: c.PropertyID, OperationID: c.OperationID, TransactionID: txid}}
	pvalue, _ := json.Marshal(property)
	ovalue, _ := json.Marshal(operation)
	writes := marshal(t, &rwset.TxReadWriteSet{NsRwset: []*rwset.NsReadWriteSet{{Namespace: "tokansh", Rwset: marshal(t, &kvrwset.KVRWSet{Writes: []*kvrwset.KVWrite{{Key: "\x00property\x00" + c.PropertyID + "\x00", Value: pvalue}, {Key: "\x00operation\x00Org1MSP\x00" + c.OperationID + "\x00", Value: ovalue}}})}}})
	response := marshal(t, &peer.ProposalResponsePayload{ProposalHash: hash(ch, sh, proposal), Extension: marshal(t, &peer.ChaincodeAction{ChaincodeId: &peer.ChaincodeID{Name: "tokansh"}, Response: &peer.Response{Status: 200, Payload: result}, Results: writes})})
	cap := &peer.ChaincodeActionPayload{ChaincodeProposalPayload: proposal, Action: &peer.ChaincodeEndorsedAction{ProposalResponsePayload: response}}
	roots := map[string]*x509.Certificate{}
	for _, id := range []string{"Org1MSP", "Org2MSP"} {
		root, key := certificate(t, nil, nil, "ca")
		peerCert, peerKey := certificate(t, root, key, "peer")
		roots[id] = root
		endorser := marshal(t, &msp.SerializedIdentity{Mspid: id, IdBytes: pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: peerCert.Raw})})
		cap.Action.Endorsements = append(cap.Action.Endorsements, &peer.Endorsement{Endorser: endorser, Signature: sign(t, peerKey, append(append([]byte{}, response...), endorser...))})
	}
	a := registration.Artifact{TransactionID: txid, Creator: creator, Command: c}
	a.Transaction = marshal(t, &gp.PreparedTransaction{TransactionId: txid, Envelope: &common.Envelope{Payload: marshal(t, &common.Payload{Header: &common.Header{ChannelHeader: ch, SignatureHeader: sh}, Data: marshal(t, &peer.Transaction{Actions: []*peer.TransactionAction{{Header: sh, Payload: marshal(t, cap)}}})})}})
	return Input{Artifact: a, Frozen: b, TransactionID: txid}, roots, cap
}
func replaceAction(t *testing.T, in Input, cap *peer.ChaincodeActionPayload) Input {
	var prepared gp.PreparedTransaction
	_ = proto.Unmarshal(in.Artifact.Transaction, &prepared)
	var payload common.Payload
	_ = proto.Unmarshal(prepared.Envelope.Payload, &payload)
	var tx peer.Transaction
	_ = proto.Unmarshal(payload.Data, &tx)
	tx.Actions[0].Payload = marshal(t, cap)
	payload.Data = marshal(t, &tx)
	prepared.Envelope.Payload = marshal(t, &payload)
	in.Artifact.Transaction = marshal(t, &prepared)
	return in
}
func TestEndorsementEvidence(t *testing.T) {
	in, roots, _ := fixture(t)
	if e := verifyEndorsedTransaction(in, time.Now(), roots); e != nil {
		t.Fatal(e)
	}
	for _, kind := range []string{"signature", "payload", "duplicate", "missing", "unknown MSP", "wrong trust", "malformed", "txid", "command", "proposal"} {
		t.Run(kind, func(t *testing.T) {
			in, roots, cap := fixture(t)
			switch kind {
			case "signature":
				cap.Action.Endorsements[0].Signature[0] ^= 1
			case "payload":
				cap.Action.ProposalResponsePayload[0] ^= 1
			case "duplicate":
				cap.Action.Endorsements[1] = cap.Action.Endorsements[0]
			case "missing":
				cap.Action.Endorsements = cap.Action.Endorsements[:1]
			case "unknown MSP":
				cap.Action.Endorsements[0].Endorser = marshal(t, &msp.SerializedIdentity{Mspid: "UntrustedMSP"})
			case "wrong trust":
				roots["Org1MSP"], _ = certificate(t, nil, nil, "ca")
			case "malformed":
				in.Artifact.Transaction = []byte{255}
			case "txid":
				in.TransactionID = strings.Repeat("0", 64)
			case "command":
				in.Frozen = bytes.Replace(in.Frozen, []byte(`"1000"`), []byte(`"1001"`), 1)
			case "proposal":
				cap.ChaincodeProposalPayload = append(cap.ChaincodeProposalPayload, 0x08, 0x01)
			}
			if kind != "malformed" {
				in = replaceAction(t, in, cap)
			}
			if verifyEndorsedTransaction(in, time.Now(), roots) == nil {
				t.Fatal("accepted invalid evidence")
			}
		})
	}
}
func TestTrustRolesExpiryAndHighS(t *testing.T) {
	root, k := certificate(t, nil, nil, "ca")
	leaf, key := certificate(t, root, k, "peer")
	trusted(leaf, root, "peer", time.Now())
	for _, kind := range []string{"role", "expiry", "highS"} {
		t.Run(kind, func(t *testing.T) {
			defer func() {
				if recover() == nil {
					t.Error("accepted")
				}
			}()
			if kind == "role" {
				trusted(leaf, root, "client", time.Now())
			} else if kind == "expiry" {
				trusted(leaf, root, "peer", time.Now().Add(2*time.Hour))
			} else {
				sig := sign(t, key, []byte("test"))
				var v struct{ R, S *big.Int }
				_, _ = asn1.Unmarshal(sig, &v)
				v.S.Sub(key.Params().N, v.S)
				sig, _ = asn1.Marshal(v)
				signature(leaf, []byte("test"), sig)
			}
		})
	}
}
func TestStrictInputsAndOuterGate(t *testing.T) {
	for _, b := range []string{`{"secret":"a","secret":"b"}`, `{"unexpected":1}`, `{bad`} {
		var v Input
		if StrictJSON([]byte(b), &v) == nil {
			t.Error("accepted", b)
		}
	}
	in, _, _ := fixture(t)
	if Verify(in, time.Now()) == nil {
		t.Fatal("outer pin/HMAC gate bypassed")
	}
	var bad common.ChannelHeader
	if wire([]byte{0x20, 0x01}, bad.ProtoReflect().Descriptor()) == nil {
		t.Fatal("wrong scalar wire type accepted")
	}
	var header common.ChannelHeader
	if wire([]byte{0x08, 1, 0x08, 1}, header.ProtoReflect().Descriptor()) == nil {
		t.Fatal("duplicate protobuf field accepted")
	}
}
func TestLocalTrustProfile(t *testing.T) {
	base := t.TempDir()
	for _, org := range []string{"1", "2"} {
		dir := filepath.Join(base, "org"+org+".example.com/msp")
		if e := os.MkdirAll(filepath.Join(dir, "cacerts"), 0700); e != nil {
			t.Fatal(e)
		}
		root, _ := certificate(t, nil, nil, "ca")
		config := "NodeOUs:\n  Enable: true\n"
		for _, role := range []string{"Client", "Peer", "Admin", "Orderer"} {
			config += "  " + role + "OUIdentifier:\n    Certificate: cacerts/ca.org" + org + ".example.com-cert.pem\n    OrganizationalUnitIdentifier: " + strings.ToLower(role) + "\n"
		}
		if e := os.WriteFile(filepath.Join(dir, "config.yaml"), []byte(config), 0600); e != nil {
			t.Fatal(e)
		}
		if e := os.WriteFile(filepath.Join(dir, "cacerts/ca.org"+org+".example.com-cert.pem"), pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: root.Raw}), 0600); e != nil {
			t.Fatal(e)
		}
	}
	if _, e := LoadTrust(base, time.Now()); e != nil {
		t.Fatal(e)
	}
	configPath := filepath.Join(base, "org1.example.com/msp/config.yaml")
	configBytes, e := os.ReadFile(configPath)
	if e != nil {
		t.Fatal(e)
	}
	if e = os.WriteFile(configPath, bytes.Replace(configBytes, []byte("Enable: true"), []byte("Enable: false"), 1), 0600); e != nil {
		t.Fatal(e)
	}
	if _, e = LoadTrust(base, time.Now()); e == nil {
		t.Fatal("unreviewed NodeOU policy accepted")
	}
	if e = os.WriteFile(configPath, configBytes, 0600); e != nil {
		t.Fatal(e)
	}
	if _, e = LoadTrust(base, time.Now().Add(2*time.Hour)); e == nil {
		t.Fatal("expired trust accepted")
	}
	if e := os.Mkdir(filepath.Join(base, "org1.example.com/msp/crls"), 0700); e != nil {
		t.Fatal(e)
	}
	_ = os.WriteFile(filepath.Join(base, "org1.example.com/msp/crls/unknown"), []byte("test-only"), 0600)
	if _, e := LoadTrust(base, time.Now()); e == nil {
		t.Fatal("unverified CRL accepted")
	}
}
