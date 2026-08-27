"""Decision Memory API endpoints."""

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.models.enums import MemoryRelevance, MemoryStatus, MemoryType, RetrievalMode
from app.schemas.memory import (
    DecisionMemoryResponse,
    MemoryCompressionRequest,
    MemoryCompressionResponse,
    MemoryListResponse,
    MemorySourceSchema,
    SemanticMemorySearchRequest,
    SemanticMemorySearchResponse,
    SemanticMemorySearchResult,
)
from app.services.memory import (
    HybridMemoryRetrievalService,
    MemoryBuilderService,
    MemoryCompressionService,
    MemoryRetrievalService,
)

router = APIRouter(prefix="/memories", tags=["Memories"])


@router.post(
    "/build/{transaction_id}",
    response_model=DecisionMemoryResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Build Decision Memory from Transaction",
    description=(
        "Converts a raw PostgreSQL source transaction into a canonical financial "
        "event and persists a deterministic decision memory with explicit provenance."
    ),
)
async def build_memory_from_transaction(
    transaction_id: uuid.UUID,
    user_id: Annotated[
        uuid.UUID | None,
        Query(description="Optional user ID context for strict cross-user isolation."),
    ] = None,
    db: AsyncSession = Depends(get_db_session),
) -> DecisionMemoryResponse:
    """Build decision memory from raw transaction."""
    memory = await MemoryBuilderService.build_from_transaction(
        transaction_id=transaction_id,
        db=db,
        requested_user_id=user_id,
    )
    return DecisionMemoryResponse.model_validate(memory)


@router.post(
    "/compress",
    response_model=MemoryCompressionResponse,
    status_code=status.HTTP_200_OK,
    summary="Deterministically Compress User Decision Memories",
    description=(
        "Consolidates redundant routine transactions into aggregated decision memories "
        "with explicit provenance while preserving safety-critical events separately. "
        "Raw PostgreSQL transaction history remains untouched and permanent."
    ),
)
async def compress_user_memories(
    payload: MemoryCompressionRequest,
    db: AsyncSession = Depends(get_db_session),
) -> MemoryCompressionResponse:
    """Execute deterministic memory compression for a user."""
    result = await MemoryCompressionService.compress_user_history(
        user_id=payload.user_id,
        db=db,
        lookback_days=payload.lookback_days,
        max_source_events=payload.max_source_events,
    )
    return MemoryCompressionResponse(
        user_id=result.user_id,
        source_event_count=result.source_event_count,
        memories_created=result.memories_created,
        memories_reused=result.memories_reused,
        events_compressed=result.events_compressed,
        events_preserved=result.events_preserved,
        compression_ratio=result.compression_ratio,
        compression_percentage=result.compression_percentage,
        status=result.status,
    )


@router.post(
    "/search",
    response_model=SemanticMemorySearchResponse,
    status_code=status.HTTP_200_OK,
    summary="Search Memories by Semantic Vector Similarity or Hybrid Ranking",
    description=(
        "Retrieves candidate decision memories ranked by vector similarity or tiered hybrid "
        "relevance precedence. Strictly scoped to user_id, active status, and temporal bounds."
    ),
)
async def search_memories(
    payload: SemanticMemorySearchRequest,
    db: AsyncSession = Depends(get_db_session),
) -> SemanticMemorySearchResponse:
    """Search decision memories using SEMANTIC or HYBRID retrieval mode."""
    now = datetime.now(UTC)

    if payload.retrieval_mode == RetrievalMode.HYBRID:
        hybrid_candidates = (
            await HybridMemoryRetrievalService.retrieve_hybrid_candidates(
                user_id=payload.user_id,
                db=db,
                query_text=payload.query_text,
                min_similarity=payload.min_similarity,
                limit=payload.limit,
                memory_type=payload.memory_type,
                min_relevance=payload.min_relevance,
                as_of=now,
            )
        )
        formatted_results = [
            SemanticMemorySearchResult(
                memory_id=c.memory.id,
                memory_type=c.memory.memory_type,
                relevance=c.memory.relevance,
                status=c.memory.status,
                summary=c.memory.summary,
                similarity_score=c.similarity_score,
                hybrid_score=c.hybrid_score,
                relevance_priority=c.relevance_priority,
                rank_tier=c.rank_tier,
                structured_data=c.memory.structured_data,
                sources=[
                    MemorySourceSchema.model_validate(s) for s in c.memory.sources
                ],
            )
            for c in hybrid_candidates
        ]
    else:
        results_with_scores = await MemoryRetrievalService.search_similar_memories(
            user_id=payload.user_id,
            db=db,
            query_text=payload.query_text,
            min_similarity=payload.min_similarity,
            limit=payload.limit,
            memory_type=payload.memory_type,
            min_relevance=payload.min_relevance,
            as_of=now,
        )
        formatted_results = [
            SemanticMemorySearchResult(
                memory_id=mem.id,
                memory_type=mem.memory_type,
                relevance=mem.relevance,
                status=mem.status,
                summary=mem.summary,
                similarity_score=round(score, 4),
                structured_data=mem.structured_data,
                sources=[MemorySourceSchema.model_validate(s) for s in mem.sources],
            )
            for mem, score in results_with_scores
        ]

    return SemanticMemorySearchResponse(
        results=formatted_results,
        count=len(formatted_results),
        query_text=payload.query_text,
        retrieval_mode=payload.retrieval_mode,
    )


