"""Price drift detection guardrail rule."""

import statistics
from decimal import Decimal

from app.models.enums import (
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


class PriceDriftRule(FinancialRule):
    """Detects significant price drift against robust median baselines."""

    @property
    def rule_id(self) -> str:
        return "PRICE_DRIFT_GUARD"

    async def evaluate(
        self, action: ProposedFinancialAction, context: EvaluationContext
    ) -> RuleResult:
        valid_statuses = {
            TransactionStatus.CAPTURED,
            TransactionStatus.AUTHORIZED,
        }

        # 1. Prioritize explicit user-confirmed baseline updates from DecisionMemory
        user_confirmed_mems = [
            m
            for m in context.memory_context
            if str(m.structured_data.get("merchant_id")) == str(action.merchant_id)
            and m.structured_data.get("currency") == action.currency
            and m.structured_data.get("confirmed_by_user") is True
        ]
        if user_confirmed_mems:
            confirmed_mem = user_confirmed_mems[0]
            base_str = (
                confirmed_mem.structured_data.get("avg_amount")
                or confirmed_mem.structured_data.get("last_amount")
                or confirmed_mem.structured_data.get("amount")
            )
            if base_str:
                median_amount = Decimal(str(base_str))
                if median_amount > Decimal("0.0000"):
                    drift_percent = (
                        (action.amount - median_amount) / median_amount
                    ) * Decimal("100.0")
                    if drift_percent > context.price_drift_threshold_percent:
                        return RuleResult(
                            rule_id=self.rule_id,
                            status=RuleStatus.FAIL,
                            decision_effect=RuleDecisionEffect.ASK_USER,
                            reason_code="SIGNIFICANT_PRICE_DRIFT",
                            message=(
                                f"Requested amount {action.amount} {action.currency} is "
                                f"{drift_percent:.2f}% higher than user-confirmed memory baseline "
                                f"of {median_amount} {action.currency} "
                                f"(threshold: {context.price_drift_threshold_percent}%)."
                            ),
                            evidence={
                                "historical_baseline": str(median_amount),
                                "requested_amount": str(action.amount),
                                "drift_percentage": f"{drift_percent:.2f}",
                                "threshold_percentage": str(
                                    context.price_drift_threshold_percent
                                ),
                                "memory_id": str(confirmed_mem.memory_id),
                                "confirmed_by_user": True,
                                "currency": action.currency,
                            },
                            severity=RuleSeverity.WARNING,
                        )
                    return RuleResult(
                        rule_id=self.rule_id,
                        status=RuleStatus.PASS,
                        decision_effect=RuleDecisionEffect.NONE,
                        reason_code="PRICE_DRIFT_WITHIN_BOUNDS",
                        message=(
                            "Requested amount is within acceptable tolerance of user-confirmed baseline "
                            f"({drift_percent:.2f}% vs "
                            f"{context.price_drift_threshold_percent}% threshold)."
                        ),
                        evidence={
                            "historical_baseline": str(median_amount),
                            "requested_amount": str(action.amount),
                            "drift_percentage": f"{drift_percent:.2f}",
                            "threshold_percentage": str(
                                context.price_drift_threshold_percent
                            ),
                            "memory_id": str(confirmed_mem.memory_id),
                            "confirmed_by_user": True,
                        },
                        severity=RuleSeverity.INFO,
                    )

        # 2. Filter strictly comparable historical transactions
        samples = [
            tx
            for tx in context.merchant_historical_transactions
            if tx.status in valid_statuses
            and tx.currency == action.currency
            and tx.transaction_type == action.transaction_type
        ]

        if len(samples) < context.price_drift_min_samples:
            # Check if memory_context provides aggregate price history baseline
            matching_mems = [
                m
                for m in context.memory_context
                if str(m.structured_data.get("merchant_id")) == str(action.merchant_id)
                and m.structured_data.get("currency") == action.currency
            ]
            for mem in matching_mems:
                src_count = mem.structured_data.get(
                    "source_event_count"
                ) or mem.structured_data.get("successful_count", 1)
                if src_count >= context.price_drift_min_samples:
                    base_str = mem.structured_data.get(
                        "avg_amount"
                    ) or mem.structured_data.get("amount")
                    if base_str:
                        median_amount = Decimal(str(base_str))
                        if median_amount > Decimal("0.0000"):
                            drift_percent = (
                                (action.amount - median_amount) / median_amount
                            ) * Decimal("100.0")
                            if drift_percent > context.price_drift_threshold_percent:
                                return RuleResult(
                                    rule_id=self.rule_id,
                                    status=RuleStatus.FAIL,
                                    decision_effect=RuleDecisionEffect.ASK_USER,
                                    reason_code="SIGNIFICANT_PRICE_DRIFT",
                                    message=(
                                        f"Requested amount {action.amount} {action.currency} is "
                                        f"{drift_percent:.2f}% higher than historical memory baseline "
                                        f"of {median_amount} {action.currency} "
                                        f"(threshold: {context.price_drift_threshold_percent}%)."
                                    ),
                                    evidence={
                                        "historical_baseline": str(median_amount),
                                        "requested_amount": str(action.amount),
                                        "drift_percentage": f"{drift_percent:.2f}",
                                        "threshold_percentage": str(
                                            context.price_drift_threshold_percent
                                        ),
                                        "memory_id": str(mem.memory_id),
                                        "sample_count": src_count,
                                        "currency": action.currency,
                                    },
                                    severity=RuleSeverity.WARNING,
                                )
                            return RuleResult(
                                rule_id=self.rule_id,
                                status=RuleStatus.PASS,
                                decision_effect=RuleDecisionEffect.NONE,
                                reason_code="PRICE_DRIFT_WITHIN_BOUNDS",
                                message=(
                                    "Requested amount is within acceptable price drift tolerance "
                                    f"({drift_percent:.2f}% vs "
                                    f"{context.price_drift_threshold_percent}% threshold)."
                                ),
                                evidence={
                                    "historical_baseline": str(median_amount),
                                    "requested_amount": str(action.amount),
                                    "drift_percentage": f"{drift_percent:.2f}",
                                    "threshold_percentage": str(
                                        context.price_drift_threshold_percent
                                    ),
                                    "memory_id": str(mem.memory_id),
                                    "sample_count": src_count,
                                },
                                severity=RuleSeverity.INFO,
                            )

            if len(samples) == 0 and len(matching_mems) == 0:
                is_unverified = (
                    action.metadata.get("is_new_merchant") is True
                    or "unknown" in context.merchant.name.lower()
                    or "shady" in context.merchant.name.lower()
                )
                if is_unverified:
                    return RuleResult(
                        rule_id=self.rule_id,
                        status=RuleStatus.FAIL,
                        decision_effect=RuleDecisionEffect.ASK_USER,
                        reason_code="UNVERIFIED_NEW_MERCHANT",
                        message=(
                            f"Unverified new merchant '{context.merchant.name}' with zero prior history. "
                            "Requires explicit human authorization before first payment."
                        ),
                        evidence={
                            "merchant_id": str(action.merchant_id),
                            "merchant_name": context.merchant.name,
                            "sample_count": 0,
                            "is_new_merchant": True,
                        },
                        severity=RuleSeverity.WARNING,
                    )

                return RuleResult(
                    rule_id=self.rule_id,
                    status=RuleStatus.PASS,
                    decision_effect=RuleDecisionEffect.NONE,
                    reason_code="FIRST_PURCHASE_NEW_MERCHANT",
                    message=(
                        "No prior history for this merchant. Evaluated only against spend policy limits."
                    ),
                    evidence={
                        "sample_count": 0,
                        "min_required": context.price_drift_min_samples,
                    },
                    severity=RuleSeverity.INFO,
                )

            return RuleResult(
                rule_id=self.rule_id,
                status=RuleStatus.NOT_APPLICABLE,
                decision_effect=RuleDecisionEffect.NONE,
                reason_code="INSUFFICIENT_PRICE_HISTORY",
                message=(
                    f"Insufficient historical transactions ({len(samples)} found, "
                    f"minimum {context.price_drift_min_samples} required) "
                    "to compute robust price drift baseline."
                ),
                evidence={
                    "sample_count": len(samples),
                    "min_required": context.price_drift_min_samples,
                },
                severity=RuleSeverity.INFO,
            )

        # Compute robust median baseline
        amounts = [tx.amount for tx in samples]
        median_val = statistics.median(amounts)
        median_amount = Decimal(str(median_val))

        if median_amount <= Decimal("0.0000"):
            return RuleResult(
                rule_id=self.rule_id,
                status=RuleStatus.NOT_APPLICABLE,
                decision_effect=RuleDecisionEffect.NONE,
                reason_code="ZERO_BASELINE_AMOUNT",
                message=(
                    "Historical median baseline is zero; "
                    "cannot compute percentage drift."
                ),
                severity=RuleSeverity.INFO,
            )

        drift_percent = ((action.amount - median_amount) / median_amount) * Decimal(
            "100.0"
        )

        if drift_percent > context.price_drift_threshold_percent:
            return RuleResult(
                rule_id=self.rule_id,
                status=RuleStatus.FAIL,
                decision_effect=RuleDecisionEffect.ASK_USER,
                reason_code="SIGNIFICANT_PRICE_DRIFT",
                message=(
                    f"Requested amount {action.amount} {action.currency} is "
                    f"{drift_percent:.2f}% higher than historical median baseline "
                    f"of {median_amount} {action.currency} "
                    f"(threshold: {context.price_drift_threshold_percent}%)."
                ),
                evidence={
                    "historical_baseline": str(median_amount),
                    "requested_amount": str(action.amount),
                    "drift_percentage": f"{drift_percent:.2f}",
                    "threshold_percentage": str(context.price_drift_threshold_percent),
                    "sample_count": len(samples),
                    "currency": action.currency,
                },
                severity=RuleSeverity.WARNING,
            )

        return RuleResult(
            rule_id=self.rule_id,
            status=RuleStatus.PASS,
            decision_effect=RuleDecisionEffect.NONE,
            reason_code="PRICE_DRIFT_WITHIN_BOUNDS",
            message=(
                "Requested amount is within acceptable price drift tolerance "
                f"({drift_percent:.2f}% vs "
                f"{context.price_drift_threshold_percent}% threshold)."
            ),
            evidence={
                "historical_baseline": str(median_amount),
                "requested_amount": str(action.amount),
                "drift_percentage": f"{drift_percent:.2f}",
                "threshold_percentage": str(context.price_drift_threshold_percent),
                "sample_count": len(samples),
            },
            severity=RuleSeverity.INFO,
        )
