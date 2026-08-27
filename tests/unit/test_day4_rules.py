"""Unit tests for Day 4 safety rules."""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.models.enums import (
    DecisionOutcome,
    RuleDecisionEffect,
    RuleStatus,
    TransactionStatus,
    TransactionType,
    UserStatus,
)
from app.models.idempotency import IdempotencyRecord
from app.models.merchant import Merchant
from app.models.transaction import Transaction
from app.models.user import User
from app.services.guardrails.base import (
    EvaluationContext,
    ProposedFinancialAction,
)
from app.services.guardrails.engine import DeterministicRuleEngine
from app.services.guardrails.rules.duplicate_rule import DuplicatePaymentRule
from app.services.guardrails.rules.idempotency_rule import IdempotencyRule
from app.services.guardrails.rules.merchant_change_rule import (
    MerchantChangeRule,
)
from app.services.guardrails.rules.price_drift_rule import PriceDriftRule


@pytest.fixture
def base_context() -> EvaluationContext:
    user_id = uuid.uuid4()
    merchant_id = uuid.uuid4()
    user = User(id=user_id, status=UserStatus.ACTIVE)
    merchant = Merchant(id=merchant_id, name="Cloud Compute", status="ACTIVE")
    return EvaluationContext(
        user=user,
        merchant=merchant,
        duplicate_window_seconds=300,
        price_drift_threshold_percent=Decimal("25.0"),
        price_drift_min_samples=3,
    )


# --- 1. Duplicate Payment Detection Tests ---


@pytest.mark.asyncio
async def test_duplicate_rule_no_history(base_context: EvaluationContext):
    """Verify duplicate rule passes when no recent transactions exist."""
    rule = DuplicatePaymentRule()
    action = ProposedFinancialAction(
        user_id=base_context.user.id,
        merchant_id=base_context.merchant.id,
        amount=Decimal("500.00"),
        currency="INR",
    )
    res = await rule.evaluate(action, base_context)
    assert res.status == RuleStatus.PASS
    assert res.reason_code == "NO_DUPLICATE_DETECTED"


@pytest.mark.asyncio
async def test_duplicate_rule_detects_recent_identical_payment(
    base_context: EvaluationContext,
):
    """Verify duplicate rule blocks when identical payment occurred within window."""
    now = datetime.now(UTC)
    tx = Transaction(
        id=uuid.uuid4(),
        user_id=base_context.user.id,
        merchant_id=base_context.merchant.id,
        amount=Decimal("1200.00"),
        currency="INR",
        transaction_type=TransactionType.PURCHASE,
        status=TransactionStatus.CAPTURED,
        occurred_at=now - timedelta(seconds=45),  # Within 300s
    )
    base_context.recent_window_transactions = [tx]

    rule = DuplicatePaymentRule()
    action = ProposedFinancialAction(
        user_id=base_context.user.id,
        merchant_id=base_context.merchant.id,
        amount=Decimal("1200.00"),
        currency="INR",
        transaction_type=TransactionType.PURCHASE,
        requested_at=now,
    )
    res = await rule.evaluate(action, base_context)
    assert res.status == RuleStatus.FAIL
    assert res.decision_effect == RuleDecisionEffect.BLOCK
    assert res.reason_code == "DUPLICATE_PAYMENT_DETECTED"


@pytest.mark.asyncio
async def test_duplicate_rule_allows_outside_window(
    base_context: EvaluationContext,
):
    """Verify duplicate rule allows identical payment outside sliding window."""
    now = datetime.now(UTC)
    tx = Transaction(
        id=uuid.uuid4(),
        user_id=base_context.user.id,
        merchant_id=base_context.merchant.id,
        amount=Decimal("1200.00"),
        currency="INR",
        transaction_type=TransactionType.PURCHASE,
        status=TransactionStatus.CAPTURED,
        occurred_at=now - timedelta(seconds=350),  # Outside 300s window
    )
    base_context.recent_window_transactions = [tx]

    rule = DuplicatePaymentRule()
    action = ProposedFinancialAction(
        user_id=base_context.user.id,
        merchant_id=base_context.merchant.id,
        amount=Decimal("1200.00"),
        currency="INR",
        transaction_type=TransactionType.PURCHASE,
        requested_at=now,
    )
    res = await rule.evaluate(action, base_context)
    assert res.status == RuleStatus.PASS
    assert res.reason_code == "NO_DUPLICATE_DETECTED"


