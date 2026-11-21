// Package preparedverify verifies offline evidence only; it has no Gateway client.
package preparedverify

import (
	"bytes"
	"crypto/ecdsa"
	"crypto/sha256"
	"crypto/x509"
	"encoding/asn1"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"encoding/pem"
	"errors"
	"fmt"
	"io"
	"math/big"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"time"

	common "github.com/hyperledger/fabric-protos-go-apiv2/common"
	gp "github.com/hyperledger/fabric-protos-go-apiv2/gateway"
	"github.com/hyperledger/fabric-protos-go-apiv2/ledger/rwset"
	"github.com/hyperledger/fabric-protos-go-apiv2/ledger/rwset/kvrwset"
	"github.com/hyperledger/fabric-protos-go-apiv2/msp"
	"github.com/hyperledger/fabric-protos-go-apiv2/peer"
	"google.golang.org/protobuf/encoding/protowire"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/reflect/protoreflect"
	"tokansh/gateway/internal/registration"
)

var invalid = errors.New("OFFLINE_VERIFICATION_FAILED")

func must(ok bool) {
	if !ok {
		panic(invalid)
	}
}

// Reject duplicate keys throughout JSON before typed decoding (including commands).
func StrictJSON(b []byte, target any) error {
	d := json.NewDecoder(bytes.NewReader(b))
	var value func() error
	value = func() error {
		tok, e := d.Token()
		if e != nil {
			return invalid
		}
		if delim, ok := tok.(json.Delim); ok {
			seen := map[string]bool{}
			for d.More() {
				if delim == '{' {
					k, e := d.Token()
					if e != nil {
						return invalid
					}
					s, ok := k.(string)
					if !ok || seen[s] {
						return invalid
					}
					seen[s] = true
				}
				if e := value(); e != nil {
					return e
				}
			}
			end, e := d.Token()
			if e != nil || (delim == '{' && end != json.Delim('}')) || (delim == '[' && end != json.Delim(']')) {
				return invalid
			}
		}
		return nil
	}
	if value() != nil {
		return invalid
	}
	if _, e := d.Token(); e != io.EOF {
		return invalid
	}
	var exactFields func([]byte, reflect.Type) bool
	exactFields = func(raw []byte, t reflect.Type) bool {
		if t.Kind() != reflect.Struct {
			return true
		}
		var fields map[string]json.RawMessage
		if json.Unmarshal(raw, &fields) != nil || len(fields) != t.NumField() {
			return false
		}
		for i := 0; i < t.NumField(); i++ {
			f := t.Field(i)
			v, ok := fields[strings.Split(f.Tag.Get("json"), ",")[0]]
			if !ok || bytes.Equal(bytes.TrimSpace(v), []byte("null")) || !exactFields(v, f.Type) {
				return false
			}
		}
		return true
	}
	if !exactFields(b, reflect.TypeOf(target).Elem()) {
		return invalid
	}
	dec := json.NewDecoder(bytes.NewReader(b))
	dec.DisallowUnknownFields()
	if dec.Decode(target) != nil {
		return invalid
	}
	return nil
}

// Verify wire structure, including nested known messages, before Unmarshal can
// discard duplicate singular fields or merge duplicate submessages.
func wire(b []byte, desc protoreflect.MessageDescriptor) error {
	seen := map[protowire.Number]bool{}
	for len(b) > 0 {
		n, t, k := protowire.ConsumeTag(b)
		if k < 0 {
			return invalid
		}
		b = b[k:]
		f := desc.Fields().ByNumber(protoreflect.FieldNumber(n))
		if f == nil {
			return invalid
		}
		expectedType := protowire.VarintType
		switch f.Kind() {
		case protoreflect.StringKind, protoreflect.BytesKind, protoreflect.MessageKind:
			expectedType = protowire.BytesType
		case protoreflect.Fixed32Kind, protoreflect.Sfixed32Kind, protoreflect.FloatKind:
			expectedType = protowire.Fixed32Type
		case protoreflect.Fixed64Kind, protoreflect.Sfixed64Kind, protoreflect.DoubleKind:
			expectedType = protowire.Fixed64Type
		}
		if t != expectedType && !(f.IsPacked() && t == protowire.BytesType) {
			return invalid
		}
		if seen[n] && !f.IsList() && !f.IsMap() {
			return invalid
		}
		seen[n] = true
		size := protowire.ConsumeFieldValue(n, t, b)
		if size < 0 {
			return invalid
		}
		if f.Kind() == protoreflect.MessageKind {
			if t != protowire.BytesType {
				return invalid
			}
			v, l := protowire.ConsumeBytes(b)
			if l < 0 || wire(v, f.Message()) != nil {
				return invalid
			}
		}
		b = b[size:]
	}
	return nil
}
func decode(b []byte, m proto.Message) {
	must(len(b) > 0 && wire(b, m.ProtoReflect().Descriptor()) == nil && proto.Unmarshal(b, m) == nil)
}
func hash(parts ...[]byte) []byte {
	h := sha256.New()
	for _, p := range parts {
		h.Write(p)
	}
	return h.Sum(nil)
}
func certPEM(b []byte) *x509.Certificate {
	p, rest := pem.Decode(b)
	must(p != nil && p.Type == "CERTIFICATE" && len(bytes.TrimSpace(rest)) == 0)
	c, e := x509.ParseCertificate(p.Bytes)
	must(e == nil)
	return c
}

