import sqlalchemy as sa

from app.db.base import (Base, created_at, currency_check, currency_col, enum_col, fk, flag, money,
                         quantity, text, timestamp, updated_at, uuid_pk)
from app.db.enums import DistributionStatus, EntitlementStatus, SnapshotMethod


class OwnershipSnapshot(Base):
    """Record-date ownership used for a distribution (Rule 10.6, ADR-014).

    Only two sources are acceptable: a verified ledger snapshot or a deterministic
    reconstruction from confirmed ledger events. Current holdings are never substituted.
    """

    __tablename__ = "ownership_snapshots"
    __table_args__ = (
        sa.UniqueConstraint("issuance_id", "record_date"),
        sa.CheckConstraint("total_eligible_quantity > 0", name="total_positive"),
        sa.CheckConstraint("as_of_block_number IS NULL OR as_of_block_number >= 0", name="block_non_negative"),
    )

    id = uuid_pk()
    issuance_id = fk("ansh_issuances.id")
    record_date = sa.orm.mapped_column(sa.Date, nullable=False)
    method = enum_col(SnapshotMethod)
    ledger_reference = text(128)  # transaction id / query reference the snapshot is traceable to
    as_of_block_number = sa.orm.mapped_column(sa.BigInteger, nullable=True)
    total_eligible_quantity = quantity()
    is_verified = flag(False)  # entitlements may be calculated only from a verified snapshot
    captured_at = created_at()
    verified_at = timestamp()


class OwnershipSnapshotLine(Base):
    __tablename__ = "ownership_snapshot_lines"
    __table_args__ = (
        sa.UniqueConstraint("snapshot_id", "investor_id"),
        sa.CheckConstraint("owned_quantity >= 0 AND pledged_quantity >= 0", name="non_negative"),
        sa.CheckConstraint("pledged_quantity <= owned_quantity", name="pledged_within_owned"),
        # Pledged units stay eligible in the MVP (Rule 10.4), so eligible = owned.
        sa.CheckConstraint("eligible_quantity >= 0 AND eligible_quantity <= owned_quantity", name="eligible_in_range"),
    )

    id = uuid_pk()
    snapshot_id = fk("ownership_snapshots.id")
    investor_id = fk("users.id")
    owned_quantity = quantity()
    pledged_quantity = quantity(default=0)
    eligible_quantity = quantity()


class Distribution(Base):
    """Declared rental distribution (DOMAIN_MODEL 2.14)."""

    __tablename__ = "distributions"
    __table_args__ = (
        currency_check(),
        sa.UniqueConstraint("issuance_id", "record_date", "period_label"),  # Rule 10.5: no duplicates
        sa.CheckConstraint("total_amount_minor > 0", name="amount_positive"),
        sa.CheckConstraint("distribution_date >= record_date", name="pays_on_or_after_record_date"),
        sa.CheckConstraint("distribution_status NOT IN ('PROCESSING','COMPLETED') OR snapshot_id IS NOT NULL",
                           name="processing_needs_snapshot"),
    )

    id = uuid_pk()
    property_id = fk("properties.id")
    issuance_id = fk("ansh_issuances.id")
    declared_by = fk("users.id", index=False)
    period_label = text(60)  # e.g. "2026-Q3 rent"
    total_amount_minor = money()
    currency = currency_col()
    record_date = sa.orm.mapped_column(sa.Date, nullable=False)
    distribution_date = sa.orm.mapped_column(sa.Date, nullable=False)
    distribution_status = enum_col(DistributionStatus, default=DistributionStatus.DRAFT, index=True)
    snapshot_id = fk("ownership_snapshots.id", nullable=True)
    rounding_method = text(120, nullable=True)  # documented residual treatment (Rule 10.5)
    created_at = created_at()
    updated_at = updated_at()


class DistributionEntitlement(Base):
    """One investor's share of a distribution (DOMAIN_MODEL 2.15). Inputs are kept to reproduce it."""

    __tablename__ = "distribution_entitlements"
    __table_args__ = (
        currency_check(),
        sa.UniqueConstraint("distribution_id", "investor_id"),
        sa.CheckConstraint("eligible_quantity > 0", name="eligible_positive"),
        sa.CheckConstraint("total_eligible_quantity >= eligible_quantity", name="eligible_within_total"),
        sa.CheckConstraint("entitlement_amount_minor >= 0", name="amount_non_negative"),
        sa.CheckConstraint("simulation_flag = 1", name="mvp_payouts_are_simulated"),
        sa.CheckConstraint("entitlement_status <> 'PAID' OR (payment_reference IS NOT NULL AND paid_at IS NOT NULL)",
                           name="paid_needs_reference"),
    )

    id = uuid_pk()
    distribution_id = fk("distributions.id")
    investor_id = fk("users.id")
    snapshot_id = fk("ownership_snapshots.id")  # calculation_reference
    eligible_quantity = quantity()
    total_eligible_quantity = quantity()
    entitlement_amount_minor = money()
    rounding_residual_minor = money(default=0)  # paise added to this row by the residual rule
    currency = currency_col()
    entitlement_status = enum_col(EntitlementStatus, default=EntitlementStatus.CALCULATED)
    payment_reference = text(128, nullable=True)
    simulation_flag = flag(True)
    created_at = created_at()
    paid_at = timestamp()
