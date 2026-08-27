"""Unit tests for deterministic financial memory compression."""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import (
    MemoryRelevance,
    MemoryStatus,
    MemoryType,
    TransactionStatus,
    TransactionType,
)
from app.models.merchant import Merchant
from app.models.transaction import Transaction
from app.models.user import User
from app.services.memory.compression import MemoryCompressionService
from app.services.memory.retrieval import MemoryRetrievalService


@pytest.mark.asyncio
async def test_compression_empty_history(test_db_session: AsyncSession):
    """Verify compression over empty history returns zero-metric result."""
    uid = uuid.uuid4()
    res = await MemoryCompressionService.compress_user_history(
        user_id=uid,
        db=test_db_session,
    )
    assert res.source_event_count == 0
    assert res.memories_created == 0
    assert res.memories_reused == 0
    assert res.events_compressed == 0
    assert res.events_preserved == 0
    assert res.compression_ratio == 1.0
    assert res.compression_percentage == 0.0
    assert res.status == "COMPLETED"


@pytest.mark.asyncio
async def test_compression_single_transaction(test_db_session: AsyncSession):
    """Verify a single transaction is preserved individually as a singleton memory."""
    user = User(id=uuid.uuid4(), external_reference="cmp_u1", status="ACTIVE")
    merchant = Merchant(id=uuid.uuid4(), name="Cloudflare", external_reference="cmp_m1")
    test_db_session.add_all([user, merchant])
    await test_db_session.flush()

    tx = Transaction(
        id=uuid.uuid4(),
        user_id=user.id,
        merchant_id=merchant.id,
        amount=Decimal("20.0000"),
        currency="USD",
        transaction_type=TransactionType.PURCHASE,
        status=TransactionStatus.CAPTURED,
        occurred_at=datetime.now(UTC),
    )
    test_db_session.add(tx)
    await test_db_session.commit()

    res = await MemoryCompressionService.compress_user_history(
        user_id=user.id,
        db=test_db_session,
    )
    assert res.source_event_count == 1
    assert res.memories_created == 1
    assert res.events_preserved == 1
    assert res.events_compressed == 0
    assert res.compression_ratio == 1.0


@pytest.mark.asyncio
async def test_compression_aggregates_compatible_routine_transactions(
    test_db_session: AsyncSession,
):
    """Verify multiple compatible routine purchases with the same merchant are consolidated."""
    user = User(id=uuid.uuid4(), external_reference="cmp_u2", status="ACTIVE")
    merchant = Merchant(id=uuid.uuid4(), name="OpenAI API", external_reference="cmp_m2")
    test_db_session.add_all([user, merchant])
    await test_db_session.flush()

    now = datetime.now(UTC)
    amounts = [Decimal("10.0000"), Decimal("20.0000"), Decimal("30.0000")]
    txs = [
        Transaction(
            id=uuid.uuid4(),
            user_id=user.id,
            merchant_id=merchant.id,
            amount=amt,
            currency="USD",
            transaction_type=TransactionType.PURCHASE,
            status=TransactionStatus.CAPTURED,
            occurred_at=now - timedelta(days=idx),
        )
        for idx, amt in enumerate(amounts)
    ]
    test_db_session.add_all(txs)
    await test_db_session.commit()

    res = await MemoryCompressionService.compress_user_history(
        user_id=user.id,
        db=test_db_session,
    )
    assert res.source_event_count == 3
    assert res.memories_created == 1
    assert res.events_compressed == 3
    assert res.events_preserved == 0
    assert res.compression_ratio == 3.0
    assert res.compression_percentage == 66.67

    # Retrieve memory and verify deterministic Decimal metrics
    memories = await MemoryRetrievalService.get_user_memories(
        user_id=user.id,
        db=test_db_session,
    )
    assert len(memories) == 1
    mem = memories[0]
    assert mem.memory_type == MemoryType.ROUTINE_PATTERN
    assert mem.relevance == MemoryRelevance.NORMAL
    assert mem.status == MemoryStatus.ACTIVE
    assert len(mem.sources) == 3

    # Check exact Decimal aggregations in structured data
    sd = mem.structured_data
    assert sd["source_event_count"] == 3
    assert sd["total_amount"] == "60.0000"
    assert sd["min_amount"] == "10.0000"
    assert sd["max_amount"] == "30.0000"
    assert sd["avg_amount"] == "20.0000"
    assert sd["is_compressed"] is True


