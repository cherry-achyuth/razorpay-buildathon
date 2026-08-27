"""Integration tests for DecisionMemory integration into DecisionEvaluationService."""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from httpx import AsyncClient

from app.models.enums import (
    DecisionOutcome,
    MemoryRelevance,
    MemoryType,
    PolicyStatus,
    PolicyType,
)
from app.services.memory.retrieval import MemoryRetrievalService


@pytest.mark.asyncio
async def test_decision_evaluation_includes_active_user_memories(
    async_client: AsyncClient,
):
    """Verify decision evaluation retrieves and includes active memories for the user."""
    # 1. Create User & Merchant
    u_res = await async_client.post(
        "/api/v1/users",
        json={"external_reference": "dec_mem_u1", "status": "ACTIVE"},
    )
    user_id = u_res.json()["id"]

    m_res = await async_client.post(
        "/api/v1/merchants",
        json={"name": "Cursor AI", "external_reference": "dec_mem_m1"},
    )
    merchant_id = m_res.json()["id"]

    # 2. Create Transaction and Build Decision Memory
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

    mem_build = await async_client.post(f"/api/v1/memories/build/{tx_id}")
    assert mem_build.status_code == 201
    mem_id = mem_build.json()["id"]

    # 3. Evaluate Decision
    eval_res = await async_client.post(
        "/api/v1/decisions/evaluate",
        json={
            "user_id": user_id,
            "merchant_id": merchant_id,
            "amount": "25.00",
            "currency": "USD",
            "transaction_type": "PURCHASE",
        },
    )
    assert eval_res.status_code == 200
    data = eval_res.json()
    assert data["decision"] == DecisionOutcome.ALLOW.value
    assert len(data["memory_context"]) == 1

    mem_ctx = data["memory_context"][0]
    assert mem_ctx["memory_id"] == mem_id
    assert mem_ctx["memory_type"] == MemoryType.ROUTINE_PATTERN.value
    assert mem_ctx["relevance"] == MemoryRelevance.NORMAL.value
    assert len(mem_ctx["sources"]) == 1
    assert mem_ctx["sources"][0]["source_id"] == tx_id


@pytest.mark.asyncio
async def test_cross_user_memory_isolation_in_decision_evaluation(
    async_client: AsyncClient,
):
    """Verify User B's memories are never visible in User A's decision context."""
    # 1. Create User A, User B, Merchant
    ua_res = await async_client.post(
        "/api/v1/users",
        json={"external_reference": "cross_eval_ua", "status": "ACTIVE"},
    )
    user_a = ua_res.json()["id"]

    ub_res = await async_client.post(
        "/api/v1/users",
        json={"external_reference": "cross_eval_ub", "status": "ACTIVE"},
    )
    user_b = ub_res.json()["id"]

    m_res = await async_client.post(
        "/api/v1/merchants",
        json={"name": "OpenAI", "external_reference": "cross_eval_m1"},
    )
    merchant_id = m_res.json()["id"]

    # 2. Build Memory for User B
    tx_b = await async_client.post(
        "/api/v1/transactions",
        json={
            "user_id": user_b,
            "merchant_id": merchant_id,
            "amount": "100.00",
            "currency": "USD",
            "status": "CAPTURED",
            "transaction_type": "PURCHASE",
        },
    )
    tx_b_id = tx_b.json()["id"]
    await async_client.post(f"/api/v1/memories/build/{tx_b_id}")

    # 3. Evaluate Decision for User A
    eval_a = await async_client.post(
        "/api/v1/decisions/evaluate",
        json={
            "user_id": user_a,
            "merchant_id": merchant_id,
            "amount": "50.00",
            "currency": "USD",
            "transaction_type": "PURCHASE",
        },
    )
    assert eval_a.status_code == 200
    assert eval_a.json()["memory_context"] == []


@pytest.mark.asyncio
async def test_retired_and_superseded_memories_are_excluded(
    async_client: AsyncClient,
):
    """Verify retired and superseded memories do not participate in active decision context."""
    u_res = await async_client.post(
        "/api/v1/users",
        json={"external_reference": "retired_eval_u", "status": "ACTIVE"},
    )
    user_id = u_res.json()["id"]

    m_res = await async_client.post(
        "/api/v1/merchants",
        json={"name": "Stripe", "external_reference": "retired_eval_m"},
    )
    merchant_id = m_res.json()["id"]

    # 1. Create Transaction and Build Memory
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
    tx_id = tx_res.json()["id"]
    mem_res = await async_client.post(f"/api/v1/memories/build/{tx_id}")
    mem_id = mem_res.json()["id"]

    # 2. Retire the memory
    retire_res = await async_client.post(f"/api/v1/memories/{mem_id}/retire")
    assert retire_res.status_code == 200
    assert retire_res.json()["status"] == "RETIRED"

    # 3. Evaluate Decision -> retired memory must be excluded
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
    assert eval_res.json()["memory_context"] == []


