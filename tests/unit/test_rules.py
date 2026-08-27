"""Unit tests for deterministic guardrail rules and exact monetary bounds."""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.models.enums import (
    DecisionOutcome,
    MandateStatus,
    MerchantStatus,
    PolicyStatus,
    PolicyType,
    TransactionStatus,
    TransactionType,
    UserStatus,
)
from app.models.mandate import Mandate
from app.models.merchant import Merchant
from app.models.policy import Policy
from app.models.transaction import Transaction
from app.models.user import User
from app.services.guardrails.base import (
    EvaluationContext,
    ProposedFinancialAction,
    RuleDecisionEffect,
    RuleStatus,
)
from app.services.guardrails.engine import DeterministicRuleEngine
from app.services.guardrails.rules.mandate_rule import MandateConstraintRule
from app.services.guardrails.rules.policy_rule import PolicyLimitRule


@pytest.fixture
def mock_context() -> EvaluationContext:
    """Fixture providing standard user, merchant, mandate, and policy entities."""
    user_id = uuid.uuid4()
    merchant_id = uuid.uuid4()
    now = datetime.now(UTC)

    user = User(id=user_id, status=UserStatus.ACTIVE)
    merchant = Merchant(
        id=merchant_id, name="Cloud Compute", status=MerchantStatus.ACTIVE
    )
    mandate = Mandate(
        id=uuid.uuid4(),
        user_id=user_id,
        merchant_id=merchant_id,
        status=MandateStatus.ACTIVE,
        currency="INR",
        max_transaction_amount=Decimal("5000.0000"),
        valid_from=now - timedelta(days=10),
        valid_until=now + timedelta(days=30),
    )
    policy = Policy(
        id=uuid.uuid4(),
        user_id=user_id,
        name="Spend Cap Guardrail",
        policy_type=PolicyType.TRANSACTION_LIMIT,
        status=PolicyStatus.ACTIVE,
        currency="INR",
        limit_amount=Decimal("4000.0000"),
        valid_from=now - timedelta(days=10),
        valid_until=now + timedelta(days=30),
    )

    return EvaluationContext(
        user=user,
        merchant=merchant,
        mandate=mandate,
        active_policies=[policy],
    )


@pytest.mark.asyncio
async def test_mandate_rule_valid_action(mock_context: EvaluationContext):
    """Verify mandate rule passes when action is within bounds."""
    rule = MandateConstraintRule()
    action = ProposedFinancialAction(
        user_id=mock_context.user.id,
        merchant_id=mock_context.merchant.id,
        mandate_id=mock_context.mandate.id,
        amount=Decimal("2500.0000"),
        currency="INR",
        transaction_type=TransactionType.PURCHASE,
    )

    result = await rule.evaluate(action, mock_context)
    assert result.status == RuleStatus.PASS
    assert result.decision_effect == RuleDecisionEffect.NONE
    assert result.reason_code == "MANDATE_CONSTRAINTS_SATISFIED"


@pytest.mark.asyncio
async def test_mandate_rule_no_mandate_specified(mock_context: EvaluationContext):
    """Verify mandate rule is not applicable when no mandate_id is supplied."""
    rule = MandateConstraintRule()
    action = ProposedFinancialAction(
        user_id=mock_context.user.id,
        merchant_id=mock_context.merchant.id,
        mandate_id=None,
        amount=Decimal("100.0000"),
        currency="INR",
    )

    result = await rule.evaluate(action, mock_context)
    assert result.status == RuleStatus.NOT_APPLICABLE
    assert result.decision_effect == RuleDecisionEffect.NONE
    assert result.reason_code == "NO_MANDATE_SPECIFIED"


@pytest.mark.asyncio
async def test_mandate_rule_user_mismatch(mock_context: EvaluationContext):
    """Verify mandate rule blocks when user is not the mandate owner."""
    rule = MandateConstraintRule()
    action = ProposedFinancialAction(
        user_id=uuid.uuid4(),  # Different user
        merchant_id=mock_context.merchant.id,
        mandate_id=mock_context.mandate.id,
        amount=Decimal("100.0000"),
        currency="INR",
    )

    result = await rule.evaluate(action, mock_context)
    assert result.status == RuleStatus.FAIL
    assert result.decision_effect == RuleDecisionEffect.BLOCK
    assert result.reason_code == "MANDATE_USER_MISMATCH"


