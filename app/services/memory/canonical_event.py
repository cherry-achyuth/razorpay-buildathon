"""Canonical Financial Event representation for the Memory Layer."""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from app.models.enums import (
    MemorySourceType,
    TransactionStatus,
    TransactionType,
)
from app.models.transaction import Transaction


@dataclass(frozen=True)
class CanonicalFinancialEvent:
    """Normalized, internal financial event representation for memory processing.

    Decouples raw relational database schema from downstream memory analysis,
    preserving exact Decimal monetary precision, temporal context, and source
    provenance.
    """

    event_id: uuid.UUID
    source_type: MemorySourceType
    source_id: uuid.UUID
    user_id: uuid.UUID
    merchant_id: uuid.UUID
    mandate_id: uuid.UUID | None
    amount: Decimal
    currency: str
    transaction_type: TransactionType
    status: TransactionStatus | str
    occurred_at: datetime
    merchant_name: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_transaction(
        cls,
        transaction: Transaction,
        merchant_name: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "CanonicalFinancialEvent":
        """Convert a database Transaction entity into a CanonicalFinancialEvent."""
        return cls(
            event_id=uuid.uuid4(),
            source_type=MemorySourceType.TRANSACTION,
            source_id=transaction.id,
            user_id=transaction.user_id,
            merchant_id=transaction.merchant_id,
            mandate_id=transaction.mandate_id,
            amount=transaction.amount,
            currency=transaction.currency,
            transaction_type=transaction.transaction_type,
            status=transaction.status,
            occurred_at=transaction.occurred_at,
            merchant_name=merchant_name,
            metadata=dict(metadata or {}),
        )
