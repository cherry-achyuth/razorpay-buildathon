"""Mandate management API endpoints."""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppException, ResourceNotFoundError
from app.db.session import get_db_session
from app.models.mandate import Mandate
from app.models.merchant import Merchant
from app.models.user import User
from app.schemas.mandate import MandateCreate, MandateRead

router = APIRouter(prefix="/mandates", tags=["Mandates"])


@router.post(
    "",
    response_model=MandateRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new Mandate",
)
async def create_mandate(
    payload: MandateCreate,
    db: AsyncSession = Depends(get_db_session),
) -> Mandate:
    """Creates a bounded financial authorization mandate."""
    # 1. Verify User exists
    user = await db.get(User, payload.user_id)
    if not user:
        raise AppException(
            message=f"User with ID {payload.user_id} does not exist",
            error_code="USER_NOT_FOUND",
            status_code=status.HTTP_404_NOT_FOUND,
        )

    # 2. Verify Merchant exists if specified
    if payload.merchant_id:
        merchant = await db.get(Merchant, payload.merchant_id)
        if not merchant:
            raise AppException(
                message=f"Merchant with ID {payload.merchant_id} does not exist",
                error_code="MERCHANT_NOT_FOUND",
                status_code=status.HTTP_404_NOT_FOUND,
            )

    valid_from = payload.valid_from or datetime.now(UTC)

    mandate = Mandate(
        user_id=payload.user_id,
        merchant_id=payload.merchant_id,
        status=payload.status,
        currency=payload.currency,
        max_transaction_amount=payload.max_transaction_amount,
        valid_from=valid_from,
        valid_until=payload.valid_until,
    )
    db.add(mandate)
    await db.flush()
    await db.refresh(mandate)
    return mandate


@router.get(
    "/{mandate_id}",
    response_model=MandateRead,
    status_code=status.HTTP_200_OK,
    summary="Get Mandate by ID",
)
async def get_mandate(
    mandate_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_session),
) -> Mandate:
    """Retrieves mandate configuration and bounds by UUID."""
    mandate = await db.get(Mandate, mandate_id)
    if not mandate:
        raise ResourceNotFoundError(f"Mandate with ID {mandate_id} was not found")
    return mandate