@pytest.mark.asyncio
async def test_mandate_rule_inactive_status(mock_context: EvaluationContext):
    """Verify mandate rule blocks when mandate is revoked or suspended."""
    mock_context.mandate.status = MandateStatus.REVOKED
    rule = MandateConstraintRule()
    action = ProposedFinancialAction(
        user_id=mock_context.user.id,
        merchant_id=mock_context.merchant.id,
        mandate_id=mock_context.mandate.id,
        amount=Decimal("100.0000"),
        currency="INR",
    )

    result = await rule.evaluate(action, mock_context)
    assert result.status == RuleStatus.FAIL
    assert result.decision_effect == RuleDecisionEffect.BLOCK
    assert result.reason_code == "MANDATE_INACTIVE"


@pytest.mark.asyncio
async def test_mandate_rule_expired_and_not_yet_valid(mock_context: EvaluationContext):
    """Verify mandate rule blocks for expired or future validity dates."""
    rule = MandateConstraintRule()
    now = datetime.now(UTC)

    # 1. Expired mandate
    mock_context.mandate.valid_until = now - timedelta(days=1)
    action = ProposedFinancialAction(
        user_id=mock_context.user.id,
        merchant_id=mock_context.merchant.id,
        mandate_id=mock_context.mandate.id,
        amount=Decimal("100.0000"),
        currency="INR",
        requested_at=now,
    )
    result = await rule.evaluate(action, mock_context)
    assert result.status == RuleStatus.FAIL
    assert result.decision_effect == RuleDecisionEffect.BLOCK
    assert result.reason_code == "MANDATE_EXPIRED"

    # 2. Not-yet-valid mandate
    mock_context.mandate.valid_from = now + timedelta(days=2)
    mock_context.mandate.valid_until = now + timedelta(days=30)
    result_future = await rule.evaluate(action, mock_context)
    assert result_future.status == RuleStatus.FAIL
    assert result_future.decision_effect == RuleDecisionEffect.BLOCK
    assert result_future.reason_code == "MANDATE_NOT_YET_VALID"


@pytest.mark.asyncio
async def test_mandate_rule_currency_and_merchant_mismatch(
    mock_context: EvaluationContext,
):
    """Verify mandate blocks on currency or restricted merchant mismatch."""
    rule = MandateConstraintRule()

    # 1. Currency mismatch
    action_usd = ProposedFinancialAction(
        user_id=mock_context.user.id,
        merchant_id=mock_context.merchant.id,
        mandate_id=mock_context.mandate.id,
        amount=Decimal("100.0000"),
        currency="USD",  # Mandate is INR
    )
    res_curr = await rule.evaluate(action_usd, mock_context)
    assert res_curr.status == RuleStatus.FAIL
    assert res_curr.reason_code == "MANDATE_CURRENCY_MISMATCH"

    # 2. Merchant mismatch
    action_merch = ProposedFinancialAction(
        user_id=mock_context.user.id,
        merchant_id=uuid.uuid4(),  # Different merchant
        mandate_id=mock_context.mandate.id,
        amount=Decimal("100.0000"),
        currency="INR",
    )
    res_merch = await rule.evaluate(action_merch, mock_context)
    assert res_merch.status == RuleStatus.FAIL
    assert res_merch.reason_code == "MANDATE_MERCHANT_MISMATCH"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "amount,expected_status,expected_effect",
    [
        (Decimal("4999.9999"), RuleStatus.PASS, RuleDecisionEffect.NONE),
        (Decimal("5000.0000"), RuleStatus.PASS, RuleDecisionEffect.NONE),
        (Decimal("5000.0001"), RuleStatus.FAIL, RuleDecisionEffect.BLOCK),
        (Decimal("10000.0000"), RuleStatus.FAIL, RuleDecisionEffect.BLOCK),
    ],
)
async def test_mandate_exact_monetary_boundaries(
    mock_context: EvaluationContext,
    amount: Decimal,
    expected_status: RuleStatus,
    expected_effect: RuleDecisionEffect,
):
    """Test exact Decimal boundary behavior for MandateConstraintRule."""
    mock_context.mandate.max_transaction_amount = Decimal("5000.0000")
    rule = MandateConstraintRule()
    action = ProposedFinancialAction(
        user_id=mock_context.user.id,
        merchant_id=mock_context.merchant.id,
        mandate_id=mock_context.mandate.id,
        amount=amount,
        currency="INR",
    )

    res = await rule.evaluate(action, mock_context)
    assert res.status == expected_status
    assert res.decision_effect == expected_effect


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "amount,expected_status,expected_effect",
    [
        (Decimal("3999.9900"), RuleStatus.PASS, RuleDecisionEffect.NONE),
        (Decimal("4000.0000"), RuleStatus.PASS, RuleDecisionEffect.NONE),
        (Decimal("4000.0001"), RuleStatus.FAIL, RuleDecisionEffect.BLOCK),
        (Decimal("7500.0000"), RuleStatus.FAIL, RuleDecisionEffect.BLOCK),
    ],
)
async def test_policy_exact_monetary_boundaries(
    mock_context: EvaluationContext,
    amount: Decimal,
    expected_status: RuleStatus,
    expected_effect: RuleDecisionEffect,
):
    """Test exact Decimal boundary behavior for PolicyLimitRule."""
    rule = PolicyLimitRule()
    action = ProposedFinancialAction(
        user_id=mock_context.user.id,
        merchant_id=mock_context.merchant.id,
        mandate_id=mock_context.mandate.id,
        amount=amount,
        currency="INR",
    )

    res = await rule.evaluate(action, mock_context)
    assert res.status == expected_status
    assert res.decision_effect == expected_effect


