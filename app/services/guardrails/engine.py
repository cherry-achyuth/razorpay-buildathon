"""Deterministic rule engine for aggregating financial safety rules."""

from dataclasses import dataclass

from app.models.enums import DecisionOutcome, RuleDecisionEffect
from app.services.guardrails.base import (
    EvaluationContext,
    FinancialRule,
    ProposedFinancialAction,
    RuleResult,
)
from app.services.guardrails.rules.duplicate_rule import DuplicatePaymentRule
from app.services.guardrails.rules.idempotency_rule import IdempotencyRule
from app.services.guardrails.rules.mandate_rule import MandateConstraintRule
from app.services.guardrails.rules.merchant_change_rule import (
    MerchantChangeRule,
)
from app.services.guardrails.rules.policy_rule import PolicyLimitRule
from app.services.guardrails.rules.price_drift_rule import PriceDriftRule


@dataclass(frozen=True)
class EngineEvaluationResult:
    """Aggregate decision outcome with full rule trace and evidence."""

    decision: DecisionOutcome
    reason_code: str
    reason: str
    rule_results: list[RuleResult]


class DeterministicRuleEngine:
    """Evaluates financial actions against registered deterministic safety rules."""

    def __init__(self, rules: list[FinancialRule] | None = None) -> None:
        self.rules: list[FinancialRule] = rules or [
            MandateConstraintRule(),
            PolicyLimitRule(),
            DuplicatePaymentRule(),
            IdempotencyRule(),
            PriceDriftRule(),
            MerchantChangeRule(),
        ]

    async def evaluate(
        self, action: ProposedFinancialAction, context: EvaluationContext
    ) -> EngineEvaluationResult:
        """Runs all registered rules and applies strict deterministic precedence."""
        results: list[RuleResult] = []

        for rule in self.rules:
            res = await rule.evaluate(action, context)
            results.append(res)

        # 1. Check for BLOCK (Absolute Precedence)
        blocking_results = [
            r for r in results if r.decision_effect == RuleDecisionEffect.BLOCK
        ]
        if blocking_results:
            primary_block = blocking_results[0]
            return EngineEvaluationResult(
                decision=DecisionOutcome.BLOCK,
                reason_code=primary_block.reason_code,
                reason=primary_block.message,
                rule_results=results,
            )

        # 2. Check for ASK_USER
        ask_user_results = [
            r for r in results if r.decision_effect == RuleDecisionEffect.ASK_USER
        ]
        if ask_user_results:
            primary_ask = ask_user_results[0]
            return EngineEvaluationResult(
                decision=DecisionOutcome.ASK_USER,
                reason_code=primary_ask.reason_code,
                reason=primary_ask.message,
                rule_results=results,
            )

        # 3. All rules passed or not applicable -> ALLOW
        return EngineEvaluationResult(
            decision=DecisionOutcome.ALLOW,
            reason_code="DETERMINISTIC_RULES_PASSED",
            reason=(
                "All deterministic financial safety and authorization "
                "constraints satisfied."
            ),
            rule_results=results,
        )
