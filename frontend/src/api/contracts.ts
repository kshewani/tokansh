/** API shapes returned by the TokANSH backend (docs/API_CONTRACTS.md). Money is a decimal string. */
export type OperationStatus = 'CREATED' | 'VALIDATING' | 'SUBMITTED' | 'COMMITTED' | 'FAILED' | 'UNKNOWN' | 'RECONCILIATION_REQUIRED';
export type Page<T> = {items: T[]; page: number; page_size: number; total_items: number; total_pages: number};
export type UserBrief = {id: string; name: string; role: string};
export type LedgerOperation = {
  operation_id: string; operation_type: string; status: OperationStatus; ledger_transaction_id: string | null;
  block_number: number | null; validation_code: string | null; error_code: string | null; error_message: string | null;
  function: string; entity_type: string; entity_id: string; created_at: string; confirmed_at: string | null; source: 'DRUNIX_LEDGER';
};
export type SystemComponent = {name: string; status: 'CONNECTED' | 'UNAVAILABLE' | 'UNKNOWN' | 'DEGRADED'; detail?: string};
export type SystemStatus = {components: SystemComponent[]; last_ledger_operation: LedgerOperation | null; unresolved_ledger_operations: number};
export type Property = {
  id: string; name: string; property_type: string; description: string | null; address: string; city: string; country: string;
  valuation: string; currency: string; proposed_supply: number; issue_price: string; approved_supply: number | null;
  approval_status: string; verification_status: string; issuer: UserBrief; is_synthetic: boolean; created_at: string;
  ledger: {approved_property_ref: string | null; registered: boolean; registration_transaction_id: string | null;
    registered_at: string | null; operation: LedgerOperation | null};
  issuance: {id: string; status: string; issued_quantity: number; ansh_asset_id: string} | null;
};
export type Issuance = {
  id: string; property_id: string; property_name: string; approved_property_ref: string; ansh_asset_id: string; issuer: UserBrief;
  approved_supply: number; requested_quantity: number; issued_quantity: number; remaining_supply: number; issue_price: string;
  currency: string; issuance_value: string; status: string; ledger_transaction_id: string | null; confirmed_at: string | null;
  operation: LedgerOperation | null;
};
export type Listing = {
  id: string; issuance_id: string; ansh_asset_id: string; seller: UserBrief; quantity: number; remaining_quantity: number;
  unit_price: string; currency: string; status: string; created_at: string;
  property: {id: string; name: string; city: string; property_type: string; valuation: string; is_synthetic: boolean};
};
export type Payment = {id: string; kind: 'PURCHASE' | 'REFUND'; reference: string; amount: string; currency: string; status: string;
  failure_reason: string | null; simulated: boolean; created_at: string};
export type Order = {
  id: string; listing_id: string; issuance_id: string; property_name: string; buyer: UserBrief; seller: UserBrief; quantity: number;
  unit_price: string; total_amount: string; currency: string; status: string; failure_reason: string | null; created_at: string;
  payments: Payment[]; transfer: LedgerOperation | null;
};
export type Holding = {
  issuance_id: string; ansh_asset_id: string; property_id: string; property_name: string; owned_units: number; pledged_units: number;
  available_units: number; acquisition_cost: string; illustrative_unit_value: string | null; illustrative_value: string | null;
  currency: string; source: string; ledger_reference: string; as_of: string; reconciliation_status: string;
  ledger_verification?: {status: 'VERIFIED' | 'MISMATCH' | 'UNAVAILABLE'; owned?: number; pledged?: number; error_code?: string};
};
export type Reit = {id: string; reit_identifier: string; reit_name: string; quantity: number; purchase_value: string;
  illustrative_market_value: string; data_source: string; is_simulated: boolean};
export type Portfolio = {user: UserBrief; ansh: Holding[]; reits: Reit[]; summary: {
  ansh: {owned_units: number; pledged_units: number; available_units: number; acquisition_cost: string; illustrative_value: string};
  reit: {holdings: number; purchase_value: string; illustrative_market_value: string};
  financing: {active_pledges: number; outstanding_loans: string}}};
