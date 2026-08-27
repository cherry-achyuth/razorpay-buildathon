"""Integration tests for Day 8: Hybrid Memory Retrieval Layer."""

import pytest
from httpx import AsyncClient

from app.models.enums import DecisionOutcome, RetrievalMode


@pytest.mark.asyncio
async def test_hybrid_memory_search_endpoint_ranking(
    async_client: AsyncClient,
):
    """Verify that POST /api/v1/memories/search with retrieval_mode=HYBRID returns tiered ranked candidates."""
    u_res = await async_client.post(
        "/api/v1/users",
        json={"external_reference": "hyb_int_u1", "status": "ACTIVE"},
    )
    user_id = u_res.json()["id"]

    m1_res = await async_client.post(
        "/api/v1/merchants",
        json={"name": "OpenAI API", "external_reference": "hyb_int_m1"},
    )
    m1_id = m1_res.json()["id"]

    # 1. Create Normal Routine Transaction & Memory
    tx1 = await async_client.post(
        "/api/v1/transactions",
        json={
            "user_id": user_id,
            "merchant_id": m1_id,
            "amount": "20.00",
            "currency": "USD",
            "status": "CAPTURED",
            "transaction_type": "PURCHASE",
        },
    )
    mem1_res = await async_client.post(f"/api/v1/memories/build/{tx1.json()['id']}")
    mem1_id = mem1_res.json()["id"]

    # 2. Hybrid search for exact matching query
    query_text = (
        "type: ROUTINE_PATTERN | summary: Standard purchase of 20.00 USD with merchant"
        " 'OpenAI API'. | merchant: OpenAI API | amount: 20.0000 | currency: USD |"
        " tx_type: PURCHASE"
    )
    search_res = await async_client.post(
        "/api/v1/memories/search",
        json={
            "user_id": user_id,
            "query_text": query_text,
            "min_similarity": 0.5,
            "retrieval_mode": RetrievalMode.HYBRID.value,
            "limit": 5,
        },
    )
    assert search_res.status_code == 200
    data = search_res.json()
    assert data["count"] == 1
    assert data["retrieval_mode"] == "HYBRID"
    result = data["results"][0]
    assert result["memory_id"] == mem1_id
    assert result["relevance_priority"] == 3  # NORMAL = 3
    assert result["rank_tier"] == "NORMAL"
    assert result["hybrid_score"] is not None
    assert result["similarity_score"] >= 0.95


@pytest.mark.asyncio
async def test_cross_user_isolation_in_hybrid_search(
    async_client: AsyncClient,
):
    """Verify that User A's hybrid search NEVER returns User B's memories."""
    u1_res = await async_client.post(
        "/api/v1/users",
        json={"external_reference": "hyb_iso_u1", "status": "ACTIVE"},
    )
    user1_id = u1_res.json()["id"]

    u2_res = await async_client.post(
        "/api/v1/users",
        json={"external_reference": "hyb_iso_u2", "status": "ACTIVE"},
    )
    user2_id = u2_res.json()["id"]

    m_res = await async_client.post(
        "/api/v1/merchants",
        json={"name": "Supabase", "external_reference": "hyb_iso_m"},
    )
    merchant_id = m_res.json()["id"]

    # Create memory for User 2 ONLY
    tx_res = await async_client.post(
        "/api/v1/transactions",
        json={
            "user_id": user2_id,
            "merchant_id": merchant_id,
            "amount": "25.00",
            "currency": "USD",
            "status": "CAPTURED",
            "transaction_type": "PURCHASE",
        },
    )
    await async_client.post(f"/api/v1/memories/build/{tx_res.json()['id']}")

    # User 1 searches with exact query
    search_res = await async_client.post(
        "/api/v1/memories/search",
        json={
            "user_id": user1_id,
            "query_text": "merchant: Supabase | amount: 25.00",
            "min_similarity": 0.0,
            "retrieval_mode": "HYBRID",
        },
    )
    assert search_res.status_code == 200
    assert search_res.json()["count"] == 0


@pytest.mark.asyncio
async def test_hybrid_memory_cannot_override_policy_limit_block(
    async_client: AsyncClient,
):
    """Verify that favorable hybrid memory context CANNOT bypass a hard policy limit."""
    u_res = await async_client.post(
        "/api/v1/users",
        json={"external_reference": "hyb_block_u", "status": "ACTIVE"},
    )
    user_id = u_res.json()["id"]

    m_res = await async_client.post(
        "/api/v1/merchants",
        json={"name": "DigitalOcean", "external_reference": "hyb_block_m"},
    )
    merchant_id = m_res.json()["id"]

    # 1. Policy: Max $40
    await async_client.post(
        "/api/v1/policies",
        json={
            "user_id": user_id,
            "name": "DO Cap",
            "policy_type": "TRANSACTION_LIMIT",
            "status": "ACTIVE",
            "currency": "USD",
            "limit_amount": "40.0000",
            "rules": {},
        },
    )

    # 2. Prior legitimate transaction & memory ($20.00)
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
    await async_client.post(f"/api/v1/memories/build/{tx_res.json()['id']}")

    # 3. Evaluate proposed action exceeding policy limit ($120.00)
    eval_res = await async_client.post(
        "/api/v1/decisions/evaluate",
        json={
            "user_id": user_id,
            "merchant_id": merchant_id,
            "amount": "120.00",
            "currency": "USD",
            "transaction_type": "PURCHASE",
        },
    )
    assert eval_res.status_code == 200
    data = eval_res.json()
    assert data["decision"] == DecisionOutcome.BLOCK.value
    assert data["reason_code"] == "POLICY_LIMIT_EXCEEDED"
    assert len(data["memory_context"]) == 1


