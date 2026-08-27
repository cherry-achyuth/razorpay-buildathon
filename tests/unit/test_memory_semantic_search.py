"""Unit tests for semantic memory search service logic."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import MemoryRelevance, MemoryStatus, MemoryType
from app.models.memory import DecisionMemory
from app.models.user import User
from app.services.memory.embedding import DeterministicHashEmbeddingProvider
from app.services.memory.retrieval import MemoryRetrievalService


@pytest.mark.asyncio
async def test_semantic_search_cosine_ranking(test_db_session: AsyncSession):
    """Verify semantic search ranks candidates by cosine similarity descending."""
    user = User(
        id=uuid.uuid4(),
        external_reference="sem_rank_u",
        status="ACTIVE",
    )
    test_db_session.add(user)
    await test_db_session.flush()

    provider = DeterministicHashEmbeddingProvider(dimension=384)

    text_target = (
        "type: ROUTINE_PATTERN | summary: OpenAI API 25.00 USD | merchant: OpenAI API"
    )
    text_different = (
        "type: ROUTINE_PATTERN | summary: Netflix 15.00 USD | merchant: Netflix"
    )

    vec_target = await provider.embed(text_target)
    vec_different = await provider.embed(text_different)

    mem_target = DecisionMemory(
        id=uuid.uuid4(),
        user_id=user.id,
        memory_type=MemoryType.ROUTINE_PATTERN,
        relevance=MemoryRelevance.NORMAL,
        status=MemoryStatus.ACTIVE,
        summary="OpenAI API 25.00 USD",
        structured_data={"merchant": "OpenAI API", "amount": "25.00"},
        embedding=vec_target,
    )
    mem_different = DecisionMemory(
        id=uuid.uuid4(),
        user_id=user.id,
        memory_type=MemoryType.ROUTINE_PATTERN,
        relevance=MemoryRelevance.NORMAL,
        status=MemoryStatus.ACTIVE,
        summary="Netflix 15.00 USD",
        structured_data={"merchant": "Netflix", "amount": "15.00"},
        embedding=vec_different,
    )
    test_db_session.add_all([mem_target, mem_different])
    await test_db_session.commit()

    # Search with exact target text -> mem_target should have similarity ~1.0
    results = await MemoryRetrievalService.search_similar_memories(
        user_id=user.id,
        db=test_db_session,
        query_text=text_target,
        min_similarity=-1.0,
        limit=10,
    )

    assert len(results) == 2
    assert results[0][0].id == mem_target.id
    assert results[0][1] >= 0.999


@pytest.mark.asyncio
async def test_semantic_search_excludes_retired_and_expired(
    test_db_session: AsyncSession,
):
    """Verify semantic search excludes retired and expired memories."""
    user = User(
        id=uuid.uuid4(),
        external_reference="sem_excl_u",
        status="ACTIVE",
    )
    test_db_session.add(user)
    await test_db_session.flush()

    provider = DeterministicHashEmbeddingProvider(dimension=384)
    query_text = "merchant: GitHub Copilot"
    vec = await provider.embed(query_text)

    now = datetime.now(UTC)

    # 1. Active & valid memory
    mem_active = DecisionMemory(
        id=uuid.uuid4(),
        user_id=user.id,
        memory_type=MemoryType.ROUTINE_PATTERN,
        relevance=MemoryRelevance.NORMAL,
        status=MemoryStatus.ACTIVE,
        summary="Active GitHub memory",
        structured_data={},
        embedding=vec,
    )
    # 2. Retired memory
    mem_retired = DecisionMemory(
        id=uuid.uuid4(),
        user_id=user.id,
        memory_type=MemoryType.ROUTINE_PATTERN,
        relevance=MemoryRelevance.NORMAL,
        status=MemoryStatus.RETIRED,
        summary="Retired GitHub memory",
        structured_data={},
        embedding=vec,
    )
    # 3. Expired memory
    mem_expired = DecisionMemory(
        id=uuid.uuid4(),
        user_id=user.id,
        memory_type=MemoryType.ROUTINE_PATTERN,
        relevance=MemoryRelevance.NORMAL,
        status=MemoryStatus.ACTIVE,
        summary="Expired GitHub memory",
        structured_data={},
        embedding=vec,
        valid_until=now - timedelta(days=1),
    )
    test_db_session.add_all([mem_active, mem_retired, mem_expired])
    await test_db_session.commit()

    results = await MemoryRetrievalService.search_similar_memories(
        user_id=user.id,
        db=test_db_session,
        query_text=query_text,
        min_similarity=0.0,
        limit=10,
        as_of=now,
    )

    assert len(results) == 1
    assert results[0][0].id == mem_active.id
