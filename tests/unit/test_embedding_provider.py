"""Unit tests for embedding provider abstraction and deterministic implementation."""

import math

import pytest

from app.services.memory.embedding import DeterministicHashEmbeddingProvider


@pytest.mark.asyncio
async def test_deterministic_embedding_properties():
    """Verify deterministic embedding produces unit-norm vectors with consistent dimensions."""
    provider = DeterministicHashEmbeddingProvider(dimension=384)
    assert provider.dimension == 384
    assert provider.model_name == "deterministic-hash-v1"

    text = (
        "type: ROUTINE_PATTERN | summary: OpenAI API 25.00 USD | merchant: OpenAI API"
    )
    vec1 = await provider.embed(text)
    vec2 = await provider.embed(text)

    # 1. Dimension matches exactly
    assert len(vec1) == 384
    assert len(vec2) == 384

    # 2. Deterministic: same text -> identical floats
    assert vec1 == vec2

    # 3. Unit-norm (L2 norm is approximately 1.0)
    norm = math.sqrt(sum(x * x for x in vec1))
    assert abs(norm - 1.0) < 1e-5


@pytest.mark.asyncio
async def test_distinct_texts_produce_distinct_vectors():
    """Verify distinct input texts map to distinct vectors."""
    provider = DeterministicHashEmbeddingProvider(dimension=384)

    vec_openai = await provider.embed("merchant: OpenAI API | amount: 25.00")
    vec_netflix = await provider.embed("merchant: Netflix | amount: 15.00")

    assert vec_openai != vec_netflix

    # Dot product / cosine similarity of distinct texts is < 1.0
    dot = sum(a * b for a, b in zip(vec_openai, vec_netflix, strict=False))
    assert dot < 0.99


@pytest.mark.asyncio
async def test_batch_embedding_consistency():
    """Verify batch embedding produces same results as individual embedding."""
    provider = DeterministicHashEmbeddingProvider(dimension=384)
    texts = [
        "type: ROUTINE_PATTERN | summary: Item 1",
        "type: ANOMALY_EVENT | summary: Item 2",
    ]

    batch_vecs = await provider.embed_batch(texts)
    indiv_1 = await provider.embed(texts[0])
    indiv_2 = await provider.embed(texts[1])

    assert batch_vecs[0] == indiv_1
    assert batch_vecs[1] == indiv_2


@pytest.mark.asyncio
async def test_empty_string_handling():
    """Verify empty/whitespace strings produce safe zero/fallback vectors."""
    provider = DeterministicHashEmbeddingProvider(dimension=384)
    vec_empty = await provider.embed("")
    vec_spaces = await provider.embed("   ")

    assert len(vec_empty) == 384
    assert all(x == 0.0 for x in vec_empty)
    assert all(x == 0.0 for x in vec_spaces)
