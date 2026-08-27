"""Day 12 Live ASGI verification script: Adversarial and Boundary Decision-Preservation Evaluation Suite."""

import asyncio
import os
import time
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import create_async_engine

from app.db.base import Base
from app.models.transaction import Transaction

DB_FILE = "d:/cherry/project/dev_test12.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{DB_FILE}"


async def main():
    if os.path.exists(DB_FILE):
        try:
            os.remove(DB_FILE)
        except Exception:
            pass

    engine = create_async_engine(f"sqlite+aiosqlite:///{DB_FILE}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    transport = httpx.ASGITransport(app=__import__("app.main", fromlist=["app"]).app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        # 1. Health Probe
        h = await client.get("/health")
        print("1. HEALTH PROBE:", h.status_code, h.json()["status"])

        # 2. Setup user and merchants
        u = await client.post(
            "/api/v1/users",
            json={"external_reference": "live12_u", "status": "ACTIVE"},
        )
        user_id = u.json()["id"]

        m_prim = await client.post(
            "/api/v1/merchants",
            json={"name": "OpenAI API", "external_reference": "live12_m_prim"},
        )
        m_prim_id = m_prim.json()["id"]

        await client.post(
            "/api/v1/merchants",
            json={"name": "Anthropic API", "external_reference": "live12_m_sec"},
        )

        # Policy: max $50.00 USD
        await client.post(
            "/api/v1/policies",
            json={
                "user_id": user_id,
                "name": "Limit $50",
                "policy_type": "TRANSACTION_LIMIT",
                "status": "ACTIVE",
                "currency": "USD",
                "limit_amount": "50.0000",
                "rules": {},
            },
        )

        # 3. Create 10 routine transactions ($25.00 USD each, occurred in past) + 1 critical failed transaction
        now = datetime.now(UTC)
        tx_ids = []
        for i in range(10):
            tx = await client.post(
                "/api/v1/transactions",
                json={
                    "user_id": user_id,
                    "merchant_id": m_prim_id,
                    "amount": "25.00",
                    "currency": "USD",
                    "status": "CAPTURED",
                    "transaction_type": "PURCHASE",
                    "occurred_at": (now - timedelta(days=i + 2)).isoformat(),
                },
            )
            tx_ids.append(tx.json()["id"])

        # Add 1 critical failed transaction (critical event inside redundant history)
        tx_fail = await client.post(
            "/api/v1/transactions",
            json={
                "user_id": user_id,
                "merchant_id": m_prim_id,
                "amount": "25.00",
                "currency": "USD",
                "status": "FAILED",
                "transaction_type": "PURCHASE",
                "occurred_at": (now - timedelta(days=1)).isoformat(),
            },
        )
        tx_ids.append(tx_fail.json()["id"])
        print(
            f"2. CREATED {len(tx_ids)} RAW TRANSACTIONS (10 Routine Captured + 1 Failed Critical)"
        )

        # 4. Run Memory Compression
        cmp_res = await client.post(
            "/api/v1/memories/compress",
            json={"user_id": user_id, "lookback_days": 90},
        )
        cmp_data = cmp_res.json()
        print(
            f"3. COMPRESSION COMPLETED: created={cmp_data['memories_created']}, "
            f"ratio={cmp_data['compression_ratio']}x, reduction={cmp_data['compression_percentage']}%"
        )

        # 5. Run Adversarial Decision-Preservation Evaluation Suite
        t0 = time.perf_counter()
        eval_res = await client.post(
            "/api/v1/evaluations/decision-preservation",
            json={"user_id": user_id, "scenario_suite": "ADVERSARIAL"},
        )
        eval_lat_ms = (time.perf_counter() - t0) * 1000.0
        rep = eval_res.json()

        print(
            f"\n4. ADVERSARIAL DECISION-PRESERVATION REPORT (latency={eval_lat_ms:.2f}ms):"
        )
        print(f"   Experiment ID:                     {rep['experiment_id']}")
        print(f"   Scenario Suite:                    {rep['scenario_suite']}")
        print(f"   Total Scenarios:                   {rep['total_scenarios']}")
        print(f"   Matching Decisions:                {rep['matching_decisions']}")
        print(f"   Mismatching Decisions:             {rep['mismatching_decisions']}")
        print(
            f"   Decision Preservation Rate:        {rep['decision_preservation_rate'] * 100.0:.1f}%"
        )
        print(
            f"   Safety-Critical Preservation Rate: {rep['safety_critical_preservation_rate'] * 100.0:.1f}%"
        )
        print(
            f"   Critical-Memory Recall:            {rep['critical_memory_recall'] * 100.0:.1f}%"
        )
        print(f"   False ALLOW Count:                 {rep['false_allow_count']}")
        print(f"   False BLOCK Count:                 {rep['false_block_count']}")
        print(f"   Missed BLOCK Count:                {rep['missed_block_count']}")
        print(f"   Compression Ratio:                 {rep['compression_ratio']}x")

        print("\n5. ADVERSARIAL SCENARIO TRACE:")
        for sc in rep["scenarios"]:
            print(
                f"   - [{sc['scenario_id']}] ({sc['category']})\n"
                f"     Full={sc['full_history_decision']} vs Comp={sc['compressed_memory_decision']} "
                f"| Match={sc['decision_match']} ({sc['mismatch_type']})"
            )

        # 6. Verify Audit Trail
        v_res = await client.get("/api/v1/audit/verify")
        print(
            f"\n6. AUDIT CHAIN INTEGRITY: valid={v_res.json()['valid']}, "
            f"records_checked={v_res.json()['records_checked']}"
        )
        assert v_res.json()["valid"] is True

        # 7. Verify Raw Transactions Permanence
        import uuid as _uuid

        async with engine.connect() as conn:
            raw_count = await conn.scalar(
                select(func.count(Transaction.id)).where(
                    Transaction.user_id == _uuid.UUID(user_id)
                )
            )
            print(f"7. RAW TRANSACTIONS INTACT: {raw_count} rows in PostgreSQL")
            assert raw_count == 11

        # 8. Deterministic Reproducibility Check
        eval_res2 = await client.post(
            "/api/v1/evaluations/decision-preservation",
            json={"user_id": user_id, "scenario_suite": "ADVERSARIAL"},
        )
        rep2 = eval_res2.json()
        assert rep2["total_scenarios"] == rep["total_scenarios"]
        assert rep2["decision_preservation_rate"] == rep["decision_preservation_rate"]
        print(
            f"8. REPRODUCIBILITY VERIFIED: Repeated run yielded identical {rep2['total_scenarios']} scenarios "
            f"and {rep2['decision_preservation_rate'] * 100.0:.1f}% preservation rate."
        )

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
