from decimal import Decimal

import pytest
from httpx import AsyncClient

from app.models.enums import MemoryRelevance, MemoryStatus, MemoryType


@pytest.mark.asyncio
async def test_build_memory_from_transaction_and_provenance(
    async_client: AsyncClient,
):
    """Verify building a memory from a valid transaction produces correct provenance."""
    # 1. Setup user, merchant, transaction
    u_res = await async_client.post(
        "/api/v1/users",
        json={"external_reference": "mem_user_01", "status": "ACTIVE"},
    )
    user_id = u_res.json()["id"]

    m_res = await async_client.post(
        "/api/v1/merchants",
        json={"name": "GitHub Copilot", "external_reference": "mem_merch_01"},
    )
    merchant_id = m_res.json()["id"]

    tx_res = await async_client.post(
        "/api/v1/transactions",
        json={
            "user_id": user_id,
            "merchant_id": merchant_id,
            "amount": "19.99",
            "currency": "USD",
            "status": "CAPTURED",
            "transaction_type": "PURCHASE",
            "idempotency_key": "mem_tx_key_01",
        },
    )
    tx_id = tx_res.json()["id"]

    # 2. Build memory
    mem_res = await async_client.post(f"/api/v1/memories/build/{tx_id}")
    assert mem_res.status_code == 201
    mem_data = mem_res.json()

    assert mem_data["user_id"] == user_id
    assert mem_data["memory_type"] == MemoryType.ROUTINE_PATTERN.value
    assert mem_data["relevance"] == MemoryRelevance.NORMAL.value
    assert mem_data["status"] == MemoryStatus.ACTIVE.value
    assert "GitHub Copilot" in mem_data["summary"]
    assert Decimal(mem_data["structured_data"]["amount"]) == Decimal("19.99")
    assert mem_data["structured_data"]["currency"] == "USD"

    # 3. Verify provenance source
    assert len(mem_data["sources"]) == 1
    source = mem_data["sources"][0]
    assert source["source_type"] == "TRANSACTION"
    assert source["source_id"] == tx_id


@pytest.mark.asyncio
async def test_idempotent_duplicate_memory_prevention(
    async_client: AsyncClient,
):
    """Verify repeated build calls on same source transaction return cached memory."""
    u_res = await async_client.post(
        "/api/v1/users",
        json={"external_reference": "mem_idem_user", "status": "ACTIVE"},
    )
    user_id = u_res.json()["id"]

    m_res = await async_client.post(
        "/api/v1/merchants",
        json={"name": "Docker Inc", "external_reference": "mem_merch_idem"},
    )
    merchant_id = m_res.json()["id"]

    tx_res = await async_client.post(
        "/api/v1/transactions",
        json={
            "user_id": user_id,
            "merchant_id": merchant_id,
            "amount": "25.00",
            "currency": "USD",
            "status": "CAPTURED",
        },
    )
    tx_id = tx_res.json()["id"]

    # First build
    res1 = await async_client.post(f"/api/v1/memories/build/{tx_id}")
    assert res1.status_code == 201
    mem_id1 = res1.json()["id"]

    # Second build (should return identical memory without creating duplicates)
    res2 = await async_client.post(f"/api/v1/memories/build/{tx_id}")
    assert res2.status_code == 201
    mem_id2 = res2.json()["id"]

    assert mem_id1 == mem_id2

    # Query all memories for user - must be exactly 1
    list_res = await async_client.get(f"/api/v1/memories?user_id={user_id}")
    assert list_res.status_code == 200
    assert list_res.json()["count"] == 1


@pytest.mark.asyncio
async def test_cross_user_isolation_protections(async_client: AsyncClient):
    """Verify User A cannot build or access User B's decision memory."""
    # User A
    u1_res = await async_client.post(
        "/api/v1/users",
        json={"external_reference": "mem_user_a", "status": "ACTIVE"},
    )
    user_a = u1_res.json()["id"]

    # User B
    u2_res = await async_client.post(
        "/api/v1/users",
        json={"external_reference": "mem_user_b", "status": "ACTIVE"},
    )
    user_b = u2_res.json()["id"]

    m_res = await async_client.post(
        "/api/v1/merchants",
        json={"name": "Cloudflare", "external_reference": "mem_merch_cross"},
    )
    merchant_id = m_res.json()["id"]

    # Transaction belongs to User A
    tx_res = await async_client.post(
        "/api/v1/transactions",
        json={
            "user_id": user_a,
            "merchant_id": merchant_id,
            "amount": "20.00",
            "currency": "USD",
            "status": "CAPTURED",
        },
    )
    tx_a_id = tx_res.json()["id"]

    # User B attempts to build memory from User A's transaction -> 403 Forbidden
    build_res = await async_client.post(
        f"/api/v1/memories/build/{tx_a_id}?user_id={user_b}"
    )
    assert build_res.status_code == 403
    assert build_res.json()["error_code"] == "CROSS_USER_ACCESS_DENIED"

    # User A builds memory successfully
    build_ok = await async_client.post(
        f"/api/v1/memories/build/{tx_a_id}?user_id={user_a}"
    )
    assert build_ok.status_code == 201
    mem_id = build_ok.json()["id"]

    # User B attempts to get User A's memory by ID -> 403 Forbidden
    get_res = await async_client.get(f"/api/v1/memories/{mem_id}?user_id={user_b}")
    assert get_res.status_code == 403
    assert get_res.json()["error_code"] == "CROSS_USER_ACCESS_DENIED"


