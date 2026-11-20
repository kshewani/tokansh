package registration

import (
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"strings"
)

// Only the typed issuance/transfer services use this common artifact layout.
// Field order and JSON encoding preserve the existing issuance MAC contract.
type commandArtifact[C any] struct {
	Version       int    `json:"version"`
	Channel       string `json:"channel"`
	Chaincode     string `json:"chaincode"`
	Signer        string `json:"signer"`
	Function      string `json:"function"`
	Command       C      `json:"command"`
	RequestDigest string `json:"request_digest"`
	TransactionID string `json:"transaction_id"`
	Transaction   []byte `json:"transaction"`
	Creator       []byte `json:"creator"`
	MAC           string `json:"mac"`
}

func typedCommandDigest[C any](c C) string {
	b, _ := json.Marshal(c)
	sum := sha256.Sum256(b)
	return hex.EncodeToString(sum[:])
}
func commandMAC[C any](key []byte, a commandArtifact[C]) string {
	a.MAC = ""
	b, _ := json.Marshal(a)
	mac := hmac.New(sha256.New, key)
	mac.Write(b)
	return hex.EncodeToString(mac.Sum(nil))
}
func commandEnvelope[C any](a commandArtifact[C]) Artifact {
	return Artifact{Channel: a.Channel, Chaincode: a.Chaincode, Signer: a.Signer, TransactionID: a.TransactionID, Transaction: a.Transaction, Creator: a.Creator}
}
func checkCommandArtifact[C any](s *Service, a commandArtifact[C], function string, validate func(C) error) error {
	if len(s.Key) != 32 || a.Version != 1 || a.Channel != "mychannel" || a.Chaincode != "tokansh" || a.Signer != Signer || a.Function != function || validate(a.Command) != nil || a.RequestDigest != typedCommandDigest(a.Command) || strings.TrimSpace(a.TransactionID) == "" || len(a.Transaction) == 0 || len(a.Creator) == 0 || !hmac.Equal([]byte(a.MAC), []byte(commandMAC(s.Key, a))) {
		return invalid
	}
	b, e := json.Marshal(a.Command)
	if e != nil {
		return invalid
	}
	return validatePreparedCommand(commandEnvelope(a), function, b)
}
func prepareCommandArtifact[C any](s *Service, ctx context.Context, c C, function string, validate func(C) error, prepare func(context.Context, C) (string, []byte, []byte, error)) (commandArtifact[C], error) {
	if validate(c) != nil || len(s.Key) != 32 {
		return commandArtifact[C]{}, invalid
	}
	id, tx, creator, e := prepare(ctx, c)
	if e != nil {
		return commandArtifact[C]{}, classifyPreparation(e, function)
	}
	a := commandArtifact[C]{1, "mychannel", "tokansh", Signer, function, c, typedCommandDigest(c), id, tx, creator, ""}
	a.MAC = commandMAC(s.Key, a)
	if e = checkCommandArtifact(s, a, function, validate); e != nil {
		return commandArtifact[C]{}, e
	}
	return a, nil
}
