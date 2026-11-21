package readonly

import (
	"context"
	"encoding/json"
	"errors"
	"os"
	"sort"
	"strings"
	"testing"
)

func TestDRUNIXReadOnlyIntegration(t *testing.T) {
	if os.Getenv("RUN_DRUNIX_INTEGRATION") != "1" {
		t.Skip("opt-in: requires existing DRUNIX credentials/network")
	}
	c, err := LoadConfig(os.Getenv)
	if err != nil {
		t.Fatal(err)
	}
	sdk, err := Connect(c)
	if err != nil {
		t.Fatal(err)
	}
	defer sdk.Close()
	result, err := sdk.GetAllAssets(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	var assets []asset
	if err := json.Unmarshal(result, &assets); err != nil {
		t.Fatal(err)
	}
	ids := make([]string, 0, len(assets))
	for _, a := range assets {
		ids = append(ids, *a.ID)
	}
	sort.Strings(ids)
	if strings.Join(ids, ",") != "asset1,asset2,asset3,asset4,asset5,asset6" {
		t.Fatalf("diagnostic baseline changed: %v", ids)
	}
	t.Logf("actual DRUNIX assets: %v", ids)
	read, err := sdk.ReadAsset(context.Background(), "asset1")
	if err != nil {
		t.Fatal(err)
	}
	var first asset
	json.Unmarshal(read, &first)
	if *first.ID != "asset1" {
		t.Fatal("wrong asset")
	}
	exists, err := sdk.AssetExists(context.Background(), "asset1")
	if err != nil || string(exists) != "true" {
		t.Fatalf("existing asset lookup: %s %v", exists, err)
	}
	_, err = sdk.ReadAsset(context.Background(), "tokansh_missing_diagnostic")
	var failure *Failure
	if !errors.As(err, &failure) || failure.Code != "ASSET_NOT_FOUND" {
		t.Fatalf("missing asset: %v", err)
	}
	wrongName := c
	wrongName.ServerName = "wrong.invalid"
	wrongSDK, err := Connect(wrongName)
	if err != nil {
		t.Fatal(err)
	}
	defer wrongSDK.Close()
	if _, err = wrongSDK.GetAllAssets(context.Background()); err == nil {
		t.Fatal("incorrect TLS server name was accepted")
	}
}
