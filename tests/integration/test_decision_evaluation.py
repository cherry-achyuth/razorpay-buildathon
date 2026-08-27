"""Integration tests for POST /api/v1/decisions/evaluate endpoint."""

import uuid
from decimal import Decimal

import pytest
from httpx import AsyncClient

from app.models.enums import DecisionOutcome, PolicyType


@pytest.mark.asyncio
async def test_evaluate_action_allow(async_client: AsyncClient):
    """Test standard evaluation request resulting in ALLOW decision."""
    # 1. Setup user, merchant, mandate, policy
    user_res = await async_client.post(
        "/api/v1/users",
        json={"external_reference": "eval_user_01", "status": "ACTIVE"},
    )
    user_id = user_res.json()["id"]

    merch_res = await async_client.post(
        "/api/v1/merchants",
        json={"name": "Eval Merchant", "external_reference": "eval_merch_01"},
    )
    merch_id = merch_res.json()["id"]

    mandate_res = await async_client.post(
        "/api/v1/mandates",
        json={
            "user_id": user_id,
            "merchant_id": merch_id,
            "currency": "INR",
            "max_transaction_amount": "5000.00",
            "status": "ACTIVE",
        },
    )
    mandate_id = mandate_res.json()["id"]

    await async_client.post(
        "/api/v1/policies",
        json={
            "user_id": user_id,
            "name": "Single Tx Guardrail",
            "policy_type": PolicyType.TRANSACTION_LIMIT.value,
            "currency": "INR",
            "limit_amount": "4000.00",
            "status": "ACTIVE",
        },
    )

    # 2. Evaluate valid action (Amount 2500 <= 4000 <= 5000)
    req_payload = {
        "user_id": user_id,
        "merchant_id": merch_id,
        "mandate_id": mandate_id,
        "amount": "2500.00",
        "currency": "INR",
        "transaction_type": "PURCHASE",
    }
    eval_res = await async_client.post("/api/v1/decisions/evaluate", json=req_payload)
    assert eval_res.status_code == 200
    data = eval_res.json()
    assert data["decision"] == DecisionOutcome.ALLOW.value
    assert data["reason_code"] == "DETERMINISTIC_RULES_PASSED"
    assert len(data["rule_results"]) == 6
    assert all(r["status"] in ("PASS", "NOT_APPLICABLE") for r in data["rule_results"])

    # 3. Verify no transaction was created in transactions table
    tx_list = await async_client.get(f"/api/v1/transactions?user_id={user_id}")
    assert tx_list.status_code == 200
    assert len(tx_list.json()) == 0


@pytest.mark.asyncio
async def test_evaluate_action_blocks_on_policy_limit(
    async_client: AsyncClient,
):
    """Test proposed action blocked when exceeding policy single-transaction cap."""
    user_res = await async_client.post(
        "/api/v1/users",
        json={"external_reference": "eval_user_02", "status": "ACTIVE"},
    )
    user_id = user_res.json()["id"]

    merch_res = await async_client.post(
        "/api/v1/merchants",
        json={"name": "Eval Merchant 2", "external_reference": "eval_merch_02"},
    )
    merch_id = merch_res.json()["id"]

    mandate_res = await async_client.post(
        "/api/v1/mandates",
        json={
            "user_id": user_id,
            "currency": "INR",
            "max_transaction_amount": "10000.00",
            "status": "ACTIVE",
        },
    )
    mandate_id = mandate_res.json()["id"]

    await async_client.post(
        "/api/v1/policies",
        json={
            "user_id": user_id,
            "name": "Strict Budget Cap",
            "policy_type": PolicyType.TRANSACTION_LIMIT.value,
            "currency": "INR",
            "limit_amount": "3000.00",
            "status": "ACTIVE",
        },
    )

    # Evaluate action (Amount 3500 <= Mandate 10000 but > Policy 3000)
    req_payload = {
        "user_id": user_id,
        "merchant_id": merch_id,
        "mandate_id": mandate_id,
        "amount": "3500.00",
        "currency": "INR",
    }
    eval_res = await async_client.post("/api/v1/decisions/evaluate", json=req_payload)
    assert eval_res.status_code == 200
    data = eval_res.json()
    assert data["decision"] == DecisionOutcome.BLOCK.value
    assert data["reason_code"] == "POLICY_LIMIT_EXCEEDED"

    policy_result = next(
        r for r in data["rule_results"] if r["rule_id"] == "POLICY_LIMIT_GUARD"
    )
    assert policy_result["status"] == "FAIL"
    assert policy_result["decision_effect"] == "BLOCK"
    assert Decimal(policy_result["evidence"]["limit_amount"]) == Decimal("3000.00")


