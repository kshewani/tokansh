package registration

import (
	"context"
	"crypto/subtle"
	"encoding/hex"
	"encoding/json"
	"io"
	"net/http"
	"strings"
)

func Secret(value string) []byte {
	b, e := hex.DecodeString(value)
	if e != nil || len(b) != 32 {
		return nil
	}
	return b
}
func Handler(s *Service, operator []byte) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.Header().Set("Cache-Control", "no-store")
		respond := func(code int, v any) { w.WriteHeader(code); json.NewEncoder(w).Encode(v) }
		fail := func(status int, code string) {
			respond(status, map[string]any{"error": map[string]string{"code": code, "message": "Private registration request could not be completed."}})
		}
		if len(s.Key) != 32 || len(operator) != 32 || subtle.ConstantTimeCompare(s.Key, operator) == 1 {
			fail(503, "AUTH_NOT_CONFIGURED")
			return
		}
		if r.Header.Get("Origin") != "" || r.Header.Get("Sec-Fetch-Mode") != "" || r.URL.RawQuery != "" {
			fail(403, "FORBIDDEN")
			return
		}
		token := Secret(strings.TrimPrefix(r.Header.Get("Authorization"), "Bearer "))
		if !strings.HasPrefix(r.Header.Get("Authorization"), "Bearer ") || len(token) != 32 || subtle.ConstantTimeCompare(token, s.Key) != 1 {
			fail(401, "UNAUTHORIZED")
			return
		}
		if r.Method == "POST" {
			op := Secret(r.Header.Get("X-Operator-Capability"))
			if len(op) != 32 || subtle.ConstantTimeCompare(op, operator) != 1 {
				fail(403, "FORBIDDEN")
				return
			}
		}
		ctx, cancel := context.WithCancel(r.Context())
		defer cancel()
		var data any
		var err error
		path := strings.TrimPrefix(r.URL.Path, "/v1/tokansh/")
		if r.Method == "GET" {
			switch {
			case path == "contract-info":
				data, err = s.Read(ctx, "GetContractInfo", "")
			case strings.HasPrefix(path, "properties/"):
				data, err = s.Read(ctx, "GetRegisteredProperty", strings.TrimPrefix(path, "properties/"))
			case strings.HasPrefix(path, "operations/"):
				data, err = s.Read(ctx, "GetOperation", strings.TrimPrefix(path, "operations/"))
			default:
				fail(404, "NOT_FOUND")
				return
			}
		} else if r.Method == "POST" {
			r.Body = http.MaxBytesReader(w, r.Body, 2<<20)
			defer r.Body.Close()
			var raw json.RawMessage
			d := json.NewDecoder(r.Body)
			if d.Decode(&raw) != nil {
				fail(400, "INVALID_REQUEST")
				return
			}
			var trailing any
			if d.Decode(&trailing) != io.EOF {
				fail(400, "INVALID_REQUEST")
				return
			}
			switch path {
			case "property-registrations/prepare":
				var c Command
				c, err = DecodeCommand(raw)
				if err == nil {
					data, err = s.Prepare(ctx, c)
				}
			case "property-registrations/submit", "commit-status":
				var a Artifact
				err = strict(raw, &a)
				if err == nil {
					err = s.Check(a)
				}
				if err == nil {
					if path == "commit-status" {
						data, err = s.Ledger.Status(ctx, a)
					} else {
						err = s.Ledger.Submit(ctx, a)
						data = map[string]string{"state": "SUBMITTED", "transaction_id": a.TransactionID}
					}
				}
			default:
				fail(404, "NOT_FOUND")
				return
			}
		} else {
			fail(405, "METHOD_NOT_ALLOWED")
			return
		}
		if err != nil {
			if err == invalid {
				fail(400, "INVALID_REQUEST")
			} else {
				fail(503, "LEDGER_UNAVAILABLE")
			}
			return
		}
		respond(200, map[string]any{"data": data})
	})
}
