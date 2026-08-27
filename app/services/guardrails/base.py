"""Base contracts and data structures for deterministic guardrail rules."""

import hashlib
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from app.models.enums import (
    MemoryRelevance,
    MemoryStatus,
    MemoryType,
    RuleDecisionEffect,
    RuleSeverity,
    RuleStatus,
    TransactionType,
)
from app.models.idempotency import IdempotencyRecord
from app.models.mandate import Mandate
from app.models.merchant import Merchant
from app.models.policy import Policy
from app.models.transaction import Transaction
from app.models.user import User

if TYPE_CHECKING:
    from app.models.memory import DecisionMemory


@dataclass(frozen=True)
class ProposedFinancialAction:
    """Represents a proposed financial action before authorization or execution."""

    user_id: uuid.UUID
    merchant_id: uuid.UUID
    amount: Decimal
    currency: str
    mandate_id: uuid.UUID | None = None
    transaction_type: TransactionType = TransactionType.PURCHASE
    request_id: uuid.UUID = field(default_factory=uuid.uuid4)
    idempotency_key: str | None = None
    requested_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = field(default_factory=dict)

    def canonical_fingerprint(self) -> str:
        """Computes a deterministic SHA-256 digest of core financial parameters."""
        raw_repr = (
            f"{self.user_id}:"
            f"{self.merchant_id}:"
            f"{self.mandate_id or 'none'}:"
            f"{self.amount:.4f}:"
            f"{self.currency.upper()}:"
            f"{self.transaction_type.value}"
        )
        return hashlib.sha256(raw_repr.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class RuleResult:
    """Structured, tamper-evident evidence emitted by a rule evaluation."""

    rule_id: str
    status: RuleStatus
    decision_effect: RuleDecisionEffect
    reason_code: str
    message: str
    evidence: dict[str, Any] = field(default_factory=dict)
    severity: RuleSeverity = RuleSeverity.INFO


@dataclass(frozen=True)
class MemorySourceReference:
    """Provenance link to an authoritative source financial entity."""

    source_type: str
    source_id: uuid.UUID
    id: uuid.UUID | None = None
    memory_id: uuid.UUID | None = None
    created_at: datetime | None = None


@dataclass(frozen=True)
class DecisionMemoryContext:
    """Clean internal representation of active decision memory context.

    Provides historical, explainable financial context to the evaluation process
    without exposing raw database internals or granting authorization authority.
    """

    memory_id: uuid.UUID
    memory_type: MemoryType
    relevance: MemoryRelevance
    status: MemoryStatus
    summary: str
    structured_data: dict[str, Any] = field(default_factory=dict)
    sources: list[MemorySourceReference] = field(default_factory=list)
    version: int = 1
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    created_at: datetime | None = None

    @classmethod
    def from_model(cls, memory: "DecisionMemory") -> "DecisionMemoryContext":
        """Convert a database DecisionMemory entity into a DecisionMemoryContext."""
        sources = [
            MemorySourceReference(
                id=s.id,
                memory_id=s.memory_id,
                source_type=(
                    s.source_type.value
                    if hasattr(s.source_type, "value")
                    else str(s.source_type)
                ),
                source_id=s.source_id,
                created_at=s.created_at,
            )
            for s in getattr(memory, "sources", [])
        ]
        return cls(
            memory_id=memory.id,
            memory_type=memory.memory_type,
            relevance=memory.relevance,
            status=memory.status,
            summary=memory.summary,
            structured_data=dict(memory.structured_data or {}),
            sources=sources,
            version=memory.version,
            valid_from=memory.valid_from,
            valid_until=memory.valid_until,
            created_at=memory.created_at,
        )


@dataclass
class EvaluationContext:
    """Authoritative relational context loaded from PostgreSQL for evaluation."""

    user: User
    merchant: Merchant
    mandate: Mandate | None = None
    active_policies: list[Policy] = field(default_factory=list)
    recent_window_transactions: list[Transaction] = field(default_factory=list)
    merchant_historical_transactions: list[Transaction] = field(default_factory=list)
    user_historical_merchant_ids: set[uuid.UUID] = field(default_factory=set)
    user_total_historical_tx_count: int = 0
    existing_idempotency_record: IdempotencyRecord | None = None
    duplicate_window_seconds: int = 300
    price_drift_threshold_percent: Decimal = Decimal("25.0")
    price_drift_min_samples: int = 3
    memory_context: list[DecisionMemoryContext] = field(default_factory=list)


class FinancialRule(ABC):
    """Abstract interface for all deterministic financial safety rules."""

    @property
    @abstractmethod
    def rule_id(self) -> str:
        """Unique identifier for the rule."""
        pass

    @abstractmethod
    async def evaluate(
        self, action: ProposedFinancialAction, context: EvaluationContext
    ) -> RuleResult:
        """Evaluates proposed action against authoritative financial context."""
        pass
