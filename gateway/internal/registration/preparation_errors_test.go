package registration

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"github.com/hyperledger/fabric-gateway/pkg/client"
	gp "github.com/hyperledger/fabric-protos-go-apiv2/gateway"
	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/status"
	"google.golang.org/grpc/test/bufconn"
	"google.golang.org/protobuf/types/known/emptypb"
	"net"
	"testing"
	"time"
)

const endorseFailure = "failed to collect enough transaction endorsements, see attached details for more info"
const supplyExceeded = `chaincode response 500, {"code":"ISSUANCE_LIMIT_EXCEEDED","message":"Requested issuance exceeds approved supply."}`
const operationConflict = `chaincode response 500, {"code":"IDEMPOTENCY_CONFLICT","message":"Operation was already used with different parameters."}`

func preparationError(messages ...string) error {
	st := status.New(codes.Aborted, endorseFailure)
	for i, message := range messages {
		var err error
		st, err = st.WithDetails(&gp.ErrorDetail{MspId: fmt.Sprintf("Org%dMSP", i%2+1), Address: "private-peer.internal:7051", Message: message})
		if err != nil {
			panic(err)
		}
	}
	return st.Err()
}
func TestIssuancePreparationClassification(t *testing.T) {
	alien, _ := status.New(codes.Aborted, endorseFailure).WithDetails(&emptypb.Empty{})
	wrongOrg, _ := status.New(codes.Aborted, endorseFailure).WithDetails(&gp.ErrorDetail{MspId: "UnknownMSP", Address: "private-peer", Message: supplyExceeded})
	missingAddress, _ := status.New(codes.Aborted, endorseFailure).WithDetails(&gp.ErrorDetail{MspId: "Org1MSP", Message: supplyExceeded})
	for _, tc := range []struct {
		name string
		err  error
		http int
		code string
	}{
		{"supply", preparationError(supplyExceeded, supplyExceeded), 422, "ISSUANCE_LIMIT_EXCEEDED"},
		{"conflict", preparationError(operationConflict), 409, "IDEMPOTENCY_CONFLICT"},
		{"property", preparationError(propertyMissing), 404, "PROPERTY_NOT_FOUND"},
		{"authorization", preparationError(`chaincode response 500, {"code":"UNAUTHORIZED","message":"Identity is not authorized."}`), 403, "UNAUTHORIZED"},
		{"wrapped", fmt.Errorf("wrapped: %w", preparationError(operationConflict)), 409, "IDEMPOTENCY_CONFLICT"},
		{"mixed", preparationError(supplyExceeded, operationConflict), 503, "LEDGER_UNAVAILABLE"},
		{"mixed infrastructure", preparationError(supplyExceeded, "private connection failed"), 503, "LEDGER_UNAVAILABLE"},
		{"missing details", preparationError(), 503, "LEDGER_UNAVAILABLE"},
		{"wrong details", alien.Err(), 503, "LEDGER_UNAVAILABLE"},
		{"unknown organization", wrongOrg.Err(), 503, "LEDGER_UNAVAILABLE"},
		{"missing peer address", missingAddress.Err(), 503, "LEDGER_UNAVAILABLE"},
		{"malformed", preparationError(`chaincode response 500, {bad`), 503, "LEDGER_UNAVAILABLE"},
		{"duplicate fields", preparationError(`chaincode response 500, {"code":"IDEMPOTENCY_CONFLICT","code":"IDEMPOTENCY_CONFLICT","message":"Operation was already used with different parameters."}`), 503, "LEDGER_UNAVAILABLE"},
		{"unknown fields", preparationError(`chaincode response 500, {"code":"ISSUANCE_LIMIT_EXCEEDED","message":"Requested issuance exceeds approved supply.","extra":1}`), 503, "LEDGER_UNAVAILABLE"},
		{"unknown business", preparationError(operationMissing), 503, "LEDGER_UNAVAILABLE"},
		{"outer text alone", status.Error(codes.Aborted, supplyExceeded), 503, "LEDGER_UNAVAILABLE"},
		{"wrong outer framing", detailed(codes.Aborted, supplyExceeded), 503, "LEDGER_UNAVAILABLE"},
		{"evaluate cannot prepare", detailed(codes.Unknown, supplyExceeded), 503, "LEDGER_UNAVAILABLE"},
		{"plain error", errors.New("private address secret"), 503, "LEDGER_UNAVAILABLE"},
		{"deadline", context.DeadlineExceeded, 504, "LEDGER_TIMEOUT"},
		{"rpc deadline", status.Error(codes.DeadlineExceeded, "private details"), 504, "LEDGER_TIMEOUT"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			var failure *readFailure
			if !errors.As(classifyIssuancePreparation(tc.err), &failure) || failure.httpStatus != tc.http || failure.code != tc.code {
				t.Fatalf("wrong classification: %v", failure)
			}
			// Exercise the real prepare handler; no endorsement/submission/network in this mock.
			m := &issuanceMock{mockLedger: mockLedger{err: tc.err}}
			s := &Service{Ledger: m, Key: bytes.Repeat([]byte{1}, 32)}
			w := issuanceRequest(s, "issuances/prepare", []byte(`{"command_version":1,"operation_id":"10000000-0000-4000-8000-000000000001","property_id":"20000000-0000-4000-8000-000000000001","quantity":40}`), true, true)
			if w.Code != tc.http || !bytes.Contains(w.Body.Bytes(), []byte(tc.code)) || bytes.Contains(w.Body.Bytes(), []byte("private")) || m.calls != 0 || m.prepares != 1 {
				t.Fatal("unsafe handler result", w.Code, w.Body.String())
			}
		})
	}
	if classifyIssuancePreparation(nil) != nil {
		t.Fatal("nil error")
	}
	// Endorse Aborted must remain infrastructure failure for read-only evaluations.
	var read *readFailure
	if !errors.As(classifyEvaluation(preparationError(propertyMissing), "GetRegisteredProperty"), &read) || read.httpStatus != 503 {
		t.Fatal("GET classification weakened")
	}
}

