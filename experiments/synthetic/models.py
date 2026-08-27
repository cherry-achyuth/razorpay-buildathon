"""Synthetic financial dataset domain models and schemas for DecisionVault experiments."""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any


class EventPosition(StrEnum):
    """Position of injected critical events within history."""

    EARLY = "EARLY"
    MIDDLE = "MIDDLE"
    LATE = "LATE"
    MIXED = "MIXED"


class DatasetScale(StrEnum):
    """Preset dataset scales for experiment configurations."""

    SMALL = "SMALL"  # e.g. 2 users, 20 txs/user
    MEDIUM = "MEDIUM"  # e.g. 5 users, 50 txs/user
    LARGE = "LARGE"  # e.g. 10 users, 100 txs/user
    CUSTOM = "CUSTOM"


class SyntheticScenarioType(StrEnum):
    """Classification of synthetic financial scenario templates."""

    ROUTINE_PURCHASE = "ROUTINE_PURCHASE"
    RECURRING_SUBSCRIPTION = "RECURRING_SUBSCRIPTION"
    PRICE_DRIFT = "PRICE_DRIFT"
    MERCHANT_CHANGE = "MERCHANT_CHANGE"
    FAILED_TRANSACTION = "FAILED_TRANSACTION"
    DUPLICATE_LIKE = "DUPLICATE_LIKE"
    POLICY_BOUNDARY = "POLICY_BOUNDARY"
    MIXED_HISTORY = "MIXED_HISTORY"


@dataclass
class SyntheticUserRecord:
    """Synthetic user principal."""

    id: uuid.UUID
    external_reference: str
    status: str = "ACTIVE"


@dataclass
class SyntheticMerchantRecord:
    """Synthetic merchant counterparty."""

    id: uuid.UUID
    name: str
    external_reference: str
    category: str = "general"
    status: str = "ACTIVE"


@dataclass
class SyntheticPolicyRecord:
    """Synthetic financial policy constraint."""

    id: uuid.UUID
    user_id: uuid.UUID
    name: str
    policy_type: str = "TRANSACTION_LIMIT"
    status: str = "ACTIVE"
    currency: str = "USD"
    limit_amount: Decimal = Decimal("50.0000")
    rules: dict[str, Any] = field(default_factory=dict)


@dataclass
class SyntheticMandateRecord:
    """Synthetic authorization mandate."""

    id: uuid.UUID
    user_id: uuid.UUID
    merchant_id: uuid.UUID
    status: str = "ACTIVE"
    currency: str = "USD"
    max_transaction_amount: Decimal = Decimal("50.0000")
    valid_from: datetime = field(
        default_factory=lambda: datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
    )
    valid_until: datetime | None = None


@dataclass
class SyntheticTransactionRecord:
    """Synthetic financial transaction with explicit ground-truth labeling."""

    id: uuid.UUID
    user_id: uuid.UUID
    merchant_id: uuid.UUID
    amount: Decimal
    currency: str = "USD"
    mandate_id: uuid.UUID | None = None
    transaction_type: str = "PURCHASE"
    status: str = "CAPTURED"
    external_reference: str | None = None
    idempotency_key: str | None = None
    occurred_at: datetime = field(
        default_factory=lambda: datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
    )
    is_decision_critical: bool = False
    is_compression_candidate: bool = True
    scenario_tag: str = "ROUTINE"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SyntheticScenarioMetadata:
    """Ground-truth metadata describing a generated scenario instance."""

    scenario_id: str
    scenario_type: SyntheticScenarioType
    user_id: uuid.UUID
    critical_transaction_ids: list[uuid.UUID] = field(default_factory=list)
    routine_transaction_ids: list[uuid.UUID] = field(default_factory=list)
    description: str = ""
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass
class DatasetManifest:
    """Manifest describing a synthetic dataset's generation parameters and summary statistics."""

    dataset_id: str
    generator_version: str = "1.0.0"
    seed: int = 42
    scale: str = "SMALL"
    user_count: int = 0
    merchant_count: int = 0
    transaction_count: int = 0
    critical_event_count: int = 0
    routine_event_count: int = 0
    scenario_counts: dict[str, int] = field(default_factory=dict)
    config_summary: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class SyntheticDataset:
    """Complete container for a generated synthetic financial dataset."""

    manifest: DatasetManifest
    users: list[SyntheticUserRecord] = field(default_factory=list)
    merchants: list[SyntheticMerchantRecord] = field(default_factory=list)
    policies: list[SyntheticPolicyRecord] = field(default_factory=list)
    mandates: list[SyntheticMandateRecord] = field(default_factory=list)
    transactions: list[SyntheticTransactionRecord] = field(default_factory=list)
    scenarios: list[SyntheticScenarioMetadata] = field(default_factory=list)


@dataclass
class DatasetConfig:
    """Configuration controlling deterministic synthetic dataset generation."""

    seed: int = 42
    scale: DatasetScale = DatasetScale.SMALL
    num_users: int = 2
    transactions_per_user: int = 20
    scenario_mix: list[SyntheticScenarioType] | None = None
    base_timestamp: datetime = field(
        default_factory=lambda: datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)
    )
    default_currency: str = "USD"
    critical_event_position: EventPosition = EventPosition.LATE
    policy_limit_amount: Decimal = Decimal("50.0000")
    routine_amount: Decimal = Decimal("25.0000")
