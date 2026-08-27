"""Integration tests for domain models, CRUD API routes, and relational integrity."""

import uuid
from decimal import Decimal

import pytest
from httpx import AsyncClient

from app.models.enums import (
    DecisionOutcome,
    MandateStatus,
    MerchantStatus,
    PolicyStatus,
    PolicyType,
    TransactionStatus,
    TransactionType,
    UserStatus,
)


@pytest.mark.asyncio
async def test_user_lifecycle(async_client: AsyncClient):
    """Test user creation, duplicate external ref handling, and retrieval."""
    # 1. Create user
    payload = {
        "external_reference": "test_ext_user_01",
        "status": UserStatus.ACTIVE.value,
    }
    res = await async_client.post("/api/v1/users", json=payload)
    assert res.status_code == 201
    user_data = res.json()
    user_id = user_data["id"]
    assert user_data["external_reference"] == "test_ext_user_01"
    assert user_data["status"] == UserStatus.ACTIVE.value

    # 2. Duplicate external_reference -> 409 Conflict
    dup_res = await async_client.post("/api/v1/users", json=payload)
    assert dup_res.status_code == 409
    assert dup_res.json()["error_code"] == "USER_ALREADY_EXISTS"

    # 3. Retrieve user by ID
    get_res = await async_client.get(f"/api/v1/users/{user_id}")
    assert get_res.status_code == 200
    assert get_res.json()["id"] == user_id

    # 4. List users
    list_res = await async_client.get("/api/v1/users")
    assert list_res.status_code == 200
    list_data = list_res.json()
    assert "users" in list_data
    assert list_data["count"] >= 1
    user_ids = [u["id"] for u in list_data["users"]]
    assert user_id in user_ids


@pytest.mark.asyncio
async def test_merchant_lifecycle(async_client: AsyncClient):
    """Test merchant creation, retrieval, and listing."""
    payload = {
        "name": "Acme Cloud Services",
        "external_reference": "merch_acme_01",
        "status": MerchantStatus.ACTIVE.value,
    }
    res = await async_client.post("/api/v1/merchants", json=payload)
    assert res.status_code == 201
    merch_data = res.json()
    merch_id = merch_data["id"]
    assert merch_data["name"] == "Acme Cloud Services"

    # Retrieve merchant by ID
    get_res = await async_client.get(f"/api/v1/merchants/{merch_id}")
    assert get_res.status_code == 200
    assert get_res.json()["id"] == merch_id

    # List merchants
    list_res = await async_client.get("/api/v1/merchants")
    assert list_res.status_code == 200
    list_data = list_res.json()
    assert "merchants" in list_data
    assert list_data["count"] >= 1
    merch_ids = [m["id"] for m in list_data["merchants"]]
    assert merch_id in merch_ids


@pytest.mark.asyncio
async def test_mandate_lifecycle_and_validation(async_client: AsyncClient):
    """Test mandate creation, foreign key checks, and retrieval."""
    # 1. Nonexistent user -> 404
    fake_user_id = str(uuid.uuid4())
    res_fake = await async_client.post(
        "/api/v1/mandates",
        json={
            "user_id": fake_user_id,
            "currency": "INR",
            "max_transaction_amount": "5000.00",
            "status": MandateStatus.ACTIVE.value,
        },
    )
    assert res_fake.status_code == 404
    assert res_fake.json()["error_code"] == "USER_NOT_FOUND"

    # 2. Create valid user and merchant
    user_res = await async_client.post(
        "/api/v1/users",
        json={"external_reference": "mandate_test_user", "status": "ACTIVE"},
    )
    user_id = user_res.json()["id"]

    merch_res = await async_client.post(
        "/api/v1/merchants",
        json={"name": "SaaS Platform", "external_reference": "merch_saas_01"},
    )
    merch_id = merch_res.json()["id"]

    # 3. Create valid mandate
    mandate_payload = {
        "user_id": user_id,
        "merchant_id": merch_id,
        "currency": "INR",
        "max_transaction_amount": "7500.50",
        "status": MandateStatus.ACTIVE.value,
    }
    mandate_res = await async_client.post("/api/v1/mandates", json=mandate_payload)
    assert mandate_res.status_code == 201
    mandate_data = mandate_res.json()
    mandate_id = mandate_data["id"]
    assert Decimal(mandate_data["max_transaction_amount"]) == Decimal("7500.5000")

    # 4. Retrieve mandate
    get_res = await async_client.get(f"/api/v1/mandates/{mandate_id}")
    assert get_res.status_code == 200
    assert get_res.json()["id"] == mandate_id


@pytest.mark.asyncio
async def test_policy_lifecycle(async_client: AsyncClient):
    """Test policy creation and retrieval."""
    # Create user
    user_res = await async_client.post(
        "/api/v1/users",
        json={"external_reference": "policy_test_user", "status": "ACTIVE"},
    )
    user_id = user_res.json()["id"]

    policy_payload = {
        "user_id": user_id,
        "name": "Daily AI Compute Limit",
        "policy_type": PolicyType.TRANSACTION_LIMIT.value,
        "status": PolicyStatus.ACTIVE.value,
        "currency": "USD",
        "limit_amount": "250.00",
        "rules": {"enforce_strict_daily": True},
    }
    res = await async_client.post("/api/v1/policies", json=policy_payload)
    assert res.status_code == 201
    policy_id = res.json()["id"]

    get_res = await async_client.get(f"/api/v1/policies/{policy_id}")
    assert get_res.status_code == 200
    assert get_res.json()["name"] == "Daily AI Compute Limit"


