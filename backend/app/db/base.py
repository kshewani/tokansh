"""Declarative base and column helpers shared by all models.

Conventions (ADR-015, API_CONTRACTS 4.3-4.5):
  * Primary keys are UUID strings.
  * Money is integer minor units (paise) in ``*_minor`` columns beside an
    explicit ISO currency code. No FLOAT and no NUMERIC: SQLite stores NUMERIC
    as binary floating point, which the business rules forbid.
  * Ratios (LTV, interest) are integer basis points (1% = 100 bps).
  * ANSH quantities are whole integers.
  * Timestamps are timezone-aware UTC.
  * Enumerations are VARCHAR + CHECK, portable to PostgreSQL / YugabyteDB YSQL.
"""
import enum
import re
import uuid

import sqlalchemy as sa
from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase, mapped_column

from app.db.types import UTCDateTime, utcnow

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def new_id() -> str:
    return str(uuid.uuid4())


def uuid_pk():
    return mapped_column(sa.String(36), primary_key=True, default=new_id)


def fk(target: str, *, nullable: bool = False, index: bool = True, **kw):
    return mapped_column(sa.String(36), sa.ForeignKey(target, ondelete="RESTRICT"),
                         nullable=nullable, index=index, **kw)


def _with_server_default(kw: dict) -> dict:
    """Mirror a Python-side default in the database, so hand-written SQL gets it too."""
    if "default" in kw and "server_default" not in kw:
        d = kw["default"]
        kw["server_default"] = d.value if isinstance(d, enum.Enum) else str(d)
    return kw


def money(*, nullable: bool = False, **kw):
    """Integer minor currency units (paise for INR)."""
    return mapped_column(sa.BigInteger, nullable=nullable, **_with_server_default(kw))


def quantity(*, nullable: bool = False, **kw):
    """Whole ANSH units."""
    return mapped_column(sa.BigInteger, nullable=nullable, **_with_server_default(kw))


def bps(*, nullable: bool = False, **kw):
    """Basis points: 6000 = 60.00%."""
    return mapped_column(sa.Integer, nullable=nullable, **_with_server_default(kw))


def integer(*, nullable: bool = False, big: bool = False, **kw):
    return mapped_column(sa.BigInteger if big else sa.Integer, nullable=nullable, **_with_server_default(kw))


def text(length: int, *, nullable: bool = False, **kw):
    return mapped_column(sa.String(length), nullable=nullable, **kw)


def flag(default: bool):
    return mapped_column(sa.Boolean, nullable=False, default=default,
                         server_default=sa.true() if default else sa.false())


def currency_col():
    return mapped_column(sa.String(3), nullable=False, default="INR", server_default="INR")


def currency_check(column: str = "currency"):
    return sa.CheckConstraint(f"length({column}) = 3 AND {column} = upper({column})", name=f"{column}_iso")


def timestamp(*, nullable: bool = True, **kw):
    return mapped_column(UTCDateTime(), nullable=nullable, **kw)


def created_at():
    return mapped_column(UTCDateTime(), nullable=False, default=utcnow, server_default=sa.func.now())


def updated_at():
    return mapped_column(UTCDateTime(), nullable=False, default=utcnow, onupdate=utcnow,
                         server_default=sa.func.now())


def _snake(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def enum_col(enum_cls: type[enum.Enum], *, nullable: bool = False, **kw):
    """VARCHAR column restricted to the enum's values by a CHECK constraint."""
    return mapped_column(
        sa.Enum(enum_cls, native_enum=False, create_constraint=True, validate_strings=True,
                length=40, name=_snake(enum_cls.__name__)),
        nullable=nullable, **_with_server_default(kw),
    )
