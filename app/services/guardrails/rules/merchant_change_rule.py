"""Merchant change detection guardrail rule."""

from app.models.enums import (
    RuleDecisionEffect,
    RuleSeverity,
    RuleStatus,
)
from app.services.guardrails.base import (
    EvaluationContext,
    FinancialRule,
    ProposedFinancialAction,
    RuleResult,
)


class MerchantChangeRule(FinancialRule):
    """Detects unexpected shifts to unfamiliar merchants for established users."""

    @property
    def rule_id(self) -> str:
        return "MERCHANT_CHANGE_GUARD"

    async def evaluate(
        self, action: ProposedFinancialAction, context: EvaluationContext
    ) -> RuleResult:
        # Determine effective merchant history and transaction count
        effective_merchant_ids = set(context.user_historical_merchant_ids)
        effective_tx_count = context.user_total_historical_tx_count

        if effective_tx_count == 0 and context.memory_context:
            import uuid as _uuid

            for mc in context.memory_context:
                m_id_str = mc.structured_data.get("merchant_id")
                if m_id_str:
                    try:
                        effective_merchant_ids.add(_uuid.UUID(str(m_id_str)))
                    except (ValueError, TypeError):
                        pass
                effective_tx_count += mc.structured_data.get("source_event_count", 1)

        # 1. Check if user has no prior transaction history
        if effective_tx_count == 0:
            return RuleResult(
                rule_id=self.rule_id,
                status=RuleStatus.NOT_APPLICABLE,
                decision_effect=RuleDecisionEffect.NONE,
                reason_code="NO_PRIOR_TRANSACTION_HISTORY",
                message=(
                    "User has no prior transaction history; "
                    "merchant change check skipped."
                ),
                severity=RuleSeverity.INFO,
            )

        # 2. Check if merchant is already known/familiar to user
        if action.merchant_id in effective_merchant_ids:
            return RuleResult(
                rule_id=self.rule_id,
                status=RuleStatus.PASS,
                decision_effect=RuleDecisionEffect.NONE,
                reason_code="FAMILIAR_MERCHANT",
                message=(
                    f"Merchant '{context.merchant.name}' ({action.merchant_id}) "
                    "is familiar and matches user's historical transactions."
                ),
                evidence={
                    "merchant_id": str(action.merchant_id),
                    "known_merchants_count": len(effective_merchant_ids),
                },
                severity=RuleSeverity.INFO,
            )

        # 3. If history is sparse (< 3 txs), do not classify as unexpected change
        if effective_tx_count < 3:
            return RuleResult(
                rule_id=self.rule_id,
                status=RuleStatus.NOT_APPLICABLE,
                decision_effect=RuleDecisionEffect.NONE,
                reason_code="INSUFFICIENT_MERCHANT_HISTORY",
                message=(
                    "User history is too sparse (< 3 transactions) "
                    "to establish fixed merchant pattern."
                ),
                severity=RuleSeverity.INFO,
            )

        # 4. User has established pattern but unfamiliar merchant
        return RuleResult(
            rule_id=self.rule_id,
            status=RuleStatus.FAIL,
            decision_effect=RuleDecisionEffect.ASK_USER,
            reason_code="UNEXPECTED_MERCHANT_CHANGE",
            message=(
                f"Proposed merchant '{context.merchant.name}' ({action.merchant_id}) "
                "differs from established historical counterparties."
            ),
            evidence={
                "requested_merchant_id": str(action.merchant_id),
                "merchant_name": context.merchant.name,
                "established_merchants_count": len(effective_merchant_ids),
                "total_historical_transactions": effective_tx_count,
            },
            severity=RuleSeverity.WARNING,
        )