@pytest.mark.asyncio
async def test_engine_deterministic_precedence(mock_context: EvaluationContext):
    """Verify that BLOCK has absolute precedence in DeterministicRuleEngine."""
    engine = DeterministicRuleEngine()

    # 1. Action passes Mandate (cap 5000) and Policy (cap 4000) -> ALLOW
    action_allow = ProposedFinancialAction(
        user_id=mock_context.user.id,
        merchant_id=mock_context.merchant.id,
        mandate_id=mock_context.mandate.id,
        amount=Decimal("3500.0000"),
        currency="INR",
    )
    res_allow = await engine.evaluate(action_allow, mock_context)
    assert res_allow.decision == DecisionOutcome.ALLOW
    assert res_allow.reason_code == "DETERMINISTIC_RULES_PASSED"

    # 2. Action passes Mandate (5000) but violates Policy (cap 4000) -> BLOCK
    action_policy_block = ProposedFinancialAction(
        user_id=mock_context.user.id,
        merchant_id=mock_context.merchant.id,
        mandate_id=mock_context.mandate.id,
        amount=Decimal("4500.0000"),
        currency="INR",
    )
    res_policy_block = await engine.evaluate(action_policy_block, mock_context)
    assert res_policy_block.decision == DecisionOutcome.BLOCK
    assert res_policy_block.reason_code == "POLICY_LIMIT_EXCEEDED"

    # 3. Action violates both Mandate (cap 5000) and Policy (cap 4000) -> BLOCK
    action_both_block = ProposedFinancialAction(
        user_id=mock_context.user.id,
        merchant_id=mock_context.merchant.id,
        mandate_id=mock_context.mandate.id,
        amount=Decimal("6000.0000"),
        currency="INR",
    )
    res_both_block = await engine.evaluate(action_both_block, mock_context)
    assert res_both_block.decision == DecisionOutcome.BLOCK
    assert res_both_block.reason_code == "MANDATE_AMOUNT_EXCEEDED"


@pytest.mark.asyncio
async def test_policy_two_tier_within_soft_limit_passes(
    mock_context: EvaluationContext,
):
    """(a) Amount within the soft limit -> PASS / NONE."""
    policy = mock_context.active_policies[0]
    policy.limit_amount = Decimal("250.0000")
    policy.hard_limit_amount = Decimal("2000.0000")

    rule = PolicyLimitRule()
    action = ProposedFinancialAction(
        user_id=mock_context.user.id,
        merchant_id=mock_context.merchant.id,
        mandate_id=mock_context.mandate.id,
        amount=Decimal("150.0000"),
        currency="INR",
    )

    res = await rule.evaluate(action, mock_context)
    assert res.status == RuleStatus.PASS
    assert res.decision_effect == RuleDecisionEffect.NONE
    assert res.reason_code == "POLICY_LIMITS_SATISFIED"