@pytest.mark.asyncio
async def test_user_scoped_memory_retrieval_and_relevance_ordering(
    async_client: AsyncClient,
):
    """Verify user-scoped retrieval returns correctly sorted memories by relevance."""
    u_res = await async_client.post(
        "/api/v1/users",
        json={"external_reference": "mem_order_user", "status": "ACTIVE"},
    )
    user_id = u_res.json()["id"]

    m_res = await async_client.post(
        "/api/v1/merchants",
        json={"name": "Vercel", "external_reference": "mem_order_merch"},
    )
    merchant_id = m_res.json()["id"]

    # 1. Normal purchase
    tx1 = await async_client.post(
        "/api/v1/transactions",
        json={
            "user_id": user_id,
            "merchant_id": merchant_id,
            "amount": "20.00",
            "currency": "USD",
            "status": "CAPTURED",
        },
    )
    await async_client.post(f"/api/v1/memories/build/{tx1.json()['id']}")

    # 2. Failed purchase (HIGH relevance anomaly)
    tx2 = await async_client.post(
        "/api/v1/transactions",
        json={
            "user_id": user_id,
            "merchant_id": merchant_id,
            "amount": "150.00",
            "currency": "USD",
            "status": "FAILED",
        },
    )
    await async_client.post(f"/api/v1/memories/build/{tx2.json()['id']}")

    # Retrieve all memories
    list_res = await async_client.get(f"/api/v1/memories?user_id={user_id}")
    assert list_res.status_code == 200
    data = list_res.json()
    assert data["count"] == 2

    # HIGH relevance must be returned before NORMAL relevance
    assert data["memories"][0]["relevance"] == MemoryRelevance.HIGH.value
    assert data["memories"][0]["memory_type"] == MemoryType.ANOMALY_EVENT.value
    assert data["memories"][1]["relevance"] == MemoryRelevance.NORMAL.value


@pytest.mark.asyncio
async def test_memory_retirement_preserves_raw_source_transaction(
    async_client: AsyncClient,
):
    """Verify retiring a decision memory preserves the raw transaction intact."""
    u_res = await async_client.post(
        "/api/v1/users",
        json={"external_reference": "mem_retire_user", "status": "ACTIVE"},
    )
    user_id = u_res.json()["id"]

    m_res = await async_client.post(
        "/api/v1/merchants",
        json={"name": "Supabase", "external_reference": "mem_retire_merch"},
    )
    merchant_id = m_res.json()["id"]

    tx_res = await async_client.post(
        "/api/v1/transactions",
        json={
            "user_id": user_id,
            "merchant_id": merchant_id,
            "amount": "49.00",
            "currency": "USD",
            "status": "CAPTURED",
        },
    )
    tx_id = tx_res.json()["id"]

    # Build memory
    mem_res = await async_client.post(f"/api/v1/memories/build/{tx_id}")
    mem_id = mem_res.json()["id"]

    # Retire memory
    retire_res = await async_client.post(f"/api/v1/memories/{mem_id}/retire")
    assert retire_res.status_code == 200
    assert retire_res.json()["status"] == MemoryStatus.RETIRED.value

    # Verify raw transaction in PostgreSQL is unchanged
    tx_fetch = await async_client.get(f"/api/v1/transactions/{tx_id}")
    assert tx_fetch.status_code == 200
    tx_data = tx_fetch.json()
    assert tx_data["id"] == tx_id
    assert Decimal(tx_data["amount"]) == Decimal("49.00")
    assert tx_data["status"] == "CAPTURED"


@pytest.mark.asyncio
async def test_deterministic_rebuildability_of_decision_memory(
    async_client: AsyncClient,
):
    """Verify memory is deterministically reconstructed from source transaction."""
    u_res = await async_client.post(
        "/api/v1/users",
        json={"external_reference": "mem_rebuild_user", "status": "ACTIVE"},
    )
    user_id = u_res.json()["id"]

    m_res = await async_client.post(
        "/api/v1/merchants",
        json={"name": "Render Hosting", "external_reference": "mem_rebuild_merch"},
    )
    merchant_id = m_res.json()["id"]

    tx_res = await async_client.post(
        "/api/v1/transactions",
        json={
            "user_id": user_id,
            "merchant_id": merchant_id,
            "amount": "85.50",
            "currency": "USD",
            "status": "CAPTURED",
        },
    )
    tx_id = tx_res.json()["id"]

    # 1. Build initial memory
    mem1_res = await async_client.post(f"/api/v1/memories/build/{tx_id}")
    assert mem1_res.status_code == 201
    mem1 = mem1_res.json()

    # 2. Retire the initial memory
    await async_client.post(f"/api/v1/memories/{mem1['id']}/retire")

    # 3. Rebuild memory from source transaction
    mem2_res = await async_client.post(f"/api/v1/memories/build/{tx_id}")
    assert mem2_res.status_code == 201
    mem2 = mem2_res.json()

    # Compare decision-relevant fields (ignoring generated row UUIDs / timestamps)
    assert mem1["memory_type"] == mem2["memory_type"]
    assert mem1["relevance"] == mem2["relevance"]
    assert mem1["summary"] == mem2["summary"]
    assert mem1["structured_data"] == mem2["structured_data"]
    assert mem1["sources"][0]["source_type"] == mem2["sources"][0]["source_type"]
    assert mem1["sources"][0]["source_id"] == mem2["sources"][0]["source_id"]