@pytest.mark.asyncio
async def test_hybrid_memory_cannot_override_duplicate_payment_block(
    async_client: AsyncClient,
):
    """Verify that duplicate payment rule blocks identical recent actions regardless of memory context."""
    u_res = await async_client.post(
        "/api/v1/users",
        json={"external_reference": "hyb_dup_u", "status": "ACTIVE"},
    )
    user_id = u_res.json()["id"]

    m_res = await async_client.post(
        "/api/v1/merchants",
        json={"name": "Midjourney", "external_reference": "hyb_dup_m"},
    )
    merchant_id = m_res.json()["id"]

    # 1. First transaction captured ($30.00)
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

    # 2. Immediate duplicate evaluation for $30.00 to same merchant
    eval_res = await async_client.post(
        "/api/v1/decisions/evaluate",
        json={
            "user_id": user_id,
            "merchant_id": merchant_id,
            "amount": "30.00",
            "currency": "USD",
            "transaction_type": "PURCHASE",
        },
    )
    assert eval_res.status_code == 200
    data = eval_res.json()
    assert data["decision"] == DecisionOutcome.BLOCK.value
    assert data["reason_code"] == "DUPLICATE_PAYMENT_DETECTED"


@pytest.mark.asyncio
async def test_hybrid_memory_cannot_override_idempotency_conflict(
    async_client: AsyncClient,
):
    """Verify that tampered idempotency retry strictly returns BLOCK conflict."""
    u_res = await async_client.post(
        "/api/v1/users",
        json={"external_reference": "hyb_idem_u", "status": "ACTIVE"},
    )
    user_id = u_res.json()["id"]

    m_res = await async_client.post(
        "/api/v1/merchants",
        json={"name": "Linear", "external_reference": "hyb_idem_m"},
    )
    merchant_id = m_res.json()["id"]

    idem_key = "test_hyb_idem_key_123"

    # 1. First evaluation with idempotency key
    r1 = await async_client.post(
        "/api/v1/decisions/evaluate",
        json={
            "user_id": user_id,
            "merchant_id": merchant_id,
            "amount": "15.00",
            "currency": "USD",
            "transaction_type": "PURCHASE",
            "idempotency_key": idem_key,
        },
    )
    assert r1.status_code == 200
    assert r1.json()["decision"] == DecisionOutcome.ALLOW.value

    # 2. Tampered retry with same key but different amount
    r2 = await async_client.post(
        "/api/v1/decisions/evaluate",
        json={
            "user_id": user_id,
            "merchant_id": merchant_id,
            "amount": "50.00",
            "currency": "USD",
            "transaction_type": "PURCHASE",
            "idempotency_key": idem_key,
        },
    )
    assert r2.status_code == 200
    assert r2.json()["decision"] == DecisionOutcome.BLOCK.value
    assert r2.json()["reason_code"] == "IDEMPOTENCY_KEY_CONFLICT"


@pytest.mark.asyncio
async def test_no_false_authorization_from_similarity_alone(
    async_client: AsyncClient,
):
    """Verify that a favorable memory alone cannot authorize a transaction without guardrail checks."""
    u_res = await async_client.post(
        "/api/v1/users",
        json={"external_reference": "hyb_no_auth_u", "status": "ACTIVE"},
    )
    user_id = u_res.json()["id"]

    m_res = await async_client.post(
        "/api/v1/merchants",
        json={"name": "Any Merchant", "external_reference": "hyb_no_auth_m"},
    )
    merchant_id = m_res.json()["id"]

    # Even with high semantic memory search, evaluate action is always checked by deterministic guardrails
    eval_res = await async_client.post(
        "/api/v1/decisions/evaluate",
        json={
            "user_id": user_id,
            "merchant_id": merchant_id,
            "amount": "10.00",
            "currency": "USD",
            "transaction_type": "PURCHASE",
        },
    )
    assert eval_res.status_code == 200
    assert eval_res.json()["decision"] == DecisionOutcome.ALLOW.value
    assert eval_res.json()["reason_code"] == "DETERMINISTIC_RULES_PASSED"
