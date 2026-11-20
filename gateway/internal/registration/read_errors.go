package registration

import (
	"context"
	"errors"
	"net/http"
	"strings"

	gp "github.com/hyperledger/fabric-protos-go-apiv2/gateway"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
)

// readFailure contains only fixed public values, never upstream infrastructure text.
type readFailure struct {
	code, message string
	httpStatus    int
}

func (e *readFailure) Error() string { return e.code + ": " + e.message }

type businessReadError struct {
	Code    string `json:"code"`
	Message string `json:"message"`
}

// DRUNIX apiutils.responseStatus wraps chaincode errors in this exact framing.
// No substring search, free-text "not found" match, or infrastructure NotFound mapping.
func recognizedBusinessError(message, function string) string {
	const prefix = "chaincode response 500, "
	if !strings.HasPrefix(message, prefix) || len(message) > 1024 {
		return ""
	}
	var business businessReadError
	if strict([]byte(strings.TrimPrefix(message, prefix)), &business) != nil {
		return ""
	}
	if (function == "GetRegisteredProperty" || function == "GetIssuanceState" || function == "GetBalance" || function == "IssueANSH" || function == "TransferANSH") && business.Code == "PROPERTY_NOT_FOUND" && business.Message == "Registered property was not found." {
		return business.Code
	}
	if (function == "GetOperation" || function == "GetIssuanceOperation") && business.Code == "OPERATION_NOT_FOUND" && business.Message == "Operation was not found." {
		return business.Code
	}
	if function == "IssueANSH" || function == "TransferANSH" {
		messages := map[string]string{"IDEMPOTENCY_CONFLICT": "Operation was already used with different parameters.", "ISSUANCE_LIMIT_EXCEEDED": "Requested issuance exceeds approved supply.", "UNAUTHORIZED": "Identity is not authorized."}
		if function == "TransferANSH" {
			delete(messages, "ISSUANCE_LIMIT_EXCEEDED")
			messages["INSUFFICIENT_BALANCE"] = "Sender has insufficient ANSH."
		}
		if message, ok := messages[business.Code]; ok && message == business.Message {
			return business.Code
		}
	}
	return ""
}
func classifyEvaluation(err error, function string) error {
	if err == nil {
		return nil
	}
	var classified *readFailure
	if errors.As(err, &classified) {
		return classified
	}
	if errors.Is(err, context.DeadlineExceeded) || status.Code(err) == codes.DeadlineExceeded {
		return &readFailure{"LEDGER_TIMEOUT", "DRUNIX evaluation timed out.", http.StatusGatewayTimeout}
	}
	unavailable := &readFailure{"LEDGER_UNAVAILABLE", "DRUNIX evaluation is unavailable.", http.StatusServiceUnavailable}
	st, ok := status.FromError(err)
	if !ok || st.Code() != codes.Unknown {
		return unavailable
	}
	expected := ""
	details := st.Details()
	if len(details) > 0 {
		for _, detail := range details {
			peer, ok := detail.(*gp.ErrorDetail)
			if !ok {
				return unavailable
			}
			code := recognizedBusinessError(peer.Message, function)
			if code == "" || (expected != "" && expected != code) {
				return unavailable
			}
			expected = code
		}
	} else {
		const prefix = "evaluate call to endorser returned error: "
		if strings.HasPrefix(st.Message(), prefix) {
			expected = recognizedBusinessError(strings.TrimPrefix(st.Message(), prefix), function)
		}
	}
	return classifiedBusinessFailure(expected)
}

func classifiedBusinessFailure(expected string) error {
	unavailable := &readFailure{"LEDGER_UNAVAILABLE", "DRUNIX evaluation is unavailable.", http.StatusServiceUnavailable}
	switch expected {
	case "INSUFFICIENT_BALANCE":
		return &readFailure{expected, "Sender has insufficient ANSH.", http.StatusConflict}
	case "IDEMPOTENCY_CONFLICT":
		return &readFailure{expected, "Operation was already used with different parameters.", http.StatusConflict}
	case "ISSUANCE_LIMIT_EXCEEDED":
		return &readFailure{expected, "Requested issuance exceeds approved supply.", http.StatusUnprocessableEntity}
	case "UNAUTHORIZED":
		return &readFailure{expected, "Identity is not authorized.", http.StatusForbidden}
	case "PROPERTY_NOT_FOUND":
		return &readFailure{expected, "Registered property was not found.", http.StatusNotFound}
	case "OPERATION_NOT_FOUND":
		return &readFailure{expected, "Operation was not found.", http.StatusNotFound}
	default:
		return unavailable
	}
}

// Explicit-organization Endorse uses Aborted with per-endorser ErrorDetail, not
// Evaluate's Unknown framing. Never infer a business rejection from outer text alone.
func classifyIssuancePreparation(err error) error { return classifyPreparation(err, "IssueANSH") }

func classifyPreparation(err error, function string) error {
	if function != "IssueANSH" && function != "TransferANSH" {
		return invalid
	}
	operation := "issuance"
	if function == "TransferANSH" {
		operation = "transfer"
	}
	if err == nil {
		return nil
	}
	if errors.Is(err, context.DeadlineExceeded) || status.Code(err) == codes.DeadlineExceeded {
		return &readFailure{"LEDGER_TIMEOUT", "DRUNIX " + operation + " preparation timed out.", http.StatusGatewayTimeout}
	}
	unavailable := &readFailure{"LEDGER_UNAVAILABLE", "DRUNIX " + operation + " preparation is unavailable.", http.StatusServiceUnavailable}
	var rpc interface{ GRPCStatus() *status.Status }
	if !errors.As(err, &rpc) {
		return unavailable
	}
	st := rpc.GRPCStatus()
	if st == nil || st.Code() != codes.Aborted || st.Message() != "failed to collect enough transaction endorsements, see attached details for more info" {
		return unavailable
	}
	details := st.Details()
	if len(details) == 0 {
		return unavailable
	}
	expected := ""
	for _, detail := range details {
		peer, ok := detail.(*gp.ErrorDetail)
		if !ok || peer.Address == "" || (peer.MspId != "Org1MSP" && peer.MspId != "Org2MSP") {
			return unavailable
		}
		code := recognizedBusinessError(peer.Message, function)
		if code == "" || (expected != "" && code != expected) {
			return unavailable
		}
		expected = code
	}
	return classifiedBusinessFailure(expected)
}
