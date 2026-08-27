"""Day 10 Live ASGI verification script: Tamper-Evident Hash-Chained Audit Log."""

import asyncio
import os
import time

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.db.base import Base
from app.models.audit import AuditLog

DB_FILE = "d:/cherry/project/dev_test10.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{DB_FILE}"


async def main():
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

        # 2. Setup user & merchant
        u = await client.post(
            "/api/v1/users",
            json={"external_reference": "live10_u", "status": "ACTIVE"},
        )
        user_id = u.json()["id"]

        m = await client.post(
            "/api/v1/merchants",
            json={"name": "OpenAI API", "external_reference": "live10_m"},
        )
        merchant_id = m.json()["id"]

        # 3. Create 3 transactions
        tx_ids = []
        for amt in ["20.00", "25.00", "20.00"]:
            tx = await client.post(
                "/api/v1/transactions",
                json={
                    "user_id": user_id,
                    "merchant_id": merchant_id,
                    "amount": amt,
                    "currency": "USD",
                    "status": "CAPTURED",
                    "transaction_type": "PURCHASE",
                },
            )
            tx_ids.append(tx.json()["id"])
        print(f"2. CREATED {len(tx_ids)} TRANSACTIONS")

        # 4. Build Memory -> MEMORY_CREATED audit event
        mem1 = await client.post(f"/api/v1/memories/build/{tx_ids[0]}")
        mem1_id = mem1.json()["id"]
        print("3. MEMORY BUILT (MEMORY_CREATED audit event): ID =", mem1_id)

        # 5. Evaluate Decision -> DECISION_EVALUATED audit event
        eval1 = await client.post(
            "/api/v1/decisions/evaluate",
            json={
                "user_id": user_id,
                "merchant_id": merchant_id,
                "amount": "20.00",
                "currency": "USD",
            },
        )
        print(
            "4. DECISION EVALUATED (DECISION_EVALUATED audit event):",
            eval1.json()["decision"],
        )

        # 6. Compress Memories -> MEMORY_COMPRESSED audit event
        cmp_res = await client.post(
            "/api/v1/memories/compress",
            json={"user_id": user_id, "lookback_days": 90},
        )
        print(
            "5. MEMORY COMPRESSED (MEMORY_COMPRESSED audit event): ratio =",
            cmp_res.json()["compression_ratio"],
        )

        # 7. Retire Memory -> MEMORY_RETIRED audit event
        ret_res = await client.post(f"/api/v1/memories/{mem1_id}/retire")
        print("6. MEMORY RETIRED (MEMORY_RETIRED audit event):", ret_res.status_code)

        # 8. Check Audit Log API
        t0 = time.perf_counter()
        audit_res = await client.get(f"/api/v1/audit?user_id={user_id}")
        query_lat_ms = (time.perf_counter() - t0) * 1000.0
        records = audit_res.json()["records"]
        print(
            f"7. AUDIT LOGS RETRIEVED: count={len(records)} (query_latency={query_lat_ms:.2f}ms)"
        )
        for r in reversed(records):
            print(
                f"   [seq={r['sequence_number']}] event={r['event_type']} "
                f"entity={r['entity_type']} prev_hash={r['previous_hash'][:8] if r['previous_hash'] else 'GENESIS'}... "
                f"hash={r['record_hash'][:8]}..."
            )

        # 9. Verify Audit Chain (Valid State)
        t1 = time.perf_counter()
        v_res = await client.get("/api/v1/audit/verify")
        verify_lat_ms = (time.perf_counter() - t1) * 1000.0
        v_data = v_res.json()
        print(
            f"8. AUDIT CHAIN VERIFICATION (VALID STATE): "
            f"valid={v_data['valid']}, records_checked={v_data['records_checked']} "
            f"(verify_latency={verify_lat_ms:.2f}ms)"
        )
        assert v_data["valid"] is True

        # 10. Verify Raw Transactions Remain Intact
        all_intact = True
        for tid in tx_ids:
            gtx = await client.get(f"/api/v1/transactions/{tid}")
            if gtx.status_code != 200:
                all_intact = False
        print(f"9. RAW TRANSACTION PERMANENCE: all {len(tx_ids)} intact = {all_intact}")

        # 11. Controlled Tampering Test in Isolated Test DB
        print("10. EXECUTING CONTROLLED TAMPERING TEST...")
        async with AsyncSession(engine) as session:
            # Tamper with record 2 event_data in the database
            r2_stmt = select(AuditLog).where(AuditLog.sequence_number == 2)
            r2 = await session.scalar(r2_stmt)
            if r2:
                r2.event_data = {"tampered": True, "fake_payload": 9999}
                await session.commit()
                print("    -> Tampered with AuditLog seq=2 event_data")

        # 12. Run Verification Again -> Tampering Detected!
        v_tamper = await client.get("/api/v1/audit/verify")
        vt_data = v_tamper.json()
        print(
            f"11. AUDIT CHAIN VERIFICATION AFTER TAMPERING: "
            f"valid={vt_data['valid']}, failure_reason={vt_data['failure_reason']}, "
            f"first_invalid_sequence={vt_data['first_invalid_sequence']}"
        )
        assert vt_data["valid"] is False
        assert vt_data["failure_reason"] == "RECORD_HASH_MISMATCH"
        print("12. TAMPERING SUCCESSFULLY DETECTED!")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
