"""Idempotency protection guardrail rule."""

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


class IdempotencyRule(FinancialRule):
    """Guarantees request idempotency and prevents parameter tampering."""

    @property
    def rule_id(self) -> str:
        return "IDEMPOTENCY_GUARD"

    async def evaluate(
        self, action: ProposedFinancialAction, context: EvaluationContext
    ) -> RuleResult:
        if not action.idempotency_key:
            return RuleResult(
                rule_id=self.rule_id,
                status=RuleStatus.NOT_APPLICABLE,
                decision_effect=RuleDecisionEffect.NONE,
                reason_code="NO_IDEMPOTENCY_KEY_SUPPLIED",
                message="No idempotency key specified for this action.",
                severity=RuleSeverity.INFO,
            )

        existing = context.existing_idempotency_record
        if not existing:
            return RuleResult(
                rule_id=self.rule_id,
                status=RuleStatus.PASS,
                decision_effect=RuleDecisionEffect.NONE,
                reason_code="IDEMPOTENCY_KEY_AVAILABLE",
                message="Idempotency key is fresh and available.",
                evidence={"idempotency_key": action.idempotency_key},
                severity=RuleSeverity.INFO,
            )

        # Key was already registered. Verify canonical fingerprint match.
        current_hash = action.canonical_fingerprint()
        if current_hash == existing.request_hash:
            return RuleResult(
                rule_id=self.rule_id,
                status=RuleStatus.PASS,
                decision_effect=RuleDecisionEffect.NONE,
                reason_code="IDEMPOTENT_RETRY_ACCEPTED",
                message="Idempotent retry with matching canonical payload accepted.",
                evidence={
                    "idempotency_key": action.idempotency_key,
                    "original_record_id": str(existing.id),
                },
                severity=RuleSeverity.INFO,
            )

        # Hash mismatch -> Tampering / Conflict
        return RuleResult(
            rule_id=self.rule_id,
            status=RuleStatus.FAIL,
            decision_effect=RuleDecisionEffect.BLOCK,
            reason_code="IDEMPOTENCY_KEY_CONFLICT",
            message=(
                f"Idempotency key {action.idempotency_key!r} was already "
                "used with different parameters. Modification prohibited."
            ),
            evidence={
                "idempotency_key": action.idempotency_key,
                "conflict_reason": "Payload modified for existing key",
            },
            severity=RuleSeverity.CRITICAL,
        )
