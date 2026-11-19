package registration

import (
	"bytes"
	"context"
	"crypto/sha256"
	"crypto/x509"
	"encoding/hex"
	"encoding/json"
	"encoding/pem"
	"errors"
	"os"
	"time"

	"github.com/hyperledger/fabric-gateway/pkg/client"
	gp "github.com/hyperledger/fabric-protos-go-apiv2/gateway"
	"github.com/hyperledger/fabric-protos-go-apiv2/msp"
	"google.golang.org/protobuf/proto"
)

type SDK struct {
	gateway *client.Gateway
	creator []byte
}

func NewSDK(gw *client.Gateway, mspID, certPath string) (*SDK, error) {
	b, e := os.ReadFile(certPath)
	if e != nil {
		return nil, invalid
	}
	p, _ := pem.Decode(b)
	if p == nil {
		return nil, invalid
	}
	cert, e := x509.ParseCertificate(p.Bytes)
	if e != nil {
		return nil, invalid
	}
	sum := sha256.Sum256(cert.Raw)
	if mspID+":"+hex.EncodeToString(sum[:]) != Signer {
		return nil, errors.New("SIGNER_NOT_ALLOWED")
	}
	// The certificate pin also fixes the reviewed Fabric subject/issuer principal.
	creator, e := proto.Marshal(&msp.SerializedIdentity{Mspid: mspID, IdBytes: pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: cert.Raw})})
	if e != nil {
		return nil, invalid
	}
	return &SDK{gw, creator}, nil
}
func (s *SDK) Read(ctx context.Context, f string, args ...string) ([]byte, error) {
	ctx, cancel := context.WithTimeout(ctx, 5*time.Second)
	defer cancel()
	return s.gateway.GetNetwork("mychannel").GetContract("tokansh").EvaluateWithContext(ctx, f, client.WithArguments(args...))
}
func (s *SDK) Prepare(ctx context.Context, c Command) (string, []byte, []byte, error) {
	ctx, cancel := context.WithTimeout(ctx, 5*time.Second)
	defer cancel()
	b, e := json.Marshal(c)
	if e != nil {
		return "", nil, nil, e
	}
	p, e := s.gateway.GetNetwork("mychannel").GetContract("tokansh").NewProposal("RegisterApprovedProperty", client.WithArguments(string(b)), client.WithEndorsingOrganizations("Org1MSP", "Org2MSP"))
	if e != nil {
		return "", nil, nil, e
	}
	tx, e := p.EndorseWithContext(ctx)
	if e != nil {
		return "", nil, nil, e
	}
	result, e := tx.Bytes()
	return tx.TransactionID(), result, s.creator, e
}
func (s *SDK) Submit(ctx context.Context, a Artifact) error {
	ctx, cancel := context.WithTimeout(ctx, 5*time.Second)
	defer cancel()
	tx, e := s.gateway.NewTransaction(a.Transaction)
	if e != nil {
		return invalid
	}
	if tx.TransactionID() != a.TransactionID {
		return invalid
	}
	_, e = tx.SubmitWithContext(ctx)
	return e
}
func (s *SDK) Status(ctx context.Context, a Artifact) (Status, error) {
	ctx, cancel := context.WithTimeout(ctx, 5*time.Second)
	defer cancel()
	// Recovery must use the same configured identity as the persisted creator.
	// Gateway.Identity returns the identity paired with the existing signer.
	id := s.gateway.Identity()
	creator, e := proto.Marshal(&msp.SerializedIdentity{Mspid: id.MspID(), IdBytes: id.Credentials()})
	if e != nil || !bytes.Equal(creator, s.creator) || !bytes.Equal(creator, a.Creator) {
		return Status{}, invalid
	}
	// Works even if Submit returned no Commit. No submission or endorsement here.
	request, e := proto.Marshal(&gp.CommitStatusRequest{ChannelId: a.Channel, TransactionId: a.TransactionID, Identity: creator})
	if e != nil {
		return Status{}, invalid
	}
	recovery, e := proto.Marshal(&gp.SignedCommitStatusRequest{Request: request})
	if e != nil {
		return Status{}, invalid
	}
	// SDK v1.10.0 NewCommit retains the configured signing identity;
	// StatusWithContext signs the unsigned request before sending the RPC.
	commit, e := s.gateway.NewCommit(recovery)
	if e != nil {
		return Status{}, invalid
	}
	v, e := commit.StatusWithContext(ctx)
	if e != nil {
		return Status{}, e
	}
	return Status{v.TransactionID, int32(v.Code), v.BlockNumber, v.Successful}, nil
}
