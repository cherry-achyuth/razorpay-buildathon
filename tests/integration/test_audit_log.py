"""Integration tests for Day 10: Tamper-Evident Hash-Chained Audit Log."""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import AuditEventType, DecisionOutcome
from app.services.audit.service import AuditLogService


@pytest.mark.asyncio
async def test_audit_log_append_and_verify_valid_chain(
    test_db_session: AsyncSession,
):
    """Verify appending sequential audit records builds a valid, verifiable hash chain."""
    uid = uuid.uuid4()

    # 1. Genesis record (seq=1, prev_hash=None)
    r1 = await AuditLogService.append_event(
        db=test_db_session,
        event_type=AuditEventType.MEMORY_CREATED,
        entity_type="MEMORY",
        entity_id=uuid.uuid4(),
        user_id=uid,
        event_data={"summary": "First memory"},
    )
    assert r1.sequence_number == 1
    assert r1.previous_hash is None
    assert len(r1.record_hash) == 64

    # 2. Second record (seq=2, prev_hash == r1.record_hash)
    r2 = await AuditLogService.append_event(
        db=test_db_session,
        event_type=AuditEventType.DECISION_EVALUATED,
        entity_type="DECISION",
        entity_id=uuid.uuid4(),
        user_id=uid,
        event_data={"decision": "ALLOW", "amount": "25.00"},
    )
    assert r2.sequence_number == 2
    assert r2.previous_hash == r1.record_hash

    # 3. Third record (seq=3, prev_hash == r2.record_hash)
    r3 = await AuditLogService.append_event(
        db=test_db_session,
        event_type=AuditEventType.MEMORY_COMPRESSED,
        entity_type="MEMORY_COMPRESSION",
        user_id=uid,
        event_data={"compression_ratio": 2.0},
    )
    assert r3.sequence_number == 3
    assert r3.previous_hash == r2.record_hash

    await test_db_session.commit()

    # 4. Verify chain integrity
    v_res = await AuditLogService.verify_chain(db=test_db_session)
    assert v_res.valid is True
    assert v_res.records_checked == 3
    assert v_res.failure_reason is None


@pytest.mark.asyncio
async def test_audit_events_integrated_across_domain_operations(
    async_client: AsyncClient,
    test_db_session: AsyncSession,
):
    """Verify that memory creation, decision evaluation, compression, and retirement generate audit records."""
    # 1. Create User & Merchant
    u_res = await async_client.post(
        "/api/v1/users",
        json={"external_reference": "aud_int_u", "status": "ACTIVE"},
    )
    user_id = u_res.json()["id"]

    m_res = await async_client.post(
        "/api/v1/merchants",
        json={"name": "Stripe", "external_reference": "aud_int_m"},
    )
    merchant_id = m_res.json()["id"]

    # 2. Create Transaction and Build Memory -> MEMORY_CREATED
    tx_res = await async_client.post(
        "/api/v1/transactions",
        json={
            "user_id": user_id,
            "merchant_id": merchant_id,
            "amount": "20.00",
            "currency": "USD",
            "status": "CAPTURED",
            "transaction_type": "PURCHASE",
        },
    )
    tx_id = tx_res.json()["id"]
    mem_res = await async_client.post(f"/api/v1/memories/build/{tx_id}")
    memory_id = mem_res.json()["id"]

    # 3. Evaluate Decision -> DECISION_EVALUATED
    eval_res = await async_client.post(
        "/api/v1/decisions/evaluate",
        json={
            "user_id": user_id,
            "merchant_id": merchant_id,
            "amount": "20.00",
            "currency": "USD",
            "transaction_type": "PURCHASE",
        },
    )
    assert eval_res.status_code == 200

    # 4. Execute Memory Compression -> MEMORY_COMPRESSED
    cmp_res = await async_client.post(
        "/api/v1/memories/compress",
        json={"user_id": user_id, "lookback_days": 90},
    )
    assert cmp_res.status_code == 200

    # 5. Retire Memory -> MEMORY_RETIRED
    ret_res = await async_client.post(f"/api/v1/memories/{memory_id}/retire")
    assert ret_res.status_code == 200

    # 6. Check Audit Log API
    audit_list = await async_client.get(f"/api/v1/audit?user_id={user_id}")
    assert audit_list.status_code == 200
    events = audit_list.json()["records"]
    assert len(events) >= 4

    event_types = [e["event_type"] for e in events]
    assert "MEMORY_CREATED" in event_types
    assert "DECISION_EVALUATED" in event_types
    assert "MEMORY_COMPRESSED" in event_types
    assert "MEMORY_RETIRED" in event_types

    # 7. Check Verification API Endpoint
    verify_api = await async_client.get("/api/v1/audit/verify")
    assert verify_api.status_code == 200
    v_data = verify_api.json()
    assert v_data["valid"] is True
    assert v_data["records_checked"] >= 4


