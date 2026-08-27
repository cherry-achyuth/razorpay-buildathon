"""Pydantic schemas for AI Buying Agent and natural-language intent parsing."""

import uuid
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import DecisionOutcome, TransactionType
from app.schemas.decision import ActionEvaluationResponse
from app.schemas.payment import PaymentExecutionResponse


class AgentInterpretRequest(BaseModel):
    """Request payload for AI Buying Agent natural language intent parsing."""

    user_id: uuid.UUID = Field(
        description="ID of the user initiating the autonomous purchase request."
    )
    prompt: str = Field(
        min_length=3,
        max_length=1000,
        description="Natural language request (e.g. 'Buy my usual OpenAI subscription').",
        examples=["Buy my usual CloudCompute server subscription for this month"],
    )
    currency: str = Field(
        default="INR",
        min_length=3,
        max_length=3,
        description="ISO 4217 currency code.",
    )


class PaymentIntent(BaseModel):
    """Structured payment intent extracted by LLM / intent parser from natural language."""

    model_config = ConfigDict(from_attributes=True)

    user_id: uuid.UUID = Field(description="Resolved user principal ID.")
    merchant_id: uuid.UUID | None = Field(
        default=None, description="Resolved merchant ID if identified."
    )
    merchant_name: str | None = Field(
        default=None, description="Target merchant name or raw mention."
    )
    amount: Decimal | None = Field(
        default=None, description="Monetary amount extracted or inferred from history."
    )
    currency: str = Field(default="INR", description="ISO 4217 currency code.")
    transaction_type: TransactionType = Field(
        default=TransactionType.PURCHASE,
        description="Categorical financial transaction classification.",
    )
    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Parsing confidence score (0.0 to 1.0).",
    )
    is_ambiguous: bool = Field(
        default=False,
        description="True if intent is underspecified, missing key params, or ambiguous.",
    )
    ambiguity_reason: str | None = Field(
        default=None,
        description="Explanation if intent could not be unambiguously resolved.",
    )
    resolution_notes: str | None = Field(
        default=None,
        description="Contextual notes on how entity or price baseline was resolved.",
    )
    intent_type: str = Field(
        default="PURCHASE",
        description="Categorical intent type: PURCHASE, COMPARISON, or INFO_QUERY.",
    )
    is_new_merchant: bool = Field(
        default=False,
        description="True if merchant is newly identified and not in pre-existing DB list.",
    )
    comparison_merchants: list[str] | None = Field(
        default=None,
        description="List of merchant names if this is a comparison request.",
    )
    comparison_data: list[dict] | None = Field(
        default=None,
        description="Structured comparison metrics e.g. annual costs.",
    )


class AgentEvaluateRequest(BaseModel):
    """End-to-end request for AI Agent interpretation + DecisionVault evaluation."""

    user_id: uuid.UUID = Field(
        description="User principal initiating the agentic purchase."
    )
    prompt: str = Field(
        min_length=3,
        max_length=1000,
        description="Natural language purchase request.",
    )
    currency: str = Field(default="INR", min_length=3, max_length=3)
    auto_execute_payment: bool = Field(
        default=False,
        description="If True and decision is ALLOW, automatically executes payment via Razorpay.",
    )
    idempotency_key: str | None = Field(
        default=None,
        description="Optional idempotency key for payment execution.",
    )


class AgentEvaluateResponse(BaseModel):
    """Comprehensive response from AI Buying Agent and DecisionVault pipeline."""

    prompt: str = Field(description="Original user natural language request.")
    structured_intent: PaymentIntent = Field(
        description="Extracted and entity-resolved payment intent."
    )
    decision: DecisionOutcome = Field(
        description="Authoritative DecisionVault outcome: ALLOW, ASK_USER, or BLOCK."
    )
    decision_details: ActionEvaluationResponse | None = Field(
        default=None,
        description="Full deterministic guardrail & memory retrieval evaluation details.",
    )
    payment_result: PaymentExecutionResponse | None = Field(
        default=None,
        description="Payment execution result if auto_execute_payment was enabled and ALLOWed.",
    )
    comparison_data: list[dict] | None = Field(
        default=None,
        description="Comparison breakdown table if user submitted a comparison query.",
    )
    decision_id: uuid.UUID | None = Field(
        default=None,
        description="Authoritative Decision ID in the database if a decision was recorded.",
    )
    explanation: str = Field(
        description="Auditable, factual human-readable explanation based on structured evidence."
    )
