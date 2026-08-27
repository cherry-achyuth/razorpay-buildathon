"""Pydantic schemas for Mandate domain model."""

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.enums import MandateStatus


class MandateBase(BaseModel):
    """Base fields for Mandate."""

    merchant_id: uuid.UUID | None = Field(
        default=None,
        description="Optional merchant restriction. If omitted, applies globally.",
    )
    currency: str = Field(
        ...,
        min_length=3,
        max_length=3,
        description="ISO 4217 currency code.",
        examples=["INR", "USD"],
    )
    max_transaction_amount: Decimal = Field(
        ...,
        gt=Decimal("0.0000"),
        description="Exact maximum authorization cap per transaction.",
        examples=[Decimal("5000.00")],
    )
    valid_from: datetime | None = Field(
        default=None,
        description="Start time for mandate validity. Defaults to current timestamp.",
    )
    valid_until: datetime | None = Field(
        default=None,
        description="Optional expiration timestamp for mandate.",
    )
    status: MandateStatus = Field(
        default=MandateStatus.ACTIVE,
        description="Mandate lifecycle status.",
    )

    @field_validator("currency")
    @classmethod
    def validate_currency_code(cls, value: str) -> str:
        code = value.strip().upper()
        if len(code) != 3 or not code.isalpha():
            raise ValueError(
                "Currency must be a 3-letter uppercase ISO 4217 code (e.g. INR, USD)"
            )
        return code

    @model_validator(mode="after")
    def validate_date_range(self) -> "MandateBase":
        if self.valid_from and self.valid_until and self.valid_until < self.valid_from:
            raise ValueError("valid_until must be greater than or equal to valid_from")
        return self


class MandateCreate(MandateBase):
    """Payload for creating a new Mandate."""

    user_id: uuid.UUID = Field(..., description="User authorizing the mandate.")


class MandateRead(MandateBase):
    """Response model for a Mandate."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    created_at: datetime
    updated_at: datetime
