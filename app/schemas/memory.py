"""Pydantic schemas for Decision Memory API."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import (
    MemoryRelevance,
    MemorySourceType,
    MemoryStatus,
    MemoryType,
    RetrievalMode,
)


class MemorySourceSchema(BaseModel):
    """Schema representing source provenance for a decision memory."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    memory_id: uuid.UUID
    source_type: MemorySourceType
    source_id: uuid.UUID
    created_at: datetime


class DecisionMemoryResponse(BaseModel):
    """Schema for returning structured decision memory details."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    memory_type: MemoryType
    relevance: MemoryRelevance
    status: MemoryStatus
    summary: str = Field(description="Deterministic structured summary.")
    structured_data: dict[str, Any] = Field(
        default_factory=dict,
        description="Explicitly typed metrics and decision parameters.",
    )
    version: int
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    created_at: datetime
    updated_at: datetime
    sources: list[MemorySourceSchema] = Field(default_factory=list)


class MemoryListResponse(BaseModel):
    """Paginated list of decision memories."""

    memories: list[DecisionMemoryResponse]
    count: int


class SemanticMemorySearchRequest(BaseModel):
    """Request payload for searching memories by vector similarity or hybrid ranking."""

    user_id: uuid.UUID = Field(
        ..., description="User ID principal for strict tenant isolation."
    )
    query_text: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Text representation of current financial context or intent.",
    )
    min_similarity: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Minimum cosine similarity threshold (0.0 to 1.0).",
    )
    limit: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Maximum candidate memories to return.",
    )
    retrieval_mode: RetrievalMode = Field(
        default=RetrievalMode.SEMANTIC,
        description="Retrieval strategy: SEMANTIC (pure vector ranking) or HYBRID (tiered relevance + vector ranking).",
    )
    memory_type: MemoryType | None = Field(
        default=None,
        description="Optional filter by domain category.",
    )
    min_relevance: MemoryRelevance | None = Field(
        default=None,
        description="Optional minimum relevance priority threshold.",
    )


class SemanticMemorySearchResult(BaseModel):
    """Candidate memory returned by semantic or hybrid vector search."""

    model_config = ConfigDict(from_attributes=True)

    memory_id: uuid.UUID
    memory_type: MemoryType
    relevance: MemoryRelevance
    status: MemoryStatus
    summary: str
    similarity_score: float = Field(
        description="Vector cosine similarity metadata score (not a risk score)."
    )
    hybrid_score: float | None = Field(
        default=None,
        description="Composite hybrid rank score (metadata only, not a financial risk score).",
    )
    relevance_priority: int | None = Field(
        default=None,
        description="Deterministic relevance tier priority (1=CRITICAL, 4=LOW).",
    )
    rank_tier: str | None = Field(
        default=None,
        description="Relevance rank tier classification.",
    )
    structured_data: dict[str, Any] = Field(default_factory=dict)
    sources: list[MemorySourceSchema] = Field(default_factory=list)


class SemanticMemorySearchResponse(BaseModel):
    """Response containing ranked candidate memories."""

    results: list[SemanticMemorySearchResult]
    count: int
    query_text: str
    retrieval_mode: RetrievalMode = RetrievalMode.SEMANTIC


class MemoryCompressionRequest(BaseModel):
    """Request payload to execute deterministic user memory compression."""

    user_id: uuid.UUID = Field(
        ..., description="User ID principal for strict tenant isolation."
    )
    lookback_days: int = Field(
        default=90,
        ge=1,
        le=365,
        description="Historical lookback window in days.",
    )
    max_source_events: int = Field(
        default=500,
        ge=1,
        le=2000,
        description="Maximum source transactions to evaluate.",
    )


class MemoryCompressionResponse(BaseModel):
    """Deterministic summary response from memory compression execution."""

    user_id: uuid.UUID
    source_event_count: int = Field(
        description="Total authoritative source transactions evaluated."
    )
    memories_created: int = Field(description="Newly created DecisionMemory records.")
    memories_reused: int = Field(
        description="Existing active DecisionMemory records reused (idempotent)."
    )
    events_compressed: int = Field(
        description="Source transactions consolidated into aggregate memories."
    )
    events_preserved: int = Field(
        description="Source transactions preserved individually for safety."
    )
    compression_ratio: float = Field(
        description="Deterministic compression ratio (source_events / active_memories)."
    )
    compression_percentage: float = Field(
        description="Deterministic compression reduction percentage."
    )
    status: str = Field(
        default="COMPLETED",
        description="Execution status.",
    )
