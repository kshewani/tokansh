package readonly

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"net/http"
	"regexp"
	"time"
)

// Only this read-only surface is available to the HTTP layer.
type Reader interface {
	GetAllAssets(context.Context) (json.RawMessage, error)
	ReadAsset(context.Context, string) (json.RawMessage, error)
	AssetExists(context.Context, string) (json.RawMessage, error)
}

type Observation struct {
	Source     string          `json:"source"`
	Channel    string          `json:"channel"`
	Chaincode  string          `json:"chaincode"`
	Function   string          `json:"function"`
	ObservedAt string          `json:"observed_at"`
	Result     json.RawMessage `json:"result"`
}

func writeJSON(w http.ResponseWriter, r *http.Request, status int, data any) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(status)
	json.NewEncoder(w).Encode(map[string]any{"data": data, "meta": map[string]string{"correlation_id": r.Header.Get("X-Correlation-ID")}})
}

func writeFailure(w http.ResponseWriter, r *http.Request, err error) {
	f := &Failure{Code: "INTERNAL_ERROR", Message: "The diagnostic request could not be completed.", Status: 500}
	var known *Failure
	if errors.As(err, &known) {
		f = known
	}
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(f.Status)
	json.NewEncoder(w).Encode(map[string]any{"error": map[string]string{"code": f.Code, "message": f.Message}, "meta": map[string]string{"correlation_id": r.Header.Get("X-Correlation-ID")}})
}

var correlationPattern = regexp.MustCompile(`^[A-Za-z0-9._:-]{1,128}$`)

func NewHandler(reader Reader, c Config) http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		writeFailure(w, r, fail("RESOURCE_NOT_FOUND", "Diagnostic endpoint was not found.", 404))
	})
	mux.HandleFunc("GET /health", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, r, 200, map[string]string{"status": "UP", "mode": "READ_ONLY"})
	})
	respond := func(w http.ResponseWriter, r *http.Request, function string, read func(context.Context) (json.RawMessage, error)) {
		ctx, cancel := context.WithTimeout(r.Context(), c.EvaluateTimeout)
		defer cancel()
		result, err := read(ctx)
		if err != nil {
			writeFailure(w, r, err)
			return
		}
		// Validate again at the HTTP boundary; test doubles never define the production data contract.
		result, err = validateResult(function, result)
		if err != nil {
			writeFailure(w, r, err)
			return
		}
		writeJSON(w, r, 200, Observation{Source: "DRUNIX_EVALUATE", Channel: c.Channel, Chaincode: c.Chaincode,
			Function: function, ObservedAt: time.Now().UTC().Format(time.RFC3339Nano), Result: result})
	}
	mux.HandleFunc("GET /v1/basic/assets", func(w http.ResponseWriter, r *http.Request) { respond(w, r, "GetAllAssets", reader.GetAllAssets) })
	mux.HandleFunc("GET /v1/basic/assets/{id}", func(w http.ResponseWriter, r *http.Request) {
		id := r.PathValue("id")
		if !ValidAssetID(id) {
			writeFailure(w, r, fail("INVALID_ARGUMENT", "Asset ID is invalid.", 400))
			return
		}
		respond(w, r, "ReadAsset", func(ctx context.Context) (json.RawMessage, error) { return reader.ReadAsset(ctx, id) })
	})
	mux.HandleFunc("GET /v1/basic/assets/{id}/exists", func(w http.ResponseWriter, r *http.Request) {
		id := r.PathValue("id")
		if !ValidAssetID(id) {
			writeFailure(w, r, fail("INVALID_ARGUMENT", "Asset ID is invalid.", 400))
			return
		}
		respond(w, r, "AssetExists", func(ctx context.Context) (json.RawMessage, error) { return reader.AssetExists(ctx, id) })
	})
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		id := r.Header.Get("X-Correlation-ID")
		if id == "" {
			var nonce [16]byte
			if _, err := rand.Read(nonce[:]); err != nil {
				writeFailure(w, r, err)
				return
			}
			id = hex.EncodeToString(nonce[:])
		}
		if !correlationPattern.MatchString(id) {
			r.Header.Set("X-Correlation-ID", "invalid-reference")
			w.Header().Set("X-Correlation-ID", "invalid-reference")
			writeFailure(w, r, fail("INVALID_ARGUMENT", "Correlation ID is invalid.", 400))
			return
		}
		r.Header.Set("X-Correlation-ID", id)
		w.Header().Set("X-Correlation-ID", id)
		if r.Method != "GET" {
			w.Header().Set("Allow", "GET")
			writeFailure(w, r, fail("METHOD_NOT_ALLOWED", "Only read-only GET requests are supported.", 405))
			return
		}
		if r.URL.RawQuery != "" || r.ContentLength > 0 || len(r.TransferEncoding) > 0 {
			writeFailure(w, r, fail("INVALID_ARGUMENT", "Query parameters and request bodies are not supported.", 400))
			return
		}
		mux.ServeHTTP(w, r)
	})
}
