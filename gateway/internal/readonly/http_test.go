package readonly

import (
	"context"
	"encoding/json"
	"errors"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

type testReader struct {
	calls    []string
	response json.RawMessage
	err      error
	wait     bool
}

func (r *testReader) get(ctx context.Context, function string) (json.RawMessage, error) {
	r.calls = append(r.calls, function)
	if r.wait {
		<-ctx.Done()
		return nil, rpcFailure(ctx.Err())
	}
	return r.response, r.err
}
func (r *testReader) GetAllAssets(ctx context.Context) (json.RawMessage, error) {
	return r.get(ctx, "GetAllAssets")
}
func (r *testReader) ReadAsset(ctx context.Context, id string) (json.RawMessage, error) {
	return r.get(ctx, "ReadAsset")
}
func (r *testReader) AssetExists(ctx context.Context, id string) (json.RawMessage, error) {
	return r.get(ctx, "AssetExists")
}

func TestHTTPReadAllowlist(t *testing.T) {
	a := `{"ID":"asset1","Color":"blue","Size":5,"Owner":"test-only","AppraisedValue":300}`
	for _, test := range []struct{ path, function, payload string }{{"/v1/basic/assets", "GetAllAssets", "[" + a + "]"}, {"/v1/basic/assets/asset1", "ReadAsset", a}, {"/v1/basic/assets/asset1/exists", "AssetExists", "true"}} {
		t.Run(test.function, func(t *testing.T) {
			reader := &testReader{response: json.RawMessage(test.payload)}
			handler := NewHandler(reader, Config{Channel: "mychannel", Chaincode: "basic", EvaluateTimeout: time.Second})
			request := httptest.NewRequest("GET", test.path, nil)
			request.Header.Set("X-Correlation-ID", "test-reference")
			response := httptest.NewRecorder()
			handler.ServeHTTP(response, request)
			if response.Code != 200 || len(reader.calls) != 1 || reader.calls[0] != test.function {
				t.Fatalf("wrong read operation: %d %v", response.Code, reader.calls)
			}
			var frame struct {
				Data Observation `json:"data"`
			}
			if err := json.Unmarshal(response.Body.Bytes(), &frame); err != nil {
				t.Fatal(err)
			}
			if frame.Data.Source != "DRUNIX_EVALUATE" || frame.Data.Function != test.function {
				t.Fatal("missing observation provenance")
			}
			if strings.Contains(response.Body.String(), "transaction_id") || strings.Contains(response.Body.String(), "COMMITTED") {
				t.Fatal("fabricated ledger evidence")
			}
			if response.Header().Get("X-Correlation-ID") != "test-reference" {
				t.Fatal("correlation lost")
			}
		})
	}
}

func TestHTTPRejectsNonReadRequests(t *testing.T) {
	for _, test := range []struct {
		method, path, body string
		status             int
	}{{"POST", "/invoke", "{}", 405}, {"GET", "/invoke", "", 404}, {"GET", "/v1/basic/assets?function=InitLedger", "", 400}, {"GET", "/v1/basic/assets/bad%20id", "", 400}, {"GET", "/v1/basic/assets", "{}", 400}} {
		reader := &testReader{}
		handler := NewHandler(reader, Config{EvaluateTimeout: time.Second})
		response := httptest.NewRecorder()
		handler.ServeHTTP(response, httptest.NewRequest(test.method, test.path, strings.NewReader(test.body)))
		if response.Code != test.status || len(reader.calls) != 0 {
			t.Fatalf("unsafe request %s %s: %d %v", test.method, test.path, response.Code, reader.calls)
		}
		if !json.Valid(response.Body.Bytes()) {
			t.Fatal("unstructured error")
		}
	}
}

func TestHTTPErrorsAndTimeout(t *testing.T) {
	for _, test := range []struct {
		reader testReader
		status int
	}{{testReader{err: fail("ASSET_NOT_FOUND", "Diagnostic asset was not found.", 404)}, 404}, {testReader{err: errors.New("test-only secret internal detail")}, 500}, {testReader{response: json.RawMessage(`{}`)}, 502}, {testReader{wait: true}, 504}} {
		reader := test.reader
		handler := NewHandler(&reader, Config{EvaluateTimeout: 10 * time.Millisecond})
		response := httptest.NewRecorder()
		handler.ServeHTTP(response, httptest.NewRequest("GET", "/v1/basic/assets", nil))
		if response.Code != test.status {
			t.Fatalf("expected %d got %d", test.status, response.Code)
		}
		if strings.Contains(response.Body.String(), "secret") {
			t.Fatal("internal error leaked")
		}
	}
}

func TestHTTPHealthDoesNotClaimLedgerReadiness(t *testing.T) {
	reader := &testReader{}
	response := httptest.NewRecorder()
	NewHandler(reader, Config{}).ServeHTTP(response, httptest.NewRequest("GET", "/health", nil))
	if response.Code != 200 || len(reader.calls) != 0 || strings.Contains(response.Body.String(), "CONNECTED") {
		t.Fatal("liveness implies ledger readiness")
	}
}