@pytest.mark.asyncio
async def test_duplicate_rule_ignores_failed_and_different_parameters(
    base_context: EvaluationContext,
):
    """Verify duplicate rule ignores failed transactions and mismatched parameters."""
    now = datetime.now(UTC)
    tx_failed = Transaction(
        id=uuid.uuid4(),
        user_id=base_context.user.id,
        merchant_id=base_context.merchant.id,
        amount=Decimal("1200.00"),
        currency="INR",
        transaction_type=TransactionType.PURCHASE,
        status=TransactionStatus.FAILED,
        occurred_at=now - timedelta(seconds=10),
    )
    tx_diff_amount = Transaction(
        id=uuid.uuid4(),
        user_id=base_context.user.id,
        merchant_id=base_context.merchant.id,
        amount=Decimal("800.00"),
        currency="INR",
        transaction_type=TransactionType.PURCHASE,
        status=TransactionStatus.CAPTURED,
        occurred_at=now - timedelta(seconds=10),
    )
    base_context.recent_window_transactions = [tx_failed, tx_diff_amount]

    rule = DuplicatePaymentRule()
    action = ProposedFinancialAction(
        user_id=base_context.user.id,
        merchant_id=base_context.merchant.id,
        amount=Decimal("1200.00"),
        currency="INR",
        requested_at=now,
    )
    res = await rule.evaluate(action, base_context)
    assert res.status == RuleStatus.PASS


# --- 2. Idempotency Protection Tests ---


@pytest.mark.asyncio
async def test_idempotency_rule_fresh_key_and_no_key(
    base_context: EvaluationContext,
):
    """Verify idempotency rule with fresh key or absent key."""
    rule = IdempotencyRule()

    # 1. No key supplied
    action_no_key = ProposedFinancialAction(
        user_id=base_context.user.id,
        merchant_id=base_context.merchant.id,
        amount=Decimal("500.00"),
        currency="INR",
        idempotency_key=None,
    )
    res_no_key = await rule.evaluate(action_no_key, base_context)
    assert res_no_key.status == RuleStatus.NOT_APPLICABLE

    # 2. Fresh key
    action_fresh = ProposedFinancialAction(
        user_id=base_context.user.id,
        merchant_id=base_context.merchant.id,
        amount=Decimal("500.00"),
        currency="INR",
        idempotency_key="fresh_key_01",
    )
    res_fresh = await rule.evaluate(action_fresh, base_context)
    assert res_fresh.status == RuleStatus.PASS
    assert res_fresh.reason_code == "IDEMPOTENCY_KEY_AVAILABLE"


@pytest.mark.asyncio
async def test_idempotency_rule_matching_retry_and_tampering_conflict(
    base_context: EvaluationContext,
):
    """Verify idempotent matching retry passes, but tampered payload blocks."""
    action = ProposedFinancialAction(
        user_id=base_context.user.id,
        merchant_id=base_context.merchant.id,
        amount=Decimal("1000.00"),
        currency="INR",
        transaction_type=TransactionType.PURCHASE,
        idempotency_key="idem_key_44",
    )
    correct_hash = action.canonical_fingerprint()

    # Setup existing idempotency record
    existing = IdempotencyRecord(
        id=uuid.uuid4(),
        key="idem_key_44",
        user_id=base_context.user.id,
        request_hash=correct_hash,
        response_payload={"decision": "ALLOW"},
    )
    base_context.existing_idempotency_record = existing

    rule = IdempotencyRule()

    # 1. Matching retry -> PASS
    res_match = await rule.evaluate(action, base_context)
    assert res_match.status == RuleStatus.PASS
    assert res_match.reason_code == "IDEMPOTENT_RETRY_ACCEPTED"

    # 2. Tampered amount with same key -> BLOCK
    action_tampered = ProposedFinancialAction(
        user_id=base_context.user.id,
        merchant_id=base_context.merchant.id,
        amount=Decimal("5000.00"),  # Changed from 1000.00
        currency="INR",
        transaction_type=TransactionType.PURCHASE,
        idempotency_key="idem_key_44",
    )
    res_tampered = await rule.evaluate(action_tampered, base_context)
    assert res_tampered.status == RuleStatus.FAIL
    assert res_tampered.decision_effect == RuleDecisionEffect.BLOCK
    assert res_tampered.reason_code == "IDEMPOTENCY_KEY_CONFLICT"