export type Pledge = {
  id: string; investor: UserBrief; issuance_id: string; property_name: string; ansh_asset_id: string; quantity: number;
  collateral_unit_value: string; collateral_value: string; currency: string; status: string; loan_id: string | null;
  valuation: {source: string; observed_at: string; is_simulated: boolean} | null; created_at: string;
  pledge_operation: LedgerOperation | null; release_operation: LedgerOperation | null;
};
export type Loan = {
  id: string; borrower: UserBrief; lender: UserBrief; pledge_id: string; principal: string; outstanding: string; currency: string;
  collateral_value: string; ltv_percent: string; max_ltv_percent: string; status: string; simulated: boolean; disbursed_at: string | null;
  interest_rate_percent: string; term_months: number; interest_quote: string; interest_outstanding: string;
  total_due: string; total_outstanding: string; interest_method: string; offer_id: string | null;
  assessments: {id: string; decision: string; assessed_ltv_percent: string; assessed_at: string}[];
  repayments: {id: string; amount: string; reference: string; outstanding_after: string; created_at: string}[];
};
export type Entitlement = {id: string; investor: UserBrief; eligible_quantity: number; total_eligible_quantity: number; amount: string;
  rounding_residual: string; status: string; payment_reference: string | null; paid_at: string | null};
export type Distribution = {
  id: string; property_id: string; property_name: string; issuance_id: string; period_label: string; total_amount: string;
  currency: string; record_date: string; distribution_date: string; status: string; rounding_method: string;
  snapshot: {method: string; ledger_reference: string; total_eligible_quantity: number; is_verified: boolean; captured_at: string} | null;
  entitlement_count: number; entitlements_total: string | null; my_entitlement: Entitlement | null;
};
export type AuditEvent = {id: string; entity_type: string; entity_id: string; operation_type: string; actor: UserBrief | null;
  previous_state: string | null; new_state: string | null; source: string; simulated: boolean; outcome: string;
  ledger_transaction_id: string | null; operation_id: string | null; occurred_at: string};
export type AssetEvent = {id: string; property_id: string | null; event_type: string; description: string; source: string;
  simulated: boolean; ledger_transaction_id: string | null; actor: UserBrief | null; occurred_at: string};
export type DemoUser = {id: string; name: string; username: string; email: string; role: string};
export type LenderOffer = {id: string; name: string; annual_rate_percent: string; annual_rate_bps: number; max_ltv_percent: string;
  effective_max_ltv_percent: string; tenures_months: number[]};
export type LenderInstitution = {id: string; username: string; name: string; simulated: boolean; offers: LenderOffer[]};
export type WalletEntry = {id: string; kind: string; amount: string; balance_after: string; loan_id: string | null; created_at: string; simulated: boolean};
export type Wallet = {balance: string; currency: string; simulated: boolean; entries: WalletEntry[]};
export type Dashboard = {
  properties: {total: number; approved: number; pending_review: number; illustrative_approved_valuation: string};
  ansh: {approved_supply: number; issued: number; pledged: number};
  financing: {outstanding: string}; ledger: {committed: number; failed: number; unresolved: number};
};

export const route = {
  status: '/api/v1/system/status', configuration: '/api/v1/system/configuration', dashboard: '/api/v1/dashboard/summary',
  users: '/api/v1/users', login: '/api/v1/auth/login', logout: '/api/v1/auth/logout', properties: '/api/v1/properties',
  issuances: '/api/v1/ansh/issuances', transfers: '/api/v1/ansh/transfers', listings: '/api/v1/marketplace/listings',
  orders: '/api/v1/marketplace/orders', payments: '/api/v1/payments/simulate', portfolios: '/api/v1/portfolios',
  pledges: '/api/v1/collateral/pledges', loans: '/api/v1/loans', loanApplications: '/api/v1/loans/applications',
  distributions: '/api/v1/distributions', audit: '/api/v1/audit/events', assetEvents: '/api/v1/assets/events',
  ledgerOps: '/api/v1/ledger/operations', reconciliation: '/api/v1/reconciliation/cases',
  lenders: '/api/v1/financing/lenders', wallet: '/api/v1/wallet',
} as const;
