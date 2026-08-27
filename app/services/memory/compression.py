"""Deterministic Decision-Preserving Financial Memory Compression Service."""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.models.enums import (
    MemoryRelevance,
    MemorySourceType,
    MemoryStatus,
    MemoryType,
    TransactionStatus,
    TransactionType,
)
from app.models.memory import DecisionMemory, DecisionMemorySource
from app.models.transaction import Transaction
from app.services.memory.canonical_event import CanonicalFinancialEvent
from app.services.memory.canonical_text import canonical_memory_text
from app.services.memory.classifier import DecisionRelevanceClassifier
from app.services.memory.embedding import get_embedding_provider

logger = logging.getLogger(__name__)


@dataclass
class MemoryCompressionResult:
    """Result summary of a deterministic memory compression run."""

    user_id: uuid.UUID
    source_event_count: int
    memories_created: int
    memories_reused: int
    events_compressed: int
    events_preserved: int
    compression_ratio: float
    compression_percentage: float
    status: str = "COMPLETED"
    details: dict[str, int] = field(default_factory=dict)


class MemoryCompressionService:
    """Service for deterministic, decision-preserving financial memory compression.

    Foundational Invariants:
    1. PostgreSQL raw transaction history is the authoritative source of truth and
       is NEVER mutated or deleted during compression.
    2. DecisionMemory is derived state; compression consolidates redundant routine
       patterns into aggregated memories with explicit provenance to all source transactions.
    3. Safety-critical events (CRITICAL/HIGH relevance, failed transactions, chargebacks,
       anomalies) MUST NEVER be absorbed into routine aggregates; they are preserved
       as dedicated individual decision memories.
    4. Monetary arithmetic uses exact Python Decimal without binary float rounding.
    5. Repeated execution against identical history is idempotent.
    """

    @classmethod
    async def compress_user_history(
        cls,
        user_id: uuid.UUID,
        db: AsyncSession,
        lookback_days: int | None = None,
        max_source_events: int | None = None,
        as_of: datetime | None = None,
    ) -> MemoryCompressionResult:
        """Deterministically compress redundant routine transactions for a user.

        Preserves safety-critical events separately and records full source provenance.
        """
        settings = get_settings()
        effective_now = as_of or datetime.now(UTC)
        effective_lookback = (
            lookback_days
            if lookback_days is not None
            else getattr(settings, "MEMORY_COMPRESSION_LOOKBACK_DAYS", 90)
        )
        effective_max = (
            max_source_events
            if max_source_events is not None
            else getattr(settings, "MEMORY_COMPRESSION_MAX_SOURCE_EVENTS", 500)
        )
        cutoff_date = effective_now - timedelta(days=effective_lookback)

        # ----------------------------------------------------------------------
        # 1. Load Bounded Authoritative Source History (Strict Tenant Isolation)
        # ----------------------------------------------------------------------
        stmt = (
            select(Transaction)
            .where(
                Transaction.user_id == user_id,
                Transaction.occurred_at >= cutoff_date,
            )
            .options(selectinload(Transaction.merchant))
            .order_by(Transaction.occurred_at.asc(), Transaction.id.asc())
            .limit(effective_max)
        )
        result = await db.scalars(stmt)
        transactions = list(result.all())

        if not transactions:
            return MemoryCompressionResult(
                user_id=user_id,
                source_event_count=0,
                memories_created=0,
                memories_reused=0,
                events_compressed=0,
                events_preserved=0,
                compression_ratio=1.0,
                compression_percentage=0.0,
                status="COMPLETED",
            )

        # ----------------------------------------------------------------------
        # 2. Canonical Financial Event Conversion & Relevance Classification
        # ----------------------------------------------------------------------
        canonical_events: list[
            tuple[CanonicalFinancialEvent, MemoryType, MemoryRelevance, str, dict]
        ] = []
        for tx in transactions:
            merchant_name = tx.merchant.name if tx.merchant else None
            event = CanonicalFinancialEvent.from_transaction(
                transaction=tx,
                merchant_name=merchant_name,
            )
            mem_type, relevance, summary, structured_data = (
                DecisionRelevanceClassifier.classify(event)
            )
            canonical_events.append(
                (event, mem_type, relevance, summary, structured_data)
            )

        # ----------------------------------------------------------------------
        # 3. Deterministic Compatibility & Safety Partitioning
        # ----------------------------------------------------------------------
        # Events are partitionable into compressible routine groups only if:
        # - Status == CAPTURED (successful)
        # - TransactionType == PURCHASE
        # - Relevance in (NORMAL, LOW)
        # Safety-critical events (CRITICAL, HIGH, FAILED, CHARGEBACK, etc.) are kept separate.
        routine_groups: dict[
            tuple[uuid.UUID, str, str, str],
            list[
                tuple[CanonicalFinancialEvent, MemoryType, MemoryRelevance, str, dict]
            ],
        ] = {}
        safety_preserved: list[
            tuple[CanonicalFinancialEvent, MemoryType, MemoryRelevance, str, dict]
        ] = []

        for item in canonical_events:
            event, mem_type, relevance, summary, structured_data = item
            is_captured = event.status in (TransactionStatus.CAPTURED, "CAPTURED")
            is_purchase = event.transaction_type in (
                TransactionType.PURCHASE,
                "PURCHASE",
            )
            is_routine = relevance in (MemoryRelevance.NORMAL, MemoryRelevance.LOW)

            if is_captured and is_purchase and is_routine:
                group_key = (
                    event.merchant_id,
                    event.currency,
                    str(event.transaction_type),
                    str(event.status),
                )
                routine_groups.setdefault(group_key, []).append(item)
            else:
                safety_preserved.append(item)

        memories_created = 0
        memories_reused = 0
        events_compressed = 0
        events_preserved = 0

        provider = get_embedding_provider()

        # ----------------------------------------------------------------------
        # 4. Process Safety-Preserved Events (Single-Event Dedicated Memories)
        # ----------------------------------------------------------------------
        for event, mem_type, relevance, summary, structured_data in safety_preserved:
            tx_id = event.source_id
            existing_source_stmt = (
                select(DecisionMemory)
                .join(
                    DecisionMemorySource,
                    DecisionMemory.id == DecisionMemorySource.memory_id,
                )
                .where(
                    DecisionMemorySource.source_type == MemorySourceType.TRANSACTION,
                    DecisionMemorySource.source_id == tx_id,
                    DecisionMemory.status == MemoryStatus.ACTIVE,
                )
                .options(selectinload(DecisionMemory.sources))
            )
            existing_mem = await db.scalar(existing_source_stmt)
            if existing_mem:
                memories_reused += 1
            else:
                # Create dedicated safety memory
                canonical_text = canonical_memory_text(
                    memory_type=mem_type,
                    summary=summary,
                    structured_data=structured_data,
                )
                try:
                    vec = await provider.embed(canonical_text)
                except Exception as exc:
                    logger.warning(
                        "Failed to generate embedding for safety memory %s: %s",
                        tx_id,
                        exc,
                    )
                    vec = None

                new_mem = DecisionMemory(
                    id=uuid.uuid4(),
                    user_id=user_id,
                    memory_type=mem_type,
                    relevance=relevance,
                    status=MemoryStatus.ACTIVE,
                    summary=summary,
                    structured_data=structured_data,
                    embedding=vec,
                    version=1,
                    valid_from=event.occurred_at,
                    valid_until=None,
                )
                db.add(new_mem)
                db.add(
                    DecisionMemorySource(
                        id=uuid.uuid4(),
                        memory_id=new_mem.id,
                        source_type=MemorySourceType.TRANSACTION,
                        source_id=tx_id,
                    )
                )
                memories_created += 1
            events_preserved += 1

        # ----------------------------------------------------------------------
        # 5. Process Routine Groups (Compressible vs Singleton)
        # ----------------------------------------------------------------------
        for group_key, items in routine_groups.items():
            merchant_id, currency, tx_type_str, status_str = group_key
            merchant_name = items[0][0].merchant_name or str(merchant_id)

            if len(items) == 1:
                # Singleton group -> Preserve individually
                event, mem_type, relevance, summary, structured_data = items[0]
                tx_id = event.source_id
                existing_source_stmt = (
                    select(DecisionMemory)
                    .join(
                        DecisionMemorySource,
                        DecisionMemory.id == DecisionMemorySource.memory_id,
                    )
                    .where(
                        DecisionMemorySource.source_type
                        == MemorySourceType.TRANSACTION,
                        DecisionMemorySource.source_id == tx_id,
                        DecisionMemory.status == MemoryStatus.ACTIVE,
                    )
                    .options(selectinload(DecisionMemory.sources))
                )
                existing_mem = await db.scalar(existing_source_stmt)
                if existing_mem:
                    memories_reused += 1
                else:
                    canonical_text = canonical_memory_text(
                        memory_type=mem_type,
                        summary=summary,
                        structured_data=structured_data,
                    )
                    try:
                        vec = await provider.embed(canonical_text)
                    except Exception as exc:
                        logger.warning(
                            "Failed to generate embedding for singleton %s: %s",
                            tx_id,
                            exc,
                        )
                        vec = None

                    new_mem = DecisionMemory(
                        id=uuid.uuid4(),
                        user_id=user_id,
                        memory_type=mem_type,
                        relevance=relevance,
                        status=MemoryStatus.ACTIVE,
                        summary=summary,
                        structured_data=structured_data,
                        embedding=vec,
                        version=1,
                        valid_from=event.occurred_at,
                        valid_until=None,
                    )
                    db.add(new_mem)
                    db.add(
                        DecisionMemorySource(
                            id=uuid.uuid4(),
                            memory_id=new_mem.id,
                            source_type=MemorySourceType.TRANSACTION,
                            source_id=tx_id,
                        )
                    )
                    memories_created += 1
                events_preserved += 1
            else:
                # Multi-event group (N >= 2) -> Deterministic Aggregation
                n = len(items)
                tx_ids = [item[0].source_id for item in items]
                amounts = [item[0].amount for item in items]
                dates = [
                    d.replace(tzinfo=UTC) if d.tzinfo is None else d
                    for d in (item[0].occurred_at for item in items)
                ]

                total_amt = sum(amounts, Decimal("0.0000"))
                min_amt = min(amounts)
                max_amt = max(amounts)
                avg_amt = round(total_amt / Decimal(n), 4)
                first_date = min(dates)
                last_date = max(dates)

                agg_structured_data = {
                    "source_event_count": n,
                    "merchant_id": str(merchant_id),
                    "merchant_name": merchant_name,
                    "currency": currency,
                    "transaction_type": tx_type_str,
                    "total_amount": str(total_amt),
                    "min_amount": str(min_amt),
                    "max_amount": str(max_amt),
                    "avg_amount": str(avg_amt),
                    "first_occurred_at": first_date.isoformat(),
                    "last_occurred_at": last_date.isoformat(),
                    "successful_count": n,
                    "failed_count": 0,
                    "is_compressed": True,
                }
                agg_summary = (
                    f"Consolidated routine pattern: {n} purchases totaling "
                    f"{total_amt:.2f} {currency} with merchant '{merchant_name}' "
                    f"({min_amt:.2f} - {max_amt:.2f} {currency})."
                )

                # Check if an active compressed memory already covers all these source txs
                existing_compressed_stmt = (
                    select(DecisionMemory)
                    .join(
                        DecisionMemorySource,
                        DecisionMemory.id == DecisionMemorySource.memory_id,
                    )
                    .where(
                        DecisionMemory.user_id == user_id,
                        DecisionMemory.status == MemoryStatus.ACTIVE,
                        DecisionMemorySource.source_type
                        == MemorySourceType.TRANSACTION,
                        DecisionMemorySource.source_id.in_(tx_ids),
                    )
                    .options(selectinload(DecisionMemory.sources))
                )
                res = await db.scalars(existing_compressed_stmt)
                matching_active_mems = list(res.unique().all())

                # Find if any active memory covers all target source IDs exactly
                perfect_match: DecisionMemory | None = None
                old_singletons: list[DecisionMemory] = []
                for m in matching_active_mems:
                    m_source_ids = {s.source_id for s in m.sources}
                    if m_source_ids == set(tx_ids) and m.structured_data.get(
                        "is_compressed"
                    ):
                        perfect_match = m
                    else:
                        old_singletons.append(m)

                if perfect_match:
                    memories_reused += 1
                else:
                    # Supersede old individual memories to maintain clean active state without deleting history
                    for old_m in old_singletons:
                        old_m.status = MemoryStatus.SUPERSEDED

                    canonical_text = canonical_memory_text(
                        memory_type=MemoryType.ROUTINE_PATTERN,
                        summary=agg_summary,
                        structured_data=agg_structured_data,
                    )
                    try:
                        vec = await provider.embed(canonical_text)
                    except Exception as exc:
                        logger.warning(
                            "Failed to generate embedding for compressed memory: %s",
                            exc,
                        )
                        vec = None

                    new_mem = DecisionMemory(
                        id=uuid.uuid4(),
                        user_id=user_id,
                        memory_type=MemoryType.ROUTINE_PATTERN,
                        relevance=MemoryRelevance.NORMAL,
                        status=MemoryStatus.ACTIVE,
                        summary=agg_summary,
                        structured_data=agg_structured_data,
                        embedding=vec,
                        version=1,
                        valid_from=first_date,
                        valid_until=None,
                    )
                    db.add(new_mem)
                    for tid in tx_ids:
                        db.add(
                            DecisionMemorySource(
                                id=uuid.uuid4(),
                                memory_id=new_mem.id,
                                source_type=MemorySourceType.TRANSACTION,
                                source_id=tid,
                            )
                        )
                    memories_created += 1

                events_compressed += n

        # ----------------------------------------------------------------------
        # 6. Calculate Deterministic Compression Metrics
        # ----------------------------------------------------------------------
        total_source_count = len(transactions)
        total_active_memories = memories_created + memories_reused

        if total_active_memories > 0:
            compression_ratio = round(
                float(total_source_count) / float(total_active_memories), 2
            )
        else:
            compression_ratio = 1.0

        if total_source_count > 0:
            compression_percentage = round(
                (1.0 - (float(total_active_memories) / float(total_source_count)))
                * 100.0,
                2,
            )
        else:
            compression_percentage = 0.0

        # ----------------------------------------------------------------------
        # 7. Append Tamper-Evident Audit Record
        # ----------------------------------------------------------------------
        from app.models.enums import AuditEventType
        from app.services.audit.service import AuditLogService

        await AuditLogService.append_event(
            db=db,
            event_type=AuditEventType.MEMORY_COMPRESSED,
            entity_type="MEMORY_COMPRESSION",
            user_id=user_id,
            event_data={
                "source_event_count": total_source_count,
                "memories_created": memories_created,
                "memories_reused": memories_reused,
                "events_compressed": events_compressed,
                "events_preserved": events_preserved,
                "compression_ratio": compression_ratio,
                "compression_percentage": compression_percentage,
            },
        )

        # Commit all memory actions and audit log in one atomic transaction
        await db.commit()

        return MemoryCompressionResult(
            user_id=user_id,
            source_event_count=total_source_count,
            memories_created=memories_created,
            memories_reused=memories_reused,
            events_compressed=events_compressed,
            events_preserved=events_preserved,
            compression_ratio=compression_ratio,
            compression_percentage=compression_percentage,
            status="COMPLETED",
            details={
                "routine_groups_count": len(routine_groups),
                "safety_preserved_count": len(safety_preserved),
            },
        )
