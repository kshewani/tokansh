package registration

import (
	"context"
	"crypto/x509"
	"encoding/pem"
	"github.com/hyperledger/fabric-gateway/pkg/client"
	"github.com/hyperledger/fabric-gateway/pkg/identity"
	gp "github.com/hyperledger/fabric-protos-go-apiv2/gateway"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/test/bufconn"
	"google.golang.org/protobuf/proto"
	"net"
	"os"
	"testing"
)

type statusServer struct {
	gp.UnimplementedGatewayServer
	t *testing.T
}

func (s statusServer) CommitStatus(ctx context.Context, r *gp.SignedCommitStatusRequest) (*gp.CommitStatusResponse, error) {
	var body gp.CommitStatusRequest
	if proto.Unmarshal(r.Request, &body) != nil || body.TransactionId != "test-only-id" || body.ChannelId != "mychannel" || len(r.Signature) == 0 {
		s.t.Error("invalid reconstructed status request")
	}
	return &gp.CommitStatusResponse{BlockNumber: 4}, nil
}
func TestPublicSDKCommitRecoveryWithoutSubmit(t *testing.T) {
	l := bufconn.Listen(1 << 20)
	server := grpc.NewServer()
	gp.RegisterGatewayServer(server, statusServer{t: t})
	go server.Serve(l)
	defer server.Stop()
	conn, e := grpc.NewClient("passthrough:///test", grpc.WithTransportCredentials(insecure.NewCredentials()), grpc.WithContextDialer(func(context.Context, string) (net.Conn, error) { return l.Dial() }))
	if e != nil {
		t.Fatal(e)
	}
	defer conn.Close()
	b, e := os.ReadFile("../../../chaincode/tokansh/contract/testdata/org1-user1-public.pem")
	if e != nil {
		t.Fatal(e)
	}
	block, _ := pem.Decode(b)
	cert, _ := x509.ParseCertificate(block.Bytes)
	id, _ := identity.NewX509Identity("Org1MSP", cert)
	gw, e := client.Connect(id, client.WithClientConnection(conn), client.WithSign(func([]byte) ([]byte, error) { return []byte("test-only-signature"), nil }))
	if e != nil {
		t.Fatal(e)
	}
	defer gw.Close()
	_, creator := prepared(t, command())
	sdk := &SDK{gw, creator}
	result, e := sdk.Status(context.Background(), Artifact{Channel: "mychannel", TransactionID: "test-only-id", Creator: creator})
	if e != nil || !result.Successful || result.BlockNumber != 4 {
		t.Fatal(result, e)
	}
	tx, _ := prepared(t, command())
	if err := sdk.Submit(context.Background(), Artifact{TransactionID: "test-only-id", Transaction: tx}); err != nil {
		t.Fatal(err)
	}
}

func (s statusServer) Submit(ctx context.Context, r *gp.SubmitRequest) (*gp.SubmitResponse, error) {
	if r.TransactionId != "test-only-id" || r.ChannelId != "mychannel" || len(r.GetPreparedTransaction().GetSignature()) == 0 {
		s.t.Error("invalid reconstructed submission")
	}
	return &gp.SubmitResponse{}, nil
}
