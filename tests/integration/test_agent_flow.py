"""Integration tests for AI Buying Agent and Natural-Language Intent Resolution."""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

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
from app.models.mandate import Mandate
from app.models.merchant import Merchant
from app.models.policy import Policy
from app.models.transaction import Transaction
from app.models.user import User
from app.services.memory.compression import MemoryCompressionService


@pytest.fixture
async def agent_setup(test_db_session: AsyncSession) -> dict:
    """Setup a user with merchants, policies, mandates, and historical transactions."""
    user = User(
        id=uuid.uuid4(),
        external_reference="agent_test_user",
        status=UserStatus.ACTIVE,
    )
    test_db_session.add(user)

    merchant_cloud = Merchant(
        id=uuid.uuid4(),
        name="CloudCompute Global",
        external_reference="m_cloud_test",
        status=MerchantStatus.ACTIVE,
    )
    merchant_github = Merchant(
        id=uuid.uuid4(),
        name="GitHub Enterprise",
        external_reference="m_gh_test",
        status=MerchantStatus.ACTIVE,
    )
    test_db_session.add_all([merchant_cloud, merchant_github])
    await test_db_session.flush()

    # Policy: 100.00 Limit
    policy = Policy(
        id=uuid.uuid4(),
        user_id=user.id,
        name="Max 100 Limit",
        policy_type=PolicyType.TRANSACTION_LIMIT,
        status=PolicyStatus.ACTIVE,
        currency="INR",
        limit_amount=Decimal("100.0000"),
        rules={"max_per_tx": "100.00"},
    )
    # Mandate: 500.00 Max
    mandate = Mandate(
        id=uuid.uuid4(),
        user_id=user.id,
        merchant_id=merchant_cloud.id,
        currency="INR",
        max_transaction_amount=Decimal("500.0000"),
        status=MandateStatus.ACTIVE,
    )
    test_db_session.add_all([policy, mandate])
    await test_db_session.flush()

    # Historical transactions: 5 routine 25.00 INR bills spread over past 30 days
    now = datetime.now(UTC)
    for i, days_ago in enumerate([25, 20, 15, 10, 5]):
        tx = Transaction(
            id=uuid.uuid4(),
            user_id=user.id,
            merchant_id=merchant_cloud.id,
            mandate_id=mandate.id,
            amount=Decimal("25.0000"),
            currency="INR",
            transaction_type=TransactionType.PURCHASE,
            status=TransactionStatus.CAPTURED,
            external_reference=f"tx_hist_{i}",
            occurred_at=now - timedelta(days=days_ago),
        )
        test_db_session.add(tx)
    await test_db_session.flush()

    # Compress history to establish baseline routine memory
    await MemoryCompressionService.compress_user_history(
        user_id=user.id, db=test_db_session
    )
    await test_db_session.commit()

    return {
        "user_id": str(user.id),
        "cloud_id": str(merchant_cloud.id),
        "github_id": str(merchant_github.id),
    }


