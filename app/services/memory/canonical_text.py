"""Deterministic canonical text representation for memory embeddings and queries."""

from decimal import Decimal
from typing import Any

from app.models.enums import MemoryType, TransactionType


def canonical_memory_text(
    memory_type: MemoryType | str,
    summary: str,
    structured_data: dict[str, Any] | None = None,
) -> str:
    """Produces a deterministic canonical text representation of a DecisionMemory.

    Formats financial memory attributes into a normalized, reproducible text string
    for vector embedding. Excludes secrets, credentials, internal primary keys,
    and transient runtime identifiers.
    """
    m_type = (
        memory_type.value if isinstance(memory_type, MemoryType) else str(memory_type)
    )
    cleaned_summary = " ".join(summary.strip().split())

    parts = [
        f"type: {m_type}",
        f"summary: {cleaned_summary}",
    ]

    data = structured_data or {}
    if "merchant_name" in data and data["merchant_name"]:
        parts.append(f"merchant: {str(data['merchant_name']).strip()}")
    elif "merchant" in data and data["merchant"]:
        parts.append(f"merchant: {str(data['merchant']).strip()}")

    if "amount" in data and data["amount"] is not None:
        parts.append(f"amount: {data['amount']}")

    if "currency" in data and data["currency"]:
        parts.append(f"currency: {str(data['currency']).strip().upper()}")

    if "transaction_type" in data and data["transaction_type"]:
        tt = data["transaction_type"]
        tt_val = tt.value if isinstance(tt, TransactionType) else str(tt)
        parts.append(f"tx_type: {tt_val}")

    if "category" in data and data["category"]:
        parts.append(f"category: {str(data['category']).strip().lower()}")

    return " | ".join(parts)


def canonical_query_text(
    merchant_name: str | None,
    amount: Decimal | str,
    currency: str,
    transaction_type: TransactionType | str = TransactionType.PURCHASE,
    category: str | None = None,
) -> str:
    """Produces a deterministic canonical text representation for semantic memory queries."""
    tt_val = (
        transaction_type.value
        if isinstance(transaction_type, TransactionType)
        else str(transaction_type)
    )
    amt_val = f"{Decimal(str(amount)):.2f}" if amount is not None else "0.00"
    curr_val = str(currency).strip().upper()

    parts = [
        "query: financial_action",
        f"merchant: {str(merchant_name or 'unknown').strip()}",
        f"amount: {amt_val}",
        f"currency: {curr_val}",
        f"tx_type: {tt_val}",
    ]

    if category:
        parts.append(f"category: {str(category).strip().lower()}")

    return " | ".join(parts)
