"""Memory Builder Service for deterministic decision memory construction."""

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import AppException, ResourceNotFoundError
from app.models.enums import MemorySourceType, MemoryStatus
from app.models.memory import DecisionMemory, DecisionMemorySource
from app.models.merchant import Merchant
from app.models.transaction import Transaction
from app.services.memory.canonical_event import CanonicalFinancialEvent
from app.services.memory.canonical_text import canonical_memory_text
from app.services.memory.classifier import DecisionRelevanceClassifier
from app.services.memory.embedding import get_embedding_provider

logger = logging.getLogger(__name__)


class MemoryBuilderService:
    """Service for building deterministic decision memories from raw source history.

    Maintains the fundamental invariant:
    Raw transaction history in PostgreSQL is authoritative. Decision memory is
    a derived, rebuildable representation. Building or retiring memory never alters
    or deletes raw source transaction rows.
    """

    @classmethod
    async def build_from_transaction(
        cls,
        transaction_id: uuid.UUID,
        db: AsyncSession,
        requested_user_id: uuid.UUID | None = None,
    ) -> DecisionMemory:
        """Construct or retrieve an idempotent decision memory from a transaction."""
        # 1. Load source transaction
        stmt = (
            select(Transaction)
            .where(Transaction.id == transaction_id)
            .options(selectinload(Transaction.merchant))
        )
        tx = await db.scalar(stmt)
        if not tx:
            raise ResourceNotFoundError(
                f"Transaction with ID '{transaction_id}' was not found."
            )

        # 2. Enforce strict cross-user tenant boundary
        if requested_user_id is not None and tx.user_id != requested_user_id:
            raise AppException(
                message=(
                    "Cannot build memory from a transaction belonging to another user."
                ),
                error_code="CROSS_USER_ACCESS_DENIED",
                status_code=403,
            )

        # 3. Idempotent Deduplication: Check if active memory already exists
        existing_mem_stmt = (
            select(DecisionMemory)
            .join(
                DecisionMemorySource,
                DecisionMemory.id == DecisionMemorySource.memory_id,
            )
            .where(
                DecisionMemorySource.source_type == MemorySourceType.TRANSACTION,
                DecisionMemorySource.source_id == tx.id,
                DecisionMemory.status == MemoryStatus.ACTIVE,
            )
            .options(selectinload(DecisionMemory.sources))
        )
        existing_memory = await db.scalar(existing_mem_stmt)
        if existing_memory:
            return existing_memory

        # 4. Resolve merchant name if loaded
        merchant_name = tx.merchant.name if tx.merchant else None
        if not merchant_name:
            m = await db.scalar(select(Merchant).where(Merchant.id == tx.merchant_id))
            merchant_name = m.name if m else None

        # 5. Convert to Canonical Financial Event
        canonical_event = CanonicalFinancialEvent.from_transaction(
            transaction=tx,
            merchant_name=merchant_name,
        )

        # 6. Deterministic Relevance & Context Classification
        mem_type, relevance, summary, structured_data = (
            DecisionRelevanceClassifier.classify(
                event=canonical_event,
            )
        )

        # 7. Generate Canonical Memory Text & Vector Embedding
        canonical_text = canonical_memory_text(
            memory_type=mem_type,
            summary=summary,
            structured_data=structured_data,
        )
        embedding_vec: list[float] | None = None
        try:
            provider = get_embedding_provider()
            embedding_vec = await provider.embed(canonical_text)
        except Exception as exc:
            logger.warning(
                "Failed to generate embedding for transaction %s: %s",
                tx.id,
                exc,
            )
            embedding_vec = None

        # 8. Create DecisionMemory record
        memory = DecisionMemory(
            id=uuid.uuid4(),
            user_id=tx.user_id,
            memory_type=mem_type,
            relevance=relevance,
            status=MemoryStatus.ACTIVE,
            summary=summary,
            structured_data=structured_data,
            embedding=embedding_vec,
            version=1,
            valid_from=tx.occurred_at or datetime.now(UTC),
            valid_until=None,
        )
        db.add(memory)

        # 9. Create Source Provenance record
        source_link = DecisionMemorySource(
            id=uuid.uuid4(),
            memory_id=memory.id,
            source_type=MemorySourceType.TRANSACTION,
            source_id=tx.id,
        )
        db.add(source_link)

        # 10. Append Tamper-Evident Audit Event
        from app.models.enums import AuditEventType
        from app.services.audit.service import AuditLogService

        await AuditLogService.append_event(
            db=db,
            event_type=AuditEventType.MEMORY_CREATED,
            entity_type="MEMORY",
            entity_id=memory.id,
            user_id=tx.user_id,
            event_data={
                "transaction_id": str(tx.id),
                "memory_type": str(mem_type),
                "relevance": str(relevance),
                "summary": summary,
            },
        )

        # 11. Commit and refresh
        await db.commit()
        await db.refresh(memory)

        # Re-query with eager loaded sources
        result_stmt = (
            select(DecisionMemory)
            .where(DecisionMemory.id == memory.id)
            .options(selectinload(DecisionMemory.sources))
        )
        return await db.scalar(result_stmt) or memory
