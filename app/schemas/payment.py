"""Schemas for payment execution and decision confirmation."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import DecisionOutcome, TransactionType
from app.schemas.decision import RuleResultSchema


class PaymentExecutionRequest(BaseModel):
    """Request payload to evaluate and execute a payment via DecisionVault."""

    model_config = ConfigDict(extra="forbid")

    user_id: uuid.UUID = Field(
        ...,
        description="UUID of the purchasing user/principal.",
    )
    merchant_id: uuid.UUID = Field(
        ...,
        description="UUID of the recipient merchant.",
    )
    amount: Decimal = Field(
        ...,
        gt=Decimal("0.0000"),
        decimal_places=4,
        description="Monetary transaction amount.",
    )
    currency: str = Field(
        default="INR",
        min_length=3,
        max_length=3,
        description="ISO 4217 currency code (e.g. INR, USD).",
    )
    transaction_type: TransactionType = Field(
        default=TransactionType.PURCHASE,
        description="Classification of the transaction.",
    )
    mandate_id: uuid.UUID | None = Field(
        default=None,
        description="Optional mandate UUID for bounded authorization.",
    )
    idempotency_key: str | None = Field(
        default=None,
        max_length=128,
        description="Client-supplied key to guarantee idempotent execution.",
    )
    decision_id: uuid.UUID | None = Field(
        default=None,
        description="Optional prior decision UUID if pre-evaluated.",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Contextual metadata for the purchase.",
    )


class PaymentExecutionResponse(BaseModel):
    """Result of payment evaluation and Razorpay execution."""

    model_config = ConfigDict(from_attributes=True)

    payment_id: uuid.UUID = Field(
        ...,
        description="Unique reference ID for this payment attempt.",
    )
    user_id: uuid.UUID
    merchant_id: uuid.UUID
    amount: Decimal
    currency: str
    decision: DecisionOutcome = Field(
        ...,
        description="Decision outcome (ALLOW, ASK_USER, BLOCK).",
    )
    status: str = Field(
        ...,
        description="Execution status (SUCCESS, BLOCKED, REQUIRES_USER_CONFIRMATION, FAILED).",
    )
    decision_id: uuid.UUID | None = None
    transaction_id: uuid.UUID | None = None
    gateway_order_id: str | None = None
    gateway_payment_id: str | None = None
    gateway_mode: str = Field(
        ...,
        description="Razorpay gateway execution mode ('RAZORPAY_TEST_MODE' or 'SANDBOX_SIMULATION').",
    )
    reason_code: str
    reason: str
    rule_results: list[RuleResultSchema] = Field(default_factory=list)
    executed_at: datetime


class DecisionConfirmationRequest(BaseModel):
    """User confirmation request for ASK_USER decisions."""

    model_config = ConfigDict(extra="forbid")

    confirmed: bool = Field(
        ...,
        description="Whether the user explicitly authorizes this transaction.",
    )
    execute_payment_now: bool = Field(
        default=True,
        description="Whether to immediately proceed to Razorpay execution upon confirmation.",
    )
    accept_as_new_baseline: bool = Field(
        default=False,
        description="If True and confirmed, permanently updates the merchant's historical baseline in memory to this transaction's amount.",
    )
    user_notes: str | None = Field(
        default=None,
        max_length=256,
        description="Optional user notes or confirmation reason.",
    )


class DecisionConfirmationResponse(BaseModel):
    """Response after processing user decision confirmation."""

    model_config = ConfigDict(from_attributes=True)

    decision_id: uuid.UUID
    status: str
    confirmed: bool
    baseline_updated: bool = Field(
        default=False,
        description="Whether a new historical baseline memory was established.",
    )
    new_baseline_amount: Decimal | None = Field(
        default=None,
        description="The updated baseline amount if accepted.",
    )
    payment_result: PaymentExecutionResponse | None = None
    message: str
    updated_at: datetime
