package registration

import (
	"bytes"
	"crypto/sha256"
	"crypto/x509"
	"encoding/hex"
	"encoding/json"
	"encoding/pem"
	common "github.com/hyperledger/fabric-protos-go-apiv2/common"
	gp "github.com/hyperledger/fabric-protos-go-apiv2/gateway"
	"github.com/hyperledger/fabric-protos-go-apiv2/msp"
	"github.com/hyperledger/fabric-protos-go-apiv2/peer"
	"google.golang.org/protobuf/proto"
)

func validatePrepared(a Artifact) error {
	command, e := json.Marshal(a.Command)
	if e != nil {
		return invalid
	}
	return validatePreparedCommand(a, "RegisterApprovedProperty", command)
}

func validatePreparedCommand(a Artifact, function string, command []byte) error {
	var prepared gp.PreparedTransaction
	if proto.Unmarshal(a.Transaction, &prepared) != nil || prepared.GetTransactionId() != a.TransactionID || prepared.GetEnvelope() == nil {
		return invalid
	}
	var payload common.Payload
	if proto.Unmarshal(prepared.Envelope.Payload, &payload) != nil || payload.Header == nil {
		return invalid
	}
	var channel common.ChannelHeader
	var signature common.SignatureHeader
	if proto.Unmarshal(payload.Header.ChannelHeader, &channel) != nil || proto.Unmarshal(payload.Header.SignatureHeader, &signature) != nil || channel.ChannelId != "mychannel" || channel.TxId != a.TransactionID || !bytes.Equal(signature.Creator, a.Creator) {
		return invalid
	}
	var creator msp.SerializedIdentity
	if proto.Unmarshal(a.Creator, &creator) != nil || creator.Mspid != "Org1MSP" {
		return invalid
	}
	block, _ := pem.Decode(creator.IdBytes)
	if block == nil {
		return invalid
	}
	cert, e := x509.ParseCertificate(block.Bytes)
	if e != nil {
		return invalid
	}
	sum := sha256.Sum256(cert.Raw)
	if "Org1MSP:"+hex.EncodeToString(sum[:]) != Signer {
		return invalid
	}
	var tx peer.Transaction
	var action peer.ChaincodeActionPayload
	var proposal peer.ChaincodeProposalPayload
	var invocation peer.ChaincodeInvocationSpec
	if proto.Unmarshal(payload.Data, &tx) != nil || len(tx.Actions) != 1 || proto.Unmarshal(tx.Actions[0].Payload, &action) != nil || proto.Unmarshal(action.ChaincodeProposalPayload, &proposal) != nil || proto.Unmarshal(proposal.Input, &invocation) != nil {
		return invalid
	}
	spec := invocation.GetChaincodeSpec()
	args := spec.GetInput().GetArgs()
	if spec.GetChaincodeId().GetName() != "tokansh" || len(args) != 2 || string(args[0]) != function || !bytes.Equal(args[1], command) {
		return invalid
	}
	return nil
}
