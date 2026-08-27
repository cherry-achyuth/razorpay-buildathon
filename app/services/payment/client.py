"""Razorpay Test Mode client for autonomous agent payment execution."""

import logging
import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class RazorpayOrderResult:
    """Result of creating an order in Razorpay Test Mode."""

    order_id: str
    amount: Decimal
    currency: str
    status: str
    receipt: str
    gateway_mode: str  # "RAZORPAY_TEST_MODE" or "SANDBOX_SIMULATION"
    raw_response: dict[str, Any]


class RazorpayTestClient:
    """Client for official Razorpay Test Mode / Sandbox payment APIs."""

    BASE_URL = "https://api.razorpay.com/v1"

    def __init__(
        self,
        key_id: str | None = None,
        key_secret: str | None = None,
        timeout: float = 10.0,
    ) -> None:
        settings = get_settings()
        self.key_id = key_id if key_id is not None else settings.RAZORPAY_KEY_ID
        self.key_secret = (
            key_secret if key_secret is not None else settings.RAZORPAY_KEY_SECRET
        )
        self.timeout = timeout
        self.is_configured = self._check_configured()

    def _check_configured(self) -> bool:
        """Returns True only when real, non-placeholder credentials are provided."""
        if not self.key_id or not self.key_secret:
            return False
        placeholders = [
            "placeholder",
            "your_key",
            "your_secret",
            "rzp_test_demo",
            "rzp_test_your_key",
            "demo",
        ]
        if any(p in self.key_id.lower() for p in placeholders) or any(
            p in self.key_secret.lower() for p in placeholders
        ):
            return False
        return True

    async def create_order(
        self,
        amount: Decimal,
        currency: str,
        receipt: str,
        notes: dict[str, Any] | None = None,
    ) -> RazorpayOrderResult:
        """Creates a Razorpay Test Mode order.

        Amount is converted to the smallest currency unit (e.g. INR -> paise: amount * 100).
        """
        # Smallest currency unit integer amount (paise/cents)
        amount_subunits = int(round(amount * Decimal("100")))

        if self.is_configured and self.key_id and self.key_secret:
            auth = (self.key_id, self.key_secret)
            payload = {
                "amount": amount_subunits,
                "currency": currency.upper(),
                "receipt": receipt[:40],  # Razorpay receipt max 40 chars
                "notes": notes or {},
            }
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    resp = await client.post(
                        f"{self.BASE_URL}/orders",
                        json=payload,
                        auth=auth,
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    return RazorpayOrderResult(
                        order_id=data["id"],
                        amount=Decimal(str(data["amount"] / 100)),
                        currency=data["currency"],
                        status=data.get("status", "created"),
                        receipt=data.get("receipt", receipt),
                        gateway_mode="RAZORPAY_TEST_MODE",
                        raw_response=data,
                    )
            except httpx.HTTPStatusError as exc:
                logger.error(
                    "Razorpay API error (%s): %s",
                    exc.response.status_code,
                    exc.response.text,
                )
                raise
            except Exception as exc:
                logger.error("Razorpay connection error: %s", exc)
                raise

        # Fallback to local sandbox simulation when API keys are not provided
        logger.info(
            "Razorpay Test Mode credentials not configured. Executing sandbox simulation."
        )
        sim_order_id = f"order_test_{uuid.uuid4().hex[:14]}"
        return RazorpayOrderResult(
            order_id=sim_order_id,
            amount=amount,
            currency=currency.upper(),
            status="created",
            receipt=receipt[:40],
            gateway_mode="SANDBOX_SIMULATION",
            raw_response={
                "id": sim_order_id,
                "entity": "order",
                "amount": amount_subunits,
                "currency": currency.upper(),
                "receipt": receipt[:40],
                "status": "created",
                "notes": notes or {},
                "simulated": True,
            },
        )
