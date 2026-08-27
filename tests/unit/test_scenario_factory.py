"""Unit tests for deterministic ScenarioFactory."""

import uuid
from decimal import Decimal

from app.models.enums import DecisionOutcome
from app.services.evaluation.scenarios import ScenarioFactory


def test_scenario_factory_generates_reproducible_standard_scenarios():
    """Verify ScenarioFactory generates standard deterministic evaluation scenarios."""
    uid = uuid.uuid4()
    m1 = uuid.uuid4()
    m2 = uuid.uuid4()

    scenarios = ScenarioFactory.create_standard_scenarios(
        user_id=uid,
        routine_merchant_id=m1,
        unfamiliar_merchant_id=m2,
        policy_limit_amount=Decimal("100.0000"),
        routine_baseline_amount=Decimal("30.0000"),
    )

    assert len(scenarios) == 5
    ids = [s.scenario_id for s in scenarios]
    assert "SCENARIO_ROUTINE_PURCHASE" in ids
    assert "SCENARIO_POLICY_BREACH" in ids
    assert "SCENARIO_SIGNIFICANT_PRICE_DRIFT" in ids
    assert "SCENARIO_PRICE_WITHIN_BOUNDS" in ids
    assert "SCENARIO_UNEXPECTED_MERCHANT" in ids

    # Check amounts and expected full decisions
    s_routine = next(
        s for s in scenarios if s.scenario_id == "SCENARIO_ROUTINE_PURCHASE"
    )
    assert s_routine.amount == Decimal("30.0000")
    assert s_routine.expected_full_decision == DecisionOutcome.ALLOW

    s_breach = next(s for s in scenarios if s.scenario_id == "SCENARIO_POLICY_BREACH")
    assert s_breach.amount == Decimal("150.0000")
    assert s_breach.expected_full_decision == DecisionOutcome.BLOCK

    s_drift = next(
        s for s in scenarios if s.scenario_id == "SCENARIO_SIGNIFICANT_PRICE_DRIFT"
    )
    assert s_drift.amount == Decimal("48.0000")  # 30 * 1.60
    assert s_drift.expected_full_decision == DecisionOutcome.ASK_USER


def test_scenario_factory_generates_reproducible_adversarial_scenarios():
    """Verify ScenarioFactory generates comprehensive adversarial/boundary scenarios."""
    uid = uuid.uuid4()
    m1 = uuid.uuid4()
    m2 = uuid.uuid4()
    m3 = uuid.uuid4()
    m4 = uuid.uuid4()

    scenarios = ScenarioFactory.create_adversarial_scenarios(
        user_id=uid,
        routine_merchant_id=m1,
        unfamiliar_merchant_id=m2,
        secondary_known_merchant_id=m3,
        similar_name_merchant_id=m4,
        policy_limit_amount=Decimal("50.0000"),
        routine_baseline_amount=Decimal("25.0000"),
        drift_threshold_percent=Decimal("25.0"),
    )

    assert len(scenarios) >= 10
    ids = [s.scenario_id for s in scenarios]

    # Policy boundary checks
    assert "SCENARIO_POLICY_EXACT_AT_LIMIT" in ids
    assert "SCENARIO_POLICY_JUST_BELOW_LIMIT" in ids
    assert "SCENARIO_POLICY_JUST_ABOVE_LIMIT" in ids

    s_at_limit = next(
        s for s in scenarios if s.scenario_id == "SCENARIO_POLICY_EXACT_AT_LIMIT"
    )
    assert s_at_limit.amount == Decimal("50.0000")
    assert s_at_limit.expected_full_decision == DecisionOutcome.ALLOW

    s_below_limit = next(
        s for s in scenarios if s.scenario_id == "SCENARIO_POLICY_JUST_BELOW_LIMIT"
    )
    assert s_below_limit.amount == Decimal("49.9900")
    assert s_below_limit.expected_full_decision == DecisionOutcome.ALLOW

    s_above_limit = next(
        s for s in scenarios if s.scenario_id == "SCENARIO_POLICY_JUST_ABOVE_LIMIT"
    )
    assert s_above_limit.amount == Decimal("50.0100")
    assert s_above_limit.expected_full_decision == DecisionOutcome.BLOCK

    # Price drift boundary checks
    assert "SCENARIO_PRICE_DRIFT_EXACT_AT_THRESHOLD" in ids
    assert "SCENARIO_PRICE_DRIFT_JUST_BELOW_THRESHOLD" in ids
    assert "SCENARIO_PRICE_DRIFT_JUST_ABOVE_THRESHOLD" in ids

    s_at_thresh = next(
        s
        for s in scenarios
        if s.scenario_id == "SCENARIO_PRICE_DRIFT_EXACT_AT_THRESHOLD"
    )
    assert s_at_thresh.amount == Decimal("31.2500")
    assert s_at_thresh.expected_full_decision == DecisionOutcome.ALLOW

    s_above_thresh = next(
        s
        for s in scenarios
        if s.scenario_id == "SCENARIO_PRICE_DRIFT_JUST_ABOVE_THRESHOLD"
    )
    assert s_above_thresh.amount == Decimal("31.5000")
    assert s_above_thresh.expected_full_decision == DecisionOutcome.ASK_USER
