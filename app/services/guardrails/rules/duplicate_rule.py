"""Duplicate payment detection guardrail rule."""

from datetime import UTC, datetime

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


def _ensure_utc(dt: datetime) -> datetime:
    """Normalizes naive and aware datetimes to UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


class DuplicatePaymentRule(FinancialRule):
    """Detects identical financial requests within a short sliding window."""

    @property
    def rule_id(self) -> str:
        return "DUPLICATE_PAYMENT_GUARD"

    async def evaluate(
        self, action: ProposedFinancialAction, context: EvaluationContext
    ) -> RuleResult:
        if not context.recent_window_transactions:
            return RuleResult(
                rule_id=self.rule_id,
                status=RuleStatus.PASS,
                decision_effect=RuleDecisionEffect.NONE,
                reason_code="NO_DUPLICATE_DETECTED",
                message="No recent transactions found in duplicate window.",
                severity=RuleSeverity.INFO,
            )

        valid_statuses = {
            TransactionStatus.CAPTURED,
            TransactionStatus.AUTHORIZED,
            TransactionStatus.PENDING,
        }

        req_time = _ensure_utc(action.requested_at)

        for tx in context.recent_window_transactions:
            # 1. Status eligibility (exclude failed, refunded, cancelled)
            if tx.status not in valid_statuses:
                continue

            # 2. Strict matching on core parameters
            if (
                tx.user_id == action.user_id
                and tx.merchant_id == action.merchant_id
                and tx.amount == action.amount
                and tx.currency == action.currency
                and tx.transaction_type == action.transaction_type
            ):
                tx_time = _ensure_utc(tx.occurred_at)
                time_diff = abs((req_time - tx_time).total_seconds())

                if time_diff <= context.duplicate_window_seconds:
                    return RuleResult(
                        rule_id=self.rule_id,
                        status=RuleStatus.FAIL,
                        decision_effect=RuleDecisionEffect.BLOCK,
                        reason_code="DUPLICATE_PAYMENT_DETECTED",
                        message=(
                            f"Identical financial action of {action.amount} "
                            f"{action.currency} to merchant {action.merchant_id} "
                            f"was already executed {int(time_diff)}s ago "
                            f"(window: {context.duplicate_window_seconds}s)."
                        ),
                        evidence={
                            "matching_transaction_id": str(tx.id),
                            "amount": str(tx.amount),
                            "currency": tx.currency,
                            "merchant_id": str(tx.merchant_id),
                            "time_difference_seconds": int(time_diff),
                            "window_seconds": context.duplicate_window_seconds,
                        },
                        severity=RuleSeverity.CRITICAL,
                    )

        return RuleResult(
            rule_id=self.rule_id,
            status=RuleStatus.PASS,
            decision_effect=RuleDecisionEffect.NONE,
            reason_code="NO_DUPLICATE_DETECTED",
            message="No duplicate payment detected within configured window.",
            evidence={"window_seconds": context.duplicate_window_seconds},
            severity=RuleSeverity.INFO,
        )
