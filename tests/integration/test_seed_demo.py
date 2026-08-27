"""Tests for deterministic Buildathon demo data seeder."""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.merchant import Merchant
from app.models.policy import Policy
from app.models.transaction import Transaction
from app.models.user import User
from scripts.seed_demo import seed_demo_data


@pytest.mark.asyncio
async def test_seed_demo_data_execution_and_idempotency(
    test_db_session: AsyncSession,
) -> None:
    """Verify that seed_demo_data creates expected principals and is safe to run multiple times."""
    # 1. Run Seeder First Time
    res1 = await seed_demo_data(session=test_db_session)
    assert res1["user_reference"] == "demo_buildathon_user"
    assert res1["audit_valid"] is True

    # 2. Check Database State
    user = await test_db_session.scalar(
        select(User).where(User.external_reference == "demo_buildathon_user")
    )
    assert user is not None

    merchants = (await test_db_session.scalars(select(Merchant))).all()
    assert len(merchants) >= 5

    policy = await test_db_session.scalar(
        select(Policy).where(Policy.user_id == user.id)
    )
    assert policy is not None
    assert policy.limit_amount == 2000.0000
    assert policy.hard_limit_amount == 3500.0000

    transactions = (
        await test_db_session.scalars(
            select(Transaction).where(Transaction.user_id == user.id)
        )
    ).all()
    assert len(transactions) == 21

    # 3. Run Seeder Second Time (Idempotent)
    res2 = await seed_demo_data(session=test_db_session)
    assert res2["user_id"] == res1["user_id"]
    assert res2["audit_valid"] is True
