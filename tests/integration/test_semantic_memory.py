"""Integration tests for Day 7: Semantic Memory & Vector Search Capabilities."""

import pytest
from httpx import AsyncClient

from app.models.enums import DecisionOutcome


@pytest.mark.asyncio
async def test_memory_build_generates_and_persists_embedding(
    async_client: AsyncClient,
):
    """Verify that building a memory from a transaction generates and persists an embedding."""
    u_res = await async_client.post(
        "/api/v1/users",
        json={"external_reference": "sem_build_u", "status": "ACTIVE"},
    )
    user_id = u_res.json()["id"]

    m_res = await async_client.post(
        "/api/v1/merchants",
        json={"name": "OpenAI", "external_reference": "sem_build_m"},
    )
    merchant_id = m_res.json()["id"]

    tx_res = await async_client.post(
        "/api/v1/transactions",
        json={
            "user_id": user_id,
            "merchant_id": merchant_id,
            "amount": "20.00",
            "currency": "USD",
            "status": "CAPTURED",
            "transaction_type": "PURCHASE",
        },
    )
    tx_id = tx_res.json()["id"]

    # Build decision memory
    mem_res = await async_client.post(f"/api/v1/memories/build/{tx_id}")
    assert mem_res.status_code == 201
    mem_data = mem_res.json()
    assert mem_data["user_id"] == user_id
    assert "OpenAI" in mem_data["summary"]

    # Search via semantic search endpoint
    search_res = await async_client.post(
        "/api/v1/memories/search",
        json={
            "user_id": user_id,
            "query_text": "type: ROUTINE_PATTERN | summary: Standard purchase of 20.00 USD with merchant 'OpenAI'. | merchant: OpenAI | amount: 20.0000 | currency: USD | tx_type: PURCHASE",
            "min_similarity": 0.5,
            "limit": 5,
        },
    )
    assert search_res.status_code == 200
    search_data = search_res.json()
    assert search_data["count"] == 1
    assert search_data["results"][0]["memory_id"] == mem_data["id"]
    assert search_data["results"][0]["similarity_score"] >= 0.95


@pytest.mark.asyncio
async def test_cross_user_isolation_in_semantic_search(
    async_client: AsyncClient,
):
    """Verify that User A's semantic search NEVER returns User B's memories."""
    u1_res = await async_client.post(
        "/api/v1/users",
        json={"external_reference": "sem_iso_u1", "status": "ACTIVE"},
    )
    user1_id = u1_res.json()["id"]

    u2_res = await async_client.post(
        "/api/v1/users",
        json={"external_reference": "sem_iso_u2", "status": "ACTIVE"},
    )
    user2_id = u2_res.json()["id"]

    m_res = await async_client.post(
        "/api/v1/merchants",
        json={"name": "Cursor AI", "external_reference": "sem_iso_m"},
    )
    merchant_id = m_res.json()["id"]

    # Create transaction & memory for User 2 ONLY
    tx_res = await async_client.post(
        "/api/v1/transactions",
        json={
            "user_id": user2_id,
            "merchant_id": merchant_id,
            "amount": "20.00",
            "currency": "USD",
            "status": "CAPTURED",
            "transaction_type": "PURCHASE",
        },
    )
    await async_client.post(f"/api/v1/memories/build/{tx_res.json()['id']}")

    # User 1 searches for the EXACT same query text
    search_res = await async_client.post(
        "/api/v1/memories/search",
        json={
            "user_id": user1_id,
            "query_text": "type: ROUTINE_PATTERN | summary: Standard purchase of 20.00 USD with merchant 'Cursor AI'. | merchant: Cursor AI",
            "min_similarity": 0.0,
            "limit": 10,
        },
    )
    assert search_res.status_code == 200
    assert search_res.json()["count"] == 0


@pytest.mark.asyncio
async def test_retired_memories_excluded_from_semantic_search(
    async_client: AsyncClient,
):
    """Verify that retiring a memory removes it from semantic search results."""
    u_res = await async_client.post(
        "/api/v1/users",
        json={"external_reference": "sem_ret_u", "status": "ACTIVE"},
    )
    user_id = u_res.json()["id"]

    m_res = await async_client.post(
        "/api/v1/merchants",
        json={"name": "Vercel", "external_reference": "sem_ret_m"},
    )
    merchant_id = m_res.json()["id"]

    tx_res = await async_client.post(
        "/api/v1/transactions",
        json={
            "user_id": user_id,
            "merchant_id": merchant_id,
            "amount": "40.00",
            "currency": "USD",
            "status": "CAPTURED",
            "transaction_type": "PURCHASE",
        },
    )
    mem_res = await async_client.post(f"/api/v1/memories/build/{tx_res.json()['id']}")
    mem_id = mem_res.json()["id"]

    query_text = (
        "type: ROUTINE_PATTERN | summary: Standard purchase of 40.00 USD with merchant"
        " 'Vercel'. | merchant: Vercel | amount: 40.0000 | currency: USD | tx_type:"
        " PURCHASE"
    )

    # 1. Search before retirement -> returns 1
    s1 = await async_client.post(
        "/api/v1/memories/search",
        json={"user_id": user_id, "query_text": query_text, "min_similarity": 0.5},
    )
    assert s1.json()["count"] == 1

    # 2. Retire the memory
    await async_client.post(f"/api/v1/memories/{mem_id}/retire")

    # 3. Search after retirement -> returns 0
    s2 = await async_client.post(
        "/api/v1/memories/search",
        json={"user_id": user_id, "query_text": query_text, "min_similarity": 0.5},
    )
    assert s2.json()["count"] == 0


