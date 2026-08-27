"""Unit tests for deterministic canonical text representation."""

from decimal import Decimal

from app.models.enums import MemoryType, TransactionType
from app.services.memory.canonical_text import (
    canonical_memory_text,
    canonical_query_text,
)


def test_canonical_memory_text_deterministic():
    """Verify memory text canonicalization produces deterministic, reproducible output."""
    t1 = canonical_memory_text(
        memory_type=MemoryType.ROUTINE_PATTERN,
        summary="Standard purchase of 25.00 USD with merchant 'OpenAI API'.",
        structured_data={
            "merchant_name": "OpenAI API",
            "amount": "25.0000",
            "currency": "USD",
            "transaction_type": "PURCHASE",
        },
    )
    t2 = canonical_memory_text(
        memory_type="ROUTINE_PATTERN",
        summary="  Standard purchase of 25.00 USD with merchant 'OpenAI API'.  ",
        structured_data={
            "transaction_type": TransactionType.PURCHASE,
            "currency": "usd",
            "amount": "25.0000",
            "merchant_name": "OpenAI API",
        },
    )
    assert t1 == t2
    assert "type: ROUTINE_PATTERN" in t1
    assert "summary: Standard purchase of 25.00 USD with merchant 'OpenAI API'." in t1
    assert "merchant: OpenAI API" in t1
    assert "amount: 25.0000" in t1
    assert "currency: USD" in t1


def test_canonical_memory_text_excludes_secrets():
    """Verify internal primary keys and credentials are not formatted into memory text."""
    text = canonical_memory_text(
        memory_type=MemoryType.ANOMALY_EVENT,
        summary="Payment failed due to provider error",
        structured_data={
            "amount": "100.00",
            "currency": "USD",
            "password": "secret_password",
            "api_key": "sk-12345",
            "user_id": "11111111-1111-1111-1111-111111111111",
        },
    )
    assert "secret_password" not in text
    assert "sk-12345" not in text
    assert "11111111-1111-1111-1111-111111111111" not in text
    assert "type: ANOMALY_EVENT" in text


def test_canonical_query_text():
    """Verify query text formatting."""
    q1 = canonical_query_text(
        merchant_name="AWS Cloud",
        amount=Decimal("49.99"),
        currency="USD",
        transaction_type=TransactionType.PURCHASE,
        category="infrastructure",
    )
    assert "query: financial_action" in q1
    assert "merchant: AWS Cloud" in q1
    assert "amount: 49.99" in q1
    assert "currency: USD" in q1
    assert "tx_type: PURCHASE" in q1
    assert "category: infrastructure" in q1