@router.get(
    "",
    response_model=MemoryListResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve Bounded User Memories",
    description="Retrieves explainable decision memories scoped to a user.",
)
async def get_user_memories(
    user_id: Annotated[uuid.UUID, Query(description="User ID principal (required).")],
    status_filter: Annotated[
        MemoryStatus | None,
        Query(alias="status", description="Lifecycle status filter."),
    ] = MemoryStatus.ACTIVE,
    memory_type: Annotated[
        MemoryType | None, Query(description="Domain category filter.")
    ] = None,
    min_relevance: Annotated[
        MemoryRelevance | None,
        Query(description="Minimum relevance priority threshold."),
    ] = None,
    limit: Annotated[
        int, Query(ge=1, le=100, description="Max records to return.")
    ] = 20,
    offset: Annotated[int, Query(ge=0, description="Pagination offset.")] = 0,
    db: AsyncSession = Depends(get_db_session),
) -> MemoryListResponse:
    """Retrieve user-scoped decision memories."""
    memories = await MemoryRetrievalService.get_user_memories(
        user_id=user_id,
        db=db,
        status=status_filter,
        memory_type=memory_type,
        min_relevance=min_relevance,
        limit=limit,
        offset=offset,
    )
    validated = [DecisionMemoryResponse.model_validate(m) for m in memories]
    return MemoryListResponse(memories=validated, count=len(validated))


@router.get(
    "/{memory_id}",
    response_model=DecisionMemoryResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Memory by ID with Provenance",
    description="Fetches a decision memory and its complete source provenance.",
)
async def get_memory_by_id(
    memory_id: uuid.UUID,
    user_id: Annotated[
        uuid.UUID | None,
        Query(description="Optional user ID context for strict cross-user isolation."),
    ] = None,
    db: AsyncSession = Depends(get_db_session),
) -> DecisionMemoryResponse:
    """Retrieve single memory by ID."""
    memory = await MemoryRetrievalService.get_memory_by_id(
        memory_id=memory_id,
        db=db,
        requested_user_id=user_id,
    )
    return DecisionMemoryResponse.model_validate(memory)


@router.post(
    "/{memory_id}/retire",
    response_model=DecisionMemoryResponse,
    status_code=status.HTTP_200_OK,
    summary="Retire Decision Memory",
    description="Retires a memory without deleting raw source transactions.",
)
async def retire_memory(
    memory_id: uuid.UUID,
    user_id: Annotated[
        uuid.UUID | None,
        Query(description="Optional user ID context for strict cross-user isolation."),
    ] = None,
    db: AsyncSession = Depends(get_db_session),
) -> DecisionMemoryResponse:
    """Retire decision memory."""
    memory = await MemoryRetrievalService.retire_memory(
        memory_id=memory_id,
        db=db,
        requested_user_id=user_id,
    )
    return DecisionMemoryResponse.model_validate(memory)
