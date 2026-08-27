"""Unit tests for Razorpay client and payment execution service."""

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import (
    DecisionOutcome,
    MerchantStatus,
    PolicyStatus,
    PolicyType,
    TransactionStatus,
    TransactionType,
    UserStatus,
)
from app.models.merchant import Merchant
from app.models.policy import Policy
from app.models.transaction import Transaction
from app.models.user import User
from app.schemas.payment import (
    DecisionConfirmationRequest,
    PaymentExecutionRequest,
)
from app.services.audit.service import AuditLogService
from app.services.payment.client import RazorpayTestClient
from app.services.payment.service import PaymentExecutionService


@pytest.mark.asyncio
async def test_razorpay_client_sandbox_simulation() -> None:
    """Test RazorpayTestClient creates deterministic sandbox orders when keys are omitted."""
    client = RazorpayTestClient(key_id=None, key_secret=None)
    assert not client.is_configured

    res = await client.create_order(
        amount=Decimal("49.99"),
        currency="INR",
        receipt="rcpt_12345",
        notes={"test": "true"},
    )
    assert res.order_id.startswith("order_test_")
    assert res.amount == Decimal("49.99")
    assert res.currency == "INR"
    assert res.gateway_mode == "SANDBOX_SIMULATION"
    assert res.raw_response["simulated"] is True


@pytest.mark.asyncio
async def test_payment_execution_allow_and_success(
    test_db_session: AsyncSession,
) -> None:
    """Test payment execution gate executes Razorpay payment on ALLOW and updates audit trail."""
    # Setup User and Merchant
    user = User(external_reference="test_pay_user_01", status=UserStatus.ACTIVE)
    merchant = Merchant(
        name="Verified Merchant",
        external_reference="m_01",
        status=MerchantStatus.ACTIVE,
    )
    test_db_session.add_all([user, merchant])
    await test_db_session.flush()

    # Add Policy with generous limit
    policy = Policy(
        user_id=user.id,
        name="Allow Budget",
        policy_type=PolicyType.TRANSACTION_LIMIT,
        status=PolicyStatus.ACTIVE,
        currency="INR",
        limit_amount=Decimal("500.00"),
    )
    test_db_session.add(policy)
    await test_db_session.commit()

    service = PaymentExecutionService()
    req = PaymentExecutionRequest(
        user_id=user.id,
        merchant_id=merchant.id,
        amount=Decimal("150.00"),
        currency="INR",
        transaction_type=TransactionType.PURCHASE,
    )
    res = await service.execute_payment(req, test_db_session)

    assert res.decision == DecisionOutcome.ALLOW
    assert res.status == "SUCCESS"
    assert res.transaction_id is not None
    assert res.gateway_order_id is not None
    assert res.amount == Decimal("150.00")

    # Verify authoritative Transaction was persisted
    tx = await test_db_session.get(Transaction, res.transaction_id)
    assert tx is not None
    assert tx.status == TransactionStatus.CAPTURED
    assert tx.amount == Decimal("150.00")

    # Verify Audit trail
    audit_res = await AuditLogService.verify_chain(test_db_session)
    assert audit_res.valid


@pytest.mark.asyncio
async def test_payment_execution_blocked_by_policy(
    test_db_session: AsyncSession,
) -> None:
    """Test payment execution is halted immediately on policy BLOCK with zero payment attempt."""
    user = User(external_reference="test_pay_user_02", status=UserStatus.ACTIVE)
    merchant = Merchant(
        name="Verified Merchant",
        external_reference="m_02",
        status=MerchantStatus.ACTIVE,
    )
    test_db_session.add_all([user, merchant])
    await test_db_session.flush()

    # Policy with 50.00 limit
    policy = Policy(
        user_id=user.id,
        name="Strict Budget",
        policy_type=PolicyType.TRANSACTION_LIMIT,
        status=PolicyStatus.ACTIVE,
        currency="INR",
        limit_amount=Decimal("50.00"),
    )
    test_db_session.add(policy)
    await test_db_session.commit()

    service = PaymentExecutionService()
    req = PaymentExecutionRequest(
        user_id=user.id,
        merchant_id=merchant.id,
        amount=Decimal("100.00"),  # Exceeds 50.00
        currency="INR",
        transaction_type=TransactionType.PURCHASE,
    )
    res = await service.execute_payment(req, test_db_session)

    assert res.decision == DecisionOutcome.BLOCK
    assert res.status == "BLOCKED"
    assert res.transaction_id is None
    assert res.gateway_order_id is None
    assert res.reason_code == "POLICY_LIMIT_EXCEEDED"

    # Verify Audit integrity
    audit_res = await AuditLogService.verify_chain(test_db_session)
    assert audit_res.valid


@pytest.mark.asyncio
async def test_payment_execution_ask_user_and_confirm(
    test_db_session: AsyncSession,
) -> None:
    """Test payment execution requiring ASK_USER halts and executes upon confirmation."""
    user = User(external_reference="test_pay_user_03", status=UserStatus.ACTIVE)
    merchant = Merchant(
        name="Cloud Service", external_reference="m_03", status=MerchantStatus.ACTIVE
    )
    test_db_session.add_all([user, merchant])
    await test_db_session.flush()

    # Seed 3 historical transactions at 20.00 to establish baseline
    for _ in range(3):
        tx = Transaction(
            user_id=user.id,
            merchant_id=merchant.id,
            amount=Decimal("20.00"),
            currency="INR",
            transaction_type=TransactionType.PURCHASE,
            status=TransactionStatus.CAPTURED,
        )
        test_db_session.add(tx)
    await test_db_session.commit()

    service = PaymentExecutionService()
    # Propose 45.00 (+125% drift)
    req = PaymentExecutionRequest(
        user_id=user.id,
        merchant_id=merchant.id,
        amount=Decimal("45.00"),
        currency="INR",
        transaction_type=TransactionType.PURCHASE,
    )
    res = await service.execute_payment(req, test_db_session)

    assert res.decision == DecisionOutcome.ASK_USER
    assert res.status == "REQUIRES_USER_CONFIRMATION"
    assert res.transaction_id is None
    assert res.decision_id is not None

    # Now Confirm via User
    confirm_req = DecisionConfirmationRequest(
        confirmed=True,
        execute_payment_now=True,
        user_notes="Authorized price increase",
    )
    confirm_res = await service.confirm_decision(
        res.decision_id, confirm_req, test_db_session
    )

    assert confirm_res.confirmed is True
    assert confirm_res.status == "CONFIRMED"
    assert confirm_res.payment_result is not None
    assert confirm_res.payment_result.status == "SUCCESS"
    assert confirm_res.payment_result.transaction_id is not None
