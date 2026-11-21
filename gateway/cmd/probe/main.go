package main

import (
	"encoding/json"
	"fmt"
	"os"
	"tokansh/gateway/internal/readonly"
)

func main() {
	c, err := readonly.LoadConfig(os.Getenv)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	sdk, err := readonly.Connect(c)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	defer sdk.Close()
	assets, err := sdk.Probe()
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	json.NewEncoder(os.Stdout).Encode(map[string]any{"source": "DRUNIX_EVALUATE", "channel": c.Channel, "chaincode": c.Chaincode, "assets": assets})
}
