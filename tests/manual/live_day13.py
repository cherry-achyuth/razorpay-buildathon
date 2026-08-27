"""Day 13 Live verification script: Synthetic Financial Dataset Generation and Experiment Fixtures."""

import asyncio
import os
import tempfile
import time
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import create_async_engine

from app.db.base import Base
from app.models.enums import ScenarioSuite
from app.models.transaction import Transaction
from app.services.evaluation.decision_preservation import (
    DecisionPreservationService,
)
from app.services.memory.compression import MemoryCompressionService
from experiments.synthetic import (
    DatasetConfig,
    DatasetScale,
    SyntheticDatasetGenerator,
    SyntheticScenarioType,
    load_dataset_from_json,
    save_dataset_to_json,
    seed_synthetic_dataset_to_db,
    serialize_dataset_to_dict,
)

DB_FILE = "d:/cherry/project/dev_test13.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{DB_FILE}"


async def main():
    print("==================================================")
    print("DAY 13 SYNTHETIC DATASET GENERATOR VERIFICATION")
    print("==================================================")

    # 1. Generate Small Dataset with Seed 42
    t0 = time.perf_counter()
    cfg_small = DatasetConfig(
        seed=42,
        scale=DatasetScale.SMALL,  # 2 users, 20 txs/user = 40 txs
    )
    ds_small = SyntheticDatasetGenerator.generate(cfg_small)
    gen_lat_ms = (time.perf_counter() - t0) * 1000.0

    print(f"\n1. DATASET GENERATION COMPLETED (latency={gen_lat_ms:.2f}ms):")
    print(f"   Dataset ID:            {ds_small.manifest.dataset_id}")
    print(f"   Seed:                  {ds_small.manifest.seed}")
    print(f"   Scale:                 {ds_small.manifest.scale}")
    print(f"   Users Generated:       {ds_small.manifest.user_count}")
    print(f"   Merchants Generated:   {ds_small.manifest.merchant_count}")
    print(f"   Total Transactions:    {ds_small.manifest.transaction_count}")
    print(f"   Routine Events:        {ds_small.manifest.routine_event_count}")
    print(f"   Critical Events:       {ds_small.manifest.critical_event_count}")
    print(f"   Scenario Mix Counts:   {ds_small.manifest.scenario_counts}")

    # 2. Reproducibility Verification
    print("\n2. REPRODUCIBILITY CHECKS:")
    ds_small_repeat = SyntheticDatasetGenerator.generate(cfg_small)
    d1 = serialize_dataset_to_dict(ds_small)
    d2 = serialize_dataset_to_dict(ds_small_repeat)
    d1["manifest"]["created_at"] = ""
    d2["manifest"]["created_at"] = ""
    is_identical = d1 == d2
    print(f"   - Same Seed (42) & Config -> Identical Dataset: {is_identical} (PASS)")
    assert is_identical is True

    ds_diff_seed = SyntheticDatasetGenerator.generate(
        DatasetConfig(seed=43, scale=DatasetScale.SMALL)
    )
    is_distinct = ds_small.users[0].id != ds_diff_seed.users[0].id
    print(f"   - Different Seed (43) -> Distinct Dataset:     {is_distinct} (PASS)")
    assert is_distinct is True

    # 3. Serialization Round-Trip
    print("\n3. SERIALIZATION ROUND-TRIP:")
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_json = Path(tmpdir) / "synth_ds_42.json"
        save_dataset_to_json(ds_small, tmp_json)
        loaded_ds = load_dataset_from_json(tmp_json)
        round_trip_ok = (
            loaded_ds.manifest.dataset_id == ds_small.manifest.dataset_id
            and len(loaded_ds.transactions) == len(ds_small.transactions)
            and loaded_ds.transactions[0].amount == ds_small.transactions[0].amount
        )
        print(
            f"   - JSON Save & Load Round-Trip:                {round_trip_ok} (PASS)"
        )
        assert round_trip_ok is True

    # 4. Database Seeding & Integration
    print("\n4. DATABASE SEEDING & PIPELINE INTEGRATION:")
    if os.path.exists(DB_FILE):
        try:
            os.remove(DB_FILE)
        except Exception:
            pass

    engine = create_async_engine(f"sqlite+aiosqlite:///{DB_FILE}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    session_maker = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    # Seed Mixed History Dataset into Database
    cfg_mixed = DatasetConfig(
        seed=100,
        scale=DatasetScale.CUSTOM,
        num_users=1,
        transactions_per_user=20,
        scenario_mix=[SyntheticScenarioType.MIXED_HISTORY],
        routine_amount=Decimal("25.0000"),
        policy_limit_amount=Decimal("50.0000"),
    )
    ds_mixed = SyntheticDatasetGenerator.generate(cfg_mixed)

    async with session_maker() as session:
        seed_res = await seed_synthetic_dataset_to_db(ds_mixed, session)
        print(
            f"   - Seeded into PostgreSQL/SQLite: {seed_res.users_seeded} users, "
            f"{seed_res.merchants_seeded} merchants, {seed_res.transactions_seeded} transactions"
        )
        assert seed_res.transactions_seeded == 20

        # Query Database directly
        tx_count = await session.scalar(select(func.count(Transaction.id)))
        print(f"   - Authoritative DB Query:       {tx_count} transactions intact")
        assert tx_count == 20

        # Run Memory Compression on seeded data
        u_id = ds_mixed.users[0].id
        as_of_eval = max(t.occurred_at for t in ds_mixed.transactions) + timedelta(
            days=1
        )
        comp_res = await MemoryCompressionService.compress_user_history(
            user_id=u_id, db=session, as_of=as_of_eval
        )
        print(
            f"   - Memory Compression on Seed:   created={comp_res.memories_created}, "
            f"ratio={comp_res.compression_ratio}x, reduction={comp_res.compression_percentage}%"
        )

        # Run Decision-Preservation Evaluation
        eval_service = DecisionPreservationService()
        report = await eval_service.run_evaluation(
            user_id=u_id,
            db=session,
            suite=ScenarioSuite.ADVERSARIAL,
            as_of=as_of_eval,
        )
        for sc in report.scenarios:
            print(
                f"     [{sc.scenario_id}] ({sc.category}) Full={sc.full_history_decision} vs Comp={sc.compressed_memory_decision} "
                f"| Match={sc.decision_match} ({sc.mismatch_type})"
            )
        # Check that high preservation is achieved
        assert report.decision_preservation_rate >= 0.90

    await engine.dispose()
    if os.path.exists(DB_FILE):
        try:
            os.remove(DB_FILE)
        except Exception:
            pass

    print("\n==================================================")
    print("DAY 13 SYNTHETIC DATASET GENERATION VERIFIED SUCCESSFULLY!")
    print("==================================================")


if __name__ == "__main__":
    asyncio.run(main())
