"""Pydantic schemas for Decision domain model and policy evaluation."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import (
    DecisionOutcome,
    MemoryRelevance,
    MemoryType,
    RuleDecisionEffect,
    RuleSeverity,
    RuleStatus,
    TransactionType,
)
from app.schemas.memory import MemorySourceSchema


class DecisionBase(BaseModel):
    """Base fields for Decision."""

    user_id: uuid.UUID = Field(
        ..., description="User for whom authorization was evaluated."
    )
    transaction_id: uuid.UUID | None = Field(
        default=None,
        description="Associated transaction ID if authorized.",
    )
    request_reference: str | None = Field(
        default=None,
        max_length=128,
        description="Agent purchase request reference identifier.",
        examples=["req_checkout_882"],
    )
    decision: DecisionOutcome = Field(
        ...,
        description="Deterministic authorization outcome.",
        examples=[DecisionOutcome.ALLOW],
    )
    reason: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Deterministic justification trace for the decision.",
        examples=["Transaction amount within active mandate cap and monthly budget."],
    )
    evidence_metadata: dict[str, Any] | None = Field(
        default=None,
        description="Structured evaluation context, remaining limits, and rule trace.",
    )


class DecisionCreate(DecisionBase):
    """Payload for recording a Decision."""

    pass


class DecisionRead(DecisionBase):
    """Response model for a Decision."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class ActionEvaluationRequest(BaseModel):
    """Payload for evaluating a proposed financial action without executing payment."""

    user_id: uuid.UUID = Field(
        ..., description="User initiating the proposed financial action."
    )
    merchant_id: uuid.UUID = Field(
        ..., description="Merchant receiving the proposed payment."
    )
    amount: Decimal = Field(
        ...,
        gt=Decimal("0.0000"),
        description="Exact monetary amount proposed for authorization.",
        examples=[Decimal("2500.00")],
    )
    currency: str = Field(
        ...,
        min_length=3,
        max_length=3,
        description="ISO 4217 currency code.",
        examples=["INR", "USD"],
    )
    mandate_id: uuid.UUID | None = Field(
        default=None,
        description="Optional mandate under which authorization is requested.",
    )
    transaction_type: TransactionType = Field(
        default=TransactionType.PURCHASE,
        description="Classification of the proposed transaction.",
    )
    request_id: uuid.UUID | None = Field(
        default=None,
        description="Optional caller-supplied request UUID for traceability.",
    )
    idempotency_key: str | None = Field(
        default=None,
        max_length=128,
        description="Client idempotency key for the proposed action.",
    )
    metadata: dict[str, Any] | None = Field(
        default_factory=dict,
        description="Optional agent or request context metadata.",
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


class RuleResultSchema(BaseModel):
    """Structured evidence trace from a single deterministic rule evaluation."""

    rule_id: str = Field(..., description="Unique identifier of the rule.")
    status: RuleStatus = Field(..., description="Execution status of the rule.")
    decision_effect: RuleDecisionEffect = Field(
        ..., description="Decision effect triggered by the rule."
    )
    reason_code: str = Field(..., description="Machine-readable outcome code.")
    message: str = Field(..., description="Human-readable explanation.")
    evidence: dict[str, Any] = Field(
        default_factory=dict,
        description="Exact numerical/string evidence supporting the outcome.",
    )
    severity: RuleSeverity = Field(
        default=RuleSeverity.INFO,
        description="Severity classification of the rule outcome.",
    )


class DecisionMemoryContextResponse(BaseModel):
    """Structured decision memory context included in an evaluation response."""

    model_config = ConfigDict(from_attributes=True)

    memory_id: uuid.UUID
    memory_type: MemoryType
    relevance: MemoryRelevance
    summary: str = Field(description="Deterministic summary of historical memory.")
    structured_data: dict[str, Any] = Field(
        default_factory=dict,
        description="Structured financial metrics and decision attributes.",
    )
    sources: list[MemorySourceSchema] = Field(
        default_factory=list,
        description="Source event provenance links.",
    )


class ActionEvaluationResponse(BaseModel):
    """Response returned when evaluating a proposed financial action."""

    request_id: uuid.UUID = Field(
        ..., description="Unique reference ID for this evaluation request."
    )
    decision_id: uuid.UUID | None = Field(
        default=None,
        description="Database primary key UUID of the persisted Decision record.",
    )
    decision: DecisionOutcome = Field(
        ...,
        description="Calculated deterministic decision (ALLOW, ASK_USER, BLOCK).",
    )
    reason_code: str = Field(
        ...,
        description="Primary machine-readable reason code for the decision.",
    )
    reason: str = Field(
        ...,
        description="Primary human-readable justification for the decision.",
    )
    rule_results: list[RuleResultSchema] = Field(
        ..., description="Complete trace of all evaluated deterministic rules."
    )
    memory_context: list[DecisionMemoryContextResponse] = Field(
        default_factory=list,
        description="Active historical decision memories included as contextual evidence.",
    )
    evaluated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Timestamp when the evaluation was computed.",
    )
