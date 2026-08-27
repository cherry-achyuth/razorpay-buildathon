"""Integration tests for synthetic dataset database seeding and decision-preservation evaluation."""

from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import ScenarioSuite
from app.models.merchant import Merchant
from app.models.policy import Policy
from app.models.transaction import Transaction
from app.models.user import User
from app.services.evaluation.decision_preservation import (
    DecisionPreservationService,
)
from app.services.memory.compression import MemoryCompressionService
from experiments.synthetic import (
    DatasetConfig,
    DatasetScale,
    SyntheticDatasetGenerator,
    SyntheticScenarioType,
    seed_synthetic_dataset_to_db,
)


@pytest.mark.asyncio
async def test_synthetic_dataset_database_seeding(
    test_db_session: AsyncSession,
):
    """Test 16: Seed synthetic dataset into PostgreSQL/SQLite database and verify row counts."""
    cfg = DatasetConfig(
        seed=101,
        scale=DatasetScale.SMALL,  # 2 users, 20 txs/user
    )
    dataset = SyntheticDatasetGenerator.generate(cfg)

    result = await seed_synthetic_dataset_to_db(dataset, test_db_session)

    assert result.users_seeded == 2
    assert result.merchants_seeded == len(dataset.merchants)
    assert result.transactions_seeded == 40

    # Query DB directly to verify persistence
    users_count = await test_db_session.scalar(select(func.count(User.id)))
    merchants_count = await test_db_session.scalar(select(func.count(Merchant.id)))
    txs_count = await test_db_session.scalar(select(func.count(Transaction.id)))

    assert users_count == 2
    assert merchants_count == len(dataset.merchants)
    assert txs_count == 40


@pytest.mark.asyncio
async def test_seeded_data_referential_integrity_and_isolation(
    test_db_session: AsyncSession,
):
    """Test 17: Verify foreign keys, user isolation, and relationship integrity of seeded dataset."""
    cfg = DatasetConfig(
        seed=202,
        scale=DatasetScale.CUSTOM,
        num_users=2,
        transactions_per_user=15,
    )
    dataset = SyntheticDatasetGenerator.generate(cfg)
    await seed_synthetic_dataset_to_db(dataset, test_db_session)

    user1_id = dataset.users[0].id
    user2_id = dataset.users[1].id

    # Check User 1 transactions
    u1_txs = (
        await test_db_session.scalars(
            select(Transaction).where(Transaction.user_id == user1_id)
        )
    ).all()
    assert len(u1_txs) == 15

    # Check User 2 transactions
    u2_txs = (
        await test_db_session.scalars(
            select(Transaction).where(Transaction.user_id == user2_id)
        )
    ).all()
    assert len(u2_txs) == 15

    # Check Policies
    u1_policy = await test_db_session.scalar(
        select(Policy).where(Policy.user_id == user1_id)
    )
    assert u1_policy is not None
    assert u1_policy.limit_amount == Decimal("50.0000")


@pytest.mark.asyncio
async def test_seeded_routine_dataset_yields_full_preservation(
    test_db_session: AsyncSession,
):
    """Test 18: Routine synthetic history yields 100% decision preservation on adversarial suite."""
    from datetime import timedelta

    cfg = DatasetConfig(
        seed=303,
        scale=DatasetScale.CUSTOM,
        num_users=1,
        transactions_per_user=15,
        routine_amount=Decimal("25.0000"),
        policy_limit_amount=Decimal("50.0000"),
        scenario_mix=[SyntheticScenarioType.ROUTINE_PURCHASE],
    )
    dataset = SyntheticDatasetGenerator.generate(cfg)
    await seed_synthetic_dataset_to_db(dataset, test_db_session)

    user_id = dataset.users[0].id
    as_of_eval = max(t.occurred_at for t in dataset.transactions) + timedelta(days=1)

    # 1. Compress
    comp_res = await MemoryCompressionService.compress_user_history(
        user_id=user_id,
        db=test_db_session,
        as_of=as_of_eval,
    )
    assert comp_res.source_event_count == 15
    assert comp_res.memories_created == 1

    # 2. Evaluate
    eval_service = DecisionPreservationService()
    report = await eval_service.run_evaluation(
        user_id=user_id,
        db=test_db_session,
        suite=ScenarioSuite.ADVERSARIAL,
        as_of=as_of_eval,
    )

    assert report.total_scenarios >= 10
    assert report.decision_preservation_rate == 1.0
    assert report.safety_critical_preservation_rate == 1.0
    assert report.critical_memory_recall == 1.0


@pytest.mark.asyncio
async def test_seeded_mixed_dataset_compression_and_evaluation(
    test_db_session: AsyncSession,
):
    """Test 19: Mixed synthetic history preserves critical recall and exercises evaluation mismatch detection."""
    from datetime import timedelta

    cfg = DatasetConfig(
        seed=404,
        scale=DatasetScale.CUSTOM,
        num_users=1,
        transactions_per_user=20,
        routine_amount=Decimal("25.0000"),
        policy_limit_amount=Decimal("50.0000"),
        scenario_mix=[SyntheticScenarioType.MIXED_HISTORY],
    )
    dataset = SyntheticDatasetGenerator.generate(cfg)
    await seed_synthetic_dataset_to_db(dataset, test_db_session)

    user_id = dataset.users[0].id
    as_of_eval = max(t.occurred_at for t in dataset.transactions) + timedelta(days=1)

    # 1. Compress
    comp_res = await MemoryCompressionService.compress_user_history(
        user_id=user_id,
        db=test_db_session,
        as_of=as_of_eval,
    )
    assert comp_res.source_event_count == 20
    assert comp_res.memories_created >= 2

    # 2. Evaluate
    eval_service = DecisionPreservationService()
    report = await eval_service.run_evaluation(
        user_id=user_id,
        db=test_db_session,
        suite=ScenarioSuite.ADVERSARIAL,
        as_of=as_of_eval,
    )

    assert report.total_scenarios >= 10
    assert report.decision_preservation_rate >= 0.90
    assert report.critical_memory_recall == 1.0