@pytest.mark.asyncio
async def test_compression_separates_different_merchants_and_currencies(
    test_db_session: AsyncSession,
):
    """Verify transactions with different merchants or currencies are NOT merged together."""
    user = User(id=uuid.uuid4(), external_reference="cmp_u3", status="ACTIVE")
    m1 = Merchant(id=uuid.uuid4(), name="AWS", external_reference="cmp_m3a")
    m2 = Merchant(id=uuid.uuid4(), name="GitHub", external_reference="cmp_m3b")
    test_db_session.add_all([user, m1, m2])
    await test_db_session.flush()

    now = datetime.now(UTC)
    # AWS USD (2 txs)
    t1 = Transaction(
        id=uuid.uuid4(),
        user_id=user.id,
        merchant_id=m1.id,
        amount=Decimal("50.0000"),
        currency="USD",
        transaction_type=TransactionType.PURCHASE,
        status=TransactionStatus.CAPTURED,
        occurred_at=now,
    )
    t2 = Transaction(
        id=uuid.uuid4(),
        user_id=user.id,
        merchant_id=m1.id,
        amount=Decimal("60.0000"),
        currency="USD",
        transaction_type=TransactionType.PURCHASE,
        status=TransactionStatus.CAPTURED,
        occurred_at=now - timedelta(days=1),
    )
    # AWS EUR (1 tx)
    t3 = Transaction(
        id=uuid.uuid4(),
        user_id=user.id,
        merchant_id=m1.id,
        amount=Decimal("45.0000"),
        currency="EUR",
        transaction_type=TransactionType.PURCHASE,
        status=TransactionStatus.CAPTURED,
        occurred_at=now - timedelta(days=2),
    )
    # GitHub USD (2 txs)
    t4 = Transaction(
        id=uuid.uuid4(),
        user_id=user.id,
        merchant_id=m2.id,
        amount=Decimal("10.0000"),
        currency="USD",
        transaction_type=TransactionType.PURCHASE,
        status=TransactionStatus.CAPTURED,
        occurred_at=now - timedelta(days=3),
    )
    t5 = Transaction(
        id=uuid.uuid4(),
        user_id=user.id,
        merchant_id=m2.id,
        amount=Decimal("10.0000"),
        currency="USD",
        transaction_type=TransactionType.PURCHASE,
        status=TransactionStatus.CAPTURED,
        occurred_at=now - timedelta(days=4),
    )
    test_db_session.add_all([t1, t2, t3, t4, t5])
    await test_db_session.commit()

    res = await MemoryCompressionService.compress_user_history(
        user_id=user.id,
        db=test_db_session,
    )
    assert res.source_event_count == 5
    # 3 distinct groups: AWS USD (2 compressed), AWS EUR (1 preserved), GitHub USD (2 compressed)
    assert res.memories_created == 3
    assert res.events_compressed == 4
    assert res.events_preserved == 1
    assert res.compression_ratio == 1.67


