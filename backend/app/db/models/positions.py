import sqlalchemy as sa
from sqlalchemy.ext.hybrid import hybrid_property

from app.db.base import (Base, created_at, currency_check, currency_col, enum_col, fk, money, quantity, text,
                         timestamp, updated_at, uuid_pk)
from app.db.enums import PositionStatus


class OwnershipPosition(Base):
    """Read-model projection of an investor's ledger balance (DOMAIN_MODEL 2.6).

    Never authoritative. Every row says which committed ledger observation it
    came from and when (ADR-007, Rule 4.4).
    """

    __tablename__ = "ownership_positions"
    __table_args__ = (
        currency_check(),
        sa.UniqueConstraint("investor_id", "issuance_id"),
        sa.CheckConstraint("acquisition_cost_minor >= 0", name="cost_non_negative"),
        sa.CheckConstraint("owned_quantity >= 0", name="owned_non_negative"),
        sa.CheckConstraint("pledged_quantity >= 0", name="pledged_non_negative"),
        sa.CheckConstraint("pledged_quantity <= owned_quantity", name="pledged_within_owned"),
    )

    id = uuid_pk()
    investor_id = fk("users.id")
    issuance_id = fk("ansh_issuances.id")
    owned_quantity = quantity(default=0)
    pledged_quantity = quantity(default=0)
    acquisition_cost_minor = money(default=0)  # application-calculated from completed orders
    currency = currency_col()
    ledger_reference = text(128)  # transaction id or query reference this row was observed from
    observed_at = timestamp(nullable=False)
    reconciliation_status = enum_col(PositionStatus, default=PositionStatus.ACTIVE)
    created_at = created_at()
    updated_at = updated_at()

    @hybrid_property
    def available_quantity(self):
        """Available ANSH = Owned ANSH - Pledged ANSH (Rule 4.2). Derived, never stored."""
        return self.owned_quantity - self.pledged_quantity
