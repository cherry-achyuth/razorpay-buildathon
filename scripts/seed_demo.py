"""Deterministic demo data seeding script for DecisionVault Buildathon demonstration.

Usage:
    uv run python scripts/seed_demo.py
"""

import asyncio
import logging
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import setup_logging
from app.db.base import Base
from app.db.session import get_db_session, get_engine
from app.models.enums import (
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
from app.services.audit.service import AuditLogService
from app.services.memory.compression import MemoryCompressionService

logger = logging.getLogger("decisionvault.seed")


async def _seed_with_session(db: AsyncSession) -> dict:
    """Internal helper to seed principals within an active database session."""
    # 1. User Principal
    user_ref = "demo_buildathon_user"
    user = await db.scalar(select(User).where(User.external_reference == user_ref))
    if not user:
        user = User(
            id=uuid.uuid4(),
            external_reference=user_ref,
            status=UserStatus.ACTIVE,
        )
        db.add(user)
        await db.flush()
        print(f"[+] Created User:     {user.external_reference} ({user.id})")
    else:
        print(f"[*] Existing User:    {user.external_reference} ({user.id})")

    # 2. Merchants & Automatic Junk Merchant Cleanup
    standard_refs = [
        "m_netflix",
        "m_prime",
        "m_spotify",
        "m_cloudcompute",
        "m_bigbasket",
        "m_unknown_mart",
    ]
    non_std_merchants = (
        await db.scalars(
            select(Merchant).where(~Merchant.external_reference.in_(standard_refs))
        )
    ).all()
    if non_std_merchants:
        non_std_ids = [m.id for m in non_std_merchants]
        from sqlalchemy import delete

        await db.execute(
            delete(Transaction).where(Transaction.merchant_id.in_(non_std_ids))
        )
        await db.execute(delete(Merchant).where(Merchant.id.in_(non_std_ids)))
        await db.flush()
        print(
            f"[+] Cleaned up {len(non_std_merchants)} non-standard/junk merchant records from DB."
        )

    # Citing current published India subscription plans:
    # - Netflix: Premium 4K plan = ₹649.00/month
    # - Amazon Prime: Monthly subscription = ₹299.00/month
    # - Spotify: Premium Individual plan = ₹119.00/month
    # - CloudCompute: Standard 2 vCPU 4GB RAM cloud instance = ₹850.00/month (~$10/mo)
    # - BigBasket: bbdaily recurring grocery basket = ₹350.00/order
    # - Unknown Shady Mart: Unrecognized/unverified merchant (0 transactions)
    merchants_spec = [
        ("Netflix", "m_netflix"),
        ("Amazon Prime", "m_prime"),
        ("Spotify", "m_spotify"),
        ("CloudCompute Global", "m_cloudcompute"),
        ("BigBasket", "m_bigbasket"),
        ("Unknown Shady Mart", "m_unknown_mart"),
    ]
    merchants = {}
    for name, ref in merchants_spec:
        m = await db.scalar(select(Merchant).where(Merchant.external_reference == ref))
        if not m:
            m = Merchant(
                id=uuid.uuid4(),
                name=name,
                external_reference=ref,
                status=MerchantStatus.ACTIVE,
            )
            db.add(m)
            await db.flush()
            print(f"[+] Created Merchant: {m.name} ({m.id})")
        else:
            print(f"[*] Existing Merchant: {m.name} ({m.id})")
        merchants[ref] = m

    # 3. Two-Tier Spend Policy
    # Soft Limit: ₹2,000.00 (comfortably fits routine subscriptions, allows drift detection up to ₹2,000)
    # Hard Ceiling: ₹3,500.00 (absolute ceiling that unconditionally blocks runaway spend)
    policy = await db.scalar(select(Policy).where(Policy.user_id == user.id))
    if not policy:
        policy = Policy(
            id=uuid.uuid4(),
            user_id=user.id,
            name="Standard Autonomous Spend Policy",
            policy_type=PolicyType.TRANSACTION_LIMIT,
            status=PolicyStatus.ACTIVE,
            currency="INR",
            limit_amount=Decimal("2000.0000"),
            hard_limit_amount=Decimal("3500.0000"),
            rules={"soft_limit": "2000.00", "hard_ceiling": "3500.00"},
        )
        db.add(policy)
        await db.flush()
        print(
            f"[+] Created Policy:   {policy.name} (Soft Limit: 2000.00 INR, Hard Ceiling: 3500.00 INR)"
        )
    else:
        policy.limit_amount = Decimal("2000.0000")
        policy.hard_limit_amount = Decimal("3500.0000")
        await db.flush()
        print(
            f"[*] Updated Policy:  {policy.name} (Soft Limit: 2000.00 INR, Hard Ceiling: 3500.00 INR)"
        )

    # 4. Mandate for Netflix
    mandate = await db.scalar(select(Mandate).where(Mandate.user_id == user.id))
    now = datetime.now(UTC)
    if not mandate:
        mandate = Mandate(
            id=uuid.uuid4(),
            user_id=user.id,
            merchant_id=merchants["m_netflix"].id,
            currency="INR",
            max_transaction_amount=Decimal("2000.0000"),
            status=MandateStatus.ACTIVE,
            valid_from=now - timedelta(days=180),
            valid_until=now + timedelta(days=365),
        )
        db.add(mandate)
        await db.flush()
        print(f"[+] Created Mandate:  Max 2000.00 INR to {merchants['m_netflix'].name}")
    else:
        mandate.max_transaction_amount = Decimal("2000.0000")
        await db.flush()
        print(f"[*] Existing Mandate: Max 2000.00 INR ({mandate.id})")

    # 5. Baseline Historical Transactions (Real published plan baselines)
    from sqlalchemy import delete

    from app.models.memory import DecisionMemory, DecisionMemorySource

    await db.execute(delete(DecisionMemorySource))
    await db.execute(delete(DecisionMemory).where(DecisionMemory.user_id == user.id))
    await db.execute(delete(Transaction).where(Transaction.user_id == user.id))
    await db.flush()

    # Netflix Premium (₹649.00 INR/month) - 5 monthly renewals
    for i, days_ago in enumerate([120, 90, 60, 30, 5]):
        tx_netflix = Transaction(
            id=uuid.uuid4(),
            user_id=user.id,
            merchant_id=merchants["m_netflix"].id,
            mandate_id=mandate.id,
            amount=Decimal("649.0000"),
            currency="INR",
            transaction_type=TransactionType.PURCHASE,
            status=TransactionStatus.CAPTURED,
            external_reference=f"seed_tx_netflix_{i + 1}",
            occurred_at=now - timedelta(days=days_ago),
        )
        db.add(tx_netflix)

    # Amazon Prime Monthly (₹299.00 INR/month) - 4 monthly renewals
    for i, days_ago in enumerate([90, 60, 30, 10]):
        tx_prime = Transaction(
            id=uuid.uuid4(),
            user_id=user.id,
            merchant_id=merchants["m_prime"].id,
            amount=Decimal("299.0000"),
            currency="INR",
            transaction_type=TransactionType.PURCHASE,
            status=TransactionStatus.CAPTURED,
            external_reference=f"seed_tx_prime_{i + 1}",
            occurred_at=now - timedelta(days=days_ago),
        )
        db.add(tx_prime)

    # Spotify Premium Individual (₹119.00 INR/month) - 4 monthly renewals
    for i, days_ago in enumerate([90, 60, 30, 12]):
        tx_spotify = Transaction(
            id=uuid.uuid4(),
            user_id=user.id,
            merchant_id=merchants["m_spotify"].id,
            amount=Decimal("119.0000"),
            currency="INR",
            transaction_type=TransactionType.PURCHASE,
            status=TransactionStatus.CAPTURED,
            external_reference=f"seed_tx_spotify_{i + 1}",
            occurred_at=now - timedelta(days=days_ago),
        )
        db.add(tx_spotify)

    # CloudCompute Standard VPS (₹850.00 INR/month) - 4 monthly renewals
    for i, days_ago in enumerate([90, 60, 30, 8]):
        tx_cloud = Transaction(
            id=uuid.uuid4(),
            user_id=user.id,
            merchant_id=merchants["m_cloudcompute"].id,
            amount=Decimal("850.0000"),
            currency="INR",
            transaction_type=TransactionType.PURCHASE,
            status=TransactionStatus.CAPTURED,
            external_reference=f"seed_tx_cloud_{i + 1}",
            occurred_at=now - timedelta(days=days_ago),
        )
        db.add(tx_cloud)

    # BigBasket recurring groceries (₹350.00 INR/order) - 4 routine orders
    for j, days_ago in enumerate([21, 14, 7, 2]):
        tx_bb = Transaction(
            id=uuid.uuid4(),
            user_id=user.id,
            merchant_id=merchants["m_bigbasket"].id,
            amount=Decimal("350.0000"),
            currency="INR",
            transaction_type=TransactionType.PURCHASE,
            status=TransactionStatus.CAPTURED,
            external_reference=f"seed_tx_bb_{j + 1}",
            occurred_at=now - timedelta(days=days_ago),
        )
        db.add(tx_bb)
    await db.flush()
    await db.commit()
    print(
        "[+] Seeded 21 Baseline Historical Transactions (Realistic plans: Netflix 649 INR, Prime 299 INR, Spotify 119 INR, Cloud 850 INR, BigBasket 350 INR)"
    )

    # 6. Trigger Baseline Memory Compression
    cmp_result = await MemoryCompressionService.compress_user_history(
        user_id=user.id,
        db=db,
        lookback_days=180,
    )
    print(
        f"[+] Memory Compression: {cmp_result.memories_created} memories created, {cmp_result.compression_ratio}x ratio"
    )
    assert cmp_result.memories_created > 0, (
        f"Memory compression failed to create baseline memories for user {user.id}"
    )

    # 7. Verify Audit Chain
    audit_res = await AuditLogService.verify_chain(db=db)
    print(
        f"[+] Audit Chain State:  Valid={audit_res.valid} ({audit_res.records_checked} events recorded)"
    )

    await db.commit()

    print("\n" + "=" * 70)
    print("DEMO DATA PREPARATION COMPLETE!")
    print("You can now open http://127.0.0.1:8000/ to explore the Buildathon Demo.")
    print("=" * 70 + "\n")

    return {
        "user_id": str(user.id),
        "user_reference": user.external_reference,
        "netflix_merchant_id": str(merchants["m_netflix"].id),
        "policy_id": str(policy.id),
        "audit_valid": audit_res.valid,
    }


async def seed_demo_data(session: AsyncSession | None = None) -> dict:
    """Seed synthetic demonstration principals into the active database."""
    settings = get_settings()
    setup_logging(settings.LOG_LEVEL)

    db_str = str(settings.DATABASE_URL or "active-session")
    print("\n" + "=" * 70)
    print("DECISIONVAULT — DETERMINISTIC BUILDATHON DEMO SEEDER")
    print("=" * 70)
    print(f"Environment: {settings.APP_ENV}")
    print(f"Database:    {db_str.split('@')[-1] if '@' in db_str else db_str}")

    if session is not None:
        return await _seed_with_session(session)

    # Ensure tables exist
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Acquire database session
    async for db in get_db_session():
        return await _seed_with_session(db)
    return {}


if __name__ == "__main__":
    asyncio.run(seed_demo_data())
