"""Integration tests for payment API endpoints."""

import httpx
import pytest


@pytest.mark.asyncio
async def test_api_payment_gateway_status(async_client: httpx.AsyncClient) -> None:
    """Test GET /api/v1/payments/status returns gateway metadata."""
    res = await async_client.get("/api/v1/payments/status")
    assert res.status_code == 200
    data = res.json()
    assert "gateway" in data
    assert "mode" in data
    assert "currency_default" in data


@pytest.mark.asyncio
async def test_api_payment_execute_allow_flow(
    async_client: httpx.AsyncClient,
) -> None:
    """Test POST /api/v1/payments/execute on ALLOW produces payment receipt and captures transaction."""
    user_res = await async_client.post(
        "/api/v1/users",
        json={"external_reference": "api_pay_user_01", "status": "ACTIVE"},
    )
    user_id = user_res.json()["id"]

    merch_res = await async_client.post(
        "/api/v1/merchants",
        json={"name": "API Merchant", "external_reference": "api_m_01"},
    )
    merchant_id = merch_res.json()["id"]

    await async_client.post(
        "/api/v1/policies",
        json={
            "user_id": user_id,
            "name": "Allow Budget",
            "policy_type": "TRANSACTION_LIMIT",
            "currency": "INR",
            "limit_amount": "1000.0000",
        },
    )

    payload = {
        "user_id": user_id,
        "merchant_id": merchant_id,
        "amount": "25.0000",
        "currency": "INR",
        "transaction_type": "PURCHASE",
    }
    res = await async_client.post("/api/v1/payments/execute", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["decision"] == "ALLOW"
    assert data["status"] == "SUCCESS"
    assert data["transaction_id"] is not None
    assert data["gateway_order_id"] is not None


@pytest.mark.asyncio
async def test_api_payment_execute_block_flow(
    async_client: httpx.AsyncClient,
) -> None:
    """Test POST /api/v1/payments/execute on policy limit breach returns BLOCKED."""
    user_res = await async_client.post(
        "/api/v1/users",
        json={"external_reference": "api_pay_user_02", "status": "ACTIVE"},
    )
    user_id = user_res.json()["id"]

    merch_res = await async_client.post(
        "/api/v1/merchants",
        json={"name": "API Merchant", "external_reference": "api_m_02"},
    )
    merchant_id = merch_res.json()["id"]

    await async_client.post(
        "/api/v1/policies",
        json={
            "user_id": user_id,
            "name": "Small Limit",
            "policy_type": "TRANSACTION_LIMIT",
            "currency": "INR",
            "limit_amount": "20.0000",
        },
    )

    payload = {
        "user_id": user_id,
        "merchant_id": merchant_id,
        "amount": "50.0000",
        "currency": "INR",
        "transaction_type": "PURCHASE",
    }
    res = await async_client.post("/api/v1/payments/execute", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["decision"] == "BLOCK"
    assert data["status"] == "BLOCKED"
    assert data["transaction_id"] is None


@pytest.mark.asyncio
async def test_api_payment_execute_missing_user_or_merchant_returns_422(
    async_client: httpx.AsyncClient,
) -> None:
    """Test POST /api/v1/payments/execute with missing user or merchant rejects with HTTP 422."""
    import uuid

    fake_id = str(uuid.uuid4())

    # 1. Missing user
    res1 = await async_client.post(
        "/api/v1/payments/execute",
        json={
            "user_id": fake_id,
            "merchant_id": fake_id,
            "amount": "50.0000",
            "currency": "INR",
        },
    )
    assert res1.status_code == 422
    assert res1.json()["error_code"] == "USER_NOT_FOUND"

    # Create user
    user_res = await async_client.post(
        "/api/v1/users",
        json={"external_reference": "api_pay_u_422", "status": "ACTIVE"},
    )
    real_user_id = user_res.json()["id"]

    # 2. Missing merchant
    res2 = await async_client.post(
        "/api/v1/payments/execute",
        json={
            "user_id": real_user_id,
            "merchant_id": fake_id,
            "amount": "50.0000",
            "currency": "INR",
        },
    )
    assert res2.status_code == 422
    assert res2.json()["error_code"] == "MERCHANT_NOT_FOUND"
