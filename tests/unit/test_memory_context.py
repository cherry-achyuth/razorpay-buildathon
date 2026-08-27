"""Unit tests for DecisionMemoryContext and Memory Context Schemas."""

import uuid
from datetime import UTC, datetime, timedelta

from app.models.enums import (
    MemoryRelevance,
    MemorySourceType,
    MemoryStatus,
    MemoryType,
)
from app.models.memory import DecisionMemory, DecisionMemorySource
from app.schemas.decision import (
    DecisionMemoryContextResponse,
)
from app.services.guardrails.base import DecisionMemoryContext


def test_decision_memory_context_from_model():
    """Verify DecisionMemoryContext accurately converts DecisionMemory model."""
    mem_id = uuid.uuid4()
    user_id = uuid.uuid4()
    source_id = uuid.uuid4()
    now = datetime.now(UTC)

    source = DecisionMemorySource(
        id=uuid.uuid4(),
        memory_id=mem_id,
        source_type=MemorySourceType.TRANSACTION,
        source_id=source_id,
        created_at=now,
    )

    memory = DecisionMemory(
        id=mem_id,
        user_id=user_id,
        memory_type=MemoryType.PRICE_PATTERN,
        relevance=MemoryRelevance.HIGH,
        status=MemoryStatus.ACTIVE,
        summary="Median baseline price for GitHub Copilot is 19.99 USD.",
        structured_data={
            "median_amount": "19.9900",
            "currency": "USD",
            "sample_count": 5,
        },
        version=1,
        valid_from=now - timedelta(days=1),
        valid_until=now + timedelta(days=30),
        created_at=now,
        updated_at=now,
    )
    memory.sources = [source]

    ctx = DecisionMemoryContext.from_model(memory)

    assert ctx.memory_id == mem_id
    assert ctx.memory_type == MemoryType.PRICE_PATTERN
    assert ctx.relevance == MemoryRelevance.HIGH
    assert ctx.status == MemoryStatus.ACTIVE
    assert "GitHub Copilot" in ctx.summary
    assert ctx.structured_data["sample_count"] == 5
    assert len(ctx.sources) == 1
    assert ctx.sources[0].source_type == "TRANSACTION"
    assert ctx.sources[0].source_id == source_id


def test_decision_memory_context_response_schema():
    """Verify DecisionMemoryContextResponse schema serialization."""
    mem_id = uuid.uuid4()
    source_id = uuid.uuid4()
    src_uuid = uuid.uuid4()
    now = datetime.now(UTC)

    resp_ctx = DecisionMemoryContextResponse(
        memory_id=mem_id,
        memory_type=MemoryType.ROUTINE_PATTERN,
        relevance=MemoryRelevance.NORMAL,
        summary="Standard recurring purchase of 50.00 USD.",
        structured_data={"amount": "50.00", "currency": "USD"},
        sources=[
            {
                "id": src_uuid,
                "memory_id": mem_id,
                "source_type": MemorySourceType.TRANSACTION,
                "source_id": source_id,
                "created_at": now,
            }
        ],
    )

    dumped = resp_ctx.model_dump(mode="json")
    assert dumped["memory_id"] == str(mem_id)
    assert dumped["memory_type"] == "ROUTINE_PATTERN"
    assert dumped["relevance"] == "NORMAL"
    assert len(dumped["sources"]) == 1
    assert dumped["sources"][0]["source_type"] == "TRANSACTION"
