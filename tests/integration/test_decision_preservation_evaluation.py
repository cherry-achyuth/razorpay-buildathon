"""Integration tests for Day 11 & Day 12: Decision-Preservation Evaluation Framework."""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import (
    DecisionMismatchType,
    DecisionOutcome,
    MemoryRelevance,
    MemoryStatus,
    MemoryType,
    PolicyStatus,
    PolicyType,
    ScenarioSuite,
    TransactionStatus,
    TransactionType,
)
from app.models.merchant import Merchant
from app.models.policy import Policy
from app.models.transaction import Transaction
from app.models.user import User
from app.services.evaluation.decision_preservation import (
    DecisionPreservationService,
)
from app.services.evaluation.scenarios import (
    EvaluationScenarioDefinition,
)
from app.services.guardrails.base import DecisionMemoryContext
from app.services.memory.compression import MemoryCompressionService


@pytest.mark.asyncio
async def test_decision_preservation_evaluation_end_to_end(
    test_db_session: AsyncSession,
):
    """Verify standard evaluation suite produces 100% preservation on compatible history."""
    user = User(id=uuid.uuid4(), external_reference="eval_u1", status="ACTIVE")
    m_openai = Merchant(
        id=uuid.uuid4(), name="OpenAI", external_reference="eval_m_openai"
    )
    m_unknown = Merchant(
        id=uuid.uuid4(), name="UnknownMerchant", external_reference="eval_m_unk"
    )
    test_db_session.add_all([user, m_openai, m_unknown])

    # Add Policy: max $50.00 USD per transaction
    policy = Policy(
        id=uuid.uuid4(),
        user_id=user.id,
        name="USD 50 Limit",
        policy_type=PolicyType.TRANSACTION_LIMIT,
        status=PolicyStatus.ACTIVE,
        currency="USD",
        limit_amount=Decimal("50.0000"),
        rules={},
    )
    test_db_session.add(policy)

    # Add 4 historical routine captured transactions ($25.00 USD each, occurred in past)
    now = datetime.now(UTC)
    txs = [
        Transaction(
            id=uuid.uuid4(),
            user_id=user.id,
            merchant_id=m_openai.id,
            amount=Decimal("25.0000"),
            currency="USD",
            transaction_type=TransactionType.PURCHASE,
            status=TransactionStatus.CAPTURED,
            occurred_at=now - timedelta(days=i + 1),
        )
        for i in range(4)
    ]
    test_db_session.add_all(txs)
    await test_db_session.commit()

    # Run Memory Compression -> produces 1 compressed DecisionMemory
    comp_res = await MemoryCompressionService.compress_user_history(
        user_id=user.id,
        db=test_db_session,
    )
    assert comp_res.memories_created == 1

    # Run Decision Preservation Evaluation (Standard Suite)
    eval_service = DecisionPreservationService()
    report = await eval_service.run_evaluation(
        user_id=user.id,
        db=test_db_session,
        suite=ScenarioSuite.STANDARD,
        as_of=now,
    )

    assert report.total_scenarios == 5
    assert report.matching_decisions == 5
    assert report.mismatching_decisions == 0
    assert report.decision_preservation_rate == 1.0
    assert report.safety_critical_preservation_rate == 1.0
    assert report.false_allow_count == 0
    assert report.false_block_count == 0
    assert report.missed_block_count == 0


