"""Pydantic schemas for Policy domain model."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.enums import PolicyStatus, PolicyType


class PolicyBase(BaseModel):
    """Base fields for Policy."""

    name: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Descriptive policy title.",
        examples=["Monthly AI Compute Budget"],
    )
    policy_type: PolicyType = Field(
        ...,
        description="Categorical type of the policy constraint.",
    )
    currency: str | None = Field(
        default=None,
        min_length=3,
        max_length=3,
        description="ISO 4217 currency code if policy is monetary.",
        examples=["INR", "USD"],
    )
    limit_amount: Decimal | None = Field(
        default=None,
        ge=Decimal("0.0000"),
        description="Soft monetary constraint amount (routine threshold).",
        examples=[Decimal("25000.00")],
    )
    hard_limit_amount: Decimal | None = Field(
        default=None,
        ge=Decimal("0.0000"),
        description="Absolute hard spend ceiling that blocks unconditionally.",
        examples=[Decimal("50000.00")],
    )
    valid_from: datetime | None = Field(
        default=None,
        description="Policy enforcement start timestamp.",
    )
    valid_until: datetime | None = Field(
        default=None,
        description="Policy enforcement end timestamp.",
    )
    rules: dict[str, Any] | None = Field(
        default=None,
        description="Structured rule criteria.",
    )
    status: PolicyStatus = Field(
        default=PolicyStatus.ACTIVE,
        description="Policy status.",
    )

    @field_validator("currency")
    @classmethod
    def validate_currency_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        code = value.strip().upper()
        if len(code) != 3 or not code.isalpha():
            raise ValueError(
                "Currency must be a 3-letter uppercase ISO 4217 code (e.g. INR, USD)"
            )
        return code

    @model_validator(mode="after")
    def validate_date_range(self) -> "PolicyBase":
        if self.valid_from and self.valid_until and self.valid_until < self.valid_from:
            raise ValueError("valid_until must be greater than or equal to valid_from")
        return self


class PolicyCreate(PolicyBase):
    """Payload for creating a new Policy."""

    user_id: uuid.UUID = Field(..., description="User to whom this policy applies.")


class PolicyRead(PolicyBase):
    """Response model for a Policy."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    created_at: datetime
    updated_at: datetime
