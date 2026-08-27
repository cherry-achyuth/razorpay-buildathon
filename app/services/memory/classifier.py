"""Deterministic Decision-Relevance Classification Engine."""

from typing import Any

from app.models.enums import (
    MemoryRelevance,
    MemoryType,
    TransactionStatus,
    TransactionType,
)
from app.services.memory.canonical_event import CanonicalFinancialEvent


class DecisionRelevanceClassifier:
    """Deterministic classifier evaluating decision-relevance of financial events.

    Operates without probabilistic LLM reasoning. Evaluates explicit financial signals
    to classify importance, memory type, and structured context.

    Safety Override Invariant:
    A safety-critical event (mandate revocation, chargeback, unauthorized attempt)
    must NEVER be downgraded to LOW merely due to elapsed time if it remains
    authoritatively relevant to future authorizations.
    """

    @classmethod
    def classify(
        cls,
        event: CanonicalFinancialEvent,
        historical_context: dict[str, Any] | None = None,
    ) -> tuple[MemoryType, MemoryRelevance, str, dict[str, Any]]:
        """Classify a CanonicalFinancialEvent into type, relevance, summary, and data.

        Returns:
            (memory_type, relevance, summary, structured_data)
        """
        merchant_label = event.merchant_name or str(event.merchant_id)
        ctx = historical_context or {}

        # 1. Critical Events (Mandate revocations, hard blocks, policy suspensions)
        if (
            event.metadata.get("mandate_revoked")
            or event.metadata.get("mandate_violation")
            or event.metadata.get("hard_block")
            or ctx.get("is_mandate_revocation")
        ):
            summary = (
                f"Critical authorization constraint for merchant '{merchant_label}': "
                f"event status {event.status}."
            )
            structured_data = {
                "amount": str(event.amount),
                "currency": event.currency,
                "merchant_id": str(event.merchant_id),
                "merchant_name": event.merchant_name,
                "event_type": "MANDATE_CONSTRAINT_EVENT",
                "transaction_status": str(event.status),
                "is_critical": True,
            }
            return (
                MemoryType.MANDATE_EVENT,
                MemoryRelevance.CRITICAL,
                summary,
                structured_data,
            )

        # 2. High Relevance: Disputed / Failed / Chargeback / Anomaly Events
        is_failed = event.status in (
            TransactionStatus.FAILED,
            TransactionStatus.CANCELLED,
            TransactionStatus.REFUNDED,
            "FAILED",
            "CANCELLED",
            "REFUNDED",
        )
        is_chargeback = (
            event.transaction_type == TransactionType.CHARGEBACK
            or str(event.transaction_type) == "CHARGEBACK"
        )

        if is_failed or is_chargeback or event.metadata.get("anomaly"):
            reason = "CHARGEBACK" if is_chargeback else f"STATUS_{event.status}"
            summary = (
                f"Anomalous transaction event with merchant '{merchant_label}' of "
                f"{event.amount:.2f} {event.currency} ({reason})."
            )
            structured_data = {
                "amount": str(event.amount),
                "currency": event.currency,
                "merchant_id": str(event.merchant_id),
                "merchant_name": event.merchant_name,
                "transaction_type": str(event.transaction_type),
                "transaction_status": str(event.status),
                "anomaly_flag": True,
            }
            return (
                MemoryType.ANOMALY_EVENT,
                MemoryRelevance.HIGH,
                summary,
                structured_data,
            )

        # 3. High Relevance: Price Drift or Pattern Shifts
        if event.metadata.get("price_drift_detected") or ctx.get("is_price_drift"):
            baseline = ctx.get("baseline_amount") or event.metadata.get("baseline")
            summary = (
                f"Significant price drift detected for merchant '{merchant_label}': "
                f"requested {event.amount:.2f} {event.currency}"
                + (f" (baseline: {baseline} {event.currency})" if baseline else ".")
            )
            structured_data = {
                "amount": str(event.amount),
                "currency": event.currency,
                "merchant_id": str(event.merchant_id),
                "merchant_name": event.merchant_name,
                "baseline_amount": str(baseline) if baseline else None,
                "pattern_flag": "PRICE_DRIFT",
            }
            return (
                MemoryType.PRICE_PATTERN,
                MemoryRelevance.HIGH,
                summary,
                structured_data,
            )

        # 4. Low Relevance: Repeated Routine Transactions
        if event.metadata.get("is_routine_repeat") or ctx.get("is_routine_repeat"):
            summary = (
                f"Repeated routine purchase of {event.amount:.2f} {event.currency} "
                f"with merchant '{merchant_label}'."
            )
            structured_data = {
                "amount": str(event.amount),
                "currency": event.currency,
                "merchant_id": str(event.merchant_id),
                "merchant_name": event.merchant_name,
                "transaction_type": str(event.transaction_type),
                "transaction_status": str(event.status),
                "routine_repeat": True,
            }
            return (
                MemoryType.ROUTINE_PATTERN,
                MemoryRelevance.LOW,
                summary,
                structured_data,
            )

        # 5. Normal Relevance: Standard Routine Transaction
        summary = (
            f"Standard purchase of {event.amount:.2f} {event.currency} "
            f"with merchant '{merchant_label}'."
        )
        structured_data = {
            "amount": str(event.amount),
            "currency": event.currency,
            "merchant_id": str(event.merchant_id),
            "merchant_name": event.merchant_name,
            "transaction_type": str(event.transaction_type),
            "transaction_status": str(event.status),
        }
        return (
            MemoryType.ROUTINE_PATTERN,
            MemoryRelevance.NORMAL,
            summary,
            structured_data,
        )