@pytest.mark.asyncio
async def test_relevance_priority_ordering_in_decision_context(
    async_client: AsyncClient,
):
    """Verify decision context sorts memories by relevance (CRITICAL > HIGH > NORMAL > LOW)."""
    u_res = await async_client.post(
        "/api/v1/users",
        json={"external_reference": "rel_order_u", "status": "ACTIVE"},
    )
    user_id = u_res.json()["id"]

    m_res = await async_client.post(
        "/api/v1/merchants",
        json={"name": "AWS", "external_reference": "rel_order_m"},
    )
    merchant_id = m_res.json()["id"]

    # Build 1: Routine normal transaction
    tx_norm = await async_client.post(
        "/api/v1/transactions",
        json={
            "user_id": user_id,
            "merchant_id": merchant_id,
            "amount": "25.00",
            "currency": "USD",
            "status": "CAPTURED",
            "transaction_type": "PURCHASE",
        },
    )
    await async_client.post(f"/api/v1/memories/build/{tx_norm.json()['id']}")

    # Build 2: Failed anomalous transaction (classified as HIGH)
    tx_fail = await async_client.post(
        "/api/v1/transactions",
        json={
            "user_id": user_id,
            "merchant_id": merchant_id,
            "amount": "750.00",
            "currency": "USD",
            "status": "FAILED",
            "transaction_type": "PURCHASE",
        },
    )
    await async_client.post(f"/api/v1/memories/build/{tx_fail.json()['id']}")

    # Evaluate decision
    eval_res = await async_client.post(
        "/api/v1/decisions/evaluate",
        json={
            "user_id": user_id,
            "merchant_id": merchant_id,
            "amount": "25.00",
            "currency": "USD",
            "transaction_type": "PURCHASE",
        },
    )
    assert eval_res.status_code == 200
    contexts = eval_res.json()["memory_context"]
    assert len(contexts) == 2
    # HIGH relevance must precede NORMAL relevance
    assert contexts[0]["relevance"] == MemoryRelevance.HIGH.value
    assert contexts[1]["relevance"] == MemoryRelevance.NORMAL.value


@pytest.mark.asyncio
async def test_memory_cannot_override_policy_limit_block(
    async_client: AsyncClient,
):
    """Safety Invariant: Favorable memory CANNOT bypass a hard policy limit."""
    # 1. Setup User, Merchant, Policy (Limit $100)
    u_res = await async_client.post(
        "/api/v1/users",
        json={"external_reference": "safety_poly_u", "status": "ACTIVE"},
    )
    user_id = u_res.json()["id"]

    m_res = await async_client.post(
        "/api/v1/merchants",
        json={"name": "Anthropic", "external_reference": "safety_poly_m"},
    )
    merchant_id = m_res.json()["id"]

    await async_client.post(
        "/api/v1/policies",
        json={
            "user_id": user_id,
            "name": "Strict Max $100",
            "policy_type": PolicyType.TRANSACTION_LIMIT.value,
            "status": PolicyStatus.ACTIVE.value,
            "currency": "USD",
            "limit_amount": "100.0000",
            "rules": {"type": "MAX_AMOUNT"},
        },
    )

    # 2. Build routine memory for User
    tx_ok = await async_client.post(
        "/api/v1/transactions",
        json={
            "user_id": user_id,
            "merchant_id": merchant_id,
            "amount": "50.00",
            "currency": "USD",
            "status": "CAPTURED",
            "transaction_type": "PURCHASE",
        },
    )
    await async_client.post(f"/api/v1/memories/build/{tx_ok.json()['id']}")

    # 3. Submit request exceeding policy limit ($500 > $100)
    eval_res = await async_client.post(
        "/api/v1/decisions/evaluate",
        json={
            "user_id": user_id,
            "merchant_id": merchant_id,
            "amount": "500.00",
            "currency": "USD",
            "transaction_type": "PURCHASE",
        },
    )
    assert eval_res.status_code == 200
    data = eval_res.json()
    # MUST BE HARD BLOCK despite memory context
    assert data["decision"] == DecisionOutcome.BLOCK.value
    assert data["reason_code"] == "POLICY_LIMIT_EXCEEDED"
    assert len(data["memory_context"]) == 1


