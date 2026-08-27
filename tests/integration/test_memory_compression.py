"""Integration tests for Day 9: Decision-Preserving Financial Memory Compression."""

import pytest
from httpx import AsyncClient

from app.models.enums import DecisionOutcome


@pytest.mark.asyncio
async def test_compression_api_endpoint_and_provenance(
    async_client: AsyncClient,
):
    """Verify POST /api/v1/memories/compress consolidates history and preserves source transactions."""
    u_res = await async_client.post(
        "/api/v1/users",
        json={"external_reference": "cmp_api_u1", "status": "ACTIVE"},
    )
    user_id = u_res.json()["id"]

    m_res = await async_client.post(
        "/api/v1/merchants",
        json={"name": "OpenAI API", "external_reference": "cmp_api_m1"},
    )
    merchant_id = m_res.json()["id"]

    # 1. Create 4 routine captured transactions
    tx_ids = []
    for amt in ["20.00", "20.00", "25.00", "20.00"]:
        tx_res = await async_client.post(
            "/api/v1/transactions",
            json={
                "user_id": user_id,
                "merchant_id": merchant_id,
                "amount": amt,
                "currency": "USD",
                "status": "CAPTURED",
                "transaction_type": "PURCHASE",
            },
        )
        assert tx_res.status_code == 201
        tx_ids.append(tx_res.json()["id"])

    # 2. Execute compression API
    cmp_res = await async_client.post(
        "/api/v1/memories/compress",
        json={"user_id": user_id, "lookback_days": 90},
    )
    assert cmp_res.status_code == 200
    data = cmp_res.json()
    assert data["source_event_count"] == 4
    assert data["memories_created"] == 1
    assert data["events_compressed"] == 4
    assert data["events_preserved"] == 0
    assert data["compression_ratio"] == 4.0
    assert data["compression_percentage"] == 75.0

    # 3. Retrieve compressed memory & check provenance
    list_res = await async_client.get(f"/api/v1/memories?user_id={user_id}")
    assert list_res.status_code == 200
    mems = list_res.json()["memories"]
    assert len(mems) == 1
    mem = mems[0]
    assert len(mem["sources"]) == 4
    source_tx_ids = {s["source_id"] for s in mem["sources"]}
    assert source_tx_ids == set(tx_ids)

    # 4. Verify raw transactions STILL EXIST (permanence)
    for tid in tx_ids:
        t_res = await async_client.get(f"/api/v1/transactions/{tid}")
        assert t_res.status_code == 200
        assert t_res.json()["status"] == "CAPTURED"


