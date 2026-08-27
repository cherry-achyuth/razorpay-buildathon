"""Database seeding utilities for synthetic datasets."""

import logging
import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
from experiments.synthetic.models import SyntheticDataset

logger = logging.getLogger(__name__)


@dataclass
class DatabaseSeedingResult:
    """Result summary of seeding synthetic dataset into PostgreSQL database."""

    dataset_id: str
    users_seeded: int = 0
    merchants_seeded: int = 0
    policies_seeded: int = 0
    mandates_seeded: int = 0
    transactions_seeded: int = 0
    seeded_user_ids: list[uuid.UUID] = field(default_factory=list)
    seeded_transaction_ids: list[uuid.UUID] = field(default_factory=list)


async def seed_synthetic_dataset_to_db(
    dataset: SyntheticDataset,
    db: AsyncSession,
) -> DatabaseSeedingResult:
    """Seed a synthetic dataset into the database using existing domain SQLAlchemy models."""
    res = DatabaseSeedingResult(dataset_id=dataset.manifest.dataset_id)

    # 1. Seed Users (avoid duplicate external_reference conflicts)
    for u_rec in dataset.users:
        existing_user = await db.scalar(
            select(User).where(
                (User.id == u_rec.id)
                | (User.external_reference == u_rec.external_reference)
            )
        )
        if not existing_user:
            user = User(
                id=u_rec.id,
                external_reference=u_rec.external_reference,
                status=UserStatus(u_rec.status),
            )
            db.add(user)
            res.users_seeded += 1
            res.seeded_user_ids.append(u_rec.id)
        else:
            res.seeded_user_ids.append(existing_user.id)

    # 2. Seed Merchants
    for m_rec in dataset.merchants:
        existing_m = await db.scalar(
            select(Merchant).where(
                (Merchant.id == m_rec.id)
                | (Merchant.external_reference == m_rec.external_reference)
            )
        )
        if not existing_m:
            merchant = Merchant(
                id=m_rec.id,
                name=m_rec.name,
                external_reference=m_rec.external_reference,
                status=MerchantStatus(m_rec.status),
            )
            db.add(merchant)
            res.merchants_seeded += 1

    await db.flush()

    # 3. Seed Policies
    for p_rec in dataset.policies:
        existing_p = await db.scalar(select(Policy).where(Policy.id == p_rec.id))
        if not existing_p:
            policy = Policy(
                id=p_rec.id,
                user_id=p_rec.user_id,
                name=p_rec.name,
                policy_type=PolicyType(p_rec.policy_type),
                status=PolicyStatus(p_rec.status),
                currency=p_rec.currency,
                limit_amount=p_rec.limit_amount,
                rules=p_rec.rules,
            )
            db.add(policy)
            res.policies_seeded += 1

    # 4. Seed Mandates
    for md_rec in dataset.mandates:
        existing_md = await db.scalar(select(Mandate).where(Mandate.id == md_rec.id))
        if not existing_md:
            mandate = Mandate(
                id=md_rec.id,
                user_id=md_rec.user_id,
                merchant_id=md_rec.merchant_id,
                status=MandateStatus(md_rec.status),
                currency=md_rec.currency,
                max_transaction_amount=md_rec.max_transaction_amount,
                valid_from=md_rec.valid_from,
                valid_until=md_rec.valid_until,
            )
            db.add(mandate)
            res.mandates_seeded += 1

    await db.flush()

    # 5. Seed Transactions
    for t_rec in dataset.transactions:
        existing_t = await db.scalar(
            select(Transaction).where(Transaction.id == t_rec.id)
        )
        if not existing_t:
            tx = Transaction(
                id=t_rec.id,
                user_id=t_rec.user_id,
                merchant_id=t_rec.merchant_id,
                mandate_id=t_rec.mandate_id,
                amount=t_rec.amount,
                currency=t_rec.currency,
                transaction_type=TransactionType(t_rec.transaction_type),
                status=TransactionStatus(t_rec.status),
                external_reference=t_rec.external_reference,
                idempotency_key=t_rec.idempotency_key,
                occurred_at=t_rec.occurred_at,
            )
            db.add(tx)
            res.transactions_seeded += 1
            res.seeded_transaction_ids.append(t_rec.id)

    await db.commit()
    logger.info(
        "Seeded synthetic dataset '%s': %d users, %d merchants, %d transactions",
        dataset.manifest.dataset_id,
        res.users_seeded,
        res.merchants_seeded,
        res.transactions_seeded,
    )
    return res