@pytest.mark.asyncio
async def test_semantic_similarity_cannot_override_policy_block(
    async_client: AsyncClient,
):
    """Verify that a positive semantic memory CANNOT bypass a hard policy limit."""
    u_res = await async_client.post(
        "/api/v1/users",
        json={"external_reference": "sem_block_u", "status": "ACTIVE"},
    )
    user_id = u_res.json()["id"]

    m_res = await async_client.post(
        "/api/v1/merchants",
        json={"name": "AWS", "external_reference": "sem_block_m"},
    )
    merchant_id = m_res.json()["id"]

    # 1. Add strict policy: Max $50
    await async_client.post(
        "/api/v1/policies",
        json={
            "user_id": user_id,
            "name": "Max $50 AWS",
            "policy_type": "TRANSACTION_LIMIT",
            "status": "ACTIVE",
            "currency": "USD",
            "limit_amount": "50.0000",
            "rules": {},
        },
    )

    # 2. Create prior legitimate transaction & memory
    tx_res = await async_client.post(
        "/api/v1/transactions",
        json={
            "user_id": user_id,
            "merchant_id": merchant_id,
            "amount": "30.00",
            "currency": "USD",
            "status": "CAPTURED",
            "transaction_type": "PURCHASE",
        },
    )
    await async_client.post(f"/api/v1/memories/build/{tx_res.json()['id']}")

    # 3. Evaluate proposed action exceeding policy ($150.00)
    eval_res = await async_client.post(
        "/api/v1/decisions/evaluate",
        json={
            "user_id": user_id,
            "merchant_id": merchant_id,
            "amount": "150.00",
            "currency": "USD",
            "transaction_type": "PURCHASE",
        },
    )
    assert eval_res.status_code == 200
    data = eval_res.json()
    # Hard guardrail MUST BLOCK despite presence of favorable memory context
    assert data["decision"] == DecisionOutcome.BLOCK.value
    assert data["reason_code"] == "POLICY_LIMIT_EXCEEDED"
    assert len(data["memory_context"]) == 1


@pytest.mark.asyncio
async def test_semantic_similarity_cannot_override_mandate_block(
    async_client: AsyncClient,
):
    """Verify that semantic memory CANNOT bypass mandate merchant mismatch."""
    u_res = await async_client.post(
        "/api/v1/users",
        json={"external_reference": "sem_mandate_u", "status": "ACTIVE"},
    )
    user_id = u_res.json()["id"]

    m1_res = await async_client.post(
        "/api/v1/merchants",
        json={"name": "Authorized Merchant", "external_reference": "sem_mandate_m1"},
    )
    m1_id = m1_res.json()["id"]

    m2_res = await async_client.post(
        "/api/v1/merchants",
        json={"name": "Unapproved Merchant", "external_reference": "sem_mandate_m2"},
    )
    m2_id = m2_res.json()["id"]

    # 1. Mandate scoped only to m1
    mandate_res = await async_client.post(
        "/api/v1/mandates",
        json={
            "user_id": user_id,
            "merchant_id": m1_id,
            "status": "ACTIVE",
            "currency": "USD",
            "max_transaction_amount": "500.0000",
        },
    )
    mandate_id = mandate_res.json()["id"]

    # 2. Evaluate with unapproved merchant m2
    eval_res = await async_client.post(
        "/api/v1/decisions/evaluate",
        json={
            "user_id": user_id,
            "merchant_id": m2_id,
            "mandate_id": mandate_id,
            "amount": "25.00",
            "currency": "USD",
            "transaction_type": "PURCHASE",
        },
    )
    assert eval_res.status_code == 200
    data = eval_res.json()
    assert data["decision"] == DecisionOutcome.BLOCK.value
    assert data["reason_code"] == "MANDATE_MERCHANT_MISMATCH"