@pytest.mark.asyncio
async def test_tampering_detection_on_altered_event_data(
    test_db_session: AsyncSession,
):
    """Verify that tampering with event_data in the database causes verification failure."""
    uid = uuid.uuid4()
    r1 = await AuditLogService.append_event(
        db=test_db_session,
        event_type=AuditEventType.DECISION_EVALUATED,
        entity_type="DECISION",
        entity_id=uuid.uuid4(),
        user_id=uid,
        event_data={"decision": "BLOCK", "amount": "100.00"},
    )
    await AuditLogService.append_event(
        db=test_db_session,
        event_type=AuditEventType.DECISION_EVALUATED,
        entity_type="DECISION",
        entity_id=uuid.uuid4(),
        user_id=uid,
        event_data={"decision": "ALLOW", "amount": "20.00"},
    )
    await test_db_session.commit()

    # Tamper with record 1 data: alter decision from BLOCK to ALLOW
    r1.event_data = {"decision": "ALLOW", "amount": "100.00"}
    await test_db_session.commit()

    v_res = await AuditLogService.verify_chain(db=test_db_session)
    assert v_res.valid is False
    assert v_res.failure_reason == "RECORD_HASH_MISMATCH"
    assert v_res.first_invalid_record_id == r1.id


@pytest.mark.asyncio
async def test_tampering_detection_on_altered_previous_hash(
    test_db_session: AsyncSession,
):
    """Verify that tampering with previous_hash linkage causes verification failure."""
    uid = uuid.uuid4()
    await AuditLogService.append_event(
        db=test_db_session,
        event_type=AuditEventType.MEMORY_CREATED,
        entity_type="MEMORY",
        user_id=uid,
        event_data={"info": "r1"},
    )
    r2 = await AuditLogService.append_event(
        db=test_db_session,
        event_type=AuditEventType.MEMORY_CREATED,
        entity_type="MEMORY",
        user_id=uid,
        event_data={"info": "r2"},
    )
    await test_db_session.commit()

    # Tamper with record 2 previous_hash
    r2.previous_hash = "fake_previous_hash_00000000000000000000000000000000"
    await test_db_session.commit()

    v_res = await AuditLogService.verify_chain(db=test_db_session)
    assert v_res.valid is False
    assert "PREVIOUS_HASH" in (v_res.failure_reason or "")


@pytest.mark.asyncio
async def test_tampering_detection_on_deleted_middle_record(
    test_db_session: AsyncSession,
):
    """Verify that deleting a middle record creates an observable sequence or hash mismatch."""
    uid = uuid.uuid4()
    await AuditLogService.append_event(
        db=test_db_session,
        event_type=AuditEventType.MEMORY_CREATED,
        entity_type="MEMORY",
        user_id=uid,
    )
    r2 = await AuditLogService.append_event(
        db=test_db_session,
        event_type=AuditEventType.MEMORY_CREATED,
        entity_type="MEMORY",
        user_id=uid,
    )
    await AuditLogService.append_event(
        db=test_db_session,
        event_type=AuditEventType.MEMORY_CREATED,
        entity_type="MEMORY",
        user_id=uid,
    )
    await test_db_session.commit()

    # Delete record 2
    await test_db_session.delete(r2)
    await test_db_session.commit()

    v_res = await AuditLogService.verify_chain(db=test_db_session)
    assert v_res.valid is False
    assert "SEQUENCE_GAP" in (v_res.failure_reason or "")


@pytest.mark.asyncio
async def test_decision_safety_invariants_preserved_with_audit(
    async_client: AsyncClient,
):
    """Verify that audit logging integration does NOT alter financial decision outcomes."""
    u_res = await async_client.post(
        "/api/v1/users",
        json={"external_reference": "aud_safe_u", "status": "ACTIVE"},
    )
    user_id = u_res.json()["id"]

    m_res = await async_client.post(
        "/api/v1/merchants",
        json={"name": "OpenAI API", "external_reference": "aud_safe_m"},
    )
    merchant_id = m_res.json()["id"]

    # 1. Policy ($30.00 limit)
    await async_client.post(
        "/api/v1/policies",
        json={
            "user_id": user_id,
            "name": "Limit $30",
            "policy_type": "TRANSACTION_LIMIT",
            "status": "ACTIVE",
            "currency": "USD",
            "limit_amount": "30.0000",
            "rules": {},
        },
    )

    # 2. Evaluate breach ($100.00 > $30.00) -> BLOCK
    eval_block = await async_client.post(
        "/api/v1/decisions/evaluate",
        json={
            "user_id": user_id,
            "merchant_id": merchant_id,
            "amount": "100.00",
            "currency": "USD",
            "transaction_type": "PURCHASE",
        },
    )
    assert eval_block.status_code == 200
    assert eval_block.json()["decision"] == DecisionOutcome.BLOCK.value
    assert eval_block.json()["reason_code"] == "POLICY_LIMIT_EXCEEDED"

    # 3. Evaluate valid purchase ($20.00 <= $30.00) -> ALLOW
    eval_allow = await async_client.post(
        "/api/v1/decisions/evaluate",
        json={
            "user_id": user_id,
            "merchant_id": merchant_id,
            "amount": "20.00",
            "currency": "USD",
            "transaction_type": "PURCHASE",
        },
    )
    assert eval_allow.status_code == 200
    assert eval_allow.json()["decision"] == DecisionOutcome.ALLOW.value
    assert eval_allow.json()["reason_code"] == "DETERMINISTIC_RULES_PASSED"

    # 4. Verify GET /audit without user_id (global list) returns all records
    audit_global_res = await async_client.get("/api/v1/audit?limit=50")
    assert audit_global_res.status_code == 200
    global_data = audit_global_res.json()
    assert "records" in global_data
    assert global_data["count"] >= 2

    # 5. Verify GET /audit/verify endpoint
    verify_res = await async_client.get("/api/v1/audit/verify")
    assert verify_res.status_code == 200
    v_data = verify_res.json()
    assert v_data["valid"] is True
    assert v_data["records_checked"] >= 2
    assert v_data["failure_reason"] is None
