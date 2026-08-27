"""Unit tests for decision-preservation evaluation metrics and mismatch classification."""

from app.models.enums import DecisionMismatchType, DecisionOutcome, ScenarioSuite
from app.services.evaluation.metrics import (
    calculate_compression_metrics,
    calculate_critical_memory_recall,
    classify_decision_mismatch,
)


def test_classify_decision_mismatch_exact_matches():
    """Verify identical decisions are classified as MATCH with safety_critical=False."""
    for outcome in [
        DecisionOutcome.ALLOW,
        DecisionOutcome.BLOCK,
        DecisionOutcome.ASK_USER,
    ]:
        mismatch_type, is_crit = classify_decision_mismatch(outcome, outcome)
        assert mismatch_type == DecisionMismatchType.MATCH
        assert is_crit is False


def test_classify_decision_mismatch_false_allow():
    """Verify full BLOCK/ASK_USER to compressed ALLOW is classified as safety-critical FALSE_ALLOW."""
    # Full BLOCK -> Comp ALLOW
    t1, crit1 = classify_decision_mismatch(DecisionOutcome.BLOCK, DecisionOutcome.ALLOW)
    assert t1 == DecisionMismatchType.FALSE_ALLOW
    assert crit1 is True

    # Full ASK_USER -> Comp ALLOW
    t2, crit2 = classify_decision_mismatch(
        DecisionOutcome.ASK_USER, DecisionOutcome.ALLOW
    )
    assert t2 == DecisionMismatchType.FALSE_ALLOW
    assert crit2 is True


def test_classify_decision_mismatch_missed_block():
    """Verify full BLOCK to compressed ASK_USER is classified as safety-critical MISSED_BLOCK."""
    t, crit = classify_decision_mismatch(
        DecisionOutcome.BLOCK, DecisionOutcome.ASK_USER
    )
    assert t == DecisionMismatchType.MISSED_BLOCK
    assert crit is True


def test_classify_decision_mismatch_false_block_and_ask_user():
    """Verify availability and usability mismatches are classified correctly without safety-critical flag."""
    # Full ALLOW -> Comp BLOCK (False block / availability penalty)
    t1, crit1 = classify_decision_mismatch(DecisionOutcome.ALLOW, DecisionOutcome.BLOCK)
    assert t1 == DecisionMismatchType.FALSE_BLOCK
    assert crit1 is False

    # Full ALLOW -> Comp ASK_USER (Unnecessary prompt / friction)
    t2, crit2 = classify_decision_mismatch(
        DecisionOutcome.ALLOW, DecisionOutcome.ASK_USER
    )
    assert t2 == DecisionMismatchType.FALSE_ASK_USER
    assert crit2 is False

    # Full ASK_USER -> Comp BLOCK
    t3, crit3 = classify_decision_mismatch(
        DecisionOutcome.ASK_USER, DecisionOutcome.BLOCK
    )
    assert t3 == DecisionMismatchType.MISSED_ASK_USER
    assert crit3 is False


def test_calculate_compression_metrics():
    """Verify exact compression ratio and percentage calculations."""
    # 6 sources -> 3 memories = 2.0x, 50%
    ratio, pct = calculate_compression_metrics(
        source_event_count=6, retained_memory_count=3
    )
    assert ratio == 2.0
    assert pct == 50.0

    # 10 sources -> 1 memory = 10.0x, 90%
    ratio2, pct2 = calculate_compression_metrics(
        source_event_count=10, retained_memory_count=1
    )
    assert ratio2 == 10.0
    assert pct2 == 90.0

    # Edge cases
    r_zero_src, pct_zero_src = calculate_compression_metrics(0, 0)
    assert r_zero_src == 1.0
    assert pct_zero_src == 0.0

    r_zero_ret, pct_zero_ret = calculate_compression_metrics(5, 0)
    assert r_zero_ret == 5.0
    assert pct_zero_ret == 100.0


def test_calculate_critical_memory_recall():
    """Verify critical memory recall metric calculation."""
    # 4 required, 4 preserved -> 1.0
    assert calculate_critical_memory_recall(4, 4) == 1.0

    # 4 required, 3 preserved -> 0.75
    assert calculate_critical_memory_recall(4, 3) == 0.75

    # 0 required -> 1.0
    assert calculate_critical_memory_recall(0, 0) == 1.0


def test_scenario_suite_enum():
    """Verify ScenarioSuite enum values."""
    assert ScenarioSuite.STANDARD == "STANDARD"
    assert ScenarioSuite.ADVERSARIAL == "ADVERSARIAL"
    assert ScenarioSuite.CUSTOM == "CUSTOM"
