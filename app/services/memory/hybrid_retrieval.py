"""Hybrid Memory Retrieval Service combining deterministic relevance and semantic vector similarity."""

import logging
import math
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.models.enums import MemoryRelevance, MemoryStatus, MemoryType
from app.models.memory import DecisionMemory
from app.services.memory.embedding import get_embedding_provider

logger = logging.getLogger(__name__)


@dataclass
class HybridMemoryCandidate:
    """Candidate memory item with combined deterministic and semantic scoring metadata."""

    memory: DecisionMemory
    similarity_score: float
    relevance_priority: int
    hybrid_score: float
    rank_tier: str


class HybridMemoryRetrievalService:
    """Service for bounded, two-stage hybrid decision memory candidate retrieval.

    Stage 1: Deterministic filtering (user scoping, active status, temporal bounds, lookback).
    Stage 2: Semantic vector similarity calculation.
    Ranking: Deterministic tiered ranking (CRITICAL > HIGH > NORMAL > LOW, then similarity, then recency).
    """

    RELEVANCE_PRIORITY = {
        MemoryRelevance.CRITICAL: 1,
        MemoryRelevance.HIGH: 2,
        MemoryRelevance.NORMAL: 3,
        MemoryRelevance.LOW: 4,
    }

    TIER_BASE_SCORES = {
        MemoryRelevance.CRITICAL: 100.0,
        MemoryRelevance.HIGH: 50.0,
        MemoryRelevance.NORMAL: 20.0,
        MemoryRelevance.LOW: 5.0,
    }

    @classmethod
    async def retrieve_hybrid_candidates(
        cls,
        user_id: uuid.UUID,
        db: AsyncSession,
        query_text: str | None = None,
        query_vector: list[float] | None = None,
        min_similarity: float = 0.5,
        limit: int = 10,
        lookback_days: int | None = None,
        memory_type: MemoryType | None = None,
        min_relevance: MemoryRelevance | None = None,
        as_of: datetime | None = None,
    ) -> list[HybridMemoryCandidate]:
        """Retrieve and rank candidate memories using two-stage deterministic + semantic ranking.

        Guarantees that financial relevance precedence (CRITICAL > HIGH > NORMAL > LOW)
        is preserved, preventing high semantic similarity from displacing critical safety context.
        """
        settings = get_settings()
        safe_limit = max(1, min(limit, 100))
        effective_now = as_of or datetime.now(UTC)
        effective_lookback = (
            lookback_days
            if lookback_days is not None
            else getattr(settings, "HISTORICAL_LOOKBACK_DAYS", 90)
        )
        cutoff_date = effective_now - timedelta(days=effective_lookback)

        # ----------------------------------------------------------------------
        # STAGE 1: Deterministic Candidate Filtering at the Database Layer
        # ----------------------------------------------------------------------
        stmt = (
            select(DecisionMemory)
            .where(
                DecisionMemory.user_id == user_id,
                DecisionMemory.status == MemoryStatus.ACTIVE,
                DecisionMemory.created_at >= cutoff_date,
            )
            .options(selectinload(DecisionMemory.sources))
        )

        # Apply temporal validity bounds in SQL
        stmt = stmt.where(
            or_(
                DecisionMemory.valid_from.is_(None),
                DecisionMemory.valid_from <= effective_now,
            ),
            or_(
                DecisionMemory.valid_until.is_(None),
                DecisionMemory.valid_until >= effective_now,
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

        # Bound the initial candidate pool
        stmt = stmt.limit(100)

        try:
            result = await db.scalars(stmt)
            candidates = result.all()
        except Exception as exc:
            logger.error(
                "Database query failed in hybrid retrieval: %s", exc, exc_info=True
            )
            return []

        if not candidates:
            return []

        # ----------------------------------------------------------------------
        # STAGE 2: Semantic Vector Similarity & Fallback Handling
        # ----------------------------------------------------------------------
        target_vector = query_vector
        if target_vector is None and query_text:
            try:
                provider = get_embedding_provider()
                target_vector = await provider.embed(query_text)
            except Exception as exc:
                logger.warning(
                    "Embedding generation failed in hybrid retrieval, falling back to deterministic: %s",
                    exc,
                )
                target_vector = None

        scored_items: list[HybridMemoryCandidate] = []

        for mem in candidates:
            sim_score = 0.0
            if target_vector and mem.embedding:
                mem_emb = list(mem.embedding)
                dot_product = sum(
                    x * y for x, y in zip(mem_emb, target_vector, strict=False)
                )
                norm_a = math.sqrt(sum(x * x for x in mem_emb))
                norm_b = math.sqrt(sum(y * y for y in target_vector))
                if norm_a > 0.0 and norm_b > 0.0:
                    sim_score = max(
                        -1.0, min(1.0, float(dot_product / (norm_a * norm_b)))
                    )

            # Filter candidates below threshold unless they are CRITICAL/HIGH safety memories
            prio = cls.RELEVANCE_PRIORITY.get(mem.relevance, 5)
            if target_vector is not None and sim_score < min_similarity and prio > 2:
                continue

            base_tier = cls.TIER_BASE_SCORES.get(mem.relevance, 5.0)
            hybrid_score = round(base_tier + (sim_score * 10.0), 4)

            scored_items.append(
                HybridMemoryCandidate(
                    memory=mem,
                    similarity_score=round(sim_score, 4),
                    relevance_priority=prio,
                    hybrid_score=hybrid_score,
                    rank_tier=mem.relevance.value,
                )
            )

        # ----------------------------------------------------------------------
        # STAGE 3: Deterministic Tiered Ranking
        # ----------------------------------------------------------------------
        # Sort by:
        # 1. Relevance Priority ascending (CRITICAL=1, HIGH=2, NORMAL=3, LOW=4)
        # 2. Semantic Similarity Score descending (-similarity_score)
        # 3. Recency descending (-created_at.timestamp)
        scored_items.sort(
            key=lambda c: (
                c.relevance_priority,
                -c.similarity_score,
                -(c.memory.created_at.timestamp() if c.memory.created_at else 0.0),
            )
        )

        return scored_items[:safe_limit]
