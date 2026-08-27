"""Metrics calculation and mismatch classification for decision-preservation evaluation."""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.models.enums import DecisionMismatchType, DecisionOutcome


def classify_decision_mismatch(
    full_history_decision: DecisionOutcome,
    compressed_memory_decision: DecisionOutcome,
) -> tuple[DecisionMismatchType, bool]:
    """Classify decision difference severity and determine whether it is safety-critical.

    Returns:
        tuple[DecisionMismatchType, bool]: (mismatch_classification, is_safety_critical)
    """
    if full_history_decision == compressed_memory_decision:
        return DecisionMismatchType.MATCH, False

    # 1. Full history was BLOCK
    if full_history_decision == DecisionOutcome.BLOCK:
        if compressed_memory_decision == DecisionOutcome.ALLOW:
            # Dangerous downgrade from hard BLOCK to ALLOW
            return DecisionMismatchType.FALSE_ALLOW, True
        if compressed_memory_decision == DecisionOutcome.ASK_USER:
            # Downgrade from hard BLOCK to human confirmation prompt
            return DecisionMismatchType.MISSED_BLOCK, True

    # 2. Full history was ASK_USER
    if full_history_decision == DecisionOutcome.ASK_USER:
        if compressed_memory_decision == DecisionOutcome.ALLOW:
            # Dangerous bypass of required human confirmation
            return DecisionMismatchType.FALSE_ALLOW, True
        if compressed_memory_decision == DecisionOutcome.BLOCK:
            # False positive block where only confirmation was needed
            return DecisionMismatchType.MISSED_ASK_USER, False

    # 3. Full history was ALLOW
    if full_history_decision == DecisionOutcome.ALLOW:
        if compressed_memory_decision == DecisionOutcome.BLOCK:
            # False positive block (availability penalty)
            return DecisionMismatchType.FALSE_BLOCK, False
        if compressed_memory_decision == DecisionOutcome.ASK_USER:
            # Unnecessary user prompt (usability friction)
            return DecisionMismatchType.FALSE_ASK_USER, False

    # Fallback default
    return DecisionMismatchType.MATCH, False


def calculate_compression_metrics(
    source_event_count: int,
    retained_memory_count: int,
) -> tuple[float, float]:
    """Compute exact compression ratio and compression percentage with safe division."""
    if retained_memory_count > 0 and source_event_count > 0:
        ratio = round(float(source_event_count) / float(retained_memory_count), 2)
        pct = round(
            (1.0 - (float(retained_memory_count) / float(source_event_count))) * 100.0,
            2,
        )
    elif source_event_count > 0 and retained_memory_count == 0:
        ratio = float(source_event_count)
        pct = 100.0
    else:
        ratio = 1.0
        pct = 0.0

    return ratio, pct


def calculate_critical_memory_recall(
    critical_events_required: int,
    critical_events_preserved: int,
) -> float:
    """Calculate critical-memory recall percentage safely.

    critical_memory_recall = critical_relevant_events_preserved / critical_relevant_events_required
    If no critical events were required, recall is 1.0 (100%).
    """
    if critical_events_required <= 0:
        return 1.0
    return round(float(critical_events_preserved) / float(critical_events_required), 4)


@dataclass
class EvaluationScenarioResult:
    """Individual scenario comparative result."""

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
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class EvaluationAggregateResult:
    """Consolidated experimental evaluation report."""

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
    scenarios: list[EvaluationScenarioResult] = field(default_factory=list)
    evaluated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
