"""Transaction management and querying API endpoints."""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppException, ResourceNotFoundError
from app.db.session import get_db_session
from app.models.enums import TransactionStatus
from app.models.mandate import Mandate
from app.models.merchant import Merchant
from app.models.transaction import Transaction
from app.models.user import User
from app.schemas.transaction import TransactionCreate, TransactionRead

router = APIRouter(prefix="/transactions", tags=["Transactions"])


@router.post(
    "",
    response_model=TransactionRead,
    status_code=status.HTTP_201_CREATED,
    summary="Record a new Transaction",
)
async def create_transaction(
    payload: TransactionCreate,
    db: AsyncSession = Depends(get_db_session),
) -> Transaction:
    """Records a financial transaction event after validation."""
    # 1. Verify User exists
    user = await db.get(User, payload.user_id)
    if not user:
        raise AppException(
            message=f"User with ID {payload.user_id} does not exist",
            error_code="USER_NOT_FOUND",
            status_code=status.HTTP_404_NOT_FOUND,
        )

    # 2. Verify Merchant exists
    merchant = await db.get(Merchant, payload.merchant_id)
    if not merchant:
        raise AppException(
            message=f"Merchant with ID {payload.merchant_id} does not exist",
            error_code="MERCHANT_NOT_FOUND",
            status_code=status.HTTP_404_NOT_FOUND,
        )

    # 3. Verify Mandate compatibility if provided
    if payload.mandate_id:
        mandate = await db.get(Mandate, payload.mandate_id)
        if not mandate:
            raise AppException(
                message=f"Mandate with ID {payload.mandate_id} does not exist",
                error_code="MANDATE_NOT_FOUND",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        if mandate.user_id != payload.user_id:
            raise AppException(
                message=(
                    f"Mandate {payload.mandate_id} does not belong to "
                    f"user {payload.user_id}"
                ),
                error_code="MANDATE_USER_MISMATCH",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        if mandate.merchant_id and mandate.merchant_id != payload.merchant_id:
            raise AppException(
                message=(
                    f"Mandate {payload.mandate_id} is restricted to "
                    f"merchant {mandate.merchant_id}"
                ),
                error_code="MANDATE_MERCHANT_MISMATCH",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        if mandate.currency != payload.currency:
            raise AppException(
                message=(
                    f"Mandate currency {mandate.currency} does not match "
                    f"transaction currency {payload.currency}"
                ),
                error_code="CURRENCY_MISMATCH",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

    # 4. Check Idempotency key uniqueness if provided
    if payload.idempotency_key:
        existing = await db.scalar(
            select(Transaction).where(
                Transaction.idempotency_key == payload.idempotency_key
            )
        )
        if existing:
            raise AppException(
                message=(
                    f"Transaction with idempotency key "
                    f"{payload.idempotency_key!r} already exists"
                ),
                error_code="DUPLICATE_IDEMPOTENCY_KEY",
                status_code=status.HTTP_409_CONFLICT,
                details={"existing_transaction_id": str(existing.id)},
            )

    occurred_at = payload.occurred_at or datetime.now(UTC)

    transaction = Transaction(
        user_id=payload.user_id,
        merchant_id=payload.merchant_id,
        mandate_id=payload.mandate_id,
        amount=payload.amount,
        currency=payload.currency,
        transaction_type=payload.transaction_type,
        status=payload.status,
        external_reference=payload.external_reference,
        idempotency_key=payload.idempotency_key,
        occurred_at=occurred_at,
    )
    db.add(transaction)
    await db.flush()
    await db.refresh(transaction)
    return transaction


@router.get(
    "/{transaction_id}",
    response_model=TransactionRead,
    status_code=status.HTTP_200_OK,
    summary="Get Transaction by ID",
)
async def get_transaction(
    transaction_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_session),
) -> Transaction:
    """Retrieves transaction record by UUID."""
    transaction = await db.get(Transaction, transaction_id)
    if not transaction:
        raise ResourceNotFoundError(
            f"Transaction with ID {transaction_id} was not found"
        )
    return transaction


@router.get(
    "",
    response_model=list[TransactionRead],
    status_code=status.HTTP_200_OK,
    summary="List and Filter Transactions",
)
async def list_transactions(
    user_id: uuid.UUID | None = Query(default=None, description="Filter by User UUID"),
    merchant_id: uuid.UUID | None = Query(
        default=None, description="Filter by Merchant UUID"
    ),
    mandate_id: uuid.UUID | None = Query(
        default=None, description="Filter by Mandate UUID"
    ),
    transaction_status: TransactionStatus | None = Query(
        default=None, alias="status", description="Filter by transaction status"
    ),
    limit: int = Query(default=50, ge=1, le=200, description="Max records to return"),
    offset: int = Query(default=0, ge=0, description="Records offset"),
    db: AsyncSession = Depends(get_db_session),
) -> list[Transaction]:
    """Queries transaction records with optional relational filters."""
    query = select(Transaction)

    if user_id:
        query = query.where(Transaction.user_id == user_id)
    if merchant_id:
        query = query.where(Transaction.merchant_id == merchant_id)
    if mandate_id:
        query = query.where(Transaction.mandate_id == mandate_id)
    if transaction_status:
        query = query.where(Transaction.status == transaction_status)

    query = query.order_by(Transaction.occurred_at.desc()).limit(limit).offset(offset)
    result = await db.execute(query)
    return list(result.scalars().all())