@pytest.mark.asyncio
async def test_evaluate_action_blocks_on_mandate_cap(
    async_client: AsyncClient,
):
    """Test proposed action blocked when exceeding mandate authorization cap."""
    user_res = await async_client.post(
        "/api/v1/users",
        json={"external_reference": "eval_user_03", "status": "ACTIVE"},
    )
    user_id = user_res.json()["id"]

    merch_res = await async_client.post(
        "/api/v1/merchants",
        json={"name": "Eval Merchant 3", "external_reference": "eval_merch_03"},
    )
    merch_id = merch_res.json()["id"]

    mandate_res = await async_client.post(
        "/api/v1/mandates",
        json={
            "user_id": user_id,
            "currency": "INR",
            "max_transaction_amount": "2000.00",
            "status": "ACTIVE",
        },
    )
    mandate_id = mandate_res.json()["id"]

    # Request exceeds mandate cap (Amount 2500 > Mandate 2000)
    req_payload = {
        "user_id": user_id,
        "merchant_id": merch_id,
        "mandate_id": mandate_id,
        "amount": "2500.00",
        "currency": "INR",
    }
    eval_res = await async_client.post("/api/v1/decisions/evaluate", json=req_payload)
    assert eval_res.status_code == 200
    data = eval_res.json()
    assert data["decision"] == DecisionOutcome.BLOCK.value
    assert data["reason_code"] == "MANDATE_AMOUNT_EXCEEDED"


@pytest.mark.asyncio
async def test_security_bypass_prevention(async_client: AsyncClient):
    """Verify that client-provided override or decision fields CANNOT bypass rules."""
    user_res = await async_client.post(
        "/api/v1/users",
        json={"external_reference": "sec_user_01", "status": "ACTIVE"},
    )
    user_id = user_res.json()["id"]

    merch_res = await async_client.post(
        "/api/v1/merchants",
        json={"name": "Sec Merchant", "external_reference": "sec_merch_01"},
    )
    merch_id = merch_res.json()["id"]

    mandate_res = await async_client.post(
        "/api/v1/mandates",
        json={
            "user_id": user_id,
            "currency": "INR",
            "max_transaction_amount": "1000.00",
            "status": "ACTIVE",
        },
    )
    mandate_id = mandate_res.json()["id"]

    # Adversarial agent attempts to force ALLOW or send override flags
    malicious_payload = {
        "user_id": user_id,
        "merchant_id": merch_id,
        "mandate_id": mandate_id,
        "amount": "99999.00",  # Grossly exceeds 1000 cap
        "currency": "INR",
        "decision": "ALLOW",  # Adversarial injection
        "override": True,  # Adversarial injection
        "force_allow": True,  # Adversarial injection
    }
    res = await async_client.post("/api/v1/decisions/evaluate", json=malicious_payload)
    assert res.status_code == 200
    data = res.json()
    # Must STILL be BLOCK
    assert data["decision"] == DecisionOutcome.BLOCK.value
    assert data["reason_code"] == "MANDATE_AMOUNT_EXCEEDED"


@pytest.mark.asyncio
async def test_evaluate_action_not_found_handling(async_client: AsyncClient):
    """Verify BLOCK decision returned when user or merchant does not exist."""
    fake_id = str(uuid.uuid4())
    valid_id = str(uuid.uuid4())

    # 1. Unknown user -> Immediate BLOCK
    res_user = await async_client.post(
        "/api/v1/decisions/evaluate",
        json={
            "user_id": fake_id,
            "merchant_id": valid_id,
            "amount": "100.00",
            "currency": "INR",
        },
    )
    assert res_user.status_code == 200
    data_user = res_user.json()
    assert data_user["decision"] == DecisionOutcome.BLOCK.value
    assert data_user["reason_code"] == "USER_NOT_FOUND"
    assert data_user["reason"] == "User account does not exist or is inactive."

    # Create real user
    u_res = await async_client.post(
        "/api/v1/users",
        json={"external_reference": "eval_u_exists", "status": "ACTIVE"},
    )
    real_user_id = u_res.json()["id"]

    # 2. Unknown merchant -> Immediate BLOCK
    res_merch = await async_client.post(
        "/api/v1/decisions/evaluate",
        json={
            "user_id": real_user_id,
            "merchant_id": fake_id,
            "amount": "100.00",
            "currency": "INR",
        },
    )
    assert res_merch.status_code == 200
    data_merch = res_merch.json()
    assert data_merch["decision"] == DecisionOutcome.BLOCK.value
    assert data_merch["reason_code"] == "MERCHANT_NOT_FOUND"
    assert data_merch["reason"] == "Merchant does not exist or is inactive."
