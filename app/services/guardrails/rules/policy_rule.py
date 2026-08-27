"""Two-tier policy and transaction limit validation rule."""

import statistics
from datetime import UTC, datetime
from decimal import Decimal

from app.models.enums import (
    PolicyStatus,
    PolicyType,
    RuleDecisionEffect,
    RuleSeverity,
    RuleStatus,
    TransactionStatus,
)
from app.services.guardrails.base import (
    EvaluationContext,
    FinancialRule,
    ProposedFinancialAction,
    RuleResult,
)


def _ensure_utc(dt: datetime) -> datetime:
    """Normalizes naive and aware datetimes to UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


class PolicyLimitRule(FinancialRule):
    """Enforces two-tier policy limits: hard absolute ceiling and soft threshold with history-grounded flexibility."""

    @property
    def rule_id(self) -> str:
        return "POLICY_LIMIT_GUARD"

    async def evaluate(
        self, action: ProposedFinancialAction, context: EvaluationContext
    ) -> RuleResult:
        if not context.active_policies:
            return RuleResult(
                rule_id=self.rule_id,
                status=RuleStatus.NOT_APPLICABLE,
                decision_effect=RuleDecisionEffect.NONE,
                reason_code="NO_POLICIES_CONFIGURED",
                message="No active policies configured for user.",
                severity=RuleSeverity.INFO,
            )

        req_time = _ensure_utc(action.requested_at)

        for policy in context.active_policies:
            # 1. Active status check
            if policy.status != PolicyStatus.ACTIVE:
                continue

            # 2. Validity window check
            valid_from = _ensure_utc(policy.valid_from)
            if req_time < valid_from:
                continue
            if policy.valid_until:
                valid_until = _ensure_utc(policy.valid_until)
                if req_time > valid_until:
                    continue

            # 3. Policy type check (Transaction Limit or Single-Action Budget)
            if policy.policy_type not in (
                PolicyType.TRANSACTION_LIMIT,
                PolicyType.BUDGET,
            ):
                continue

            # 4. Currency matching
            if policy.currency and policy.currency != action.currency:
                continue

            limit_curr = policy.currency or action.currency

            # 5. Tier 1: Hard Ceiling Enforcement (Unconditional Hard BLOCK)
            if policy.hard_limit_amount is not None:
                if action.amount > policy.hard_limit_amount:
                    return RuleResult(
                        rule_id=self.rule_id,
                        status=RuleStatus.FAIL,
                        decision_effect=RuleDecisionEffect.BLOCK,
                        reason_code="POLICY_HARD_LIMIT_EXCEEDED",
                        message=(
                            f"Requested amount {action.amount} {action.currency} "
                            f"exceeds policy '{policy.name}' hard ceiling of "
                            f"{policy.hard_limit_amount} {limit_curr}. "
                            "Absolute spend limit exceeded regardless of history."
                        ),
                        evidence={
                            "policy_id": str(policy.id),
                            "policy_name": policy.name,
                            "policy_type": policy.policy_type.value,
                            "requested_amount": str(action.amount),
                            "hard_limit_amount": str(policy.hard_limit_amount),
                            "limit_amount": str(policy.limit_amount)
                            if policy.limit_amount
                            else None,
                            "currency": action.currency,
                        },
                        severity=RuleSeverity.CRITICAL,
                    )

            # 6. Tier 2: Soft Limit Evaluation (Context-Aware Grounding)
            if policy.limit_amount is not None and action.amount > policy.limit_amount:
                valid_statuses = {
                    TransactionStatus.CAPTURED,
                    TransactionStatus.AUTHORIZED,
                }
                merchant_samples = [
                    tx
                    for tx in context.merchant_historical_transactions
                    if tx.status in valid_statuses
                    and tx.currency == action.currency
                    and tx.transaction_type == action.transaction_type
                ]

                median_amount: Decimal | None = None
                if len(merchant_samples) >= 1:
                    amounts = [tx.amount for tx in merchant_samples]
                    median_amount = Decimal(str(statistics.median(amounts)))
                else:
                    matching_mems = [
                        m
                        for m in context.memory_context
                        if str(m.structured_data.get("merchant_id"))
                        == str(action.merchant_id)
                        and m.structured_data.get("currency") == action.currency
                    ]
                    for mem in matching_mems:
                        base_str = (
                            mem.structured_data.get("avg_amount")
                            or mem.structured_data.get("amount")
                            or mem.structured_data.get("last_amount")
                        )
                        if base_str:
                            median_amount = Decimal(str(base_str))
                            break

                is_consistent_with_history = False
                if median_amount is not None and median_amount > Decimal("0.0000"):
                    drift_pct = (
                        (action.amount - median_amount) / median_amount
                    ) * Decimal("100.0")
                    if (
                        drift_pct <= context.price_drift_threshold_percent
                        or action.amount <= median_amount * Decimal("1.25")
                    ):
                        is_consistent_with_history = True

                merchant_label = (
                    context.merchant.name if context.merchant else "merchant"
                )

                if is_consistent_with_history and median_amount is not None:
                    # Downgrade to ASK_USER instead of hard BLOCK
                    return RuleResult(
                        rule_id=self.rule_id,
                        status=RuleStatus.FAIL,
                        decision_effect=RuleDecisionEffect.ASK_USER,
                        reason_code="POLICY_SOFT_LIMIT_EXCEEDED",
                        message=(
                            f"Requested amount {action.amount} {action.currency} "
                            f"exceeds soft policy limit of {policy.limit_amount} {limit_curr}, "
                            f"but is consistent with '{merchant_label}' historical baseline of "
                            f"{median_amount} {action.currency}. Human confirmation required."
                        ),
                        evidence={
                            "policy_id": str(policy.id),
                            "policy_name": policy.name,
                            "policy_type": policy.policy_type.value,
                            "requested_amount": str(action.amount),
                            "soft_limit_amount": str(policy.limit_amount),
                            "historical_baseline": str(median_amount),
                            "merchant_name": merchant_label,
                            "currency": action.currency,
                        },
                        severity=RuleSeverity.WARNING,
                    )
                else:
                    history_note = (
                        f"deviates from historical baseline of {median_amount} {action.currency}"
                        if median_amount is not None
                        else "no established merchant history to justify it"
                    )
                    return RuleResult(
                        rule_id=self.rule_id,
                        status=RuleStatus.FAIL,
                        decision_effect=RuleDecisionEffect.BLOCK,
                        reason_code="POLICY_LIMIT_EXCEEDED",
                        message=(
                            f"Requested amount {action.amount} {action.currency} "
                            f"exceeds policy '{policy.name}' limit of "
                            f"{policy.limit_amount} {limit_curr} ({history_note})."
                        ),
                        evidence={
                            "policy_id": str(policy.id),
                            "policy_name": policy.name,
                            "policy_type": policy.policy_type.value,
                            "requested_amount": str(action.amount),
                            "limit_amount": str(policy.limit_amount),
                            "historical_baseline": str(median_amount)
                            if median_amount
                            else None,
                            "currency": action.currency,
                        },
                        severity=RuleSeverity.CRITICAL,
                    )

        # All policy checks satisfied
        return RuleResult(
            rule_id=self.rule_id,
            status=RuleStatus.PASS,
            decision_effect=RuleDecisionEffect.NONE,
            reason_code="POLICY_LIMITS_SATISFIED",
            message="Proposed action satisfies all policy limit constraints.",
            evidence={
                "evaluated_policies_count": len(context.active_policies),
                "requested_amount": str(action.amount),
                "currency": action.currency,
            },
            severity=RuleSeverity.INFO,
        )