@pytest.mark.asyncio
async def test_adversarial_decision_preservation_suite(
    test_db_session: AsyncSession,
):
    """Verify Day 12 adversarial and boundary scenario suite execution."""
    user = User(id=uuid.uuid4(), external_reference="eval_u_adv", status="ACTIVE")
    m_primary = Merchant(
        id=uuid.uuid4(), name="PrimaryMerchant", external_reference="m_prim"
    )
    m_sec = Merchant(
        id=uuid.uuid4(), name="SecondaryMerchant", external_reference="m_sec"
    )
    m_unfam = Merchant(
        id=uuid.uuid4(), name="UnfamiliarMerchant", external_reference="m_unfam"
    )
    test_db_session.add_all([user, m_primary, m_sec, m_unfam])

    policy = Policy(
        id=uuid.uuid4(),
        user_id=user.id,
        name="USD 50 Limit",
        policy_type=PolicyType.TRANSACTION_LIMIT,
        status=PolicyStatus.ACTIVE,
        currency="USD",
        limit_amount=Decimal("50.0000"),
        rules={},
    )
    test_db_session.add(policy)

    now = datetime.now(UTC)
    # Add 10 routine transactions at primary merchant + 1 critical failed transaction
    routine_txs = [
        Transaction(
            id=uuid.uuid4(),
            user_id=user.id,
            merchant_id=m_primary.id,
            amount=Decimal("25.0000"),
            currency="USD",
            transaction_type=TransactionType.PURCHASE,
            status=TransactionStatus.CAPTURED,
            occurred_at=now - timedelta(days=i + 2),
        )
        for i in range(10)
    ]
    failed_tx = Transaction(
        id=uuid.uuid4(),
        user_id=user.id,
        merchant_id=m_primary.id,
        amount=Decimal("25.0000"),
        currency="USD",
        transaction_type=TransactionType.PURCHASE,
        status=TransactionStatus.FAILED,
        occurred_at=now - timedelta(days=1),
    )
    test_db_session.add_all(routine_txs + [failed_tx])
    await test_db_session.commit()

    # Run Memory Compression: routine txs are compressed; failed tx is preserved as critical memory
    comp_res = await MemoryCompressionService.compress_user_history(
        user_id=user.id,
        db=test_db_session,
    )
    assert (
        comp_res.memories_created >= 2
    )  # 1 routine aggregate + 1 critical failed memory

    # Run Adversarial Evaluation Suite
    eval_service = DecisionPreservationService()
    report = await eval_service.run_evaluation(
        user_id=user.id,
        db=test_db_session,
        suite=ScenarioSuite.ADVERSARIAL,
        as_of=now,
    )

    assert report.total_scenarios >= 10
    assert report.scenario_suite == ScenarioSuite.ADVERSARIAL.value
    assert report.critical_memory_recall == 1.0  # Failed tx provenance preserved
    assert report.decision_preservation_rate == 1.0
    assert report.safety_critical_preservation_rate == 1.0
    assert report.false_allow_count == 0
    assert report.false_block_count == 0
    assert report.missed_block_count == 0


@pytest.mark.asyncio
async def test_mismatch_detected_when_compressed_memory_is_damaged(
    test_db_session: AsyncSession,
):
    """Verify that damaged/missing memory produces a detectable mismatch (e.g. FALSE_ALLOW)."""
    user = User(id=uuid.uuid4(), external_reference="eval_u2", status="ACTIVE")
    merchant = Merchant(
        id=uuid.uuid4(), name="Anthropic", external_reference="eval_m_anthropic"
    )
    test_db_session.add_all([user, merchant])

    now = datetime.now(UTC)
    # Add 4 raw transactions ($20.00 USD each)
    txs = [
        Transaction(
            id=uuid.uuid4(),
            user_id=user.id,
            merchant_id=merchant.id,
            amount=Decimal("20.0000"),
            currency="USD",
            transaction_type=TransactionType.PURCHASE,
            status=TransactionStatus.CAPTURED,
            occurred_at=now - timedelta(days=i + 1),
        )
        for i in range(4)
    ]
    test_db_session.add_all(txs)
    await test_db_session.commit()

    # Scenario: Request $35.00 USD (+75% drift above $20 baseline)
    drift_scenario = EvaluationScenarioDefinition(
        scenario_id="SCENARIO_DRIFT_TEST",
        name="Price Drift Test",
        user_id=user.id,
        merchant_id=merchant.id,
        amount=Decimal("35.0000"),
        currency="USD",
    )

    # Damaged memory context: corrupted price baseline
    corrupted_memories = [
        DecisionMemoryContext(
            memory_id=uuid.uuid4(),
            memory_type=MemoryType.ROUTINE_PATTERN,
            relevance=MemoryRelevance.NORMAL,
            status=MemoryStatus.ACTIVE,
            summary="Corrupted summary without price data",
            structured_data={"corrupted_field": True},
        )
    ]

    eval_service = DecisionPreservationService()
    report = await eval_service.run_evaluation(
        user_id=user.id,
        db=test_db_session,
        scenarios=[drift_scenario],
        as_of=now,
        custom_memory_contexts=corrupted_memories,
    )

    # Result: FALSE_ALLOW is explicitly detected
    assert report.total_scenarios == 1
    assert report.matching_decisions == 0
    assert report.mismatching_decisions == 1
    assert report.decision_preservation_rate == 0.0
    assert report.false_allow_count == 1

    sc_res = report.scenarios[0]
    assert sc_res.full_history_decision == DecisionOutcome.ASK_USER
    assert sc_res.compressed_memory_decision == DecisionOutcome.ALLOW
    assert sc_res.mismatch_type == DecisionMismatchType.FALSE_ALLOW
    assert sc_res.safety_critical is True


