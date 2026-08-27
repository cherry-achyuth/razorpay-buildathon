"""API routes for Demo Data Seeding & Buildathon Scenarios."""

from typing import Any

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from scripts.seed_demo import seed_demo_data

router = APIRouter(prefix="/demo", tags=["Demo & Scenarios"])


@router.post(
    "/seed",
    status_code=status.HTTP_200_OK,
    summary="Seed Deterministic 30-Day Buildathon Demo Data",
    description=(
        "Populates or verifies deterministic demo dataset (user, merchants, spend policies, "
        "mandates, 30-day baseline history, compressed memories, and valid audit chain) "
        "safely and idempotently."
    ),
)
async def seed_demo(
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Execute deterministic demo seeding in the active database."""
    result = await seed_demo_data(session=db)
    return {
        "status": "SUCCESS",
        "message": "Deterministic Buildathon demo data seeded successfully.",
        "data": result,
    }