@pytest.mark.asyncio
async def test_compression_preserves_safety_critical_and_failed_events(
    test_db_session: AsyncSession,
):
    """Verify failed transactions and anomaly events are NEVER absorbed into routine aggregates."""
    user = User(id=uuid.uuid4(), external_reference="cmp_u4", status="ACTIVE")
    merchant = Merchant(id=uuid.uuid4(), name="Stripe", external_reference="cmp_m4")
    test_db_session.add_all([user, merchant])
    await test_db_session.flush()

    now = datetime.now(UTC)
    # 2 routine captured purchases
    t1 = Transaction(
        id=uuid.uuid4(),
        user_id=user.id,
        merchant_id=merchant.id,
        amount=Decimal("15.0000"),
        currency="USD",
        transaction_type=TransactionType.PURCHASE,
        status=TransactionStatus.CAPTURED,
        occurred_at=now,
    )
    t2 = Transaction(
        id=uuid.uuid4(),
        user_id=user.id,
        merchant_id=merchant.id,
        amount=Decimal("15.0000"),
        currency="USD",
        transaction_type=TransactionType.PURCHASE,
        status=TransactionStatus.CAPTURED,
        occurred_at=now - timedelta(days=1),
    )
    # 1 failed transaction (anomaly)
    t3_fail = Transaction(
        id=uuid.uuid4(),
        user_id=user.id,
        merchant_id=merchant.id,
        amount=Decimal("100.0000"),
        currency="USD",
        transaction_type=TransactionType.PURCHASE,
        status=TransactionStatus.FAILED,
        occurred_at=now - timedelta(days=2),
    )
    # 1 chargeback (critical anomaly)
    t4_cb = Transaction(
        id=uuid.uuid4(),
        user_id=user.id,
        merchant_id=merchant.id,
        amount=Decimal("50.0000"),
        currency="USD",
        transaction_type=TransactionType.CHARGEBACK,
        status=TransactionStatus.REFUNDED,
        occurred_at=now - timedelta(days=3),
    )
    test_db_session.add_all([t1, t2, t3_fail, t4_cb])
    await test_db_session.commit()

    res = await MemoryCompressionService.compress_user_history(
        user_id=user.id,
        db=test_db_session,
    )
    assert res.source_event_count == 4
    # 1 compressed memory (t1 + t2) + 2 dedicated safety memories (t3_fail + t4_cb)
    assert res.memories_created == 3
    assert res.events_compressed == 2
    assert res.events_preserved == 2

    # Verify active memories
    memories = await MemoryRetrievalService.get_user_memories(
        user_id=user.id,
        db=test_db_session,
    )
    assert len(memories) == 3
    relevances = {m.relevance for m in memories}
    assert MemoryRelevance.HIGH in relevances
    assert MemoryRelevance.NORMAL in relevances


@pytest.mark.asyncio
async def test_compression_idempotent_repeated_execution(
    test_db_session: AsyncSession,
):
    """Verify running compression twice against unchanged history does NOT create duplicate memories."""
    user = User(id=uuid.uuid4(), external_reference="cmp_u5", status="ACTIVE")
    merchant = Merchant(id=uuid.uuid4(), name="Vercel", external_reference="cmp_m5")
    test_db_session.add_all([user, merchant])
    await test_db_session.flush()

    now = datetime.now(UTC)
    txs = [
        Transaction(
            id=uuid.uuid4(),
            user_id=user.id,
            merchant_id=merchant.id,
            amount=Decimal("20.0000"),
            currency="USD",
            transaction_type=TransactionType.PURCHASE,
            status=TransactionStatus.CAPTURED,
            occurred_at=now - timedelta(days=i),
        )
        for i in range(3)
    ]
    test_db_session.add_all(txs)
    await test_db_session.commit()

    # First run
    r1 = await MemoryCompressionService.compress_user_history(
        user_id=user.id,
        db=test_db_session,
    )
    assert r1.memories_created == 1
    assert r1.memories_reused == 0

    # Second run (exact same history)
    r2 = await MemoryCompressionService.compress_user_history(
        user_id=user.id,
        db=test_db_session,
    )
    assert r2.memories_created == 0
    assert r2.memories_reused == 1
    assert r2.events_compressed == 3

    # Total active memories remains exactly 1
    memories = await MemoryRetrievalService.get_user_memories(
        user_id=user.id,
        db=test_db_session,
    )
    assert len(memories) == 1
