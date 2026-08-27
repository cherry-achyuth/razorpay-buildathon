"""Pydantic schemas for Decision-Preservation Evaluation API."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import (
    DecisionMismatchType,
    DecisionOutcome,
    ScenarioSuite,
    TransactionType,
)


class ScenarioInputSchema(BaseModel):
    """Input scenario definition for comparative evaluation."""

    scenario_id: str
    name: str
    merchant_id: uuid.UUID
    amount: Decimal = Field(
        gt=Decimal("0.0000"), description="Proposed transaction amount."
    )
    currency: str = Field(
        min_length=3, max_length=3, description="ISO-4217 currency code."
    )
    mandate_id: uuid.UUID | None = None
    transaction_type: TransactionType = TransactionType.PURCHASE
    category: str = "CUSTOM"
    description: str = ""


class EvaluationRequest(BaseModel):
    """Request payload to trigger decision-preservation evaluation."""

    user_id: uuid.UUID = Field(
        description="Target user ID principal (strict tenant boundary)."
    )
    scenario_suite: ScenarioSuite = Field(
        default=ScenarioSuite.STANDARD,
        description="Benchmark scenario suite to execute (STANDARD, ADVERSARIAL).",
    )
    scenarios: list[ScenarioInputSchema] | None = Field(
        default=None,
        description="Optional explicit custom scenario list. If provided, overrides scenario_suite.",
    )


class EvaluationScenarioResultSchema(BaseModel):
    """Detailed result for an individual evaluation scenario."""

    model_config = ConfigDict(from_attributes=True)

    scenario_id: str
    name: str
    full_history_decision: DecisionOutcome
    full_history_reason_code: str
    compressed_memory_decision: DecisionOutcome
    compressed_memory_reason_code: str
    decision_match: bool
    mismatch_type: DecisionMismatchType
    safety_critical: bool
    category: str = "GENERAL"
    details: dict[str, Any] = Field(default_factory=dict)


class EvaluationResponse(BaseModel):
    """Comprehensive decision-preservation evaluation report."""

    model_config = ConfigDict(from_attributes=True)

    experiment_id: uuid.UUID
    user_id: uuid.UUID
    total_scenarios: int
    matching_decisions: int
    mismatching_decisions: int
    decision_preservation_rate: float
    safety_critical_cases: int
    safety_critical_matches: int
    safety_critical_preservation_rate: float
    false_allow_count: int
    false_block_count: int
    false_ask_user_count: int
    missed_block_count: int
    missed_ask_user_count: int
    source_event_count: int
    retained_memory_count: int
    compression_ratio: float
    compression_percentage: float
    scenario_suite: str = "STANDARD"
    critical_memory_recall: float = 1.0
    scenarios: list[EvaluationScenarioResultSchema]
    evaluated_at: datetime