@pytest.mark.asyncio
async def test_policy_two_tier_above_soft_limit_with_consistent_merchant_history_asks_user(
    mock_context: EvaluationContext,
):
    """(b) Amount above soft limit but consistent with merchant history -> ASK_USER."""
    policy = mock_context.active_policies[0]
    policy.limit_amount = Decimal("250.0000")
    policy.hard_limit_amount = Decimal("2000.0000")

    # Add historical merchant transactions establishing a ₹300 baseline
    now = datetime.now(UTC)
    mock_context.merchant_historical_transactions = [
        Transaction(
            id=uuid.uuid4(),
            user_id=mock_context.user.id,
            merchant_id=mock_context.merchant.id,
            amount=Decimal("300.0000"),
            currency="INR",
            transaction_type=TransactionType.PURCHASE,
            status=TransactionStatus.CAPTURED,
            occurred_at=now - timedelta(days=10),
        ),
        Transaction(
            id=uuid.uuid4(),
            user_id=mock_context.user.id,
            merchant_id=mock_context.merchant.id,
            amount=Decimal("300.0000"),
            currency="INR",
            transaction_type=TransactionType.PURCHASE,
            status=TransactionStatus.CAPTURED,
            occurred_at=now - timedelta(days=5),
        ),
    ]

    rule = PolicyLimitRule()
    action = ProposedFinancialAction(
        user_id=mock_context.user.id,
        merchant_id=mock_context.merchant.id,
        mandate_id=mock_context.mandate.id,
        amount=Decimal("300.0000"),
        currency="INR",
    )

    res = await rule.evaluate(action, mock_context)
    assert res.status == RuleStatus.FAIL
    assert res.decision_effect == RuleDecisionEffect.ASK_USER
    assert res.reason_code == "POLICY_SOFT_LIMIT_EXCEEDED"


@pytest.mark.asyncio
async def test_policy_two_tier_above_hard_ceiling_blocks_regardless_of_history(
    mock_context: EvaluationContext,
):
    """(c) Amount above the hard ceiling -> BLOCK unconditionally regardless of history."""
    policy = mock_context.active_policies[0]
    policy.limit_amount = Decimal("250.0000")
    policy.hard_limit_amount = Decimal("2000.0000")

    # Even with established high baseline history (₹2500)
    now = datetime.now(UTC)
    mock_context.merchant_historical_transactions = [
        Transaction(
            id=uuid.uuid4(),
            user_id=mock_context.user.id,
            merchant_id=mock_context.merchant.id,
            amount=Decimal("2500.0000"),
            currency="INR",
            transaction_type=TransactionType.PURCHASE,
            status=TransactionStatus.CAPTURED,
            occurred_at=now - timedelta(days=5),
        ),
    ]

    rule = PolicyLimitRule()
    action = ProposedFinancialAction(
        user_id=mock_context.user.id,
        merchant_id=mock_context.merchant.id,
        mandate_id=mock_context.mandate.id,
        amount=Decimal("2500.0000"),
        currency="INR",
    )

    res = await rule.evaluate(action, mock_context)
    assert res.status == RuleStatus.FAIL
    assert res.decision_effect == RuleDecisionEffect.BLOCK
    assert res.reason_code == "POLICY_HARD_LIMIT_EXCEEDED"


@pytest.mark.asyncio
async def test_policy_two_tier_above_soft_limit_with_no_history_blocks(
    mock_context: EvaluationContext,
):
    """(d) Amount above soft limit with no merchant history at all -> BLOCK (fail-closed)."""
    policy = mock_context.active_policies[0]
    policy.limit_amount = Decimal("250.0000")
    policy.hard_limit_amount = Decimal("2000.0000")
    mock_context.merchant_historical_transactions = []
    mock_context.memory_context = []

    rule = PolicyLimitRule()
    action = ProposedFinancialAction(
        user_id=mock_context.user.id,
        merchant_id=mock_context.merchant.id,
        mandate_id=mock_context.mandate.id,
        amount=Decimal("350.0000"),
        currency="INR",
    )

    res = await rule.evaluate(action, mock_context)
    assert res.status == RuleStatus.FAIL
    assert res.decision_effect == RuleDecisionEffect.BLOCK
    assert res.reason_code == "POLICY_LIMIT_EXCEEDED"
