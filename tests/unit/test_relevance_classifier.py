"""Unit tests for deterministic DecisionRelevanceClassifier."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from app.models.enums import (
    MemoryRelevance,
    MemorySourceType,
    MemoryType,
    TransactionStatus,
    TransactionType,
)
from app.services.memory.canonical_event import CanonicalFinancialEvent
from app.services.memory.classifier import DecisionRelevanceClassifier


def _make_event(
    amount: str = "100.00",
    status: TransactionStatus | str = TransactionStatus.CAPTURED,
    tx_type: TransactionType = TransactionType.PURCHASE,
    metadata: dict | None = None,
    occurred_at: datetime | None = None,
) -> CanonicalFinancialEvent:
    return CanonicalFinancialEvent(
        event_id=uuid.uuid4(),
        source_type=MemorySourceType.TRANSACTION,
        source_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        merchant_id=uuid.uuid4(),
        mandate_id=None,
        amount=Decimal(amount),
        currency="INR",
        transaction_type=tx_type,
        status=status,
        occurred_at=occurred_at or datetime.now(UTC),
        merchant_name="Acme Supermarket",
        metadata=metadata or {},
    )


def test_standard_routine_purchase_classification():
    """Verify standard captured purchase is classified as NORMAL ROUTINE_PATTERN."""
    event = _make_event(amount="150.00")
    mem_type, rel, summary, data = DecisionRelevanceClassifier.classify(event)

    assert mem_type == MemoryType.ROUTINE_PATTERN
    assert rel == MemoryRelevance.NORMAL
    assert "Acme Supermarket" in summary
    assert data["amount"] == "150.00"
    assert data["currency"] == "INR"


def test_repeated_routine_purchase_classification():
    """Verify routine repeat with stable amount is classified as LOW."""
    event = _make_event(
        amount="50.00",
        metadata={"is_routine_repeat": True},
    )
    mem_type, rel, summary, data = DecisionRelevanceClassifier.classify(event)

    assert mem_type == MemoryType.ROUTINE_PATTERN
    assert rel == MemoryRelevance.LOW
    assert "Repeated routine purchase" in summary
    assert data["routine_repeat"] is True


def test_failed_transaction_anomaly_classification():
    """Verify failed/declined transactions are classified as HIGH ANOMALY_EVENT."""
    event = _make_event(
        amount="850.00",
        status=TransactionStatus.FAILED,
    )
    mem_type, rel, summary, data = DecisionRelevanceClassifier.classify(event)

    assert mem_type == MemoryType.ANOMALY_EVENT
    assert rel == MemoryRelevance.HIGH
    assert "Anomalous transaction event" in summary
    assert data["anomaly_flag"] is True


def test_chargeback_anomaly_classification():
    """Verify chargeback events are classified as HIGH ANOMALY_EVENT."""
    event = _make_event(
        amount="2500.00",
        tx_type=TransactionType.CHARGEBACK,
    )
    mem_type, rel, summary, data = DecisionRelevanceClassifier.classify(event)

    assert mem_type == MemoryType.ANOMALY_EVENT
    assert rel == MemoryRelevance.HIGH
    assert "CHARGEBACK" in summary


def test_price_drift_classification():
    """Verify price drift anomalies are classified as HIGH PRICE_PATTERN."""
    event = _make_event(
        amount="350.00",
        metadata={"price_drift_detected": True, "baseline": "200.00"},
    )
    mem_type, rel, summary, data = DecisionRelevanceClassifier.classify(event)

    assert mem_type == MemoryType.PRICE_PATTERN
    assert rel == MemoryRelevance.HIGH
    assert "price drift detected" in summary.lower()
    assert data["baseline_amount"] == "200.00"
    assert data["pattern_flag"] == "PRICE_DRIFT"


def test_mandate_revocation_safety_override():
    """Verify mandate revocation events are strictly classified as CRITICAL."""
    event = _make_event(
        amount="0.00",
        metadata={"mandate_revoked": True, "hard_block": True},
        occurred_at=datetime(2025, 1, 1, tzinfo=UTC),  # Old historical event
    )
    mem_type, rel, summary, data = DecisionRelevanceClassifier.classify(event)

    assert mem_type == MemoryType.MANDATE_EVENT
    assert rel == MemoryRelevance.CRITICAL
    assert data["is_critical"] is True
    # Safety Override Invariant: Old critical events are never downgraded due to age
    assert rel != MemoryRelevance.LOW
