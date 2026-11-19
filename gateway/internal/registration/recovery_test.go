package registration

import (
	"bytes"
	"context"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/sha256"
	"crypto/x509"
	"crypto/x509/pkix"
	"errors"
	"math/big"
	"net"
	"sync/atomic"
	"testing"
	"time"

	"github.com/hyperledger/fabric-gateway/pkg/client"
	"github.com/hyperledger/fabric-gateway/pkg/identity"
	gp "github.com/hyperledger/fabric-protos-go-apiv2/gateway"
	"github.com/hyperledger/fabric-protos-go-apiv2/msp"
	"github.com/hyperledger/fabric-protos-go-apiv2/peer"
	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/status"
	"google.golang.org/grpc/test/bufconn"
	"google.golang.org/protobuf/proto"
)

type statusServer struct {
	gp.UnimplementedGatewayServer
	creator []byte
	public  *ecdsa.PublicKey
	result  peer.TxValidationCode
	calls   atomic.Int32
}

func (s *statusServer) CommitStatus(ctx context.Context, r *gp.SignedCommitStatusRequest) (*gp.CommitStatusResponse, error) {
	s.calls.Add(1)
	var body gp.CommitStatusRequest
	if proto.Unmarshal(r.Request, &body) != nil || body.TransactionId != "test-only-id" || body.ChannelId != "mychannel" || !bytes.Equal(body.Identity, s.creator) {
		return nil, status.Error(codes.InvalidArgument, "unexpected recovery metadata")
	}
	digest := sha256.Sum256(r.Request)
	if len(r.Signature) == 0 || !ecdsa.VerifyASN1(s.public, digest[:], r.Signature) {
		return nil, status.Error(codes.Unauthenticated, "invalid recovery signature")
	}
	deadline, ok := ctx.Deadline()
	if !ok || time.Until(deadline) > 5*time.Second {
		return nil, status.Error(codes.InvalidArgument, "missing bounded deadline")
	}
	return &gp.CommitStatusResponse{BlockNumber: 4, Result: s.result}, nil
}

// Preserve the pre-existing reconstructed-submission test using bufconn only.
func (s *statusServer) Submit(_ context.Context, r *gp.SubmitRequest) (*gp.SubmitResponse, error) {
	if r.TransactionId != "test-only-id" || r.ChannelId != "mychannel" || len(r.GetPreparedTransaction().GetSignature()) == 0 {
		return nil, status.Error(codes.InvalidArgument, "invalid reconstructed submission")
	}
	return &gp.SubmitResponse{}, nil
}

// All signing material is generated in memory for this isolated test only.
func recoveryIdentity(t *testing.T) (*identity.X509Identity, identity.Sign, *ecdsa.PublicKey, []byte) {
	t.Helper()
	key, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	cert := &x509.Certificate{SerialNumber: big.NewInt(1), Subject: pkix.Name{CommonName: "test-only-recovery"}, NotBefore: time.Now().Add(-time.Hour), NotAfter: time.Now().Add(time.Hour), KeyUsage: x509.KeyUsageDigitalSignature}
	der, err := x509.CreateCertificate(rand.Reader, cert, cert, &key.PublicKey, key)
	if err != nil {
		t.Fatal(err)
	}
	cert, err = x509.ParseCertificate(der)
	if err != nil {
		t.Fatal(err)
	}
	id, err := identity.NewX509Identity("Org1MSP", cert)
	if err != nil {
		t.Fatal(err)
	}
	sign, err := identity.NewPrivateKeySign(key)
	if err != nil {
		t.Fatal(err)
	}
	creator, err := proto.Marshal(&msp.SerializedIdentity{Mspid: id.MspID(), IdBytes: id.Credentials()})
	if err != nil {
		t.Fatal(err)
	}
	return id, sign, &key.PublicKey, creator
}

func recoverySDK(t *testing.T, server *statusServer, id identity.Identity, sign identity.Sign) *SDK {
	t.Helper()
	l := bufconn.Listen(1 << 20)
	t.Cleanup(func() { _ = l.Close() })
	rpc := grpc.NewServer()
	gp.RegisterGatewayServer(rpc, server)
	go func() { _ = rpc.Serve(l) }()
	t.Cleanup(rpc.Stop)
	conn, err := grpc.NewClient("passthrough:///test", grpc.WithTransportCredentials(insecure.NewCredentials()), grpc.WithContextDialer(func(context.Context, string) (net.Conn, error) { return l.Dial() }))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = conn.Close() })
	opts := []client.ConnectOption{client.WithClientConnection(conn)}
	if sign != nil {
		opts = append(opts, client.WithSign(sign))
	}
	gw, err := client.Connect(id, opts...)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = gw.Close() })
	return &SDK{gateway: gw, creator: server.creator}
}

