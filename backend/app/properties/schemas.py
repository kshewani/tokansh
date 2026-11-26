from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

MoneyString = Annotated[str, StringConstraints(pattern=r"^(0|[1-9][0-9]{0,13})(\.[0-9]{1,2})?$")]


class NewProperty(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=200)]
    location: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=300)]
    category: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    valuation: MoneyString
    proposed_supply: Annotated[int, Field(strict=True, gt=0, le=9_007_199_254_740_991)]
    issue_price: MoneyString | None = None
    currency: Literal["INR"]

    @field_validator("valuation", "issue_price")
    @classmethod
    def positive_money(cls, value: str | None) -> str | None:
        if value is None:
            return None
        amount = Decimal(value)
        if amount <= 0:
            raise ValueError("Monetary amounts must be positive")
        return format(amount, ".2f")


class PropertyRead(BaseModel):
    id: str
    name: str
    location: str
    category: str
    valuation: str
    proposed_supply: int
    approved_supply: int = 0
    unit_price: str
    currency: Literal["INR"]
    issuer_id: str
    status: Literal["DRAFT"]
    verification_status: Literal["NOT_VERIFIED"] = "NOT_VERIFIED"
    ledger_registration_status: Literal["NOT_REGISTERED", "REGISTERED"] = "NOT_REGISTERED"
    ledger_transaction_id: str | None = None
    created_at: str


class PropertyPage(BaseModel):
    items: list[PropertyRead]
    page: int
    page_size: int
    total_items: int
    total_pages: int
