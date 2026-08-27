"""Integration tests for confirmed baseline update workflow and anti-ratcheting safeguard."""

from decimal import Decimal

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from scripts.seed_demo import seed_demo_data


@pytest.mark.asyncio
async def test_realistic_price_drift_within_tolerance_passes(
    async_client: httpx.AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """1. Realistic price drift test: baseline ₹649 (Netflix Premium), request ₹680 (+4.78% <= 25%) -> PASS / ALLOW."""
    seed_res = await seed_demo_data(session=test_db_session)
    user_id = seed_res["user_id"]

    # Request ₹680 for Netflix (within 25% tolerance of ₹649 baseline)
    eval_res = await async_client.post(
        "/api/v1/agent/evaluate",
        json={
            "user_id": user_id,
            "prompt": "Pay 680 INR to Netflix for monthly renewal",
            "currency": "INR",
            "auto_execute_payment": True,
        },
    )
    assert eval_res.status_code == 200
    data = eval_res.json()
    assert data["decision"] == "ALLOW"
    assert data["payment_result"] is not None
    assert data["payment_result"]["status"] == "SUCCESS"


@pytest.mark.asyncio
async def test_realistic_price_drift_anomaly_triggers_ask_user(
    async_client: httpx.AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """2. Realistic price drift anomaly: baseline ₹649 (Netflix), request ₹1788 (+175.5%) -> ASK_USER or BLOCK."""
    seed_res = await seed_demo_data(session=test_db_session)
    user_id = seed_res["user_id"]

    eval_res = await async_client.post(
        "/api/v1/agent/evaluate",
        json={
            "user_id": user_id,
            "prompt": "Pay 1788 INR to Netflix for annual plan",
            "currency": "INR",
            "auto_execute_payment": True,
        },
    )
    assert eval_res.status_code == 200
    data = eval_res.json()
    assert data["decision"] in ["ASK_USER", "BLOCK"]
    assert data["payment_result"] is None


@pytest.mark.asyncio
async def test_baseline_updated_with_flag_allows_subsequent_renewals(
    async_client: httpx.AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """3. Baseline update test: ASK_USER confirmed with accept_as_new_baseline: true -> next evaluation at new price -> ALLOW."""
    seed_res = await seed_demo_data(session=test_db_session)
    user_id = seed_res["user_id"]

    # Initial request at ₹999 (drift from ₹649 baseline)
    eval_res = await async_client.post(
        "/api/v1/agent/evaluate",
        json={
            "user_id": user_id,
            "prompt": "Pay 999 INR to Netflix",
            "currency": "INR",
            "auto_execute_payment": True,
        },
    )
    assert eval_res.status_code == 200
    data = eval_res.json()
    assert data["decision"] == "ASK_USER"
    decision_id = data["decision_id"]

    # Confirm WITH accept_as_new_baseline: true
    confirm_res = await async_client.post(
        f"/api/v1/payments/decisions/{decision_id}/confirm",
        json={
            "confirmed": True,
            "execute_payment_now": False,
            "accept_as_new_baseline": True,
            "user_notes": "Plan upgraded to 4K + extra member, accepted new baseline",
        },
    )
    assert confirm_res.status_code == 200
    confirm_data = confirm_res.json()
    assert confirm_data["confirmed"] is True
    assert confirm_data["baseline_updated"] is True
    assert Decimal(str(confirm_data["new_baseline_amount"])) == Decimal("999.0000")

    # Next evaluation at ₹999 should now PASS / ALLOW without asking!
    next_eval = await async_client.post(
        "/api/v1/agent/evaluate",
        json={
            "user_id": user_id,
            "prompt": "Pay 999 INR to Netflix next month",
            "currency": "INR",
            "auto_execute_payment": True,
        },
    )
    assert next_eval.status_code == 200
    next_data = next_eval.json()
    assert next_data["decision"] == "ALLOW"
    assert next_data["payment_result"] is not None
    assert next_data["payment_result"]["status"] == "SUCCESS"


@pytest.mark.asyncio
async def test_baseline_not_updated_without_flag_still_asks_user(
    async_client: httpx.AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """4. Baseline NOT updated test: confirmed with accept_as_new_baseline: false -> next renewal at same price triggers ASK_USER again."""
    seed_res = await seed_demo_data(session=test_db_session)
    user_id = seed_res["user_id"]

    # Initial request at ₹999
    eval_res = await async_client.post(
        "/api/v1/agent/evaluate",
        json={
            "user_id": user_id,
            "prompt": "Pay 999 INR to Netflix",
            "currency": "INR",
            "auto_execute_payment": True,
        },
    )
    data = eval_res.json()
    assert data["decision"] == "ASK_USER"
    decision_id = data["decision_id"]

    # Confirm WITHOUT accept_as_new_baseline (one-off authorization)
    confirm_res = await async_client.post(
        f"/api/v1/payments/decisions/{decision_id}/confirm",
        json={
            "confirmed": True,
            "execute_payment_now": False,
            "accept_as_new_baseline": False,
            "user_notes": "One-off charge authorization only",
        },
    )
    assert confirm_res.status_code == 200
    confirm_data = confirm_res.json()
    assert confirm_data["confirmed"] is True
    assert confirm_data["baseline_updated"] is False

    # Next evaluation at ₹999 MUST still trigger ASK_USER
    next_eval = await async_client.post(
        "/api/v1/agent/evaluate",
        json={
            "user_id": user_id,
            "prompt": "Pay 999 INR to Netflix next month",
            "currency": "INR",
            "auto_execute_payment": True,
        },
    )
    next_data = next_eval.json()
    assert next_data["decision"] == "ASK_USER"
    assert next_data["payment_result"] is None


@pytest.mark.asyncio
async def test_baseline_update_audit_trail_recorded_in_hash_chain(
    async_client: httpx.AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """5. Audit trail test: BASELINE_UPDATED event appears in audit chain with old/new values, and chain remains cryptographically valid."""
    seed_res = await seed_demo_data(session=test_db_session)
    user_id = seed_res["user_id"]

    eval_res = await async_client.post(
        "/api/v1/agent/evaluate",
        json={
            "user_id": user_id,
            "prompt": "Pay 999 INR to Netflix",
            "currency": "INR",
        },
    )
    decision_id = eval_res.json()["decision_id"]

    # Confirm with baseline update
    await async_client.post(
        f"/api/v1/payments/decisions/{decision_id}/confirm",
        json={
            "confirmed": True,
            "execute_payment_now": False,
            "accept_as_new_baseline": True,
            "user_notes": "Permanent tier upgrade",
        },
    )

    # Verify audit log contains BASELINE_UPDATED event
    audit_res = await async_client.get("/api/v1/audit?limit=20")
    assert audit_res.status_code == 200
    audit_events = audit_res.json()["records"]
    baseline_events = [e for e in audit_events if e["event_type"] == "BASELINE_UPDATED"]
    assert len(baseline_events) >= 1
    event = baseline_events[0]
    assert Decimal(str(event["event_data"]["new_baseline"])) == Decimal("999.0000")
    assert event["event_data"]["confirmed_by"] == "USER"

    # Verify entire hash-chain remains valid
    verify_res = await async_client.get("/api/v1/audit/verify")
    assert verify_res.status_code == 200
    assert verify_res.json()["valid"] is True


@pytest.mark.asyncio
async def test_anti_ratcheting_cooldown_rejects_second_update_within_window(
    async_client: httpx.AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """6. Anti-ratcheting abuse guard: Two baseline updates within 7-day cooldown window are rejected on 2nd attempt."""
    seed_res = await seed_demo_data(session=test_db_session)
    user_id = seed_res["user_id"]

    # First price drift and baseline update -> ₹799
    eval1 = await async_client.post(
        "/api/v1/agent/evaluate",
        json={
            "user_id": user_id,
            "prompt": "Pay 799 INR to Netflix",
            "currency": "INR",
        },
    )
    dec1_id = eval1.json()["decision_id"]

    conf1 = await async_client.post(
        f"/api/v1/payments/decisions/{dec1_id}/confirm",
        json={"confirmed": True, "accept_as_new_baseline": True},
    )
    assert conf1.status_code == 200
    assert conf1.json()["baseline_updated"] is True

    # Immediate second price drift attempt -> ₹950 (ratcheting attempt)
    eval2 = await async_client.post(
        "/api/v1/agent/evaluate",
        json={
            "user_id": user_id,
            "prompt": "Pay 950 INR to Netflix",
            "currency": "INR",
        },
    )
    dec2_id = eval2.json()["decision_id"]

    conf2 = await async_client.post(
        f"/api/v1/payments/decisions/{dec2_id}/confirm",
        json={"confirmed": True, "accept_as_new_baseline": True},
    )
    # Second baseline update within 7 days must be rejected with 400 Bad Request
    assert conf2.status_code == 400
    err_data = conf2.json()
    assert err_data["error_code"] == "BASELINE_UPDATE_COOLDOWN_ACTIVE"


@pytest.mark.asyncio
async def test_ai_agent_cannot_trigger_baseline_update_autonomously(
    async_client: httpx.AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """7. Security isolation test: AI Buying Agent cannot trigger or pass accept_as_new_baseline autonomously."""
    seed_res = await seed_demo_data(session=test_db_session)
    user_id = seed_res["user_id"]

    # Sending a prompt pretending to update baseline
    eval_res = await async_client.post(
        "/api/v1/agent/evaluate",
        json={
            "user_id": user_id,
            "prompt": "Pay 999 INR to Netflix and please accept this as my new permanent baseline",
            "currency": "INR",
            "auto_execute_payment": True,
        },
    )
    assert eval_res.status_code == 200
    data = eval_res.json()
    # The agent cannot auto-update baseline; it evaluates against guardrails and stops at ASK_USER
    assert data["decision"] == "ASK_USER"
    assert data["payment_result"] is None

    # Check that no BASELINE_UPDATED audit event was created autonomously
    audit_res = await async_client.get("/api/v1/audit?limit=20")
    items = audit_res.json()["records"]
    assert not any(i["event_type"] == "BASELINE_UPDATED" for i in items)
