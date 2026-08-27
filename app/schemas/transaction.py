"""Pydantic schemas for Transaction domain model."""

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import TransactionStatus, TransactionType


class TransactionBase(BaseModel):
    """Base fields for Transaction."""

    user_id: uuid.UUID = Field(
        ..., description="User executing or associated with the transaction."
    )
    merchant_id: uuid.UUID = Field(
        ..., description="Merchant receiving the transaction."
    )
    mandate_id: uuid.UUID | None = Field(
        default=None,
        description="Optional mandate authorization under which initiated.",
    )
    amount: Decimal = Field(
        ...,
        gt=Decimal("0.0000"),
        description="Exact monetary transaction amount (must be positive).",
        examples=[Decimal("1299.50")],
    )
    currency: str = Field(
        ...,
        min_length=3,
        max_length=3,
        description="ISO 4217 currency code.",
        examples=["INR", "USD"],
    )
    transaction_type: TransactionType = Field(
        default=TransactionType.PURCHASE,
        description="Financial transaction classification.",
    )
    status: TransactionStatus = Field(
        default=TransactionStatus.PENDING,
        description="Transaction lifecycle status.",
    )
    external_reference: str | None = Field(
        default=None,
        max_length=128,
        description="External payment gateway reference.",
        examples=["pay_N9b2x8731"],
    )
    idempotency_key: str | None = Field(
        default=None,
        max_length=128,
        description="Idempotency key to prevent duplicate execution.",
        examples=["idem_agent_task_492"],
    )
    occurred_at: datetime | None = Field(
        default=None,
        description="Timestamp when financial transaction occurred. Defaults to now.",
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


class TransactionCreate(TransactionBase):
    """Payload for creating a new Transaction."""

    pass


class TransactionRead(TransactionBase):
    """Response model for a Transaction."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    occurred_at: datetime
    created_at: datetime
    updated_at: datetime
