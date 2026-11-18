package registration

import (
	"context"
	"errors"
	"fmt"
	gp "github.com/hyperledger/fabric-protos-go-apiv2/gateway"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
	"testing"
)

const propertyMissing = `chaincode response 500, {"code":"PROPERTY_NOT_FOUND","message":"Registered property was not found."}`
const operationMissing = `chaincode response 500, {"code":"OPERATION_NOT_FOUND","message":"Operation was not found."}`

func detailed(code codes.Code, message string) error {
	s, e := status.New(code, "evaluate call to endorser returned error: "+message).WithDetails(&gp.ErrorDetail{Address: "private-peer.internal:7051", MspId: "Org1MSP", Message: message})
	if e != nil {
		panic(e)
	}
	return s.Err()
}
func TestEvaluationClassification(t *testing.T) {
	for _, tc := range []struct {
		name, function string
		err            error
		http           int
		code           string
	}{
		{"property detail", "GetRegisteredProperty", detailed(codes.Unknown, propertyMissing), 404, "PROPERTY_NOT_FOUND"},
		{"operation detail", "GetOperation", detailed(codes.Unknown, operationMissing), 404, "OPERATION_NOT_FOUND"},
		{"documented framing without details", "GetOperation", status.Error(codes.Unknown, "evaluate call to endorser returned error: "+operationMissing), 404, "OPERATION_NOT_FOUND"},
		{"wrapped", "GetOperation", fmt.Errorf("wrapper: %w", detailed(codes.Unknown, operationMissing)), 404, "OPERATION_NOT_FOUND"},
		{"context deadline", "GetRegisteredProperty", context.DeadlineExceeded, 504, "LEDGER_TIMEOUT"},
		{"rpc deadline takes precedence", "GetRegisteredProperty", detailed(codes.DeadlineExceeded, propertyMissing), 504, "LEDGER_TIMEOUT"},
		{"transport", "GetOperation", detailed(codes.Unavailable, operationMissing), 503, "LEDGER_UNAVAILABLE"},
		{"infra NotFound", "GetOperation", status.Error(codes.NotFound, "peer not found"), 503, "LEDGER_UNAVAILABLE"},
		{"plain error", "GetOperation", errors.New(operationMissing), 503, "LEDGER_UNAVAILABLE"},
		{"arbitrary not found", "GetOperation", status.Error(codes.Unknown, "resource not found"), 503, "LEDGER_UNAVAILABLE"},
		{"wrong function", "GetRegisteredProperty", detailed(codes.Unknown, operationMissing), 503, "LEDGER_UNAVAILABLE"},
		{"info cannot notfound", "GetContractInfo", detailed(codes.Unknown, propertyMissing), 503, "LEDGER_UNAVAILABLE"},
		{"substring injection", "GetOperation", detailed(codes.Unknown, "unexpected prefix "+operationMissing), 503, "LEDGER_UNAVAILABLE"},
		{"unknown field", "GetOperation", detailed(codes.Unknown, `chaincode response 500, {"code":"OPERATION_NOT_FOUND","message":"Operation was not found.","extra":1}`), 503, "LEDGER_UNAVAILABLE"},
		{"unknown business error", "GetOperation", detailed(codes.Unknown, `chaincode response 500, {"code":"OTHER_NOT_FOUND","message":"Operation was not found."}`), 503, "LEDGER_UNAVAILABLE"},
		{"malformed", "GetOperation", detailed(codes.Unknown, `chaincode response 500, {broken`), 503, "LEDGER_UNAVAILABLE"},
		{"duplicate code", "GetOperation", detailed(codes.Unknown, `chaincode response 500, {"code":"OPERATION_NOT_FOUND","code":"OPERATION_NOT_FOUND","message":"Operation was not found."}`), 503, "LEDGER_UNAVAILABLE"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			var failure *readFailure
			if !errors.As(classifyEvaluation(tc.err, tc.function), &failure) || failure.httpStatus != tc.http || failure.code != tc.code {
				t.Fatalf("wrong classification: %v", failure)
			}
		})
	}
	if classifyEvaluation(nil, "GetOperation") != nil {
		t.Fatal("nil became error")
	}
}
