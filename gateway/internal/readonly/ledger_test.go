package readonly

import (
	"context"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/pem"
	"errors"
	"math/big"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func configEnv() map[string]string {
	return map[string]string{"DRUNIX_MSP_ID": "Org1MSP", "DRUNIX_CERT_PATH": "/test/cert", "DRUNIX_KEY_PATH": "/test/key", "DRUNIX_TLS_CA_PATH": "/test/ca", "DRUNIX_PEER_ENDPOINT": "dns:///localhost:7051", "DRUNIX_TLS_SERVER_NAME": "peer0.org1.example.com"}
}
func TestConfiguration(t *testing.T) {
	base := configEnv()
	c, err := LoadConfig(func(k string) string { return base[k] })
	if err != nil {
		t.Fatal(err)
	}
	if c.ListenAddress != "127.0.0.1:8001" || c.Channel != "mychannel" || c.Chaincode != "basic" {
		t.Fatal("unsafe defaults")
	}
	for _, pair := range [][2]string{{"DRUNIX_KEY_PATH", ""}, {"DRUNIX_PEER_ENDPOINT", ":7051"}, {"DRUNIX_PEER_ENDPOINT", "localhost:bad"}, {"DRUNIX_LISTEN_ADDRESS", "0.0.0.0:8001"}, {"DRUNIX_LISTEN_ADDRESS", "127.0.0.1:0"}, {"DRUNIX_CHANNEL", "other"}, {"DRUNIX_CHAINCODE", "other"}, {"DRUNIX_EVALUATE_TIMEOUT", "0s"}, {"DRUNIX_EVALUATE_TIMEOUT", "30s"}} {
		t.Run(pair[0]+pair[1], func(t *testing.T) {
			env := configEnv()
			env[pair[0]] = pair[1]
			if _, err := LoadConfig(func(k string) string { return env[k] }); err == nil {
				t.Fatal("invalid configuration accepted")
			}
		})
	}
}

// All generated credentials in this file are ephemeral, isolated test identities.
func testIdentity(t *testing.T) Config {
	t.Helper()
	dir := t.TempDir()
	key, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	template := &x509.Certificate{SerialNumber: big.NewInt(1), Subject: pkix.Name{CommonName: "test-only"}, NotBefore: time.Now().Add(-time.Hour), NotAfter: time.Now().Add(time.Hour), IsCA: true, BasicConstraintsValid: true, KeyUsage: x509.KeyUsageCertSign | x509.KeyUsageDigitalSignature}
	der, err := x509.CreateCertificate(rand.Reader, template, template, &key.PublicKey, key)
	if err != nil {
		t.Fatal(err)
	}
	keyDER, err := x509.MarshalPKCS8PrivateKey(key)
	if err != nil {
		t.Fatal(err)
	}
	certPath, keyPath := filepath.Join(dir, "cert.pem"), filepath.Join(dir, "key.pem")
	if err := os.WriteFile(certPath, pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: der}), 0600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(keyPath, pem.EncodeToMemory(&pem.Block{Type: "PRIVATE KEY", Bytes: keyDER}), 0600); err != nil {
		t.Fatal(err)
	}
	return Config{MSPID: "TestOnlyMSP", CertPath: certPath, KeyPath: keyPath, TLSCAPath: certPath, PeerEndpoint: "127.0.0.1:1", ServerName: "test-only", Channel: "mychannel", Chaincode: "basic", EvaluateTimeout: 100 * time.Millisecond}
}

func TestIdentityAndTLSLoading(t *testing.T) {
	for _, kind := range []string{"certificate", "key", "ca", "mismatch"} {
		t.Run(kind, func(t *testing.T) {
			c := testIdentity(t)
			switch kind {
			case "certificate":
				c.CertPath = "/missing"
			case "key":
				os.WriteFile(c.KeyPath, []byte("invalid-test-key"), 0600)
			case "ca":
				c.TLSCAPath = c.KeyPath
			case "mismatch":
				c.KeyPath = testIdentity(t).KeyPath
			}
			_, err := Connect(c)
			var failure *Failure
			if !errors.As(err, &failure) {
				t.Fatal("configuration failure not returned")
			}
			if kind == "ca" && failure.Code != "TLS_CONFIGURATION_ERROR" {
				t.Fatal(failure)
			}
			if kind != "ca" && failure.Code != "IDENTITY_ERROR" {
				t.Fatal(failure)
			}
		})
	}
}

func TestConnectionDeadline(t *testing.T) {
	sdk, err := Connect(testIdentity(t))
	if err != nil {
		t.Fatal(err)
	}
	defer sdk.Close()
	_, err = sdk.GetAllAssets(context.Background())
	var failure *Failure
	if !errors.As(err, &failure) || (failure.Code != "LEDGER_TIMEOUT" && failure.Code != "LEDGER_UNAVAILABLE") {
		t.Fatalf("expected explicit connection failure, got %v", err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	_, err = sdk.GetAllAssets(ctx)
	if !errors.As(err, &failure) || failure.Code != "REQUEST_CANCELLED" {
		t.Fatalf("cancellation lost: %v", err)
	}
}

func TestPayloadValidation(t *testing.T) {
	asset := `{"ID":"asset1","Color":"blue","Size":5,"Owner":"test","AppraisedValue":300}`
	for _, test := range []struct {
		function, data string
		ok             bool
	}{{"GetAllAssets", "[" + asset + "]", true}, {"ReadAsset", asset, true}, {"AssetExists", "false", true}, {"GetAllAssets", "null", true}, {"ReadAsset", "null", false}, {"GetAllAssets", "[{}]", false}, {"AssetExists", "null", false}, {"AssetExists", "{}", false}, {"AssetExists", "true false", false}, {"ReadAsset", "{broken", false}, {"GetAllAssets", "[" + asset + "," + asset + "]", false}, {"InitLedger", "[]", false}} {
		_, err := validateResult(test.function, []byte(test.data))
		if (err == nil) != test.ok {
			t.Errorf("%s %s: %v", test.function, test.data, err)
		}
	}
}
