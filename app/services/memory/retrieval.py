"""Memory Retrieval Service for bounded, user-scoped memory querying."""

import logging
import math
import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import case, desc, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import AppException, ResourceNotFoundError
from app.models.enums import MemoryRelevance, MemoryStatus, MemoryType
from app.models.memory import DecisionMemory
from app.services.memory.embedding import get_embedding_provider

logger = logging.getLogger(__name__)


class MemoryRetrievalService:
    """Service for bounded, explainable decision memory retrieval.

    Enforces strict user scoping, relevance priority ordering, and bounded pagination.
    Supports both deterministic structured queries and pgvector semantic retrieval.
    """

    RELEVANCE_PRIORITY = {
        MemoryRelevance.CRITICAL: 1,
        MemoryRelevance.HIGH: 2,
        MemoryRelevance.NORMAL: 3,
        MemoryRelevance.LOW: 4,
    }

    @classmethod
    async def get_user_memories(
        cls,
        user_id: uuid.UUID,
        db: AsyncSession,
        status: MemoryStatus | None = MemoryStatus.ACTIVE,
        memory_type: MemoryType | None = None,
        min_relevance: MemoryRelevance | None = None,
        as_of: datetime | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> Sequence[DecisionMemory]:
        """Retrieve bounded decision memories for a specific user.

        Filters by user, status, and temporal validity before applying relevance
        precedence ordering and limits.
        """
        safe_limit = max(1, min(limit, 100))
        safe_offset = max(0, offset)

        stmt = select(DecisionMemory).where(DecisionMemory.user_id == user_id)

        if status is not None:
            stmt = stmt.where(DecisionMemory.status == status)

        if as_of is not None:
            stmt = stmt.where(
                or_(
                    DecisionMemory.valid_from.is_(None),
                    DecisionMemory.valid_from <= as_of,
                ),
                or_(
                    DecisionMemory.valid_until.is_(None),
                    DecisionMemory.valid_until >= as_of,
                ),
            )

        if memory_type is not None:
            stmt = stmt.where(DecisionMemory.memory_type == memory_type)

        if min_relevance is not None:
            target_priority = cls.RELEVANCE_PRIORITY[min_relevance]
            allowed_relevances = [
                rel
                for rel, prio in cls.RELEVANCE_PRIORITY.items()
                if prio <= target_priority
            ]
            stmt = stmt.where(DecisionMemory.relevance.in_(allowed_relevances))

        # Order by relevance precedence (CRITICAL > HIGH > NORMAL > LOW)
        relevance_order = case(
            {
                MemoryRelevance.CRITICAL: 1,
                MemoryRelevance.HIGH: 2,
                MemoryRelevance.NORMAL: 3,
                MemoryRelevance.LOW: 4,
            },
            value=DecisionMemory.relevance,
            else_=5,
        )

        stmt = (
            stmt.options(selectinload(DecisionMemory.sources))
            .order_by(relevance_order, desc(DecisionMemory.created_at))
            .limit(safe_limit)
            .offset(safe_offset)
        )

        result = await db.scalars(stmt)
        return result.all()

    @classmethod
    async def search_similar_memories(
        cls,
        user_id: uuid.UUID,
        db: AsyncSession,
        query_text: str | None = None,
        query_vector: list[float] | None = None,
        min_similarity: float = 0.5,
        limit: int = 10,
        memory_type: MemoryType | None = None,
        min_relevance: MemoryRelevance | None = None,
        as_of: datetime | None = None,
    ) -> list[tuple[DecisionMemory, float]]:
        """Search decision memories by semantic vector similarity.

        Filters strictly by user_id, active lifecycle status, and temporal validity
        before computing cosine similarity scores and enforcing bounds.
        """
        safe_limit = max(1, min(limit, 100))

        # 1. Compute query vector if not explicitly provided
        target_vector = query_vector
        if target_vector is None and query_text:
            try:
                provider = get_embedding_provider()
                target_vector = await provider.embed(query_text)
            except Exception as exc:
                logger.error("Failed to generate query embedding: %s", exc)
                return []

        if target_vector is None:
            return []

        # 2. Query candidate memories with user scope and lifecycle filters
        stmt = (
            select(DecisionMemory)
            .where(
                DecisionMemory.user_id == user_id,
                DecisionMemory.status == MemoryStatus.ACTIVE,
                DecisionMemory.embedding.is_not(None),
            )
            .options(selectinload(DecisionMemory.sources))
        )

        if as_of is not None:
            stmt = stmt.where(
                or_(
                    DecisionMemory.valid_from.is_(None),
                    DecisionMemory.valid_from <= as_of,
                ),
                or_(
                    DecisionMemory.valid_until.is_(None),
                    DecisionMemory.valid_until >= as_of,
                ),
            )

        if memory_type is not None:
            stmt = stmt.where(DecisionMemory.memory_type == memory_type)

        if min_relevance is not None:
            target_priority = cls.RELEVANCE_PRIORITY[min_relevance]
            allowed_relevances = [
                rel
                for rel, prio in cls.RELEVANCE_PRIORITY.items()
                if prio <= target_priority
            ]
            stmt = stmt.where(DecisionMemory.relevance.in_(allowed_relevances))

        result = await db.scalars(stmt)
        candidates = result.all()

        # 3. Compute cosine similarity
        scored_candidates: list[tuple[DecisionMemory, float]] = []

        for mem in candidates:
            if not mem.embedding:
                continue

            # Compute cosine similarity: (a . b) / (||a|| * ||b||)
            # Both vectors are L2-normalized float lists
            mem_emb = list(mem.embedding)
            dot_product = sum(
                x * y for x, y in zip(mem_emb, target_vector, strict=False)
            )
            norm_a = math.sqrt(sum(x * x for x in mem_emb))
            norm_b = math.sqrt(sum(y * y for y in target_vector))

            if norm_a == 0.0 or norm_b == 0.0:
                sim_score = 0.0
            else:
                sim_score = float(dot_product / (norm_a * norm_b))

            if sim_score >= min_similarity:
                scored_candidates.append((mem, sim_score))

        # 4. Sort by similarity descending, then created_at descending
        scored_candidates.sort(
            key=lambda item: (item[1], item[0].created_at or datetime.min),
            reverse=True,
        )

        return scored_candidates[:safe_limit]

    @classmethod
    async def get_memory_by_id(
        cls,
        memory_id: uuid.UUID,
        db: AsyncSession,
        requested_user_id: uuid.UUID | None = None,
    ) -> DecisionMemory:
        """Retrieve a specific decision memory by ID including provenance."""
        stmt = (
            select(DecisionMemory)
            .where(DecisionMemory.id == memory_id)
            .options(selectinload(DecisionMemory.sources))
        )
        mem = await db.scalar(stmt)
        if not mem:
            raise ResourceNotFoundError(
                f"DecisionMemory with ID '{memory_id}' was not found."
            )

        if requested_user_id is not None and mem.user_id != requested_user_id:
            raise AppException(
                message="Cannot access decision memory belonging to another user.",
                error_code="CROSS_USER_ACCESS_DENIED",
                status_code=403,
            )

        return mem

    @classmethod
    async def retire_memory(
        cls,
        memory_id: uuid.UUID,
        db: AsyncSession,
        requested_user_id: uuid.UUID | None = None,
    ) -> DecisionMemory:
        """Retire a decision memory without deleting source transactions."""
        mem = await cls.get_memory_by_id(
            memory_id=memory_id,
            db=db,
            requested_user_id=requested_user_id,
        )
        mem.status = MemoryStatus.RETIRED

        from app.models.enums import AuditEventType
        from app.services.audit.service import AuditLogService

        await AuditLogService.append_event(
            db=db,
            event_type=AuditEventType.MEMORY_RETIRED,
            entity_type="MEMORY",
            entity_id=mem.id,
            user_id=mem.user_id,
            event_data={
                "memory_type": str(mem.memory_type),
                "relevance": str(mem.relevance),
                "summary": mem.summary,
            },
        )

        await db.commit()
        await db.refresh(mem)
        return mem
