"""Integration tests for Day 4 safety controls."""

from decimal import Decimal

import pytest
from httpx import AsyncClient

from app.models.enums import DecisionOutcome, TransactionStatus, TransactionType


@pytest.mark.asyncio
async def test_duplicate_payment_detection_integration(
    async_client: AsyncClient,
):
    """Verify duplicate payment within sliding window is blocked."""
    # 1. Setup user & merchant
    user_res = await async_client.post(
        "/api/v1/users",
        json={"external_reference": "dup_user_01", "status": "ACTIVE"},
    )
    user_id = user_res.json()["id"]

    merch_res = await async_client.post(
        "/api/v1/merchants",
        json={
            "name": "Duplicate Test Store",
            "external_reference": "dup_merch_01",
        },
    )
    merch_id = merch_res.json()["id"]

    # 2. Record an authorized transaction
    await async_client.post(
        "/api/v1/transactions",
        json={
            "user_id": user_id,
            "merchant_id": merch_id,
            "amount": "650.00",
            "currency": "INR",
            "status": TransactionStatus.CAPTURED.value,
        },
    )

    # 3. Immediately propose identical financial action
    eval_res = await async_client.post(
        "/api/v1/decisions/evaluate",
        json={
            "user_id": user_id,
            "merchant_id": merch_id,
            "amount": "650.00",
            "currency": "INR",
            "transaction_type": TransactionType.PURCHASE.value,
        },
    )
    assert eval_res.status_code == 200
    data = eval_res.json()
    assert data["decision"] == DecisionOutcome.BLOCK.value
    assert data["reason_code"] == "DUPLICATE_PAYMENT_DETECTED"


@pytest.mark.asyncio
async def test_idempotency_exact_retry_and_tampering_conflict(
    async_client: AsyncClient,
):
    """Verify idempotent retry and payload tampering conflict."""
    user_res = await async_client.post(
        "/api/v1/users",
        json={"external_reference": "idem_int_user_01", "status": "ACTIVE"},
    )
    user_id = user_res.json()["id"]

    merch_res = await async_client.post(
        "/api/v1/merchants",
        json={
            "name": "Idem Test Merchant",
            "external_reference": "idem_merch_01",
        },
    )
    merch_id = merch_res.json()["id"]

    key = "unique_idem_key_7788"

    # 1. First evaluation request
    payload_original = {
        "user_id": user_id,
        "merchant_id": merch_id,
        "amount": "800.00",
        "currency": "INR",
        "idempotency_key": key,
    }
    res1 = await async_client.post("/api/v1/decisions/evaluate", json=payload_original)
    assert res1.status_code == 200
    data1 = res1.json()
    assert data1["decision"] == DecisionOutcome.ALLOW.value
    req_id = data1["request_id"]

    # 2. Exact retry with same idempotency key -> returns identical cached result
    res2 = await async_client.post("/api/v1/decisions/evaluate", json=payload_original)
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["request_id"] == req_id
    assert data2["decision"] == DecisionOutcome.ALLOW.value

    # 3. Tampered payload with same idempotency key (amount modified) -> BLOCK
    payload_tampered = {
        "user_id": user_id,
        "merchant_id": merch_id,
        "amount": "2500.00",  # Altered amount
        "currency": "INR",
        "idempotency_key": key,
    }
    res3 = await async_client.post("/api/v1/decisions/evaluate", json=payload_tampered)
    assert res3.status_code == 200
    data3 = res3.json()
    assert data3["decision"] == DecisionOutcome.BLOCK.value
    assert data3["reason_code"] == "IDEMPOTENCY_KEY_CONFLICT"


