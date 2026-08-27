"""Mandate constraint validation rule."""

from datetime import UTC, datetime

from app.models.enums import MandateStatus
from app.services.guardrails.base import (
    EvaluationContext,
    FinancialRule,
    ProposedFinancialAction,
    RuleDecisionEffect,
    RuleResult,
    RuleSeverity,
    RuleStatus,
)


def _ensure_utc(dt: datetime) -> datetime:
    """Normalizes naive and aware datetimes to UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


class MandateConstraintRule(FinancialRule):
    """Enforces authorization mandate bounds, currency, lifecycle, and caps."""

    @property
    def rule_id(self) -> str:
        return "MANDATE_CONSTRAINT_GUARD"

    async def evaluate(
        self, action: ProposedFinancialAction, context: EvaluationContext
    ) -> RuleResult:
        # If no mandate was specified in the action, rule is not applicable
        if not action.mandate_id:
            return RuleResult(
                rule_id=self.rule_id,
                status=RuleStatus.NOT_APPLICABLE,
                decision_effect=RuleDecisionEffect.NONE,
                reason_code="NO_MANDATE_SPECIFIED",
                message="No mandate constraint specified for this action.",
                severity=RuleSeverity.INFO,
            )

        mandate = context.mandate
        if not mandate:
            return RuleResult(
                rule_id=self.rule_id,
                status=RuleStatus.FAIL,
                decision_effect=RuleDecisionEffect.BLOCK,
                reason_code="MANDATE_NOT_FOUND",
                message=f"Mandate {action.mandate_id} could not be found.",
                evidence={"mandate_id": str(action.mandate_id)},
                severity=RuleSeverity.CRITICAL,
            )

        # 1. User Ownership Check
        if mandate.user_id != action.user_id:
            return RuleResult(
                rule_id=self.rule_id,
                status=RuleStatus.FAIL,
                decision_effect=RuleDecisionEffect.BLOCK,
                reason_code="MANDATE_USER_MISMATCH",
                message=(
                    f"Mandate {mandate.id} does not belong to user {action.user_id}."
                ),
                evidence={
                    "mandate_id": str(mandate.id),
                    "mandate_user_id": str(mandate.user_id),
                    "action_user_id": str(action.user_id),
                },
                severity=RuleSeverity.CRITICAL,
            )

        # 2. Lifecycle Status Check
        if mandate.status != MandateStatus.ACTIVE:
            return RuleResult(
                rule_id=self.rule_id,
                status=RuleStatus.FAIL,
                decision_effect=RuleDecisionEffect.BLOCK,
                reason_code="MANDATE_INACTIVE",
                message=(
                    f"Mandate {mandate.id} is {mandate.status} and cannot "
                    "authorize transactions."
                ),
                evidence={
                    "mandate_id": str(mandate.id),
                    "status": mandate.status.value,
                },
                severity=RuleSeverity.CRITICAL,
            )

        # 3. Validity Window Check
        req_time = _ensure_utc(action.requested_at)
        valid_from = _ensure_utc(mandate.valid_from)

        if req_time < valid_from:
            return RuleResult(
                rule_id=self.rule_id,
                status=RuleStatus.FAIL,
                decision_effect=RuleDecisionEffect.BLOCK,
                reason_code="MANDATE_NOT_YET_VALID",
                message=(
                    f"Mandate {mandate.id} is not valid until {valid_from.isoformat()}."
                ),
                evidence={
                    "mandate_id": str(mandate.id),
                    "valid_from": valid_from.isoformat(),
                    "requested_at": req_time.isoformat(),
                },
                severity=RuleSeverity.CRITICAL,
            )

        if mandate.valid_until:
            valid_until = _ensure_utc(mandate.valid_until)
            if req_time > valid_until:
                return RuleResult(
                    rule_id=self.rule_id,
                    status=RuleStatus.FAIL,
                    decision_effect=RuleDecisionEffect.BLOCK,
                    reason_code="MANDATE_EXPIRED",
                    message=(
                        f"Mandate {mandate.id} expired at {valid_until.isoformat()}."
                    ),
                    evidence={
                        "mandate_id": str(mandate.id),
                        "valid_until": valid_until.isoformat(),
                        "requested_at": req_time.isoformat(),
                    },
                    severity=RuleSeverity.CRITICAL,
                )

        # 4. Currency Compatibility Check
        if mandate.currency != action.currency:
            return RuleResult(
                rule_id=self.rule_id,
                status=RuleStatus.FAIL,
                decision_effect=RuleDecisionEffect.BLOCK,
                reason_code="MANDATE_CURRENCY_MISMATCH",
                message=(
                    f"Mandate currency {mandate.currency} does not match "
                    f"action currency {action.currency}."
                ),
                evidence={
                    "mandate_id": str(mandate.id),
                    "mandate_currency": mandate.currency,
                    "action_currency": action.currency,
                },
                severity=RuleSeverity.CRITICAL,
            )

        # 5. Merchant Restriction Check
        if mandate.merchant_id and mandate.merchant_id != action.merchant_id:
            return RuleResult(
                rule_id=self.rule_id,
                status=RuleStatus.FAIL,
                decision_effect=RuleDecisionEffect.BLOCK,
                reason_code="MANDATE_MERCHANT_MISMATCH",
                message=(
                    f"Mandate {mandate.id} is restricted to merchant "
                    f"{mandate.merchant_id}."
                ),
                evidence={
                    "mandate_id": str(mandate.id),
                    "mandate_merchant_id": str(mandate.merchant_id),
                    "action_merchant_id": str(action.merchant_id),
                },
                severity=RuleSeverity.CRITICAL,
            )

        # 6. Single-Transaction Cap Check
        if action.amount > mandate.max_transaction_amount:
            return RuleResult(
                rule_id=self.rule_id,
                status=RuleStatus.FAIL,
                decision_effect=RuleDecisionEffect.BLOCK,
                reason_code="MANDATE_AMOUNT_EXCEEDED",
                message=(
                    f"Requested amount {action.amount} {action.currency} "
                    f"exceeds mandate maximum cap of "
                    f"{mandate.max_transaction_amount} {mandate.currency}."
                ),
                evidence={
                    "mandate_id": str(mandate.id),
                    "requested_amount": str(action.amount),
                    "mandate_cap": str(mandate.max_transaction_amount),
                    "currency": action.currency,
                },
                severity=RuleSeverity.CRITICAL,
            )

        # All mandate checks satisfied
        return RuleResult(
            rule_id=self.rule_id,
            status=RuleStatus.PASS,
            decision_effect=RuleDecisionEffect.NONE,
            reason_code="MANDATE_CONSTRAINTS_SATISFIED",
            message=(
                f"Proposed action is within mandate {mandate.id} authorization bounds."
            ),
            evidence={
                "mandate_id": str(mandate.id),
                "mandate_cap": str(mandate.max_transaction_amount),
                "requested_amount": str(action.amount),
                "currency": action.currency,
            },
            severity=RuleSeverity.INFO,
        )
