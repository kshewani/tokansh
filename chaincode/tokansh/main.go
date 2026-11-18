package main

import (
	"github.com/hyperledger/fabric-contract-api-go/v2/contractapi"
	"log"
	"tokansh/chaincode/contract"
)

func main() {
	cc, err := contractapi.NewChaincode(&contract.SmartContract{})
	if err != nil {
		log.Fatal("chaincode construction failed")
	}
	if err := cc.Start(); err != nil {
		log.Fatal("chaincode startup failed")
	}
}
