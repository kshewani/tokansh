package registration

type Command struct {
	CommandVersion    int    `json:"command_version"`
	OperationID       string `json:"operation_id"`
	PropertyID        string `json:"property_id"`
	IssuerID          string `json:"issuer_id"`
	ApprovalReference string `json:"approval_reference"`
	ApprovalDigest    string `json:"approval_digest"`
	ApprovedSupply    int64  `json:"approved_supply"`
	IssuePriceMinor   string `json:"issue_price_minor"`
	Currency          string `json:"currency"`
}

type Property struct {
	SchemaVersion             int    `json:"schema_version"`
	PropertyID                string `json:"property_id"`
	IssuerID                  string `json:"issuer_id"`
	ApprovalReference         string `json:"approval_reference"`
	ApprovalDigest            string `json:"approval_digest"`
	ApprovedSupply            int64  `json:"approved_supply"`
	IssuePriceMinor           string `json:"issue_price_minor"`
	Currency                  string `json:"currency"`
	RegisteredByMSP           string `json:"registered_by_msp"`
	RegisteredByPrincipal     string `json:"registered_by_principal"`
	RegistrationOperationID   string `json:"registration_operation_id"`
	RegistrationTransactionID string `json:"registration_transaction_id"`
	ProposalTimestamp         string `json:"proposal_timestamp"`
}

type RegistrationResult struct {
	PropertyID    string `json:"property_id"`
	OperationID   string `json:"operation_id"`
	TransactionID string `json:"transaction_id"`
}

type Operation struct {
	SchemaVersion         int                `json:"schema_version"`
	OperationID           string             `json:"operation_id"`
	AuthorizingMSP        string             `json:"authorizing_msp"`
	AuthorizingPrincipal  string             `json:"authorizing_principal"`
	Function              string             `json:"function"`
	RequestDigest         string             `json:"request_digest"`
	PropertyID            string             `json:"property_id"`
	OriginalTransactionID string             `json:"original_transaction_id"`
	Result                RegistrationResult `json:"result"`
}

type ContractInfo struct {
	Contract             string   `json:"contract"`
	SchemaVersion        int      `json:"schema_version"`
	Functions            []string `json:"functions"`
	SupplyInterpretation string   `json:"supply_interpretation"`
}
