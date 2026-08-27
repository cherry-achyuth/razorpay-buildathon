"""Unit tests for CanonicalFinancialEvent representation."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from app.models.enums import (
    MemorySourceType,
    TransactionStatus,
    TransactionType,
)
from app.models.transaction import Transaction
from app.services.memory.canonical_event import CanonicalFinancialEvent


def test_canonical_event_from_transaction():
    """Verify CanonicalFinancialEvent properly normalizes transaction fields."""
    tx_id = uuid.uuid4()
    user_id = uuid.uuid4()
    merch_id = uuid.uuid4()
    mandate_id = uuid.uuid4()
    now = datetime.now(UTC)
    exact_amount = Decimal("249.9900")

    tx = Transaction(
        id=tx_id,
        user_id=user_id,
        merchant_id=merch_id,
        mandate_id=mandate_id,
        amount=exact_amount,
        currency="INR",
        transaction_type=TransactionType.PURCHASE,
        status=TransactionStatus.CAPTURED,
        idempotency_key="canon_tx_001",
        occurred_at=now,
    )

    event = CanonicalFinancialEvent.from_transaction(
        transaction=tx,
        merchant_name="AWS Cloud Services",
        metadata={"category": "software_subscription"},
    )

    assert event.source_type == MemorySourceType.TRANSACTION
    assert event.source_id == tx_id
    assert event.user_id == user_id
    assert event.merchant_id == merch_id
    assert event.mandate_id == mandate_id
    assert event.amount == exact_amount
    assert isinstance(event.amount, Decimal)
    assert event.currency == "INR"
    assert event.transaction_type == TransactionType.PURCHASE
    assert event.status == TransactionStatus.CAPTURED
    assert event.occurred_at == now
    assert event.merchant_name == "AWS Cloud Services"
    assert event.metadata == {"category": "software_subscription"}
