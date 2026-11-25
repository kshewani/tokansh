package registration

import (
	"context"
	"encoding/json"

	"github.com/hyperledger/fabric-gateway/pkg/client"
)

// Adapter is the single in-process DRUNIX adapter. It is the SDK type, not a
// separate module or binary.
type Adapter = SDK

func NewAdapter(gw *client.Gateway, mspID, certPath string) (*Adapter, error) {
	return NewSDK(gw, mspID, certPath)
}

// Typed read helpers over the adapter. They preserve the gateway's fail-closed
// JSON decoding and never fabricate transaction evidence.
func (a *Adapter) ContractInfo(ctx context.Context) (ContractInfo, error) {
	b, err := a.Read(ctx, "GetContractInfo")
	if err != nil {
		return ContractInfo{}, err
	}
	var v ContractInfo
	if err := strict(b, &v); err != nil {
		return ContractInfo{}, err
	}
	return v, nil
}

func (a *Adapter) RegisteredProperty(ctx context.Context, propertyID string) (Property, error) {
	b, err := a.Read(ctx, "GetRegisteredProperty", propertyID)
	if err != nil {
		return Property{}, err
	}
	var v Property
	if err := strict(b, &v); err != nil {
		return Property{}, err
	}
	return v, nil
}

func (a *Adapter) Operation(ctx context.Context, operationID string) (Operation, error) {
	b, err := a.Read(ctx, "GetOperation", "Org1MSP", operationID)
	if err != nil {
		return Operation{}, err
	}
	var v Operation
	if err := strict(b, &v); err != nil {
		return Operation{}, err
	}
	return v, nil
}

func (a *Adapter) IssuanceState(ctx context.Context, propertyID string) (IssuanceState, error) {
	b, err := a.Read(ctx, "GetIssuanceState", propertyID)
	if err != nil {
		return IssuanceState{}, err
	}
	var v IssuanceState
	if err := strict(b, &v); err != nil {
		return IssuanceState{}, err
	}
	return v, nil
}

func (a *Adapter) Balance(ctx context.Context, propertyID, holderID string) (Balance, error) {
	b, err := a.Read(ctx, "GetBalance", propertyID, holderID)
	if err != nil {
		return Balance{}, err
	}
	var v Balance
	if err := strict(b, &v); err != nil {
		return Balance{}, err
	}
	return v, nil
}

func (a *Adapter) IssuanceOperation(ctx context.Context, operationID string) (IssuanceOperation, error) {
	b, err := a.Read(ctx, "GetIssuanceOperation", operationID)
	if err != nil {
		return IssuanceOperation{}, err
	}
	var v IssuanceOperation
	if err := strict(b, &v); err != nil {
		return IssuanceOperation{}, err
	}
	return v, nil
}

// Keep imports used.
var _ = json.Marshal
