import sqlalchemy as sa

from app.db.base import (Base, created_at, currency_check, currency_col, enum_col, fk, flag, money,
                         quantity, text, timestamp, updated_at, uuid_pk)
from app.db.enums import DocumentType, PropertyStatus, ReviewDecision, ValuationPurpose, VerificationStatus


class Property(Base):
    """Real-estate asset (DOMAIN_MODEL 2.2). Onboarding and approval are application state."""

    __tablename__ = "properties"
    __table_args__ = (
        currency_check("valuation_currency"),
        sa.CheckConstraint("illustrative_valuation_minor > 0", name="valuation_positive"),
        sa.CheckConstraint("approved_supply IS NULL OR approved_supply > 0", name="approved_supply_positive"),
        # The ledger reference exists only with the genuine DRUNIX registration evidence.
        sa.CheckConstraint(
            "(approved_property_ref IS NULL AND drunix_registration_transaction_id IS NULL "
            "AND ledger_registered_at IS NULL) OR "
            "(approved_property_ref IS NOT NULL AND drunix_registration_transaction_id IS NOT NULL "
            "AND ledger_registered_at IS NOT NULL)",
            name="ledger_registration_evidence"),
        sa.CheckConstraint("approved_property_ref IS NULL OR approval_status = 'APPROVED' "
                           "OR approval_status = 'SUSPENDED'", name="registered_only_if_approved"),
        sa.UniqueConstraint("approved_property_ref"),
        sa.UniqueConstraint("drunix_registration_transaction_id"),
    )

    id = uuid_pk()
    property_name = text(160)
    property_type = text(60)
    description = sa.orm.mapped_column(sa.Text, nullable=True)
    address = text(255)
    city = text(80)
    country = text(80)
    illustrative_valuation_minor = money()
    valuation_currency = currency_col()
    issuer_id = fk("users.id")
    verification_status = enum_col(VerificationStatus, default=VerificationStatus.PENDING)
    approval_status = enum_col(PropertyStatus, default=PropertyStatus.DRAFT, index=True)
    approved_supply = quantity(nullable=True)  # issuance constraint fixed at approval
    approved_property_ref = text(64, nullable=True)
    drunix_registration_transaction_id = text(128, nullable=True)
    ledger_registered_at = timestamp()
    is_synthetic = flag(True)  # demo data must be labelled (ADR-020)
    created_at = created_at()
    updated_at = updated_at()


class PropertyDocument(Base):
    """Supporting document reference (DOMAIN_MODEL 2.3). Files stay off-chain."""

    __tablename__ = "property_documents"
    __table_args__ = (sa.CheckConstraint("content_sha256 IS NULL OR length(content_sha256) = 64", name="sha256_len"),)

    id = uuid_pk()
    property_id = fk("properties.id")
    document_type = enum_col(DocumentType)
    document_name = text(200)
    document_reference = text(500)
    content_sha256 = text(64, nullable=True)
    verification_status = enum_col(VerificationStatus, default=VerificationStatus.PENDING)
    is_synthetic = flag(True)
    uploaded_at = created_at()


class PropertyReview(Base):
    """Reviewer decision on a property. Application workflow, never a ledger transaction."""

    __tablename__ = "property_reviews"

    id = uuid_pk()
    property_id = fk("properties.id")
    reviewer_id = fk("users.id")
    decision = enum_col(ReviewDecision)
    approved_supply = quantity(nullable=True)
    notes = sa.orm.mapped_column(sa.Text, nullable=True)
    decided_at = created_at()

    __table_args__ = (
        sa.CheckConstraint("decision <> 'APPROVED' OR (approved_supply IS NOT NULL AND approved_supply > 0)",
                           name="approval_needs_supply"),
    )


class PropertyValuation(Base):
    """Valuation history. Market value and approved collateral value are separate (Rule 8.3)."""

    __tablename__ = "property_valuations"
    __table_args__ = (
        currency_check(),
        sa.CheckConstraint("property_value_minor > 0", name="value_positive"),
        sa.CheckConstraint("unit_value_minor > 0", name="unit_value_positive"),
        sa.Index("ix_property_valuations_lookup", "property_id", "purpose", "observed_at"),
    )

    id = uuid_pk()
    property_id = fk("properties.id", index=False)
    purpose = enum_col(ValuationPurpose)
    property_value_minor = money()
    unit_value_minor = money()
    currency = currency_col()
    valuation_source = text(120)
    is_simulated = flag(True)
    approved_by = fk("users.id", nullable=True, index=False)
    observed_at = timestamp(nullable=False)
    created_at = created_at()