type preparationServer struct {
	gp.UnimplementedGatewayServer
	t *testing.T
}

func (s preparationServer) Endorse(ctx context.Context, r *gp.EndorseRequest) (*gp.EndorseResponse, error) {
	if r.ChannelId != "mychannel" || len(r.EndorsingOrganizations) != 2 || r.EndorsingOrganizations[0] != "Org1MSP" || r.EndorsingOrganizations[1] != "Org2MSP" {
		s.t.Error("unexpected endorsement scope")
	}
	deadline, ok := ctx.Deadline()
	if !ok || time.Until(deadline) > 5*time.Second {
		s.t.Error("missing five-second bound")
	}
	return nil, preparationError(supplyExceeded, supplyExceeded)
}
func TestIssuancePreparationErrorThroughPinnedSDK(t *testing.T) {
	listener := bufconn.Listen(1 << 20)
	defer listener.Close()
	server := grpc.NewServer()
	gp.RegisterGatewayServer(server, preparationServer{t: t})
	go server.Serve(listener)
	defer server.Stop()
	conn, err := grpc.NewClient("passthrough:///test", grpc.WithTransportCredentials(insecure.NewCredentials()), grpc.WithContextDialer(func(context.Context, string) (net.Conn, error) { return listener.Dial() }))
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close()
	id, sign, _, creator := recoveryIdentity(t)
	gw, err := client.Connect(id, client.WithClientConnection(conn), client.WithSign(sign))
	if err != nil {
		t.Fatal(err)
	}
	defer gw.Close()
	sdk := &SDK{gateway: gw, creator: creator}
	_, _, _, err = sdk.PrepareIssuance(context.Background(), issuanceCommand())
	var endorse *client.EndorseError
	if !errors.As(err, &endorse) {
		t.Fatal("expected SDK EndorseError", err)
	}
	var failure *readFailure
	if !errors.As(classifyIssuancePreparation(err), &failure) || failure.httpStatus != 422 {
		t.Fatal("SDK error not recognized", failure)
	}
}
