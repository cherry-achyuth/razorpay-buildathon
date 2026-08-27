"""Merchant management API endpoints."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppException, ResourceNotFoundError
from app.db.session import get_db_session
from app.models.enums import MerchantStatus
from app.models.merchant import Merchant
from app.schemas.merchant import (
    MerchantCreate,
    MerchantListResponse,
    MerchantRead,
)

router = APIRouter(prefix="/merchants", tags=["Merchants"])


@router.get(
    "",
    response_model=MerchantListResponse,
    status_code=status.HTTP_200_OK,
    summary="List all Merchants",
    description="Retrieves a collection of registered merchants with optional filtering and pagination.",
)
async def list_merchants(
    limit: Annotated[
        int, Query(ge=1, le=100, description="Max records to return.")
    ] = 50,
    offset: Annotated[int, Query(ge=0, description="Records offset.")] = 0,
    status_filter: Annotated[
        MerchantStatus | None,
        Query(alias="status", description="Filter by merchant status."),
    ] = None,
    db: AsyncSession = Depends(get_db_session),
) -> MerchantListResponse:
    """Retrieves collection of registered merchants."""
    query = select(Merchant)
    if status_filter:
        query = query.where(Merchant.status == status_filter)
    query = query.order_by(Merchant.created_at.desc()).limit(limit).offset(offset)
    result = await db.execute(query)
    merchants = list(result.scalars().all())
    validated = [MerchantRead.model_validate(m) for m in merchants]
    return MerchantListResponse(merchants=validated, count=len(validated))


@router.post(
    "",
    response_model=MerchantRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new Merchant",
)
async def create_merchant(
    payload: MerchantCreate,
    db: AsyncSession = Depends(get_db_session),
) -> Merchant:
    """Registers a new Merchant."""
    if payload.external_reference:
        existing = await db.scalar(
            select(Merchant).where(
                Merchant.external_reference == payload.external_reference
            )
        )
        if existing:
            raise AppException(
                message=(
                    f"Merchant with external reference "
                    f"{payload.external_reference!r} already exists"
                ),
                error_code="MERCHANT_ALREADY_EXISTS",
                status_code=status.HTTP_409_CONFLICT,
            )

    merchant = Merchant(
        name=payload.name,
        external_reference=payload.external_reference,
        status=payload.status,
    )
    db.add(merchant)
    await db.flush()
    await db.refresh(merchant)
    return merchant


@router.get(
    "/{merchant_id}",
    response_model=MerchantRead,
    status_code=status.HTTP_200_OK,
    summary="Get Merchant by ID",
)
async def get_merchant(
    merchant_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_session),
) -> Merchant:
    """Retrieves merchant details by UUID."""
    merchant = await db.get(Merchant, merchant_id)
    if not merchant:
        raise ResourceNotFoundError(f"Merchant with ID {merchant_id} was not found")
    return merchant