@pytest.mark.asyncio
async def test_agent_interpret_explicit_request(
    async_client: AsyncClient,
    agent_setup: dict,
) -> None:
    """Verify natural language request with explicit merchant and amount."""
    res = await async_client.post(
        "/api/v1/agent/interpret",
        json={
            "user_id": agent_setup["user_id"],
            "prompt": "Please pay 25 INR for CloudCompute Global server hosting",
            "currency": "INR",
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["merchant_name"] == "CloudCompute Global"
    assert data["merchant_id"] == agent_setup["cloud_id"]
    assert float(data["amount"]) == 25.00
    assert data["is_ambiguous"] is False


@pytest.mark.asyncio
async def test_agent_interpret_ambiguous_request(
    async_client: AsyncClient,
    agent_setup: dict,
) -> None:
    """Verify that underspecified or gibberish requests fail safely as ambiguous."""
    res = await async_client.post(
        "/api/v1/agent/interpret",
        json={
            "user_id": agent_setup["user_id"],
            "prompt": "hello buy stuff",
            "currency": "INR",
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["is_ambiguous"] is True
    assert data["ambiguity_reason"] is not None


@pytest.mark.asyncio
async def test_agent_evaluate_routine_allow_and_execute(
    async_client: AsyncClient,
    agent_setup: dict,
) -> None:
    """Verify end-to-end flow where request is ALLOWed and payment executes."""
    res = await async_client.post(
        "/api/v1/agent/evaluate",
        json={
            "user_id": agent_setup["user_id"],
            "prompt": "Pay my regular 25 INR to CloudCompute Global",
            "currency": "INR",
            "auto_execute_payment": True,
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["decision"] == DecisionOutcome.ALLOW.value
    assert data["payment_result"] is not None
    assert data["payment_result"]["status"] in ["SUCCESS", "CAPTURED", "SIMULATED"]
    assert "ALLOWED" in data["explanation"]


@pytest.mark.asyncio
async def test_agent_evaluate_policy_block(
    async_client: AsyncClient,
    agent_setup: dict,
) -> None:
    """Verify that agent request exceeding policy limit ($150 > $100 limit) is BLOCKED and no payment executes."""
    res = await async_client.post(
        "/api/v1/agent/evaluate",
        json={
            "user_id": agent_setup["user_id"],
            "prompt": "Buy 150 INR server upgrade on CloudCompute Global",
            "currency": "INR",
            "auto_execute_payment": True,
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["decision"] == DecisionOutcome.BLOCK.value
    assert data["payment_result"] is None
    assert "BLOCKED" in data["explanation"]


@pytest.mark.asyncio
async def test_agent_evaluate_price_drift_ask_user(
    async_client: AsyncClient,
    agent_setup: dict,
) -> None:
    """Verify that price drift ($65 vs $25 baseline) triggers ASK_USER and blocks payment until confirmation."""
    res = await async_client.post(
        "/api/v1/agent/evaluate",
        json={
            "user_id": agent_setup["user_id"],
            "prompt": "Pay 65 INR to CloudCompute Global",
            "currency": "INR",
            "auto_execute_payment": True,
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["decision"] == DecisionOutcome.ASK_USER.value
    assert data["payment_result"] is None
    assert "ASK_USER" in data["explanation"]


@pytest.mark.asyncio
async def test_demo_seed_endpoint(
    async_client: AsyncClient,
) -> None:
    """Verify POST /api/v1/demo/seed triggers deterministic seeding."""
    res = await async_client.post("/api/v1/demo/seed")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "SUCCESS"
    assert "demo_buildathon_user" in str(data["data"])


@pytest.mark.asyncio
async def test_agent_comparison_query(
    async_client: AsyncClient,
    agent_setup: dict,
) -> None:
    """Verify comparison query returns comparison_data breakdown without moving money."""
    res = await async_client.post(
        "/api/v1/agent/evaluate",
        json={
            "user_id": agent_setup["user_id"],
            "prompt": "Compare Netflix vs Amazon Prime cost per year",
            "currency": "INR",
            "auto_execute_payment": True,
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["decision"] == DecisionOutcome.ASK_USER.value
    assert data["payment_result"] is None
    assert data["comparison_data"] is not None
    assert len(data["comparison_data"]) >= 2
    assert "Netflix" in data["explanation"]
    assert "Amazon Prime" in data["explanation"]


@pytest.mark.asyncio
async def test_agent_auto_creates_new_merchant(
    async_client: AsyncClient,
    agent_setup: dict,
) -> None:
    """Verify dynamic real-world merchant auto-creation when a new merchant is requested."""
    res = await async_client.post(
        "/api/v1/agent/interpret",
        json={
            "user_id": agent_setup["user_id"],
            "prompt": "Pay 499 INR to Spotify Premium",
            "currency": "INR",
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert "Spotify" in data["merchant_name"]
    assert data["merchant_id"] is not None
    assert float(data["amount"]) == 499.00


@pytest.mark.asyncio
async def test_agent_interpret_then_evaluate_creates_exactly_one_merchant(
    async_client: AsyncClient,
    agent_setup: dict,
) -> None:
    """Verify calling interpret then evaluate for a new merchant yields exactly ONE merchant row in DB."""
    prompt = "Buy 250 INR groceries from Zepto Express"

    # Step 1: Call Interpret
    res_interp = await async_client.post(
        "/api/v1/agent/interpret",
        json={
            "user_id": agent_setup["user_id"],
            "prompt": prompt,
            "currency": "INR",
        },
    )
    assert res_interp.status_code == 200
    d_interp = res_interp.json()
    assert "Zepto" in d_interp["merchant_name"]
    merchant_id_1 = d_interp["merchant_id"]

    # Step 2: Call Evaluate
    res_eval = await async_client.post(
        "/api/v1/agent/evaluate",
        json={
            "user_id": agent_setup["user_id"],
            "prompt": prompt,
            "currency": "INR",
            "auto_execute_payment": False,
        },
    )
    assert res_eval.status_code == 200
    d_eval = res_eval.json()
    merchant_id_2 = d_eval["structured_intent"]["merchant_id"]

    assert merchant_id_1 == merchant_id_2

    # Step 3: Verify DB has exactly ONE record for Zepto
    m_list_res = await async_client.get("/api/v1/merchants")
    assert m_list_res.status_code == 200
    merchants = m_list_res.json()["merchants"]
    zepto_merchants = [m for m in merchants if "Zepto" in m["name"]]
    assert len(zepto_merchants) == 1
