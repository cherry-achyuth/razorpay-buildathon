"""Synthetic development demo data seeder for DecisionVault.

Explicit execution only:
    uv run python scripts/seed_demo_data.py
"""

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.db.session import close_db_engine, get_session_factory
from app.models.decision import Decision
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


async def seed_data() -> None:
    """Inserts synthetic demo data for development and testing."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        # Check if already seeded
        existing_user = await session.scalar(
            select(User).where(User.external_reference == "demo_agent_principal_01")
        )
        if existing_user:
            print("Demo data already seeded. Skipping insertion.")
            return

        print("Seeding synthetic demo data for DecisionVault...")

        # 1. Demo User
        user = User(
            external_reference="demo_agent_principal_01",
            status=UserStatus.ACTIVE,
        )
        session.add(user)
        await session.flush()

        # 2. Demo Merchants
        merchant_cloud = Merchant(
            name="CloudCompute Infrastructure Ltd",
            external_reference="demo_merch_cloud_01",
            status=MerchantStatus.ACTIVE,
        )
        merchant_tools = Merchant(
            name="AI Tooling Services Inc",
            external_reference="demo_merch_tools_02",
            status=MerchantStatus.ACTIVE,
        )
        session.add_all([merchant_cloud, merchant_tools])
        await session.flush()

        # 3. Demo Mandate
        now = datetime.now(UTC)
        mandate = Mandate(
            user_id=user.id,
            merchant_id=None,  # Applies to all verified merchants
            status=MandateStatus.ACTIVE,
            currency="INR",
            max_transaction_amount=Decimal("10000.0000"),
            valid_from=now,
            valid_until=now + timedelta(days=365),
        )
        session.add(mandate)
        await session.flush()

        # 4. Demo Policies
        policy_budget = Policy(
            user_id=user.id,
            name="Monthly Cloud & AI Spend Budget",
            policy_type=PolicyType.BUDGET,
            status=PolicyStatus.ACTIVE,
            currency="INR",
            limit_amount=Decimal("50000.0000"),
            valid_from=now,
            valid_until=now + timedelta(days=30),
            rules={"period": "monthly", "category": "compute"},
        )
        policy_tx_cap = Policy(
            user_id=user.id,
            name="Autonomous Agent Single-Purchase Guardrail",
            policy_type=PolicyType.TRANSACTION_LIMIT,
            status=PolicyStatus.ACTIVE,
            currency="INR",
            limit_amount=Decimal("10000.0000"),
            valid_from=now,
            valid_until=now + timedelta(days=365),
            rules={"enforce_strict_cap": True},
        )
        session.add_all([policy_budget, policy_tx_cap])
        await session.flush()

        # 5. Demo Transactions
        tx1 = Transaction(
            user_id=user.id,
            merchant_id=merchant_cloud.id,
            mandate_id=mandate.id,
            amount=Decimal("1899.5000"),
            currency="INR",
            transaction_type=TransactionType.PURCHASE,
            status=TransactionStatus.CAPTURED,
            external_reference="demo_gw_tx_001",
            idempotency_key="demo_idem_seed_001",
            occurred_at=now - timedelta(days=2),
        )
        tx2 = Transaction(
            user_id=user.id,
            merchant_id=merchant_tools.id,
            mandate_id=mandate.id,
            amount=Decimal("4500.0000"),
            currency="INR",
            transaction_type=TransactionType.PURCHASE,
            status=TransactionStatus.CAPTURED,
            external_reference="demo_gw_tx_002",
            idempotency_key="demo_idem_seed_002",
            occurred_at=now - timedelta(days=1),
        )
        session.add_all([tx1, tx2])
        await session.flush()

        # 6. Demo Decision Audit Record
        decision = Decision(
            user_id=user.id,
            transaction_id=tx1.id,
            request_reference="demo_agent_req_alpha",
            decision=DecisionOutcome.ALLOW,
            reason=(
                "Transaction amount 1899.50 INR is within active mandate cap "
                "(10000 INR) and monthly budget."
            ),
            evidence_metadata={
                "mandate_id": str(mandate.id),
                "mandate_cap": "10000.0000",
                "evaluated_amount": "1899.5000",
                "remaining_budget": "48100.5000",
            },
        )
        session.add(decision)
        await session.commit()

        print("Synthetic demo data successfully seeded!")
        print(f"  User ID: {user.id}")
        print(f"  Merchants: {merchant_cloud.id}, {merchant_tools.id}")
        print(f"  Mandate ID: {mandate.id}")
        print(f"  Transactions: {tx1.id}, {tx2.id}")
        print(f"  Decision ID: {decision.id}")


if __name__ == "__main__":
    try:
        asyncio.run(seed_data())
    finally:
        asyncio.run(close_db_engine())
