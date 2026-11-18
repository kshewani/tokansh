package registration

import (
	"bytes"
	"context"
	"crypto/x509"
	"encoding/hex"
	"encoding/pem"
	"net"
	"net/http/httptest"
	"os"
	"testing"
	"time"

	"github.com/hyperledger/fabric-gateway/pkg/client"
	"github.com/hyperledger/fabric-gateway/pkg/identity"
	gp "github.com/hyperledger/fabric-protos-go-apiv2/gateway"
	"github.com/hyperledger/fabric-protos-go-apiv2/peer"
	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/status"
	"google.golang.org/grpc/test/bufconn"
)

type evaluateServer struct {
	gp.UnimplementedGatewayServer
	err  error
	wait bool
	t    *testing.T
}

func (s evaluateServer) Evaluate(ctx context.Context, r *gp.EvaluateRequest) (*gp.EvaluateResponse, error) {
	deadline, ok := ctx.Deadline()
	if !ok || time.Until(deadline) > 5*time.Second {
		s.t.Error("five-second evaluation bound not preserved")
	}
	if r.ChannelId != "mychannel" {
		s.t.Error("wrong channel")
	}
	if s.wait {
		<-ctx.Done()
		return nil, status.FromContextError(ctx.Err()).Err()
	}
	if s.err != nil {
		return nil, s.err
	}
	return &gp.EvaluateResponse{Result: &peer.Response{Status: 200, Payload: []byte(`{"contract":"tokansh","schema_version":1,"functions":["GetContractInfo","GetRegisteredProperty","GetOperation","RegisterApprovedProperty"],"supply_interpretation":"LIFETIME_CUMULATIVE_ISSUANCE_CEILING"}`)}}, nil
}
func TestReadHTTPThroughPinnedSDK(t *testing.T) {
	for _, tc := range []struct {
		name, path string
		err        error
		wait       bool
		http       int
		code       string
	}{
		{"success", "contract-info", nil, false, 200, ""},
		{"property", "properties/ffffffff-ffff-4fff-8fff-ffffffffffff", detailed(codes.Unknown, propertyMissing), false, 404, "PROPERTY_NOT_FOUND"},
		{"operation", "operations/ffffffff-ffff-4fff-8fff-ffffffffffff", detailed(codes.Unknown, operationMissing), false, 404, "OPERATION_NOT_FOUND"},
		{"deadline", "contract-info", nil, true, 504, "LEDGER_TIMEOUT"},
		{"disconnected", "contract-info", nil, false, 503, "LEDGER_UNAVAILABLE"},
		{"transport", "contract-info", status.Error(codes.Unavailable, "private-peer.internal:7051 password=secret"), false, 503, "LEDGER_UNAVAILABLE"},
		{"unexpected", "contract-info", status.Error(codes.Unknown, "not found private-peer.internal:7051 password=secret"), false, 503, "LEDGER_UNAVAILABLE"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			l := bufconn.Listen(1 << 20)
			server := grpc.NewServer()
			gp.RegisterGatewayServer(server, evaluateServer{err: tc.err, wait: tc.wait, t: t})
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
			cert, e := x509.ParseCertificate(block.Bytes)
			if e != nil {
				t.Fatal(e)
			}
			id, e := identity.NewX509Identity("Org1MSP", cert)
			if e != nil {
				t.Fatal(e)
			}
			gw, e := client.Connect(id, client.WithClientConnection(conn), client.WithSign(func([]byte) ([]byte, error) { return []byte("test-only-signature"), nil }))
			if e != nil {
				t.Fatal(e)
			}
			defer gw.Close()
			key := bytes.Repeat([]byte{1}, 32)
			handler := Handler(&Service{Ledger: &SDK{gateway: gw}, Key: key}, bytes.Repeat([]byte{2}, 32))
			if tc.name == "disconnected" {
				server.Stop()
			}
			r := httptest.NewRequest("GET", "/v1/tokansh/"+tc.path, nil)
			r.Header.Set("Authorization", "Bearer "+hex.EncodeToString(key))
			w := httptest.NewRecorder()
			start := time.Now()
			handler.ServeHTTP(w, r)
			if w.Code != tc.http {
				t.Fatalf("HTTP %d: %s", w.Code, w.Body.String())
			}
			if tc.code != "" && !bytes.Contains(w.Body.Bytes(), []byte(tc.code)) {
				t.Fatal("missing code")
			}
			for _, secret := range []string{"private-peer.internal", "password=secret", hex.EncodeToString(key)} {
				if bytes.Contains(w.Body.Bytes(), []byte(secret)) {
					t.Fatal("internal detail leaked")
				}
			}
			if tc.wait && time.Since(start) < 4*time.Second {
				t.Fatal("deadline was shortened")
			}
		})
	}
}