// Local profile intentionally supports direct enrollment-root issuance only.
// No TLS roots, system trust store, intermediate CAs or unreviewed NodeOU config.
func LoadTrust(base string, now time.Time) (trust map[string]*x509.Certificate, err error) {
	defer func() {
		if recover() != nil {
			trust = nil
			err = errors.New("BLOCKED_MSP_TRUST_INCOMPLETE")
		}
	}()
	trust = map[string]*x509.Certificate{}
	for _, org := range []int{1, 2} {
		dir := filepath.Join(base, fmt.Sprintf("org%d.example.com/msp", org))
		config, e := os.ReadFile(filepath.Join(dir, "config.yaml"))
		must(e == nil)
		expected := "NodeOUs:\n  Enable: true\n"
		for _, role := range []string{"Client", "Peer", "Admin", "Orderer"} {
			expected += fmt.Sprintf("  %sOUIdentifier:\n    Certificate: cacerts/ca.org%d.example.com-cert.pem\n    OrganizationalUnitIdentifier: %s\n", role, org, strings.ToLower(role))
		}
		must(string(config) == expected)
		files, e := os.ReadDir(filepath.Join(dir, "cacerts"))
		must(e == nil && len(files) == 1 && !files[0].IsDir())
		rootBytes, e := os.ReadFile(filepath.Join(dir, "cacerts", fmt.Sprintf("ca.org%d.example.com-cert.pem", org)))
		must(e == nil)
		root := certPEM(rootBytes)
		must(root.IsCA && root.BasicConstraintsValid && root.CheckSignatureFrom(root) == nil && now.After(root.NotBefore) && now.Before(root.NotAfter))
		for _, name := range []string{"intermediatecerts", "crls"} {
			entries, e := os.ReadDir(filepath.Join(dir, name))
			must(os.IsNotExist(e) || (e == nil && len(entries) == 0))
		}
		trust[fmt.Sprintf("Org%dMSP", org)] = root
	}
	return trust, nil
}
func trusted(c, root *x509.Certificate, role string, now time.Time) {
	must(root != nil && !c.IsCA && c.KeyUsage&x509.KeyUsageDigitalSignature != 0)
	must(len(c.Subject.OrganizationalUnit) == 1 && c.Subject.OrganizationalUnit[0] == role)
	roots := x509.NewCertPool()
	roots.AddCert(root)
	chains, e := c.Verify(x509.VerifyOptions{Roots: roots, CurrentTime: now, KeyUsages: []x509.ExtKeyUsage{x509.ExtKeyUsageAny}})
	must(e == nil && len(chains) == 1 && len(chains[0]) == 2 && bytes.Equal(chains[0][1].Raw, root.Raw))
}
func signature(c *x509.Certificate, message, sig []byte) {
	key, ok := c.PublicKey.(*ecdsa.PublicKey)
	must(ok && key.Curve.Params().BitSize == 256)
	var pair struct{ R, S *big.Int }
	rest, e := asn1.Unmarshal(sig, &pair)
	must(e == nil && len(rest) == 0 && pair.R != nil && pair.S != nil && pair.R.Sign() > 0 && pair.S.Sign() > 0)
	canonical, e := asn1.Marshal(pair)
	must(e == nil && bytes.Equal(canonical, sig))
	must(pair.S.Cmp(new(big.Int).Rsh(new(big.Int).Set(key.Params().N), 1)) <= 0)
	must(ecdsa.Verify(key, hash(message), pair.R, pair.S))
}

