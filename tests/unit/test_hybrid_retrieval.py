"""Unit tests for Hybrid Memory Retrieval Service."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import MemoryRelevance, MemoryStatus, MemoryType
from app.models.memory import DecisionMemory
from app.models.user import User
from app.schemas.memory import SemanticMemorySearchResult
from app.services.memory.embedding import (
    DeterministicHashEmbeddingProvider,
    EmbeddingProvider,
)
from app.services.memory.hybrid_retrieval import HybridMemoryRetrievalService


@pytest.mark.asyncio
async def test_hybrid_empty_candidate_set(test_db_session: AsyncSession):
    """Verify hybrid retrieval returns empty list for user with no memories."""
    uid = uuid.uuid4()
    results = await HybridMemoryRetrievalService.retrieve_hybrid_candidates(
        user_id=uid,
        db=test_db_session,
        query_text="AWS Cloud invoice",
        limit=10,
    )
    assert results == []


@pytest.mark.asyncio
async def test_hybrid_relevance_precedence_critical_over_high_sim_normal(
    test_db_session: AsyncSession,
):
    """Verify that a CRITICAL memory with lower similarity strictly outranks a NORMAL memory with high similarity."""
    user = User(id=uuid.uuid4(), external_reference="hyb_prio_u", status="ACTIVE")
    test_db_session.add(user)
    await test_db_session.flush()

    provider = DeterministicHashEmbeddingProvider(dimension=384)
    query_text = (
        "type: ROUTINE_PATTERN | summary: OpenAI API 25.00 USD | merchant: OpenAI API"
    )
    target_vec = await provider.embed(query_text)

    # 1. NORMAL memory that is identical to query (similarity ~1.0)
    mem_normal = DecisionMemory(
        id=uuid.uuid4(),
        user_id=user.id,
        memory_type=MemoryType.ROUTINE_PATTERN,
        relevance=MemoryRelevance.NORMAL,
        status=MemoryStatus.ACTIVE,
        summary="OpenAI API 25.00 USD",
        structured_data={"merchant": "OpenAI API", "amount": "25.00"},
        embedding=target_vec,
        created_at=datetime.now(UTC),
    )

    # 2. CRITICAL memory with different text (lower similarity)
    critical_text = (
        "type: MANDATE_EVENT | summary: Mandate revoked due to security limit"
    )
    crit_vec = await provider.embed(critical_text)
    mem_critical = DecisionMemory(
        id=uuid.uuid4(),
        user_id=user.id,
        memory_type=MemoryType.MANDATE_EVENT,
        relevance=MemoryRelevance.CRITICAL,
        status=MemoryStatus.ACTIVE,
        summary="Mandate revoked due to security limit",
        structured_data={"event": "REVOCATION"},
        embedding=crit_vec,
        created_at=datetime.now(UTC),
    )

    test_db_session.add_all([mem_normal, mem_critical])
    await test_db_session.commit()

    candidates = await HybridMemoryRetrievalService.retrieve_hybrid_candidates(
        user_id=user.id,
        db=test_db_session,
        query_text=query_text,
        min_similarity=0.0,
        limit=10,
    )

    assert len(candidates) == 2
    # CRITICAL memory MUST be ranked first, despite lower similarity score
    assert candidates[0].memory.id == mem_critical.id
    assert candidates[0].rank_tier == "CRITICAL"
    assert candidates[0].hybrid_score > candidates[1].hybrid_score

    # NORMAL memory ranked second with higher similarity
    assert candidates[1].memory.id == mem_normal.id
    assert candidates[1].rank_tier == "NORMAL"
    assert candidates[1].similarity_score >= 0.99


@pytest.mark.asyncio
async def test_hybrid_similarity_ordering_within_same_relevance_tier(
    test_db_session: AsyncSession,
):
    """Verify that inside the same relevance tier, higher similarity ranks higher."""
    user = User(id=uuid.uuid4(), external_reference="hyb_sim_u", status="ACTIVE")
    test_db_session.add(user)
    await test_db_session.flush()

    provider = DeterministicHashEmbeddingProvider(dimension=384)
    query_text = "merchant: Cloudflare CDN | amount: 20.00"
    target_vec = await provider.embed(query_text)
    diff_vec = await provider.embed("merchant: GitHub Copilot | amount: 10.00")

    # High match NORMAL
    mem_high_sim = DecisionMemory(
        id=uuid.uuid4(),
        user_id=user.id,
        memory_type=MemoryType.ROUTINE_PATTERN,
        relevance=MemoryRelevance.NORMAL,
        status=MemoryStatus.ACTIVE,
        summary="Cloudflare CDN 20.00 USD",
        structured_data={"merchant": "Cloudflare CDN"},
        embedding=target_vec,
        created_at=datetime.now(UTC) - timedelta(days=2),
    )

    # Low match NORMAL
    mem_low_sim = DecisionMemory(
        id=uuid.uuid4(),
        user_id=user.id,
        memory_type=MemoryType.ROUTINE_PATTERN,
        relevance=MemoryRelevance.NORMAL,
        status=MemoryStatus.ACTIVE,
        summary="GitHub Copilot 10.00 USD",
        structured_data={"merchant": "GitHub Copilot"},
        embedding=diff_vec,
        created_at=datetime.now(UTC) - timedelta(days=1),
    )

    test_db_session.add_all([mem_high_sim, mem_low_sim])
    await test_db_session.commit()

    candidates = await HybridMemoryRetrievalService.retrieve_hybrid_candidates(
        user_id=user.id,
        db=test_db_session,
        query_text=query_text,
        min_similarity=-1.0,
        limit=10,
    )

    assert len(candidates) == 2
    # In same tier (NORMAL), high match outranks low match
    assert candidates[0].memory.id == mem_high_sim.id
    assert candidates[0].similarity_score > candidates[1].similarity_score


@pytest.mark.asyncio
async def test_hybrid_recency_ordering_when_similarity_and_relevance_equal(
    test_db_session: AsyncSession,
):
    """Verify that when relevance and similarity are equal, newer memory ranks higher."""
    user = User(id=uuid.uuid4(), external_reference="hyb_rec_u", status="ACTIVE")
    test_db_session.add(user)
    await test_db_session.flush()

    provider = DeterministicHashEmbeddingProvider(dimension=384)
    query_text = "merchant: Stripe"
    vec = await provider.embed(query_text)

    now = datetime.now(UTC)
    mem_older = DecisionMemory(
        id=uuid.uuid4(),
        user_id=user.id,
        memory_type=MemoryType.ROUTINE_PATTERN,
        relevance=MemoryRelevance.NORMAL,
        status=MemoryStatus.ACTIVE,
        summary="Stripe payment 1",
        structured_data={},
        embedding=vec,
        created_at=now - timedelta(days=5),
    )
    mem_newer = DecisionMemory(
        id=uuid.uuid4(),
        user_id=user.id,
        memory_type=MemoryType.ROUTINE_PATTERN,
        relevance=MemoryRelevance.NORMAL,
        status=MemoryStatus.ACTIVE,
        summary="Stripe payment 2",
        structured_data={},
        embedding=vec,
        created_at=now - timedelta(days=1),
    )

    test_db_session.add_all([mem_older, mem_newer])
    await test_db_session.commit()

    candidates = await HybridMemoryRetrievalService.retrieve_hybrid_candidates(
        user_id=user.id,
        db=test_db_session,
        query_text=query_text,
        min_similarity=0.5,
        limit=10,
    )

    assert len(candidates) == 2
    assert candidates[0].memory.id == mem_newer.id
    assert candidates[1].memory.id == mem_older.id


@pytest.mark.asyncio
async def test_hybrid_lifecycle_and_temporal_filters(
    test_db_session: AsyncSession,
):
    """Verify retired, superseded, expired, and future memories are excluded."""
    user = User(id=uuid.uuid4(), external_reference="hyb_filt_u", status="ACTIVE")
    test_db_session.add(user)
    await test_db_session.flush()

    provider = DeterministicHashEmbeddingProvider(dimension=384)
    query_text = "merchant: TestFilter"
    vec = await provider.embed(query_text)

    now = datetime.now(UTC)

    # 1. Valid Active
    mem_active = DecisionMemory(
        id=uuid.uuid4(),
        user_id=user.id,
        memory_type=MemoryType.ROUTINE_PATTERN,
        relevance=MemoryRelevance.NORMAL,
        status=MemoryStatus.ACTIVE,
        summary="Valid Active",
        structured_data={},
        embedding=vec,
        created_at=now,
    )
    # 2. Retired
    mem_retired = DecisionMemory(
        id=uuid.uuid4(),
        user_id=user.id,
        memory_type=MemoryType.ROUTINE_PATTERN,
        relevance=MemoryRelevance.NORMAL,
        status=MemoryStatus.RETIRED,
        summary="Retired",
        structured_data={},
        embedding=vec,
        created_at=now,
    )
    # 3. Superseded
    mem_superseded = DecisionMemory(
        id=uuid.uuid4(),
        user_id=user.id,
        memory_type=MemoryType.ROUTINE_PATTERN,
        relevance=MemoryRelevance.NORMAL,
        status=MemoryStatus.SUPERSEDED,
        summary="Superseded",
        structured_data={},
        embedding=vec,
        created_at=now,
    )
    # 4. Expired
    mem_expired = DecisionMemory(
        id=uuid.uuid4(),
        user_id=user.id,
        memory_type=MemoryType.ROUTINE_PATTERN,
        relevance=MemoryRelevance.NORMAL,
        status=MemoryStatus.ACTIVE,
        summary="Expired",
        structured_data={},
        embedding=vec,
        valid_until=now - timedelta(days=1),
        created_at=now,
    )
    # 5. Future
    mem_future = DecisionMemory(
        id=uuid.uuid4(),
        user_id=user.id,
        memory_type=MemoryType.ROUTINE_PATTERN,
        relevance=MemoryRelevance.NORMAL,
        status=MemoryStatus.ACTIVE,
        summary="Future",
        structured_data={},
        embedding=vec,
        valid_from=now + timedelta(days=2),
        created_at=now,
    )

    test_db_session.add_all(
        [mem_active, mem_retired, mem_superseded, mem_expired, mem_future]
    )
    await test_db_session.commit()

    candidates = await HybridMemoryRetrievalService.retrieve_hybrid_candidates(
        user_id=user.id,
        db=test_db_session,
        query_text=query_text,
        as_of=now,
    )

    assert len(candidates) == 1
    assert candidates[0].memory.id == mem_active.id


@pytest.mark.asyncio
async def test_hybrid_embedding_failure_fallback(test_db_session: AsyncSession):
    """Verify hybrid retrieval safely falls back to deterministic tiering when embedding generation fails."""
    user = User(id=uuid.uuid4(), external_reference="hyb_fail_u", status="ACTIVE")
    test_db_session.add(user)
    await test_db_session.flush()

    mem = DecisionMemory(
        id=uuid.uuid4(),
        user_id=user.id,
        memory_type=MemoryType.ROUTINE_PATTERN,
        relevance=MemoryRelevance.NORMAL,
        status=MemoryStatus.ACTIVE,
        summary="Routine pattern memory",
        structured_data={},
        embedding=None,
        created_at=datetime.now(UTC),
    )
    test_db_session.add(mem)
    await test_db_session.commit()

    with patch.object(
        EmbeddingProvider, "embed", side_effect=RuntimeError("Embedding API down")
    ):
        candidates = await HybridMemoryRetrievalService.retrieve_hybrid_candidates(
            user_id=user.id,
            db=test_db_session,
            query_text="Some query text",
            min_similarity=0.0,
            limit=10,
        )
        assert len(candidates) == 1
        assert candidates[0].memory.id == mem.id
        assert candidates[0].similarity_score == 0.0


def test_search_result_schema_omits_raw_vectors():
    """Verify that SemanticMemorySearchResult Pydantic schema contains no raw vector fields."""
    fields = set(SemanticMemorySearchResult.model_fields.keys())
    assert "embedding" not in fields
    assert "raw_vector" not in fields
    assert "vector" not in fields
    assert "similarity_score" in fields
    assert "hybrid_score" in fields
    assert "relevance_priority" in fields
    assert "rank_tier" in fields
