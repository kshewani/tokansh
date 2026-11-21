package registration

import "context"

// Exact version-1 chaincode TransferANSH command; no caller-supplied signer.
type TransferCommand struct {
	CommandVersion int    `json:"command_version"`
	OperationID    string `json:"operation_id"`
	PropertyID     string `json:"property_id"`
	FromHolderID   string `json:"from_holder_id"`
	ToHolderID     string `json:"to_holder_id"`
	Quantity       int64  `json:"quantity"`
}
type TransferArtifact = commandArtifact[TransferCommand]
type TransferLedger interface {
	PrepareTransfer(context.Context, TransferCommand) (string, []byte, []byte, error)
}

func validateTransfer(c TransferCommand) error {
	if c.CommandVersion != 1 || !uuid.MatchString(c.OperationID) || !uuid.MatchString(c.PropertyID) || !uuid.MatchString(c.FromHolderID) || !uuid.MatchString(c.ToHolderID) || c.FromHolderID == c.ToHolderID || c.Quantity < 1 || c.Quantity > maxIssuance {
		return invalid
	}
	return nil
}
func DecodeTransferCommand(b []byte) (TransferCommand, error) {
	var c TransferCommand
	if len(b) > 4096 || strict(b, &c) != nil {
		return c, invalid
	}
	return c, validateTransfer(c)
}
func (s *Service) CheckTransfer(a TransferArtifact) error {
	return checkCommandArtifact(s, a, "TransferANSH", validateTransfer)
}
func (s *Service) PrepareTransfer(ctx context.Context, c TransferCommand) (TransferArtifact, error) {
	ledger, ok := s.Ledger.(TransferLedger)
	if !ok {
		return TransferArtifact{}, invalid
	}
	return prepareCommandArtifact(s, ctx, c, "TransferANSH", validateTransfer, ledger.PrepareTransfer)
}