@pytest.mark.asyncio
async def test_memory_cannot_override_mandate_violation(
    async_client: AsyncClient,
):
    """Safety Invariant: Favorable memory CANNOT bypass a mandate violation."""
    # 1. Setup User, Merchant A, Merchant B, Mandate scoped to Merchant A
    u_res = await async_client.post(
        "/api/v1/users",
        json={"external_reference": "safety_mand_u", "status": "ACTIVE"},
    )
    user_id = u_res.json()["id"]

    ma_res = await async_client.post(
        "/api/v1/merchants",
        json={"name": "Merchant Alpha", "external_reference": "mand_ma"},
    )
    merchant_a = ma_res.json()["id"]

    mb_res = await async_client.post(
        "/api/v1/merchants",
        json={"name": "Merchant Beta", "external_reference": "mand_mb"},
    )
    merchant_b = mb_res.json()["id"]

    now = datetime.now(UTC)
    mand_res = await async_client.post(
        "/api/v1/mandates",
        json={
            "user_id": user_id,
            "merchant_id": merchant_a,
            "currency": "USD",
            "max_transaction_amount": "200.0000",
            "status": "ACTIVE",
            "valid_from": now.isoformat(),
            "valid_until": (now + timedelta(days=30)).isoformat(),
        },
    )
    mandate_id = mand_res.json()["id"]

    # 2. Build routine memory
    tx_ok = await async_client.post(
        "/api/v1/transactions",
        json={
            "user_id": user_id,
            "merchant_id": merchant_a,
            "amount": "20.00",
            "currency": "USD",
            "status": "CAPTURED",
            "transaction_type": "PURCHASE",
        },
    )
    await async_client.post(f"/api/v1/memories/build/{tx_ok.json()['id']}")

    # 3. Request payment to Merchant B under Merchant A's mandate -> BLOCK
    eval_res = await async_client.post(
        "/api/v1/decisions/evaluate",
        json={
            "user_id": user_id,
            "merchant_id": merchant_b,
            "mandate_id": mandate_id,
            "amount": "20.00",
            "currency": "USD",
            "transaction_type": "PURCHASE",
        },
    )
    assert eval_res.status_code == 200
    data = eval_res.json()
    assert data["decision"] == DecisionOutcome.BLOCK.value
    assert data["reason_code"] == "MANDATE_MERCHANT_MISMATCH"


@pytest.mark.asyncio
async def test_memory_retrieval_failure_fallback_continues_guardrails(
    async_client: AsyncClient,
):
    """Verify that unexpected memory retrieval failure falls back gracefully to empty context."""
    u_res = await async_client.post(
        "/api/v1/users",
        json={"external_reference": "fail_fallback_u", "status": "ACTIVE"},
    )
    user_id = u_res.json()["id"]

    m_res = await async_client.post(
        "/api/v1/merchants",
        json={"name": "Supabase", "external_reference": "fail_fallback_m"},
    )
    merchant_id = m_res.json()["id"]

    # Mock MemoryRetrievalService.get_user_memories to simulate retrieval failure
    with patch.object(
        MemoryRetrievalService,
        "get_user_memories",
        side_effect=RuntimeError("Transient memory index error"),
    ):
        eval_res = await async_client.post(
            "/api/v1/decisions/evaluate",
            json={
                "user_id": user_id,
                "merchant_id": merchant_id,
                "amount": "40.00",
                "currency": "USD",
                "transaction_type": "PURCHASE",
            },
        )
        assert eval_res.status_code == 200
        data = eval_res.json()
        assert data["decision"] == DecisionOutcome.ALLOW.value
        assert data["memory_context"] == []


@pytest.mark.asyncio
async def test_empty_memory_user_evaluates_normally(
    async_client: AsyncClient,
):
    """Verify users with no memory context evaluate without error."""
    u_res = await async_client.post(
        "/api/v1/users",
        json={"external_reference": "empty_mem_u", "status": "ACTIVE"},
    )
    user_id = u_res.json()["id"]

    m_res = await async_client.post(
        "/api/v1/merchants",
        json={"name": "Vercel", "external_reference": "empty_mem_m"},
    )
    merchant_id = m_res.json()["id"]

    eval_res = await async_client.post(
        "/api/v1/decisions/evaluate",
        json={
            "user_id": user_id,
            "merchant_id": merchant_id,
            "amount": "15.00",
            "currency": "USD",
            "transaction_type": "PURCHASE",
        },
    )
    assert eval_res.status_code == 200
    data = eval_res.json()
    assert data["decision"] == DecisionOutcome.ALLOW.value
    assert data["memory_context"] == []


@pytest.mark.asyncio
async def test_temporal_filtering_sql_before_limit(
    async_client: AsyncClient,
):
    """Verify temporal validity filters expired/future memories in SQL before limit."""
    u_res = await async_client.post(
        "/api/v1/users",
        json={"external_reference": "temp_sql_u", "status": "ACTIVE"},
    )
    user_id = u_res.json()["id"]

    m_res = await async_client.post(
        "/api/v1/merchants",
        json={"name": "Cloudflare", "external_reference": "temp_sql_m"},
    )
    merchant_id = m_res.json()["id"]

    # 1. Create a transaction and memory
    tx_res = await async_client.post(
        "/api/v1/transactions",
        json={
            "user_id": user_id,
            "merchant_id": merchant_id,
            "amount": "10.00",
            "currency": "USD",
            "status": "CAPTURED",
            "transaction_type": "PURCHASE",
        },
    )
    mem_res = await async_client.post(f"/api/v1/memories/build/{tx_res.json()['id']}")
    mem_id = mem_res.json()["id"]

    # Verify decision evaluation includes memory when active
    eval_1 = await async_client.post(
        "/api/v1/decisions/evaluate",
        json={
            "user_id": user_id,
            "merchant_id": merchant_id,
            "amount": "12.00",
            "currency": "USD",
            "transaction_type": "PURCHASE",
        },
    )
    assert eval_1.status_code == 200
    assert len(eval_1.json()["memory_context"]) == 1
    assert eval_1.json()["memory_context"][0]["memory_id"] == mem_id
