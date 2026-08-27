"""User management API endpoints."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppException, ResourceNotFoundError
from app.db.session import get_db_session
from app.models.enums import UserStatus
from app.models.user import User
from app.schemas.user import UserCreate, UserListResponse, UserRead

router = APIRouter(prefix="/users", tags=["Users"])


@router.get(
    "",
    response_model=UserListResponse,
    status_code=status.HTTP_200_OK,
    summary="List all Users",
    description="Retrieves a collection of registered users with optional filtering and pagination.",
)
async def list_users(
    limit: Annotated[
        int, Query(ge=1, le=100, description="Max records to return.")
    ] = 50,
    offset: Annotated[int, Query(ge=0, description="Records offset.")] = 0,
    status_filter: Annotated[
        UserStatus | None,
        Query(alias="status", description="Filter by user status."),
    ] = None,
    db: AsyncSession = Depends(get_db_session),
) -> UserListResponse:
    """Retrieves collection of registered users."""
    query = select(User)
    if status_filter:
        query = query.where(User.status == status_filter)
    query = query.order_by(User.created_at.desc()).limit(limit).offset(offset)
    result = await db.execute(query)
    users = list(result.scalars().all())
    validated = [UserRead.model_validate(u) for u in users]
    return UserListResponse(users=validated, count=len(validated))


@router.post(
    "",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new User",
)
async def create_user(
    payload: UserCreate,
    db: AsyncSession = Depends(get_db_session),
) -> User:
    """Registers a new User for financial authorization."""
    if payload.external_reference:
        existing = await db.scalar(
            select(User).where(User.external_reference == payload.external_reference)
        )
        if existing:
            raise AppException(
                message=(
                    f"User with external reference "
                    f"{payload.external_reference!r} already exists"
                ),
                error_code="USER_ALREADY_EXISTS",
                status_code=status.HTTP_409_CONFLICT,
            )

    user = User(
        external_reference=payload.external_reference,
        status=payload.status,
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


@router.get(
    "/{user_id}",
    response_model=UserRead,
    status_code=status.HTTP_200_OK,
    summary="Get User by ID",
)
async def get_user(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_session),
) -> User:
    """Retrieves user details by UUID."""
    user = await db.get(User, user_id)
    if not user:
        raise ResourceNotFoundError(f"User with ID {user_id} was not found")
    return user
