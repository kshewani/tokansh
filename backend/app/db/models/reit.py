import sqlalchemy as sa

from app.db.base import (Base, created_at, currency_check, currency_col, fk, flag, money, text, timestamp,
                         updated_at, uuid_pk)


class ReitHolding(Base):
    """REIT position (DOMAIN_MODEL 2.16). A separate asset class: no link to any ANSH table (ADR-019)."""

    __tablename__ = "reit_holdings"
    __table_args__ = (
        currency_check(),
        sa.UniqueConstraint("investor_id", "reit_identifier"),
        sa.CheckConstraint("quantity > 0", name="quantity_positive"),
        sa.CheckConstraint("purchase_value_minor >= 0 AND illustrative_market_value_minor >= 0",
                           name="values_non_negative"),
    )

    id = uuid_pk()
    investor_id = fk("users.id")
    reit_identifier = text(40)
    reit_name = text(160)
    quantity = sa.orm.mapped_column(sa.BigInteger, nullable=False)
    purchase_value_minor = money()
    illustrative_market_value_minor = money()
    currency = currency_col()
    data_source = text(120)
    is_simulated = flag(True)
    observed_at = timestamp(nullable=False)
    created_at = created_at()
    updated_at = updated_at()