func TestPublicSDKCommitRecoveryWithoutSubmit(t *testing.T) {
	for _, code := range []peer.TxValidationCode{peer.TxValidationCode_VALID, peer.TxValidationCode_MVCC_READ_CONFLICT} {
		t.Run(code.String(), func(t *testing.T) {
			id, sign, public, creator := recoveryIdentity(t)
			server := &statusServer{creator: creator, public: public, result: code}
			// A fresh Gateway has no prior proposal, transaction or Submit result.
			sdk := recoverySDK(t, server, id, sign)
			result, err := sdk.Status(context.Background(), Artifact{Channel: "mychannel", TransactionID: "test-only-id", Creator: creator})
			if err != nil || result.TransactionID != "test-only-id" || result.Code != int32(code) || result.Successful != (code == peer.TxValidationCode_VALID) || result.BlockNumber != 4 || server.calls.Load() != 1 {
				t.Fatalf("unexpected recovery result: %+v, %v; calls=%d", result, err, server.calls.Load())
			}
		})
	}
}

func TestPublicSDKReconstructedSubmission(t *testing.T) {
	id, sign, public, creator := recoveryIdentity(t)
	sdk := recoverySDK(t, &statusServer{creator: creator, public: public}, id, sign)
	tx, _ := prepared(t, command())
	if err := sdk.Submit(context.Background(), Artifact{TransactionID: "test-only-id", Transaction: tx}); err != nil {
		t.Fatal(err)
	}
}

func TestCommitRecoveryRejectsInvalidAuthentication(t *testing.T) {
	for _, name := range []string{"missing signer", "signing error", "empty signature", "invalid signature", "wrong signing key", "different creator", "missing creator", "configured identity mismatch", "stored creator mismatch"} {
		t.Run(name, func(t *testing.T) {
			id, sign, public, creator := recoveryIdentity(t)
			server := &statusServer{creator: creator, public: public}
			artifact := Artifact{Channel: "mychannel", TransactionID: "test-only-id", Creator: creator}
			wantCalls := int32(0)
			switch name {
			case "missing signer":
				sign = nil
			case "signing error":
				sign = func([]byte) ([]byte, error) { return nil, errors.New("test-only signing failure") }
			case "empty signature":
				sign = func([]byte) ([]byte, error) { return nil, nil }
				wantCalls = 1
			case "invalid signature":
				sign = func([]byte) ([]byte, error) { return []byte("invalid"), nil }
				wantCalls = 1
			case "wrong signing key":
				_, sign, _, _ = recoveryIdentity(t)
				wantCalls = 1
			case "different creator":
				_, _, _, artifact.Creator = recoveryIdentity(t)
			case "missing creator":
				artifact.Creator = nil
			case "configured identity mismatch":
				id, sign, _, _ = recoveryIdentity(t)
			}
			sdk := recoverySDK(t, server, id, sign)
			if name == "stored creator mismatch" {
				sdk.creator = nil
			}
			result, err := sdk.Status(context.Background(), artifact)
			if err == nil || result != (Status{}) || server.calls.Load() != wantCalls {
				t.Fatalf("recovery must fail closed: result=%+v err=%v calls=%d want=%d", result, err, server.calls.Load(), wantCalls)
			}
		})
	}
}

func TestRecoveryServerRejectsTamperedRequests(t *testing.T) {
	_, sign, public, creator := recoveryIdentity(t)
	for _, name := range []string{"missing signature", "invalid signature", "transaction", "channel", "creator"} {
		t.Run(name, func(t *testing.T) {
			body := &gp.CommitStatusRequest{ChannelId: "mychannel", TransactionId: "test-only-id", Identity: creator}
			digest := sha256.Sum256(marshal(body))
			signature, err := sign(digest[:])
			if err != nil {
				t.Fatal(err)
			}
			switch name {
			case "missing signature":
				signature = nil
			case "invalid signature":
				signature = []byte("invalid")
			case "transaction":
				body.TransactionId = "other"
			case "channel":
				body.ChannelId = "other"
			case "creator":
				body.Identity = []byte("other")
			}
			server := &statusServer{creator: creator, public: public}
			ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
			defer cancel()
			if _, err := server.CommitStatus(ctx, &gp.SignedCommitStatusRequest{Request: marshal(body), Signature: signature}); err == nil {
				t.Fatal("tampered request accepted by test server")
			}
		})
	}
}
