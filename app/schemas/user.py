"""Pydantic schemas for User domain model."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import UserStatus


class UserBase(BaseModel):
    """Base fields for User."""

    external_reference: str | None = Field(
        default=None,
        max_length=128,
        description="External identifier from client or auth provider.",
        examples=["ext_user_10293"],
    )
    status: UserStatus = Field(
        default=UserStatus.ACTIVE,
        description="User account status.",
    )


class UserCreate(UserBase):
    """Payload for creating a new User."""

    pass


class UserUpdate(BaseModel):
    """Payload for updating an existing User."""

    status: UserStatus | None = None
    external_reference: str | None = Field(default=None, max_length=128)


class UserRead(UserBase):
    """Response model for a User."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class UserListResponse(BaseModel):
    """Response model for a list of Users."""

    users: list[UserRead]
    count: int
