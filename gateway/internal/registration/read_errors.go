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
func recognizedMissing(message, function string) string {
	const prefix = "chaincode response 500, "
	if !strings.HasPrefix(message, prefix) || len(message) > 1024 {
		return ""
	}
	var business businessReadError
	if strict([]byte(strings.TrimPrefix(message, prefix)), &business) != nil {
		return ""
	}
	if function == "GetRegisteredProperty" && business.Code == "PROPERTY_NOT_FOUND" && business.Message == "Registered property was not found." {
		return business.Code
	}
	if function == "GetOperation" && business.Code == "OPERATION_NOT_FOUND" && business.Message == "Operation was not found." {
		return business.Code
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
			code := recognizedMissing(peer.Message, function)
			if code == "" || (expected != "" && expected != code) {
				return unavailable
			}
			expected = code
		}
	} else {
		const prefix = "evaluate call to endorser returned error: "
		if strings.HasPrefix(st.Message(), prefix) {
			expected = recognizedMissing(strings.TrimPrefix(st.Message(), prefix), function)
		}
	}
	switch expected {
	case "PROPERTY_NOT_FOUND":
		return &readFailure{expected, "Registered property was not found.", http.StatusNotFound}
	case "OPERATION_NOT_FOUND":
		return &readFailure{expected, "Operation was not found.", http.StatusNotFound}
	default:
		return unavailable
	}
}
