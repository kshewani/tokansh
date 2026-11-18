package readonly

import (
	"bytes"
	"context"
	"crypto/ecdsa"
	"crypto/tls"
	"crypto/x509"
	"encoding/json"
	"errors"
	"io"
	"os"
	"regexp"
	"time"

	"github.com/hyperledger/fabric-gateway/pkg/client"
	"github.com/hyperledger/fabric-gateway/pkg/hash"
	"github.com/hyperledger/fabric-gateway/pkg/identity"
	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/credentials"
	"google.golang.org/grpc/status"
)

type Failure struct {
	Code, Message string
	Status        int
}

func (e *Failure) Error() string                  { return e.Code + ": " + e.Message }
func fail(code, message string, status int) error { return &Failure{code, message, status} }

type SDK struct {
	connection *grpc.ClientConn
	gateway    *client.Gateway
	contract   *client.Contract
	config     Config
}

func Connect(c Config) (*SDK, error) {
	certPEM, err := os.ReadFile(c.CertPath)
	if err != nil {
		return nil, fail("IDENTITY_ERROR", "Signing certificate could not be loaded.", 503)
	}
	cert, err := identity.CertificateFromPEM(certPEM)
	if err != nil || time.Now().Before(cert.NotBefore) || time.Now().After(cert.NotAfter) {
		return nil, fail("IDENTITY_ERROR", "Signing certificate is invalid or outside its validity period.", 503)
	}
	keyPEM, err := os.ReadFile(c.KeyPath)
	if err != nil {
		return nil, fail("IDENTITY_ERROR", "Signing key could not be loaded.", 503)
	}
	key, err := identity.PrivateKeyFromPEM(keyPEM)
	if err != nil {
		return nil, fail("IDENTITY_ERROR", "Signing key is invalid.", 503)
	}
	ec, ok := key.(*ecdsa.PrivateKey)
	if !ok || ec.Curve.Params().BitSize != 256 {
		return nil, fail("IDENTITY_ERROR", "This gateway requires an ECDSA P-256 signing key.", 503)
	}
	public, ok := cert.PublicKey.(*ecdsa.PublicKey)
	if !ok || !public.Equal(ec.Public()) {
		return nil, fail("IDENTITY_ERROR", "Signing certificate and key do not match.", 503)
	}
	id, err := identity.NewX509Identity(c.MSPID, cert)
	if err != nil {
		return nil, fail("IDENTITY_ERROR", "Signing identity could not be constructed.", 503)
	}
	sign, err := identity.NewPrivateKeySign(key)
	if err != nil {
		return nil, fail("IDENTITY_ERROR", "Signing identity is unsupported.", 503)
	}
	caPEM, err := os.ReadFile(c.TLSCAPath)
	if err != nil {
		return nil, fail("TLS_CONFIGURATION_ERROR", "Peer TLS CA could not be loaded.", 503)
	}
	pool := x509.NewCertPool()
	if !pool.AppendCertsFromPEM(caPEM) {
		return nil, fail("TLS_CONFIGURATION_ERROR", "Peer TLS CA is invalid.", 503)
	}
	tlsConfig := &tls.Config{RootCAs: pool, ServerName: c.ServerName, MinVersion: tls.VersionTLS12}
	connection, err := grpc.NewClient(c.PeerEndpoint, grpc.WithTransportCredentials(credentials.NewTLS(tlsConfig)), grpc.WithDefaultCallOptions(grpc.MaxCallRecvMsgSize(2<<20)))
	if err != nil {
		return nil, fail("LEDGER_UNAVAILABLE", "TLS gateway client could not be created.", 503)
	}
	gw, err := client.Connect(id, client.WithSign(sign), client.WithHash(hash.SHA256), client.WithClientConnection(connection), client.WithEvaluateTimeout(c.EvaluateTimeout))
	if err != nil {
		connection.Close()
		return nil, fail("LEDGER_UNAVAILABLE", "Gateway client could not be created.", 503)
	}
	return &SDK{connection: connection, gateway: gw, contract: gw.GetNetwork(c.Channel).GetContract(c.Chaincode), config: c}, nil
}

func (s *SDK) Close() { s.gateway.Close(); s.connection.Close() }

// Probe deliberately uses only EvaluateTransaction, as in the reviewed sample.
func (s *SDK) Probe() (json.RawMessage, error) {
	data, err := s.contract.EvaluateTransaction("GetAllAssets")
	if err != nil {
		return nil, rpcFailure(err)
	}
	return validateResult("GetAllAssets", data)
}

