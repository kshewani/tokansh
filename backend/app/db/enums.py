"""Enumerations. Values come from docs/DOMAIN_MODEL.md and docs/API_CONTRACTS.md.

Enums marked PROPOSED fill a gap the documents leave open; they need team
approval (DECISIONS.md section 5) before they are treated as agreed.
"""
import enum


class S(str, enum.Enum):
    def __str__(self) -> str:
        return self.value


class UserRole(S):
    ADMIN = "ADMIN"
    ISSUER = "ISSUER"
    INVESTOR = "INVESTOR"
    LENDER = "LENDER"


class UserStatus(S):  # PROPOSED
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class PropertyStatus(S):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUSPENDED = "SUSPENDED"


class VerificationStatus(S):  # PROPOSED
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class DocumentType(S):  # PROPOSED
    TITLE_DEED = "TITLE_DEED"
    VALUATION_REPORT = "VALUATION_REPORT"
    TAX_RECEIPT = "TAX_RECEIPT"
    OCCUPANCY_CERTIFICATE = "OCCUPANCY_CERTIFICATE"
    LEASE_AGREEMENT = "LEASE_AGREEMENT"
    OTHER = "OTHER"


class ReviewDecision(S):  # PROPOSED
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ValuationPurpose(S):  # PROPOSED: BUSINESS_RULES 8.3 separates market value from collateral value
    ILLUSTRATIVE_MARKET = "ILLUSTRATIVE_MARKET"
    COLLATERAL = "COLLATERAL"


class IssuanceStatus(S):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    SUBMITTED = "SUBMITTED"
    CONFIRMED = "CONFIRMED"
    FAILED = "FAILED"


class PositionStatus(S):
    ACTIVE = "ACTIVE"
    RESTRICTED = "RESTRICTED"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"


class ListingStatus(S):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class OrderStatus(S):
    CREATED = "CREATED"
    VALIDATED = "VALIDATED"
    PAYMENT_PENDING = "PAYMENT_PENDING"
    PAYMENT_FAILED = "PAYMENT_FAILED"
    PAYMENT_SUCCEEDED = "PAYMENT_SUCCEEDED"
    TRANSFER_PENDING = "TRANSFER_PENDING"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class PaymentKind(S):  # PROPOSED: BUSINESS_RULES 6.3 requires a refund/compensation record
    PURCHASE = "PURCHASE"
    REFUND = "REFUND"


class PaymentStatus(S):
    INITIATED = "INITIATED"
    AUTHORIZED = "AUTHORIZED"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    REVERSED = "REVERSED"
    UNKNOWN = "UNKNOWN"


class OperationType(S):
    APPROVED_PROPERTY_REGISTRATION = "APPROVED_PROPERTY_REGISTRATION"
    ANSH_ISSUANCE = "ANSH_ISSUANCE"
    ANSH_TRANSFER = "ANSH_TRANSFER"
    ANSH_PLEDGE = "ANSH_PLEDGE"
    ANSH_RELEASE = "ANSH_RELEASE"


class OperationStatus(S):  # API_CONTRACTS section 8 (superset of DOMAIN_MODEL 2.10)
    CREATED = "CREATED"
    VALIDATING = "VALIDATING"
    SUBMITTED = "SUBMITTED"
    COMMITTED = "COMMITTED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"


class ReconciliationStatus(S):  # PROPOSED
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"


class PledgeStatus(S):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    SUBMITTED = "SUBMITTED"
    ACTIVE = "ACTIVE"
    RELEASE_PENDING = "RELEASE_PENDING"
    RELEASED = "RELEASED"
    FAILED = "FAILED"


class LoanStatus(S):
    REQUESTED = "REQUESTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    DISBURSED = "DISBURSED"
    ACTIVE = "ACTIVE"
    PARTIALLY_REPAID = "PARTIALLY_REPAID"
    REPAID = "REPAID"
    DEFAULTED = "DEFAULTED"
    REJECTED = "REJECTED"


class CreditDecision(S):  # PROPOSED: outcome of the simulated assessment
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"


class RepaymentStatus(S):
    INITIATED = "INITIATED"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class DistributionStatus(S):
    DRAFT = "DRAFT"
    DECLARED = "DECLARED"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class SnapshotMethod(S):  # BUSINESS_RULES 10.6: the only two acceptable sources
    LEDGER_SNAPSHOT = "LEDGER_SNAPSHOT"
    EVENT_RECONSTRUCTION = "EVENT_RECONSTRUCTION"


class EntitlementStatus(S):  # PROPOSED
    CALCULATED = "CALCULATED"
    PAID = "PAID"
    FAILED = "FAILED"


class WalletEntryKind(S):  # simulated demo cash (adopted from the connected-mode branch)
    DEMO_FUNDS = "DEMO_FUNDS"
    WITHDRAWAL = "WITHDRAWAL"
    DISBURSEMENT = "DISBURSEMENT"
    REPAYMENT = "REPAYMENT"
    PURCHASE_PAYMENT = "PURCHASE_PAYMENT"  # buyer pays for ANSH from demo cash
    SALE_PROCEEDS = "SALE_PROCEEDS"  # seller is credited only after the transfer commits
    PURCHASE_REFUND = "PURCHASE_REFUND"  # buyer refunded when the ledger transfer fails


class EventSource(S):
    DRUNIX_LEDGER = "DRUNIX_LEDGER"
    APPLICATION = "APPLICATION"
    PAYMENT_SIMULATOR = "PAYMENT_SIMULATOR"
    LENDER_SIMULATOR = "LENDER_SIMULATOR"
    EXTERNAL_SIMULATOR = "EXTERNAL_SIMULATOR"
