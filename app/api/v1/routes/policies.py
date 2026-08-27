"""Policy management API endpoints."""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppException, ResourceNotFoundError
from app.db.session import get_db_session
from app.models.policy import Policy
from app.models.user import User
from app.schemas.policy import PolicyCreate, PolicyRead

router = APIRouter(prefix="/policies", tags=["Policies"])


@router.post(
    "",
    response_model=PolicyRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new Policy",
)
async def create_policy(
    payload: PolicyCreate,
    db: AsyncSession = Depends(get_db_session),
) -> Policy:
    """Configures a spending or restriction policy for a user."""
    user = await db.get(User, payload.user_id)
    if not user:
        raise AppException(
            message=f"User with ID {payload.user_id} does not exist",
            error_code="USER_NOT_FOUND",
            status_code=status.HTTP_404_NOT_FOUND,
        )

    valid_from = payload.valid_from or datetime.now(UTC)

    policy = Policy(
        user_id=payload.user_id,
        name=payload.name,
        policy_type=payload.policy_type,
        status=payload.status,
        currency=payload.currency,
        limit_amount=payload.limit_amount,
        valid_from=valid_from,
        valid_until=payload.valid_until,
        rules=payload.rules,
    )
    db.add(policy)
    await db.flush()
    await db.refresh(policy)
    return policy


@router.get(
    "/{policy_id}",
    response_model=PolicyRead,
    status_code=status.HTTP_200_OK,
    summary="Get Policy by ID",
)
async def get_policy(
    policy_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_session),
) -> Policy:
    """Retrieves policy definition by UUID."""
    policy = await db.get(Policy, policy_id)
    if not policy:
        raise ResourceNotFoundError(f"Policy with ID {policy_id} was not found")
    return policy