@pytest.mark.asyncio
async def test_cross_user_isolation_in_compression(
    async_client: AsyncClient,
):
    """Verify compressing User 1's history does not touch User 2's transactions or memories."""
    u1_res = await async_client.post(
        "/api/v1/users",
        json={"external_reference": "cmp_iso_u1", "status": "ACTIVE"},
    )
    user1_id = u1_res.json()["id"]

    u2_res = await async_client.post(
        "/api/v1/users",
        json={"external_reference": "cmp_iso_u2", "status": "ACTIVE"},
    )
    user2_id = u2_res.json()["id"]

    m_res = await async_client.post(
        "/api/v1/merchants",
        json={"name": "Supabase", "external_reference": "cmp_iso_m"},
    )
    merchant_id = m_res.json()["id"]

    # Create 2 transactions for User 2
    for _ in range(2):
        await async_client.post(
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

    # Compress User 1 (who has 0 transactions)
    cmp_u1 = await async_client.post(
        "/api/v1/memories/compress",
        json={"user_id": user1_id, "lookback_days": 90},
    )
    assert cmp_u1.json()["source_event_count"] == 0
    assert cmp_u1.json()["memories_created"] == 0

    # Verify User 2 has 0 memories until explicitly compressed
    list_u2 = await async_client.get(f"/api/v1/memories?user_id={user2_id}")
    assert list_u2.json()["count"] == 0


@pytest.mark.asyncio
async def test_safety_preservation_decision_invariants_across_compression(
    async_client: AsyncClient,
):
    """REGRESSION SAFETY TEST: Full Source History vs Compressed Decision Memory.

    Demonstrates that deterministic safety guardrails produce identical BLOCK/ASK_USER/ALLOW
    decisions regardless of whether memory is uncompressed or consolidated.
    """
    u_res = await async_client.post(
        "/api/v1/users",
        json={"external_reference": "cmp_safe_u", "status": "ACTIVE"},
    )
    user_id = u_res.json()["id"]

    m_res = await async_client.post(
        "/api/v1/merchants",
        json={"name": "Cloudflare", "external_reference": "cmp_safe_m"},
    )
    merchant_id = m_res.json()["id"]

    # 1. Setup Policy ($50.00 Limit)
    await async_client.post(
        "/api/v1/policies",
        json={
            "user_id": user_id,
            "name": "Cloudflare Cap",
            "policy_type": "TRANSACTION_LIMIT",
            "status": "ACTIVE",
            "currency": "USD",
            "limit_amount": "50.0000",
            "rules": {},
        },
    )

    # 2. Setup Mandate ($100.00 max limit)
    await async_client.post(
        "/api/v1/mandates",
        json={
            "user_id": user_id,
            "merchant_id": merchant_id,
            "max_transaction_amount": "100.0000",
            "currency": "USD",
            "status": "ACTIVE",
        },
    )

    # 3. Create 3 routine transactions ($20.00 each)
    for _ in range(3):
        await async_client.post(
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

    # 4. Scenario A: Policy Limit Violation ($80.00 > $50.00 cap) BEFORE compression
    eval_pre = await async_client.post(
        "/api/v1/decisions/evaluate",
        json={
            "user_id": user_id,
            "merchant_id": merchant_id,
            "amount": "80.00",
            "currency": "USD",
            "transaction_type": "PURCHASE",
        },
    )
    assert eval_pre.status_code == 200
    assert eval_pre.json()["decision"] == DecisionOutcome.BLOCK.value
    assert eval_pre.json()["reason_code"] == "POLICY_LIMIT_EXCEEDED"

    # 5. Execute Memory Compression
    cmp_res = await async_client.post(
        "/api/v1/memories/compress",
        json={"user_id": user_id, "lookback_days": 90},
    )
    assert cmp_res.status_code == 200
    assert cmp_res.json()["events_compressed"] == 3

    # 6. Scenario B: Policy Limit Violation ($80.00 > $50.00 cap) AFTER compression
    eval_post = await async_client.post(
        "/api/v1/decisions/evaluate",
        json={
            "user_id": user_id,
            "merchant_id": merchant_id,
            "amount": "80.00",
            "currency": "USD",
            "transaction_type": "PURCHASE",
        },
    )
    assert eval_post.status_code == 200
    # DECISION A == DECISION B: Exactly BLOCK
    assert eval_post.json()["decision"] == DecisionOutcome.BLOCK.value
    assert eval_post.json()["reason_code"] == "POLICY_LIMIT_EXCEEDED"
    assert len(eval_post.json()["memory_context"]) == 1

    # 7. Scenario C: Price Drift ($30.00 vs $20.00 baseline = +50% > 25%) -> ASK_USER
    eval_drift = await async_client.post(
        "/api/v1/decisions/evaluate",
        json={
            "user_id": user_id,
            "merchant_id": merchant_id,
            "amount": "30.00",
            "currency": "USD",
            "transaction_type": "PURCHASE",
        },
    )
    assert eval_drift.status_code == 200
    assert eval_drift.json()["decision"] == DecisionOutcome.ASK_USER.value
    assert eval_drift.json()["reason_code"] == "SIGNIFICANT_PRICE_DRIFT"

    # 8. Scenario D: Valid Routine Purchase within drift tolerance ($22.00 vs $20.00 baseline = +10% < 25%) -> ALLOW
    eval_allow = await async_client.post(
        "/api/v1/decisions/evaluate",
        json={
            "user_id": user_id,
            "merchant_id": merchant_id,
            "amount": "22.00",
            "currency": "USD",
            "transaction_type": "PURCHASE",
        },
    )
    assert eval_allow.status_code == 200
    assert eval_allow.json()["decision"] == DecisionOutcome.ALLOW.value
    assert eval_allow.json()["reason_code"] == "DETERMINISTIC_RULES_PASSED"
