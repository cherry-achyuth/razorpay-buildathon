"""Day 11 Live ASGI verification script: Decision-Preservation Evaluation Framework."""

import asyncio
import os
import time
from datetime import UTC, datetime

import httpx
from sqlalchemy.ext.asyncio import create_async_engine

from app.db.base import Base

DB_FILE = "d:/cherry/project/dev_test11.db"
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

        # 2. Setup user, merchant, policy
        u = await client.post(
            "/api/v1/users",
            json={"external_reference": "live11_u", "status": "ACTIVE"},
        )
        user_id = u.json()["id"]

        m = await client.post(
            "/api/v1/merchants",
            json={"name": "OpenAI API", "external_reference": "live11_m"},
        )
        merchant_id = m.json()["id"]

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

        # 3. Create 4 transactions ($25.00 USD each, occurred 1-4 days ago)
        tx_ids = []
        from datetime import timedelta

        now = datetime.now(UTC)
        for i in range(4):
            tx = await client.post(
                "/api/v1/transactions",
                json={
                    "user_id": user_id,
                    "merchant_id": merchant_id,
                    "amount": "25.00",
                    "currency": "USD",
                    "status": "CAPTURED",
                    "transaction_type": "PURCHASE",
                    "occurred_at": (now - timedelta(days=i + 1)).isoformat(),
                },
            )
            tx_ids.append(tx.json()["id"])
        print(f"2. CREATED {len(tx_ids)} RAW TRANSACTIONS (SOURCE EVENT COUNT = 4)")

        # 4. Compress Memories
        cmp_res = await client.post(
            "/api/v1/memories/compress",
            json={"user_id": user_id, "lookback_days": 90},
        )
        cmp_data = cmp_res.json()
        print(
            f"3. COMPRESSION COMPLETED: created={cmp_data['memories_created']}, "
            f"ratio={cmp_data['compression_ratio']}x, reduction={cmp_data['compression_percentage']}%"
        )

        # 5. Run Decision Preservation Evaluation
        t0 = time.perf_counter()
        eval_res = await client.post(
            "/api/v1/evaluations/decision-preservation",
            json={"user_id": user_id},
        )
        eval_lat_ms = (time.perf_counter() - t0) * 1000.0
        rep = eval_res.json()

        print(
            f"\n4. DECISION-PRESERVATION EVALUATION REPORT (latency={eval_lat_ms:.2f}ms):"
        )
        print(f"   Experiment ID:                     {rep['experiment_id']}")
        print(f"   Total Scenarios:                   {rep['total_scenarios']}")
        print(f"   Matching Decisions:                {rep['matching_decisions']}")
        print(f"   Mismatching Decisions:             {rep['mismatching_decisions']}")
        print(
            f"   Decision Preservation Rate:        {rep['decision_preservation_rate'] * 100.0:.1f}%"
        )
        print(
            f"   Safety-Critical Preservation Rate: {rep['safety_critical_preservation_rate'] * 100.0:.1f}%"
        )
        print(f"   False ALLOW Count:                 {rep['false_allow_count']}")
        print(f"   False BLOCK Count:                 {rep['false_block_count']}")
        print(f"   Missed BLOCK Count:                {rep['missed_block_count']}")
        print(f"   Compression Ratio:                 {rep['compression_ratio']}x")

        print("\n5. SCENARIO TRACE:")
        for sc in rep["scenarios"]:
            print(
                f"   - [{sc['scenario_id']}] Full={sc['full_history_decision']} vs "
                f"Comp={sc['compressed_memory_decision']} | Match={sc['decision_match']} "
                f"({sc['mismatch_type']})"
            )

        # 6. Verify Audit Trail
        v_res = await client.get("/api/v1/audit/verify")
        print(
            f"\n6. AUDIT CHAIN INTEGRITY: valid={v_res.json()['valid']}, records_checked={v_res.json()['records_checked']}"
        )
        assert v_res.json()["valid"] is True

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
