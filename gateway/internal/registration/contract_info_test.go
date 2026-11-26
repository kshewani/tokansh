package registration

import (
	"context"
	"encoding/json"
	"reflect"
	"strings"
	"testing"
)

// Exact metadata returned by chaincode/tokansh/contract/contract.go GetContractInfo
// for M4.1; schema_version remains 1 and is not the lifecycle version.
const contractInfoV11 = `{"contract":"tokansh","schema_version":1,"functions":["GetContractInfo","GetRegisteredProperty","GetOperation","RegisterApprovedProperty","IssueANSH","GetIssuanceState","GetBalance","GetIssuanceOperation"],"supply_interpretation":"LIFETIME_CUMULATIVE_ISSUANCE_CEILING"}`

// Exact nine-function interface in the reviewed local M4.2 chaincode.
const contractInfoV12 = `{"contract":"tokansh","schema_version":1,"functions":["GetContractInfo","GetRegisteredProperty","GetOperation","RegisterApprovedProperty","IssueANSH","GetIssuanceState","GetBalance","GetIssuanceOperation","TransferANSH"],"supply_interpretation":"ONE_TIME_FULL_SUPPLY_ISSUANCE"}`

func TestReviewedContractInterfaces(t *testing.T) {
	for _, body := range []string{contractInfoV12, contractInfoV11, strings.Replace(contractInfoV11, `,"IssueANSH","GetIssuanceState","GetBalance","GetIssuanceOperation"`, "", 1)} {
		ledger := &readLedger{body: []byte(body)}
		got, err := (&Service{Ledger: ledger}).Read(context.Background(), "GetContractInfo", "")
		var want ContractInfo
		if err != nil || json.Unmarshal([]byte(body), &want) != nil || !reflect.DeepEqual(got, want) {
			t.Fatalf("reviewed interface rejected or altered: %v", err)
		}
	}
}

func TestUnexpectedContractMetadataRejected(t *testing.T) {
	cases := map[string]string{
		"malformed":              `{`,
		"duplicate key":          strings.Replace(contractInfoV11, `"contract":"tokansh"`, `"contract":"wrong","contract":"tokansh"`, 1),
		"case variant":           strings.Replace(contractInfoV11, `"functions"`, `"Functions"`, 1),
		"trailing JSON":          contractInfoV11 + `{}`,
		"v12 unknown function":   strings.Replace(contractInfoV12, "TransferANSH", "BurnANSH", 1),
		"v12 duplicate function": strings.Replace(contractInfoV12, "TransferANSH", "GetBalance", 1),
		"v12 extra function":     strings.Replace(contractInfoV12, `"TransferANSH"]`, `"TransferANSH","FutureFunction"]`, 1),
	}
	for name, change := range map[string]func(map[string]any){
		"identity":           func(v map[string]any) { v["contract"] = "basic" },
		"schema":             func(v map[string]any) { v["schema_version"] = 2 },
		"supply":             func(v map[string]any) { v["supply_interpretation"] = "MINTED_SUPPLY" },
		"extra field":        func(v map[string]any) { v["version"] = "1.1" },
		"missing":            func(v map[string]any) { delete(v, "functions") },
		"null":               func(v map[string]any) { v["functions"] = nil },
		"empty":              func(v map[string]any) { v["functions"] = []string{} },
		"wrong type":         func(v map[string]any) { v["functions"] = "IssueANSH" },
		"missing function":   func(v map[string]any) { v["functions"] = v["functions"].([]any)[:7] },
		"unknown function":   func(v map[string]any) { v["functions"].([]any)[7] = "BurnANSH" },
		"duplicate function": func(v map[string]any) { v["functions"].([]any)[7] = "GetBalance" },
		"reordered":          func(v map[string]any) { f := v["functions"].([]any); f[0], f[1] = f[1], f[0] },
		"extra function":     func(v map[string]any) { v["functions"] = append(v["functions"].([]any), "FutureFunction") },
	} {
		var v map[string]any
		if err := json.Unmarshal([]byte(contractInfoV11), &v); err != nil {
			t.Fatal(err)
		}
		change(v)
		b, err := json.Marshal(v)
		if err != nil {
			t.Fatal(err)
		}
		cases[name] = string(b)
	}
	for name, body := range cases {
		t.Run(name, func(t *testing.T) {
			_, err := (&Service{Ledger: &readLedger{body: []byte(body)}}).Read(context.Background(), "GetContractInfo", "")
			if err == nil {
				t.Fatal("unreviewed metadata accepted")
			}
		})
	}
}