func (s *SDK) evaluate(ctx context.Context, function string, args ...string) (json.RawMessage, error) {
	ctx, cancel := context.WithTimeout(ctx, s.config.EvaluateTimeout)
	defer cancel()
	data, err := s.contract.EvaluateWithContext(ctx, function, client.WithArguments(args...))
	if err != nil {
		return nil, rpcFailure(err)
	}
	return validateResult(function, data)
}

func rpcFailure(err error) error {
	if errors.Is(err, context.DeadlineExceeded) || status.Code(err) == codes.DeadlineExceeded {
		return fail("LEDGER_TIMEOUT", "DRUNIX evaluation timed out.", 504)
	}
	if errors.Is(err, context.Canceled) || status.Code(err) == codes.Canceled {
		return fail("REQUEST_CANCELLED", "DRUNIX evaluation was cancelled.", 408)
	}
	// Raw SDK errors can contain peer topology and chaincode internals. Never return them over HTTP.
	return fail("LEDGER_UNAVAILABLE", "DRUNIX evaluation failed (gRPC "+status.Code(err).String()+").", 503)
}

var assetID = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$`)

func ValidAssetID(id string) bool { return assetID.MatchString(id) }

func decode(data []byte, target any) error {
	if len(data) > 1<<20 {
		return fail("MALFORMED_LEDGER_RESPONSE", "DRUNIX response exceeds the diagnostic limit.", 502)
	}
	d := json.NewDecoder(bytes.NewReader(data))
	d.DisallowUnknownFields()
	if err := d.Decode(target); err != nil {
		return fail("MALFORMED_LEDGER_RESPONSE", "DRUNIX returned an invalid diagnostic payload.", 502)
	}
	if err := d.Decode(new(any)); err != io.EOF {
		return fail("MALFORMED_LEDGER_RESPONSE", "DRUNIX returned trailing payload data.", 502)
	}
	return nil
}

type asset struct {
	ID             *string `json:"ID"`
	Color          *string `json:"Color"`
	Size           *int64  `json:"Size"`
	Owner          *string `json:"Owner"`
	AppraisedValue *int64  `json:"AppraisedValue"`
}

func validAsset(a asset) bool {
	return a.ID != nil && ValidAssetID(*a.ID) && a.Color != nil && a.Size != nil && a.Owner != nil && a.AppraisedValue != nil
}

func validateResult(function string, data []byte) (json.RawMessage, error) {
	bad := func() (json.RawMessage, error) {
		return nil, fail("MALFORMED_LEDGER_RESPONSE", "DRUNIX diagnostic data has an unexpected shape.", 502)
	}
	switch function {
	case "GetAllAssets":
		var assets []asset
		if err := decode(data, &assets); err != nil {
			return nil, err
		}
		seen := map[string]bool{}
		for _, a := range assets {
			if !validAsset(a) || seen[*a.ID] {
				return bad()
			}
			seen[*a.ID] = true
		}
		if assets == nil {
			return json.RawMessage("[]"), nil
		} // The basic contract returns null for an empty range.
	case "ReadAsset":
		var a asset
		if err := decode(data, &a); err != nil {
			return nil, err
		}
		if !validAsset(a) {
			return bad()
		}
	case "AssetExists":
		var exists *bool
		if err := decode(data, &exists); err != nil {
			return nil, err
		}
		if exists == nil {
			return bad()
		}
	default:
		return nil, fail("INVALID_ARGUMENT", "Diagnostic function is not allowlisted.", 400)
	}
	return json.RawMessage(data), nil
}

func (s *SDK) GetAllAssets(ctx context.Context) (json.RawMessage, error) {
	return s.evaluate(ctx, "GetAllAssets")
}
func (s *SDK) AssetExists(ctx context.Context, id string) (json.RawMessage, error) {
	if !ValidAssetID(id) {
		return nil, fail("INVALID_ARGUMENT", "Asset ID is invalid.", 400)
	}
	return s.evaluate(ctx, "AssetExists", id)
}
func (s *SDK) ReadAsset(ctx context.Context, id string) (json.RawMessage, error) {
	exists, err := s.AssetExists(ctx, id)
	if err != nil {
		return nil, err
	}
	if bytes.Equal(bytes.TrimSpace(exists), []byte("false")) {
		return nil, fail("ASSET_NOT_FOUND", "Diagnostic asset was not found.", 404)
	}
	result, err := s.evaluate(ctx, "ReadAsset", id)
	if err != nil {
		return nil, err
	}
	var a asset
	if err := decode(result, &a); err != nil {
		return nil, err
	}
	if *a.ID != id {
		return nil, fail("MALFORMED_LEDGER_RESPONSE", "DRUNIX returned a different diagnostic asset.", 502)
	}
	return result, nil
}

// GatewayClient is shared only with the typed internal transaction adapter.
func (s *SDK) GatewayClient() *client.Gateway { return s.gateway }