# --- 3. Price Drift Detection Tests ---


@pytest.mark.asyncio
async def test_price_drift_insufficient_samples(
    base_context: EvaluationContext,
):
    """Verify price drift is NOT_APPLICABLE when fewer than 3 samples exist."""
    rule = PriceDriftRule()
    action = ProposedFinancialAction(
        user_id=base_context.user.id,
        merchant_id=base_context.merchant.id,
        amount=Decimal("150.00"),
        currency="INR",
    )

    # 2 samples (< 3 min required)
    base_context.merchant_historical_transactions = [
        Transaction(
            id=uuid.uuid4(),
            user_id=base_context.user.id,
            merchant_id=base_context.merchant.id,
            amount=Decimal("100.00"),
            currency="INR",
            transaction_type=TransactionType.PURCHASE,
            status=TransactionStatus.CAPTURED,
        ),
        Transaction(
            id=uuid.uuid4(),
            user_id=base_context.user.id,
            merchant_id=base_context.merchant.id,
            amount=Decimal("105.00"),
            currency="INR",
            transaction_type=TransactionType.PURCHASE,
            status=TransactionStatus.CAPTURED,
        ),
    ]

    res = await rule.evaluate(action, base_context)
    assert res.status == RuleStatus.NOT_APPLICABLE
    assert res.reason_code == "INSUFFICIENT_PRICE_HISTORY"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "requested_amount,expected_status,expected_effect,expected_reason",
    [
        (
            Decimal("110.00"),
            RuleStatus.PASS,
            RuleDecisionEffect.NONE,
            "PRICE_DRIFT_WITHIN_BOUNDS",
        ),
        (
            Decimal("125.00"),
            RuleStatus.PASS,
            RuleDecisionEffect.NONE,
            "PRICE_DRIFT_WITHIN_BOUNDS",
        ),
        (
            Decimal("125.01"),
            RuleStatus.FAIL,
            RuleDecisionEffect.ASK_USER,
            "SIGNIFICANT_PRICE_DRIFT",
        ),
        (
            Decimal("160.00"),
            RuleStatus.FAIL,
            RuleDecisionEffect.ASK_USER,
            "SIGNIFICANT_PRICE_DRIFT",
        ),
    ],
)
async def test_price_drift_exact_boundaries(
    base_context: EvaluationContext,
    requested_amount: Decimal,
    expected_status: RuleStatus,
    expected_effect: RuleDecisionEffect,
    expected_reason: str,
):
    """Verify price drift calculation against median baseline (100.00 INR)."""
    # 3 historical transactions: [98.00, 100.00, 102.00] -> Median = 100.00
    base_context.merchant_historical_transactions = [
        Transaction(
            id=uuid.uuid4(),
            user_id=base_context.user.id,
            merchant_id=base_context.merchant.id,
            amount=Decimal("98.00"),
            currency="INR",
            transaction_type=TransactionType.PURCHASE,
            status=TransactionStatus.CAPTURED,
        ),
        Transaction(
            id=uuid.uuid4(),
            user_id=base_context.user.id,
            merchant_id=base_context.merchant.id,
            amount=Decimal("100.00"),
            currency="INR",
            transaction_type=TransactionType.PURCHASE,
            status=TransactionStatus.CAPTURED,
        ),
        Transaction(
            id=uuid.uuid4(),
            user_id=base_context.user.id,
            merchant_id=base_context.merchant.id,
            amount=Decimal("102.00"),
            currency="INR",
            transaction_type=TransactionType.PURCHASE,
            status=TransactionStatus.CAPTURED,
        ),
    ]

    rule = PriceDriftRule()
    action = ProposedFinancialAction(
        user_id=base_context.user.id,
        merchant_id=base_context.merchant.id,
        amount=requested_amount,
        currency="INR",
        transaction_type=TransactionType.PURCHASE,
    )
    res = await rule.evaluate(action, base_context)
    assert res.status == expected_status
    assert res.decision_effect == expected_effect
    assert res.reason_code == expected_reason


# --- 4. Merchant Change Detection Tests ---


