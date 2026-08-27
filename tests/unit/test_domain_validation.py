"""Unit tests for domain model schemas and financial validation rules."""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.models.enums import (
    MandateStatus,
    PolicyType,
    TransactionStatus,
    TransactionType,
)
from app.schemas.mandate import MandateBase
from app.schemas.policy import PolicyBase
from app.schemas.transaction import TransactionBase


def test_transaction_valid():
    """Verify a valid transaction schema passes validation."""
    tx = TransactionBase(
        user_id=uuid.uuid4(),
        merchant_id=uuid.uuid4(),
        amount=Decimal("150.75"),
        currency="INR",
        transaction_type=TransactionType.PURCHASE,
        status=TransactionStatus.PENDING,
    )
    assert tx.amount == Decimal("150.75")
    assert tx.currency == "INR"


def test_transaction_rejects_negative_amount():
    """Verify transactions reject negative amounts."""
    with pytest.raises(ValidationError) as exc_info:
        TransactionBase(
            user_id=uuid.uuid4(),
            merchant_id=uuid.uuid4(),
            amount=Decimal("-50.00"),
            currency="INR",
        )
    assert "Input should be greater than 0" in str(exc_info.value)


def test_transaction_rejects_zero_amount():
    """Verify transactions reject zero amount."""
    with pytest.raises(ValidationError) as exc_info:
        TransactionBase(
            user_id=uuid.uuid4(),
            merchant_id=uuid.uuid4(),
            amount=Decimal("0.0000"),
            currency="INR",
        )
    assert "Input should be greater than 0" in str(exc_info.value)


def test_transaction_rejects_invalid_currency():
    """Verify transaction rejects non-ISO 3-letter currency codes."""
    with pytest.raises(ValidationError) as exc_info:
        TransactionBase(
            user_id=uuid.uuid4(),
            merchant_id=uuid.uuid4(),
            amount=Decimal("100.00"),
            currency="IN",
        )
    assert "String should have at least 3 characters" in str(exc_info.value)

    with pytest.raises(ValidationError) as exc_info2:
        TransactionBase(
            user_id=uuid.uuid4(),
            merchant_id=uuid.uuid4(),
            amount=Decimal("100.00"),
            currency="12A",
        )
    assert "Currency must be a 3-letter uppercase ISO 4217 code" in str(exc_info2.value)


def test_mandate_rejects_invalid_date_range():
    """Verify mandate rejects valid_until preceding valid_from."""
    now = datetime.now(UTC)
    with pytest.raises(ValidationError) as exc_info:
        MandateBase(
            currency="USD",
            max_transaction_amount=Decimal("500.00"),
            valid_from=now,
            valid_until=now - timedelta(days=1),
            status=MandateStatus.ACTIVE,
        )
    assert "valid_until must be greater than or equal to valid_from" in str(
        exc_info.value
    )


def test_policy_rejects_negative_limit():
    """Verify policies reject negative limit amounts."""
    with pytest.raises(ValidationError) as exc_info:
        PolicyBase(
            name="Test Policy",
            policy_type=PolicyType.BUDGET,
            limit_amount=Decimal("-100.00"),
            currency="USD",
        )
    assert "Input should be greater than or equal to 0" in str(exc_info.value)


def test_policy_rejects_negative_hard_limit():
    """Verify policies reject negative hard ceiling amounts."""
    with pytest.raises(ValidationError) as exc_info:
        PolicyBase(
            name="Test Policy",
            policy_type=PolicyType.BUDGET,
            hard_limit_amount=Decimal("-500.00"),
            currency="USD",
        )
    assert "Input should be greater than or equal to 0" in str(exc_info.value)
