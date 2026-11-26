/** Selected frontend API shapes and status model from the team's API_CONTRACTS.md. */
export type ApiStatus='CREATED'|'DRAFT'|'PENDING'|'PROCESSING'|'SUBMITTED'|'COMMITTED'|'COMMITTED_VALID'|'COMMITTED_INVALID'|'FAILED'|'UNKNOWN'|'RECONCILIATION_REQUIRED';
export type ApiError={code:string;message:string;details?:Record<string,unknown>};
export type ApiResult<T>={data:T;meta?:{request_id?:string;timestamp?:string}};
export type SystemComponent={name:string;status:'CONNECTED'|'UNAVAILABLE'|'UNKNOWN'|'DEGRADED';detail?:string};
export type SystemStatus={components:SystemComponent[];last_ledger_operation?:string|null};
export type PropertyRecord={id:string;name:string;location:string;category:string;valuation:string;proposed_supply:number;approved_supply:number;unit_price:string;currency:'INR';status:string;issuer_id:string;verification_status:string;ledger_registration_status:'NOT_REGISTERED'|'REGISTERED';ledger_transaction_id:string|null};
export type PortfolioItem={property_id:string;ansh_id:string;name:string;category:string;location:string;issuer_id:string;registration_status:'REGISTERED'|'NOT_REGISTERED';issuance_status:'ISSUED'|'REGISTERED'|'UNAVAILABLE';approved_valuation_minor:string;initial_issue_price_minor:string;currency:'INR';approved_supply:number;issued_supply:number|null;owned_units:number|null;pledged_units:number;offering_committed_units:number;transferable_units:number|null;observation_status:'AVAILABLE'|'UNAVAILABLE';source:'DRUNIX_EVALUATE';observed_at:string|null;error_code:string|null};
export type PortfolioRecord={investor_id:string;currency:'INR';items:PortfolioItem[];aggregate:{status:'COMPLETE'|'PARTIAL'|'UNAVAILABLE';observed_property_count:number;total_indicative_value_minor:string|null;valuation_basis:'INITIAL_ISSUE_PRICE'|null};source:'DRUNIX_EVALUATE'};
export type LedgerOperation={operation_id:string;status:ApiStatus;ledger_transaction_id?:string|null;error_code?:string;created_at:string;confirmed_at?:string|null};
export type NewProperty={name:string;location:string;category:string;valuation:string;proposed_supply:number;issue_price?:string;currency:'INR'};
export type NewIssuance={property_id:string;quantity:number;issue_price_minor:string;currency:'INR'};
export type IssuanceState='PREPARING'|'PREPARED'|'SUBMISSION_PENDING'|'SUBMITTED'|'COMMITTED_VALID'|'COMMITTED_INVALID'|'FAILED'|'UNKNOWN'|'RECONCILIATION_REQUIRED';
export type IssuanceResult={operation_id:string;state:IssuanceState;transaction_id:string|null;request:NewIssuance;commit:{transaction_id:string;code:number;block_number:number;successful:boolean}|null;issuance:Record<string,unknown>|null;error_code:string|null;ownership_confirmed:boolean};
export type PropertyIssuanceState={property_id:string;approved_supply:number;issued_supply:number;remaining_supply:number;state:string;source:'DRUNIX'};
export type NewOrder={listing_id:string;quantity:number;currency:'INR'};
export type NewPledge={property_id:string;quantity:number;loan_amount:string};
export const route={
 status:'/api/v1/system/status',properties:'/api/v1/properties',issuances:'/api/v1/ansh/issuances',
 offerings:'/api/v1/marketplace/offerings',purchases:'/api/v1/marketplace/purchases',wallet:'/api/v1/demo-wallet',portfolio:'/api/v1/portfolio',
 listings:'/api/v1/marketplace/listings',orders:'/api/v1/marketplace/orders',
 payments:'/api/v1/payments/simulate',pledges:'/api/v1/collateral/pledges',
 loans:'/api/v1/loans/applications',distributions:'/api/v1/distributions',
 audit:'/api/v1/audit/events'
} as const;