@pytest.mark.asyncio
async def test_merchant_change_scenarios(base_context: EvaluationContext):
    """Test merchant change logic: no history, familiar, and unfamiliar merchant."""
    rule = MerchantChangeRule()
    known_merchant_id = uuid.uuid4()
    new_merchant_id = base_context.merchant.id

    # 1. No history -> NOT_APPLICABLE
    base_context.user_total_historical_tx_count = 0
    base_context.user_historical_merchant_ids = set()
    action = ProposedFinancialAction(
        user_id=base_context.user.id,
        merchant_id=new_merchant_id,
        amount=Decimal("100.00"),
        currency="INR",
    )
    res_no_hist = await rule.evaluate(action, base_context)
    assert res_no_hist.status == RuleStatus.NOT_APPLICABLE
    assert res_no_hist.reason_code == "NO_PRIOR_TRANSACTION_HISTORY"

    # 2. Familiar merchant -> PASS
    base_context.user_total_historical_tx_count = 5
    base_context.user_historical_merchant_ids = {
        known_merchant_id,
        new_merchant_id,
    }
    res_familiar = await rule.evaluate(action, base_context)
    assert res_familiar.status == RuleStatus.PASS
    assert res_familiar.reason_code == "FAMILIAR_MERCHANT"

    # 3. Established history but unfamiliar new merchant -> ASK_USER
    base_context.user_historical_merchant_ids = {known_merchant_id}
    res_unfamiliar = await rule.evaluate(action, base_context)
    assert res_unfamiliar.status == RuleStatus.FAIL
    assert res_unfamiliar.decision_effect == RuleDecisionEffect.ASK_USER
    assert res_unfamiliar.reason_code == "UNEXPECTED_MERCHANT_CHANGE"


# --- 5. Multi-Rule Precedence Tests ---


@pytest.mark.asyncio
async def test_engine_precedence_block_overrides_ask_user(
    base_context: EvaluationContext,
):
    """Verify BLOCK strictly overrides ASK_USER while preserving all evidence."""
    now = datetime.now(UTC)
    # Duplicate transaction within window (causes DuplicatePaymentRule to produce BLOCK)
    tx_dup = Transaction(
        id=uuid.uuid4(),
        user_id=base_context.user.id,
        merchant_id=base_context.merchant.id,
        amount=Decimal("150.00"),
        currency="INR",
        transaction_type=TransactionType.PURCHASE,
        status=TransactionStatus.CAPTURED,
        occurred_at=now - timedelta(seconds=20),
    )
    base_context.recent_window_transactions = [tx_dup]

    # Price history with median 100.00 (Proposed 150.00 is +50% drift -> ASK_USER)
    base_context.merchant_historical_transactions = [
        Transaction(
            id=uuid.uuid4(),
            user_id=base_context.user.id,
            merchant_id=base_context.merchant.id,
            amount=Decimal("100.00"),
            currency="INR",
            transaction_type=TransactionType.PURCHASE,
            status=TransactionStatus.CAPTURED,
        ),
        Transaction(
            id=uuid.uuid4(),
            user_id=base_context.user.id,
            merchant_id=base_context.merchant.id,
            amount=Decimal("100.00"),
            currency="INR",
            transaction_type=TransactionType.PURCHASE,
            status=TransactionStatus.CAPTURED,
        ),
        Transaction(
            id=uuid.uuid4(),
            user_id=base_context.user.id,
            merchant_id=base_context.merchant.id,
            amount=Decimal("100.00"),
            currency="INR",
            transaction_type=TransactionType.PURCHASE,
            status=TransactionStatus.CAPTURED,
        ),
    ]

    engine = DeterministicRuleEngine()
    action = ProposedFinancialAction(
        user_id=base_context.user.id,
        merchant_id=base_context.merchant.id,
        amount=Decimal("150.00"),
        currency="INR",
        transaction_type=TransactionType.PURCHASE,
        requested_at=now,
    )

    result = await engine.evaluate(action, base_context)

    # BLOCK must win over ASK_USER
    assert result.decision == DecisionOutcome.BLOCK
    assert result.reason_code == "DUPLICATE_PAYMENT_DETECTED"

    # Rule results must retain both the BLOCK and the ASK_USER signals
    dup_res = next(
        r for r in result.rule_results if r.rule_id == "DUPLICATE_PAYMENT_GUARD"
    )
    drift_res = next(r for r in result.rule_results if r.rule_id == "PRICE_DRIFT_GUARD")

    assert dup_res.decision_effect == RuleDecisionEffect.BLOCK
    assert drift_res.decision_effect == RuleDecisionEffect.ASK_USER