@pytest.mark.asyncio
async def test_transaction_lifecycle_and_invariants(async_client: AsyncClient):
    """Test transaction creation, mandate validation, idempotency, and filtering."""
    # 1. Setup user, merchant, and mandate
    user1_res = await async_client.post(
        "/api/v1/users",
        json={"external_reference": "tx_user_1", "status": "ACTIVE"},
    )
    user1_id = user1_res.json()["id"]

    user2_res = await async_client.post(
        "/api/v1/users",
        json={"external_reference": "tx_user_2", "status": "ACTIVE"},
    )
    user2_id = user2_res.json()["id"]

    merch_res = await async_client.post(
        "/api/v1/merchants",
        json={"name": "Hosting Provider", "external_reference": "tx_merch_1"},
    )
    merch_id = merch_res.json()["id"]

    mandate_res = await async_client.post(
        "/api/v1/mandates",
        json={
            "user_id": user1_id,
            "merchant_id": merch_id,
            "currency": "INR",
            "max_transaction_amount": "5000.00",
            "status": "ACTIVE",
        },
    )
    mandate_id = mandate_res.json()["id"]

    # 2. Mandate User Mismatch test (User 2 tries to use User 1's mandate)
    mismatch_res = await async_client.post(
        "/api/v1/transactions",
        json={
            "user_id": user2_id,
            "merchant_id": merch_id,
            "mandate_id": mandate_id,
            "amount": "100.00",
            "currency": "INR",
        },
    )
    assert mismatch_res.status_code == 400
    assert mismatch_res.json()["error_code"] == "MANDATE_USER_MISMATCH"

    # 3. Currency mismatch test (mandate is INR, tx requested is USD)
    curr_mismatch = await async_client.post(
        "/api/v1/transactions",
        json={
            "user_id": user1_id,
            "merchant_id": merch_id,
            "mandate_id": mandate_id,
            "amount": "100.00",
            "currency": "USD",
        },
    )
    assert curr_mismatch.status_code == 400
    assert curr_mismatch.json()["error_code"] == "CURRENCY_MISMATCH"

    # 4. Valid Transaction creation
    tx_payload = {
        "user_id": user1_id,
        "merchant_id": merch_id,
        "mandate_id": mandate_id,
        "amount": "1299.50",
        "currency": "INR",
        "transaction_type": TransactionType.PURCHASE.value,
        "status": TransactionStatus.AUTHORIZED.value,
        "idempotency_key": "idem_unique_test_101",
    }
    tx_res = await async_client.post("/api/v1/transactions", json=tx_payload)
    assert tx_res.status_code == 201
    tx_data = tx_res.json()
    tx_id = tx_data["id"]
    assert Decimal(tx_data["amount"]) == Decimal("1299.5000")

    # 5. Duplicate Idempotency Key -> 409 Conflict
    dup_idem_res = await async_client.post("/api/v1/transactions", json=tx_payload)
    assert dup_idem_res.status_code == 409
    assert dup_idem_res.json()["error_code"] == "DUPLICATE_IDEMPOTENCY_KEY"

    # 6. Retrieve transaction by ID
    get_tx_res = await async_client.get(f"/api/v1/transactions/{tx_id}")
    assert get_tx_res.status_code == 200
    assert get_tx_res.json()["id"] == tx_id

    # 7. List and filter transactions by user_id
    list_res = await async_client.get(f"/api/v1/transactions?user_id={user1_id}")
    assert list_res.status_code == 200
    records = list_res.json()
    assert len(records) >= 1
    assert all(r["user_id"] == user1_id for r in records)


@pytest.mark.asyncio
async def test_decision_lifecycle(async_client: AsyncClient):
    """Test recording and retrieving an authorization decision."""
    # 1. Setup user & merchant & transaction
    user_res = await async_client.post(
        "/api/v1/users",
        json={"external_reference": "decision_user_01", "status": "ACTIVE"},
    )
    user_id = user_res.json()["id"]

    merch_res = await async_client.post(
        "/api/v1/merchants",
        json={"name": "Decision Test Merchant", "external_reference": "dec_merch_01"},
    )
    merch_id = merch_res.json()["id"]

    tx_res = await async_client.post(
        "/api/v1/transactions",
        json={
            "user_id": user_id,
            "merchant_id": merch_id,
            "amount": "499.00",
            "currency": "INR",
            "status": "PENDING",
        },
    )
    tx_id = tx_res.json()["id"]

    # 2. Record Decision
    dec_payload = {
        "user_id": user_id,
        "transaction_id": tx_id,
        "request_reference": "req_agent_buy_001",
        "decision": DecisionOutcome.ALLOW.value,
        "reason": (
            "Transaction is within active daily budget limits and "
            "verified merchant profile."
        ),
        "evidence_metadata": {
            "evaluated_amount": "499.00",
            "budget_cap": "5000.00",
            "remaining": "4501.00",
        },
    }
    dec_res = await async_client.post("/api/v1/decisions", json=dec_payload)
    assert dec_res.status_code == 201
    dec_id = dec_res.json()["id"]

    # 3. Retrieve Decision
    get_dec_res = await async_client.get(f"/api/v1/decisions/{dec_id}")
    assert get_dec_res.status_code == 200
    dec_data = get_dec_res.json()
    assert dec_data["decision"] == DecisionOutcome.ALLOW.value
    assert dec_data["evidence_metadata"]["evaluated_amount"] == "499.00"
