"""Integration tests for database connectivity, session, and models."""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import SystemMetadata


@pytest.mark.asyncio
async def test_system_metadata_crud(test_db_session: AsyncSession):
    """Verify ORM model creation, query, update, and deletion lifecycle."""
    # 1. Create
    meta = SystemMetadata(
        key="schema_version",
        value="1.0.0",
        description="Day 1 Initial Schema Version",
    )
    test_db_session.add(meta)
    await test_db_session.commit()

    # 2. Query
    query = select(SystemMetadata).where(SystemMetadata.key == "schema_version")
    result = await test_db_session.execute(query)
    record = result.scalar_one_or_none()

    assert record is not None
    assert record.key == "schema_version"
    assert record.value == "1.0.0"
    assert record.id is not None
    assert record.created_at is not None
    assert record.updated_at is not None

    # 3. Update
    record.value = "1.0.1"
    await test_db_session.commit()

    result = await test_db_session.execute(query)
    updated_record = result.scalar_one()
    assert updated_record.value == "1.0.1"

    # 4. Delete
    await test_db_session.delete(updated_record)
    await test_db_session.commit()

    result = await test_db_session.execute(query)
    assert result.scalar_one_or_none() is None