@pytest.mark.asyncio
async def test_price_drift_detection_integration(async_client: AsyncClient):
    """Verify significant upward price drift produces ASK_USER."""
    user_res = await async_client.post(
        "/api/v1/users",
        json={"external_reference": "drift_user_01", "status": "ACTIVE"},
    )
    user_id = user_res.json()["id"]

    merch_res = await async_client.post(
        "/api/v1/merchants",
        json={
            "name": "Drift Test Store",
            "external_reference": "drift_merch_01",
        },
    )
    merch_id = merch_res.json()["id"]

    # Record 3 historical transactions with amounts: [100.00, 100.00, 100.00]
    for i in range(3):
        await async_client.post(
            "/api/v1/transactions",
            json={
                "user_id": user_id,
                "merchant_id": merch_id,
                "amount": "100.00",
                "currency": "INR",
                "status": TransactionStatus.CAPTURED.value,
                "idempotency_key": f"drift_hist_{i}_{user_id}",
            },
        )

    # Propose action for 140.00 INR (+40% drift > 25% threshold)
    eval_res = await async_client.post(
        "/api/v1/decisions/evaluate",
        json={
            "user_id": user_id,
            "merchant_id": merch_id,
            "amount": "140.00",
            "currency": "INR",
        },
    )
    assert eval_res.status_code == 200
    data = eval_res.json()
    assert data["decision"] == DecisionOutcome.ASK_USER.value
    assert data["reason_code"] == "SIGNIFICANT_PRICE_DRIFT"

    drift_rule = next(
        r for r in data["rule_results"] if r["rule_id"] == "PRICE_DRIFT_GUARD"
    )
    assert drift_rule["status"] == "FAIL"
    assert drift_rule["decision_effect"] == "ASK_USER"
    assert Decimal(drift_rule["evidence"]["historical_baseline"]) == Decimal("100.00")


@pytest.mark.asyncio
async def test_merchant_change_detection_integration(
    async_client: AsyncClient,
):
    """Verify shifting to unfamiliar merchant with history produces ASK_USER."""
    user_res = await async_client.post(
        "/api/v1/users",
        json={"external_reference": "merch_chg_user_01", "status": "ACTIVE"},
    )
    user_id = user_res.json()["id"]

    merch_a = await async_client.post(
        "/api/v1/merchants",
        json={
            "name": "Established Merchant A",
            "external_reference": "merch_a_01",
        },
    )
    merch_a_id = merch_a.json()["id"]

    merch_b = await async_client.post(
        "/api/v1/merchants",
        json={"name": "New Merchant B", "external_reference": "merch_b_01"},
    )
    merch_b_id = merch_b.json()["id"]

    # Record 3 historical transactions with Merchant A
    for i in range(3):
        await async_client.post(
            "/api/v1/transactions",
            json={
                "user_id": user_id,
                "merchant_id": merch_a_id,
                "amount": "200.00",
                "currency": "INR",
                "status": TransactionStatus.CAPTURED.value,
                "idempotency_key": f"merch_hist_{i}_{user_id}",
            },
        )

    # Propose action with unfamiliar Merchant B
    eval_res = await async_client.post(
        "/api/v1/decisions/evaluate",
        json={
            "user_id": user_id,
            "merchant_id": merch_b_id,
            "amount": "200.00",
            "currency": "INR",
        },
    )
    assert eval_res.status_code == 200
    data = eval_res.json()
    assert data["decision"] == DecisionOutcome.ASK_USER.value
    assert data["reason_code"] == "UNEXPECTED_MERCHANT_CHANGE"


@pytest.mark.asyncio
async def test_concurrency_same_idempotency_key(async_client: AsyncClient):
    """Verify rapid requests with same idempotency key produce consistent responses."""
    user_res = await async_client.post(
        "/api/v1/users",
        json={"external_reference": "concurr_user_01", "status": "ACTIVE"},
    )
    user_id = user_res.json()["id"]

    merch_res = await async_client.post(
        "/api/v1/merchants",
        json={
            "name": "Concurr Store",
            "external_reference": "concurr_merch_01",
        },
    )
    merch_id = merch_res.json()["id"]

    payload = {
        "user_id": user_id,
        "merchant_id": merch_id,
        "amount": "450.00",
        "currency": "INR",
        "idempotency_key": "concurrent_test_key_999",
    }

    # Initial request
    res1 = await async_client.post("/api/v1/decisions/evaluate", json=payload)
    assert res1.status_code == 200
    data1 = res1.json()

    # Rapid retries
    res2 = await async_client.post("/api/v1/decisions/evaluate", json=payload)
    res3 = await async_client.post("/api/v1/decisions/evaluate", json=payload)

    assert res2.status_code == 200
    assert res3.status_code == 200
    assert res2.json()["request_id"] == data1["request_id"]
    assert res3.json()["request_id"] == data1["request_id"]
    assert res2.json()["decision"] == DecisionOutcome.ALLOW.value
    assert res3.json()["decision"] == DecisionOutcome.ALLOW.value