type Input struct {
	Artifact      registration.Artifact `json:"artifact"`
	Frozen        json.RawMessage       `json:"frozen"`
	Command       json.RawMessage       `json:"command"`
	OperationID   string                `json:"operation_id"`
	TransactionID string                `json:"transaction_id"`
	PropertyID    string                `json:"property_id"`
	RequestDigest string                `json:"request_digest"`
	Signer        string                `json:"signer"`
	Channel       string                `json:"channel"`
	Chaincode     string                `json:"chaincode"`
	State         string                `json:"state"`
	Secret        string                `json:"secret"`
	TrustPath     string                `json:"trust_path"`
}

// Verify returns no endorsed or credential material. It does not submit/status-query.
func Verify(in Input, now time.Time) (err error) {
	defer func() {
		if recover() != nil {
			err = invalid
		}
	}()
	a := in.Artifact
	frozen, e := registration.DecodeCommand(in.Frozen)
	must(e == nil)
	local, e := registration.DecodeCommand(in.Command)
	must(e == nil && local == frozen && a.Command == frozen)
	must(in.State == "PREPARED" && in.OperationID == frozen.OperationID && in.PropertyID == frozen.PropertyID && in.TransactionID == a.TransactionID)
	must(in.RequestDigest == a.RequestDigest && in.Signer == a.Signer && in.Channel == a.Channel && in.Chaincode == a.Chaincode)
	key, e := hex.DecodeString(in.Secret)
	must(e == nil && len(key) == 32)
	must((&registration.Service{Key: key}).Check(a) == nil)
	trust, e := LoadTrust(in.TrustPath, now)
	if e != nil {
		return e
	}
	var creator msp.SerializedIdentity
	decode(a.Creator, &creator)
	must(creator.Mspid == "Org1MSP")
	trusted(certPEM(creator.IdBytes), trust[creator.Mspid], "client", now)
	return verifyEndorsedTransaction(in, now, trust)
}

