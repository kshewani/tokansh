// Offline stdin-only verifier. No SDK connection and no submission endpoints.
package main

import (
	"fmt"
	"io"
	"os"
	"time"
	"tokansh/gateway/internal/preparedverify"
)

func main() {
	var in preparedverify.Input
	b, e := io.ReadAll(io.LimitReader(os.Stdin, 4<<20))
	if e != nil || len(b) >= 4<<20 || preparedverify.StrictJSON(b, &in) != nil {
		fmt.Println("FAIL: INVALID_OFFLINE_INPUT")
		os.Exit(1)
	}
	if e = preparedverify.Verify(in, time.Now()); e != nil {
		fmt.Println("FAIL:", e.Error())
		os.Exit(1)
	}
	fmt.Println("PASS: OFFLINE_LOCAL_MSP_VERIFIED; operation=" + in.OperationID + "; transaction=" + in.TransactionID + "; endorsers=Org1MSP,Org2MSP; commit=NOT_VERIFIED")
}
