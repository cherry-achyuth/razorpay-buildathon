"""Pydantic schemas for Merchant domain model."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import MerchantStatus


class MerchantBase(BaseModel):
    """Base fields for Merchant."""

    name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Legal or trading name of the merchant.",
        examples=["Cloud Services Inc."],
    )
    external_reference: str | None = Field(
        default=None,
        max_length=128,
        description="External merchant identifier.",
        examples=["merch_9921"],
    )
    status: MerchantStatus = Field(
        default=MerchantStatus.ACTIVE,
        description="Merchant status.",
    )


class MerchantCreate(MerchantBase):
    """Payload for creating a new Merchant."""

    pass


class MerchantRead(MerchantBase):
    """Response model for a Merchant."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class MerchantListResponse(BaseModel):
    """Response model for a list of Merchants."""

    merchants: list[MerchantRead]
    count: int