// Caller verifies the pinned creator and local operation/HMAC first.
func verifyEndorsedTransaction(in Input, now time.Time, trust map[string]*x509.Certificate) (err error) {
	defer func() {
		if recover() != nil {
			err = invalid
		}
	}()
	a := in.Artifact
	frozen, e := registration.DecodeCommand(in.Frozen)
	must(e == nil)
	var prepared gp.PreparedTransaction
	decode(a.Transaction, &prepared)
	must(prepared.TransactionId == a.TransactionID && prepared.Envelope != nil && len(prepared.Envelope.Signature) == 0)
	var payload common.Payload
	decode(prepared.Envelope.Payload, &payload)
	must(payload.Header != nil)
	var ch common.ChannelHeader
	decode(payload.Header.ChannelHeader, &ch)
	var sh common.SignatureHeader
	decode(payload.Header.SignatureHeader, &sh)
	must(ch.Type == int32(common.HeaderType_ENDORSER_TRANSACTION) && ch.ChannelId == "mychannel" && ch.TxId == in.TransactionID && len(sh.Nonce) == 24)
	must(hex.EncodeToString(hash(sh.Nonce, sh.Creator)) == ch.TxId && bytes.Equal(sh.Creator, a.Creator))
	var creator msp.SerializedIdentity
	decode(sh.Creator, &creator)
	must(creator.Mspid == "Org1MSP")

	var tx peer.Transaction
	decode(payload.Data, &tx)
	must(len(tx.Actions) == 1 && tx.Actions[0] != nil && bytes.Equal(tx.Actions[0].Header, payload.Header.SignatureHeader))
	var cap peer.ChaincodeActionPayload
	decode(tx.Actions[0].Payload, &cap)
	must(cap.Action != nil && len(cap.Action.Endorsements) == 2)
	var proposal peer.ChaincodeProposalPayload
	decode(cap.ChaincodeProposalPayload, &proposal)
	must(len(proposal.TransientMap) == 0)
	var invocation peer.ChaincodeInvocationSpec
	decode(proposal.Input, &invocation)
	must(invocation.ChaincodeSpec != nil && invocation.ChaincodeSpec.Input != nil && len(invocation.ChaincodeSpec.Input.Decorations) == 0)
	canonical, e := json.Marshal(frozen)
	must(e == nil)
	spec := invocation.ChaincodeSpec
	must(spec.ChaincodeId != nil && spec.ChaincodeId.Name == "tokansh" && len(spec.Input.Args) == 2 && string(spec.Input.Args[0]) == "RegisterApprovedProperty" && bytes.Equal(spec.Input.Args[1], canonical))
	principal := base64.StdEncoding.EncodeToString([]byte("x509::CN=User1@org1.example.com,OU=client,L=San Francisco,ST=California,C=US::CN=ca.org1.example.com,O=org1.example.com,L=San Francisco,ST=California,C=US"))
	digestBytes, e := json.Marshal(struct {
		Function  string               `json:"function"`
		MSP       string               `json:"msp"`
		Principal string               `json:"principal"`
		Command   registration.Command `json:"command"`
	}{"RegisterApprovedProperty", "Org1MSP", principal, frozen})
	must(e == nil)
	receiptDigest := hex.EncodeToString(hash(digestBytes))
	var extension peer.ChaincodeHeaderExtension
	decode(ch.Extension, &extension)
	must(extension.ChaincodeId != nil && extension.ChaincodeId.Name == "tokansh")
	var response peer.ProposalResponsePayload
	decode(cap.Action.ProposalResponsePayload, &response)
	must(bytes.Equal(response.ProposalHash, hash(payload.Header.ChannelHeader, payload.Header.SignatureHeader, cap.ChaincodeProposalPayload)))
	var action peer.ChaincodeAction
	decode(response.Extension, &action)
	must(action.ChaincodeId != nil && action.ChaincodeId.Name == "tokansh" && action.Response != nil && action.Response.Status == 200 && len(action.Results) > 0 && len(action.Events) == 0)
	var result registration.RegistrationResult
	must(StrictJSON(action.Response.Payload, &result) == nil && result == (registration.RegistrationResult{PropertyID: frozen.PropertyID, OperationID: frozen.OperationID, TransactionID: in.TransactionID}))
	var writes rwset.TxReadWriteSet
	decode(action.Results, &writes)
	must(writes.DataModel == rwset.TxReadWriteSet_KV)
	found := map[string]bool{}
	names := map[string]bool{}
	for _, namespace := range writes.NsRwset {
		must(namespace != nil && namespace.Namespace != "" && !names[namespace.Namespace] && len(namespace.CollectionHashedRwset) == 0)
		names[namespace.Namespace] = true
		var kv kvrwset.KVRWSet
		decode(namespace.Rwset, &kv)
		must(len(kv.MetadataWrites) == 0)
		if namespace.Namespace != "tokansh" {
			must(len(kv.Writes) == 0)
			continue
		}
		must(len(kv.Writes) == 2)
		for _, write := range kv.Writes {
			must(write != nil && !write.IsDelete && !found[write.Key])
			found[write.Key] = true
			switch write.Key {
			case "\x00property\x00" + frozen.PropertyID + "\x00":
				var property registration.Property
				must(StrictJSON(write.Value, &property) == nil)
				must(property.SchemaVersion == 1 && property.PropertyID == frozen.PropertyID && property.IssuerID == frozen.IssuerID && property.ApprovalReference == frozen.ApprovalReference && property.ApprovalDigest == frozen.ApprovalDigest && property.ApprovedSupply == frozen.ApprovedSupply && property.IssuePriceMinor == frozen.IssuePriceMinor && property.Currency == frozen.Currency && property.RegisteredByMSP == "Org1MSP" && property.RegistrationOperationID == frozen.OperationID && property.RegistrationTransactionID == in.TransactionID && property.RegisteredByPrincipal == principal)
			case "\x00operation\x00Org1MSP\x00" + frozen.OperationID + "\x00":
				var operation registration.Operation
				must(StrictJSON(write.Value, &operation) == nil)
				must(operation.SchemaVersion == 1 && operation.OperationID == frozen.OperationID && operation.PropertyID == frozen.PropertyID && operation.AuthorizingMSP == "Org1MSP" && operation.AuthorizingPrincipal == principal && operation.RequestDigest == receiptDigest && operation.Function == "RegisterApprovedProperty" && operation.OriginalTransactionID == in.TransactionID && operation.Result == result)
			default:
				must(false)
			}
		}
	}
	must(len(found) == 2)
	seen := map[string]bool{}
	for _, endorsement := range cap.Action.Endorsements {
		must(endorsement != nil)
		var id msp.SerializedIdentity
		decode(endorsement.Endorser, &id)
		must((id.Mspid == "Org1MSP" || id.Mspid == "Org2MSP") && !seen[id.Mspid])
		seen[id.Mspid] = true
		cert := certPEM(id.IdBytes)
		trusted(cert, trust[id.Mspid], "peer", now)
		signature(cert, append(append([]byte{}, cap.Action.ProposalResponsePayload...), endorsement.Endorser...), endorsement.Signature)
	}
	return nil
}
