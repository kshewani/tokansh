import sqlalchemy as sa

from app.db.base import (Base, created_at, currency_check, currency_col, enum_col, fk, money, quantity,
                         text, timestamp, updated_at, uuid_pk)
from app.db.enums import IssuanceStatus


class AnshIssuance(Base):
    """Issuance of fungible ANSH against an approved property (DOMAIN_MODEL 2.4 / 2.5).

    ``ansh_asset_id`` identifies the fungible asset class. There is no row per unit.
    ``issued_quantity`` is a projection of committed ledger state.
    """

    __tablename__ = "ansh_issuances"
    __table_args__ = (
        currency_check(),
        sa.UniqueConstraint("ansh_asset_id"),
        sa.UniqueConstraint("ledger_transaction_id"),
        sa.CheckConstraint("approved_supply > 0", name="approved_supply_positive"),
        sa.CheckConstraint("requested_quantity > 0", name="requested_positive"),
        sa.CheckConstraint("requested_quantity <= approved_supply", name="requested_within_supply"),
        sa.CheckConstraint("issued_quantity >= 0 AND issued_quantity <= approved_supply", name="issued_within_supply"),
        sa.CheckConstraint("issue_price_minor > 0", name="price_positive"),
        # Supply is recognised only with a genuine committed transaction (Rule 3.4).
        sa.CheckConstraint("issued_quantity = 0 OR issuance_status = 'CONFIRMED'", name="issued_only_when_confirmed"),
        sa.CheckConstraint("issuance_status <> 'CONFIRMED' OR (ledger_transaction_id IS NOT NULL "
                           "AND confirmed_at IS NOT NULL)", name="confirmed_needs_ledger_evidence"),
    )

    id = uuid_pk()
    property_id = fk("properties.id")
    approved_property_ref = text(64)
    ansh_asset_id = text(64)
    issuer_id = fk("users.id")
    approved_supply = quantity()
    requested_quantity = quantity()
    issued_quantity = quantity(default=0)
    issue_price_minor = money()
    currency = currency_col()
    issuance_status = enum_col(IssuanceStatus, default=IssuanceStatus.DRAFT, index=True)
    ledger_operation_id = fk("ledger_operations.id", nullable=True)
    ledger_transaction_id = text(128, nullable=True)
    created_at = created_at()
    updated_at = updated_at()
    confirmed_at = timestamp()