@pytest.mark.asyncio
async def test_cross_user_isolation_in_evaluation(
    test_db_session: AsyncSession,
):
    """Verify that evaluation for User A is strictly isolated from User B's raw history and memories."""
    u_a = User(id=uuid.uuid4(), external_reference="eval_ua", status="ACTIVE")
    u_b = User(id=uuid.uuid4(), external_reference="eval_ub", status="ACTIVE")
    m = Merchant(id=uuid.uuid4(), name="Cloudflare", external_reference="eval_m_cf")
    test_db_session.add_all([u_a, u_b, m])

    now = datetime.now(UTC)
    # User B has transactions, but User A has none
    tx_b = Transaction(
        id=uuid.uuid4(),
        user_id=u_b.id,
        merchant_id=m.id,
        amount=Decimal("100.0000"),
        currency="USD",
        transaction_type=TransactionType.PURCHASE,
        status=TransactionStatus.CAPTURED,
        occurred_at=now,
    )
    test_db_session.add(tx_b)
    await test_db_session.commit()

    # Evaluate User A
    sc_a = EvaluationScenarioDefinition(
        scenario_id="SCENARIO_USER_A",
        name="User A Evaluation",
        user_id=u_a.id,
        merchant_id=m.id,
        amount=Decimal("20.0000"),
        currency="USD",
    )

    eval_service = DecisionPreservationService()
    report_a = await eval_service.run_evaluation(
        user_id=u_a.id,
        db=test_db_session,
        scenarios=[sc_a],
        as_of=now,
    )

    assert report_a.source_event_count == 0
    assert report_a.retained_memory_count == 0


@pytest.mark.asyncio
async def test_evaluation_api_endpoint_standard_and_adversarial(
    async_client: AsyncClient,
    test_db_session: AsyncSession,
):
    """Verify POST /api/v1/evaluations/decision-preservation endpoint with suite selection."""
    u_res = await async_client.post(
        "/api/v1/users",
        json={"external_reference": "eval_api_u_suite", "status": "ACTIVE"},
    )
    user_id = u_res.json()["id"]

    await async_client.post(
        "/api/v1/merchants",
        json={"name": "Twilio API", "external_reference": "eval_api_m_suite"},
    )

    # 1. Trigger Standard Suite
    std_res = await async_client.post(
        "/api/v1/evaluations/decision-preservation",
        json={"user_id": user_id, "scenario_suite": "STANDARD"},
    )
    assert std_res.status_code == 200
    std_data = std_res.json()
    assert std_data["scenario_suite"] == "STANDARD"
    assert std_data["total_scenarios"] == 5
    assert "critical_memory_recall" in std_data

    # 2. Trigger Adversarial Suite
    adv_res = await async_client.post(
        "/api/v1/evaluations/decision-preservation",
        json={"user_id": user_id, "scenario_suite": "ADVERSARIAL"},
    )
    assert adv_res.status_code == 200
    adv_data = adv_res.json()
    assert adv_data["scenario_suite"] == "ADVERSARIAL"
    assert adv_data["total_scenarios"] >= 10
    assert "critical_memory_recall" in adv_data

    # 3. Verify audit trail recorded both suites
    audit_res = await async_client.get(f"/api/v1/audit?user_id={user_id}")
    assert audit_res.status_code == 200
    events = audit_res.json()["records"]
    assert len(events) >= 2
    assert all(e["event_type"] == "DECISION_PRESERVATION_EVALUATED" for e in events)
