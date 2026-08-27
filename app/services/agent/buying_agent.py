"""Autonomous AI Buying Agent and Natural Language Intent Resolution Service.

Architecture & Safety Rules:
1. Translates natural-language purchase instructions into structured PaymentIntent models.
2. Grounded entity resolution: resolves merchants and routine price baselines from historical DecisionVault state.
3. Strict Security Boundary: LLM outputs are untrusted input. The LLM NEVER directly authorizes money movement
   and CANNOT bypass deterministic guardrails.
4. Fail-Safe: Malformed, ambiguous, or timed-out LLM invocations fail safely to ASK_USER without executing payments.
"""

import json
import logging
import re
import uuid
from decimal import Decimal, InvalidOperation

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.decision import Decision
from app.models.enums import (
    AuditEventType,
    DecisionOutcome,
    MemoryStatus,
    MerchantStatus,
    TransactionType,
)
from app.models.memory import DecisionMemory
from app.models.merchant import Merchant
from app.schemas.agent import (
    AgentEvaluateRequest,
    AgentEvaluateResponse,
    PaymentIntent,
)
from app.schemas.decision import ActionEvaluationRequest, ActionEvaluationResponse
from app.schemas.payment import (
    PaymentExecutionRequest,
    PaymentExecutionResponse,
)
from app.services.audit.service import AuditLogService
from app.services.decision_service import DecisionEvaluationService
from app.services.payment.service import PaymentExecutionService

logger = logging.getLogger("decisionvault.agent")


class BuyingAgentService:
    """Service providing natural language intent parsing and agentic orchestration."""

    @classmethod
    async def interpret_request(
        cls,
        prompt: str,
        user_id: uuid.UUID,
        db: AsyncSession,
        currency: str = "INR",
    ) -> PaymentIntent:
        """Parse natural language request into a validated, entity-resolved PaymentIntent."""
        settings = get_settings()

        # 1. Fetch available merchants and recent context for grounded entity resolution
        merchants = (
            await db.scalars(
                select(Merchant).where(Merchant.status == MerchantStatus.ACTIVE)
            )
        ).all()

        # Fetch recent routine memories / transactions to resolve phrases like "my usual subscription"
        recent_memories = (
            await db.scalars(
                select(DecisionMemory)
                .where(
                    DecisionMemory.user_id == user_id,
                    DecisionMemory.status == MemoryStatus.ACTIVE,
                )
                .order_by(DecisionMemory.created_at.desc())
                .limit(5)
            )
        ).all()

        # 2. Try LLM Provider if configured, otherwise use deterministic semantic parser
        intent: PaymentIntent | None = None
        if settings.GEMINI_API_KEY:
            intent = await cls._interpret_with_gemini(
                prompt=prompt,
                user_id=user_id,
                merchants=merchants,
                memories=recent_memories,
                api_key=settings.GEMINI_API_KEY,
                default_currency=currency,
            )
        elif settings.OPENAI_API_KEY:
            intent = await cls._interpret_with_openai(
                prompt=prompt,
                user_id=user_id,
                merchants=merchants,
                memories=recent_memories,
                api_key=settings.OPENAI_API_KEY,
                default_currency=currency,
            )

        # Fallback to Deterministic Semantic Parser
        if intent is None:
            intent = cls._interpret_deterministic(
                prompt=prompt,
                user_id=user_id,
                merchants=merchants,
                memories=recent_memories,
                default_currency=currency,
            )

        # 3. Grounded Merchant Entity Resolution (Verify/Map or auto-create in DB)
        await cls._resolve_merchant_entity(intent, merchants, recent_memories, db)

        return intent

    @classmethod
    def _interpret_deterministic(
        cls,
        prompt: str,
        user_id: uuid.UUID,
        merchants: list[Merchant],
        memories: list[DecisionMemory],
        default_currency: str,
    ) -> PaymentIntent:
        """Deterministic rule-based intent parser for robust, offline, testable execution."""
        clean_p = prompt.strip().lower()

        # Check for gibberish / empty / underspecified
        if len(clean_p) < 4 or clean_p in ["buy", "pay", "order", "hello", "test"]:
            return PaymentIntent(
                user_id=user_id,
                currency=default_currency,
                is_ambiguous=True,
                ambiguity_reason="Request is underspecified or lacks a clear merchant and amount.",
                confidence=0.1,
            )

        # Check for comparison requests e.g. "compare X vs Y" or "X vs Y"
        if "compare" in clean_p or " vs " in clean_p or " versus " in clean_p:
            service_prices = {
                "netflix": ("Netflix", 1788),
                "prime": ("Amazon Prime", 1499),
                "amazon prime": ("Amazon Prime", 1499),
                "spotify": ("Spotify Premium", 1189),
                "apple music": ("Apple Music", 1188),
                "youtube": ("YouTube Premium", 1548),
                "hotstar": ("Disney+ Hotstar", 1499),
                "swiggy": ("Swiggy One", 899),
                "zomato": ("Zomato Gold", 999),
                "bigbasket": ("BigBasket Star", 499),
            }
            comp_data = []
            merchants_found = []
            for k, (name, price) in service_prices.items():
                if k in clean_p:
                    if name not in merchants_found:
                        merchants_found.append(name)
                        comp_data.append({"name": name, "estimated_annual_inr": price})

            if len(comp_data) >= 2 or ("netflix" in clean_p and "prime" in clean_p):
                if not comp_data:
                    comp_data = [
                        {"name": "Netflix", "estimated_annual_inr": 1788},
                        {"name": "Amazon Prime", "estimated_annual_inr": 1499},
                    ]
                    merchants_found = ["Netflix", "Amazon Prime"]
                return PaymentIntent(
                    user_id=user_id,
                    intent_type="COMPARISON",
                    currency="INR",
                    comparison_merchants=merchants_found,
                    comparison_data=comp_data,
                    confidence=0.95,
                    is_ambiguous=False,
                    resolution_notes="Deterministic comparison resolution for subscription services.",
                )

        # Resolve Merchant Name match from existing list
        matched_merchant: Merchant | None = None
        for m in merchants:
            if m.name.lower() in clean_p or m.external_reference.lower() in clean_p:
                matched_merchant = m
                break

        # Check for keywords matching known common merchants
        merchant_name_extracted = matched_merchant.name if matched_merchant else None
        if not matched_merchant:
            if "netflix" in clean_p:
                merchant_name_extracted = "Netflix"
            elif "prime" in clean_p or "amazon" in clean_p:
                merchant_name_extracted = "Amazon Prime"
            elif "spotify" in clean_p:
                merchant_name_extracted = "Spotify"
            elif "swiggy instamart" in clean_p or "instamart" in clean_p:
                merchant_name_extracted = "Swiggy Instamart"
            elif "swiggy" in clean_p:
                merchant_name_extracted = "Swiggy"
            elif "blinkit" in clean_p:
                merchant_name_extracted = "Blinkit"
            elif "zepto" in clean_p:
                merchant_name_extracted = "Zepto"
            elif "zomato" in clean_p:
                merchant_name_extracted = "Zomato"
            elif "bigbasket" in clean_p or "basket" in clean_p:
                merchant_name_extracted = "BigBasket"
            elif "cloud" in clean_p or "server" in clean_p or "hosting" in clean_p:
                merchant_name_extracted = "CloudCompute Global"
            elif re.search(r"\b(?:github|git|repo)\b", clean_p):
                merchant_name_extracted = "GitHub Enterprise"
            elif re.search(r"\b(?:openai|chatgpt|gpt)\b", clean_p):
                merchant_name_extracted = "OpenAI"
            elif "shady" in clean_p or "unknown" in clean_p:
                merchant_name_extracted = "Unknown Shady Mart"
            else:
                # Try extracting name after "pay", "buy from", "order from", "from", "to", "at"
                m_match = re.search(
                    r"(?:pay|buy from|order from|subscribe to|order|from|at|to)\s+(?:my\s+)?(?:usual\s+)?([a-zA-Z0-9\s]+?)(?:\s+(?:subscription|bill|plan|for|of|online|\d)|\.|$)",
                    clean_p,
                )
                if m_match:
                    raw_candidate = m_match.group(1).strip().title()
                    # Clean out common filler words and leading amount tokens
                    raw_candidate = re.sub(
                        r"^(?:\d+(?:\.\d+)?\s*(?:inr|usd|rs\.?|dollars|rupees)?\s*)+(?:snacks|food|groceries|items|from|at|to)?\s*",
                        "",
                        raw_candidate,
                        flags=re.IGNORECASE,
                    ).strip()
                    raw_candidate = re.sub(
                        r"^(?:groceries|snacks|food|items|products|plan|service)\s+(?:from|at|on)\s+",
                        "",
                        raw_candidate,
                        flags=re.IGNORECASE,
                    ).strip()
                    if len(raw_candidate) > 2 and raw_candidate.lower() not in [
                        "usual",
                        "my",
                        "the",
                        "groceries",
                        "snacks",
                        "food",
                    ]:
                        merchant_name_extracted = raw_candidate

        # Resolve Amount
        amount: Decimal | None = None
        amt_match = re.search(
            r"(?:[\$₹£€]\s*|inr\s*|usd\s*)?(\d+(?:\.\d{1,4})?)(?:\s*(?:inr|usd|dollars|rupees|cents))?",
            clean_p,
        )
        if amt_match:
            try:
                extracted = Decimal(amt_match.group(1))
                if extracted > 0:
                    amount = extracted
            except InvalidOperation:
                pass

        # If amount was not explicitly provided but user requested "usual subscription" or "normal"
        resolution_notes = None
        if amount is None and (
            "usual" in clean_p
            or "normal" in clean_p
            or "regular" in clean_p
            or "subscription" in clean_p
        ):
            # Look up historical routine memory for this specific merchant
            target_m_id = str(matched_merchant.id) if matched_merchant else None
            target_m_name = (
                matched_merchant.name
                if matched_merchant
                else merchant_name_extracted or ""
            ).lower()

            for mem in memories:
                mem_m_id = str(mem.structured_data.get("merchant_id") or "")
                mem_m_name = str(mem.structured_data.get("merchant_name") or "").lower()
                summary_lower = mem.summary.lower()

                if (target_m_id and mem_m_id == target_m_id) or (
                    target_m_name
                    and (target_m_name in mem_m_name or target_m_name in summary_lower)
                ):
                    avg_amt = mem.structured_data.get(
                        "avg_amount"
                    ) or mem.structured_data.get("last_amount")
                    if avg_amt:
                        amount = Decimal(str(avg_amt))
                        m_label = (
                            matched_merchant.name if matched_merchant else target_m_name
                        )
                        resolution_notes = f"Resolved historical routine amount {amount} {default_currency} for '{m_label}' from memory #{mem.id}"
                        break

        # Default pricing database for known services if amount is still missing and "subscribe" / "plan" is mentioned
        if amount is None and merchant_name_extracted:
            m_lower = merchant_name_extracted.lower()
            default_catalog = {
                "amazon prime": Decimal("1499.00"),
                "prime": Decimal("1499.00"),
                "netflix": Decimal("1788.00"),
                "spotify": Decimal("1189.00"),
                "apple music": Decimal("1188.00"),
                "youtube": Decimal("1548.00"),
                "hotstar": Decimal("1499.00"),
                "swiggy": Decimal("899.00"),
                "zomato": Decimal("999.00"),
                "bigbasket": Decimal("499.00"),
            }
            for k, def_price in default_catalog.items():
                if k in m_lower:
                    amount = def_price
                    resolution_notes = f"Inferred standard annual subscription price of {amount} {default_currency} for {merchant_name_extracted}"
                    break

        # Resolve Currency
        resolved_currency = default_currency
        if "usd" in clean_p or "$" in clean_p or "dollar" in clean_p:
            resolved_currency = "USD"
        elif "inr" in clean_p or "₹" in clean_p or "rupee" in clean_p:
            resolved_currency = "INR"

        # Check Ambiguity
        is_ambiguous = False
        ambiguity_reason = None
        if not merchant_name_extracted and not matched_merchant:
            is_ambiguous = True
            ambiguity_reason = (
                "Unable to identify target merchant from natural language prompt."
            )
        elif amount is None:
            is_ambiguous = True
            ambiguity_reason = "Purchase amount is missing and could not be determined from historical memory."

        return PaymentIntent(
            user_id=user_id,
            merchant_id=matched_merchant.id if matched_merchant else None,
            merchant_name=matched_merchant.name
            if matched_merchant
            else merchant_name_extracted,
            amount=amount,
            currency=resolved_currency,
            transaction_type=TransactionType.PURCHASE,
            intent_type="PURCHASE",
            confidence=0.95 if not is_ambiguous else 0.4,
            is_ambiguous=is_ambiguous,
            ambiguity_reason=ambiguity_reason,
            resolution_notes=resolution_notes,
        )

    @classmethod
    async def _interpret_with_gemini(
        cls,
        prompt: str,
        user_id: uuid.UUID,
        merchants: list[Merchant],
        memories: list[DecisionMemory],
        api_key: str,
        default_currency: str,
    ) -> PaymentIntent | None:
        """Call Google Gemini API with JSON mode for structured intent extraction and comparison queries."""
        try:
            merchant_names = [f"{m.name} (id={m.id})" for m in merchants]
            memory_context = [
                f"Memory: {mem.summary} (data={mem.structured_data})"
                for mem in memories[:3]
            ]

            sys_prompt = (
                "You are an AI Commerce and Financial Decision Assistant. "
                "Analyze the user's natural language request and extract structured intent. "
                "Output strictly valid JSON with keys:\n"
                "- 'intent_type': 'PURCHASE' | 'COMPARISON' | 'INFO_QUERY'\n"
                "- 'merchant_name': the primary merchant/store mentioned (e.g. 'Netflix', 'Amazon Prime', 'Spotify', 'Swiggy', 'BigBasket', 'Zomato'), or null if comparing multiple\n"
                "- 'is_new_merchant': true if this merchant is NOT in the available merchants list, false otherwise\n"
                "- 'amount': monetary amount as number/string, or null\n"
                "- 'currency': currency code (e.g. 'INR', 'USD')\n"
                "- 'comparison_merchants': list of merchant/service names if comparing (e.g. ['Netflix', 'Amazon Prime'])\n"
                "- 'comparison_data': list of dicts with estimated real-world annual costs in INR if comparing (e.g. [{'name': 'Netflix', 'estimated_annual_inr': 1788}, {'name': 'Amazon Prime', 'estimated_annual_inr': 1499}])\n"
                "- 'is_ambiguous': boolean (true if request is complete gibberish or impossible to understand)\n"
                "- 'ambiguity_reason': explanation string or null\n\n"
                "CRITICAL RULES:\n"
                "1. Do not restrict yourself to only the available merchants list. If the user mentions a merchant you know exists in the real world (e.g. Netflix, Amazon Prime, Spotify, Swiggy, BigBasket, Zomato, DMart, Hotstar, GitHub, etc.), extract it even if it is not in the available list. Mark is_new_merchant: true in that case.\n"
                "2. For comparison queries (e.g. 'compare Netflix vs Amazon Prime', 'Spotify vs Apple Music cost per year'), set intent_type: 'COMPARISON', populate comparison_merchants and comparison_data with estimated annual prices in INR based on your real-world knowledge.\n"
                "3. If the user asks for 'usual subscription', 'my usual plan', or 'regular payment', resolve the merchant and amount from the memory context.\n"
                f"Available Merchants in DB: {merchant_names}\n"
                f"Historical Memory Context: {memory_context}"
            )

            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
            payload = {
                "contents": [
                    {
                        "role": "user",
                        "parts": [{"text": f"{sys_prompt}\n\nUser Request: {prompt}"}],
                    }
                ],
                "generationConfig": {"response_mime_type": "application/json"},
            }

            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post(url, json=payload)
                if res.status_code == 200:
                    data = res.json()
                    raw_text = data["candidates"][0]["content"]["parts"][0]["text"]
                    parsed = json.loads(raw_text)

                    amt = (
                        Decimal(str(parsed.get("amount")))
                        if parsed.get("amount") is not None
                        else None
                    )
                    intent_type = parsed.get("intent_type", "PURCHASE")
                    comp_merchants = parsed.get("comparison_merchants")
                    comp_data = parsed.get("comparison_data")

                    return PaymentIntent(
                        user_id=user_id,
                        merchant_name=parsed.get("merchant_name"),
                        amount=amt,
                        currency=parsed.get("currency", default_currency),
                        transaction_type=TransactionType.PURCHASE,
                        intent_type=intent_type,
                        is_new_merchant=bool(parsed.get("is_new_merchant", False)),
                        comparison_merchants=comp_merchants,
                        comparison_data=comp_data,
                        is_ambiguous=bool(parsed.get("is_ambiguous", False)),
                        ambiguity_reason=parsed.get("ambiguity_reason"),
                        confidence=0.98,
                    )
        except Exception as e:
            logger.warning(
                "Gemini LLM parsing failed or timed out: %s. Falling back safely.", e
            )
            return None

    @classmethod
    async def _interpret_with_openai(
        cls,
        prompt: str,
        user_id: uuid.UUID,
        merchants: list[Merchant],
        memories: list[DecisionMemory],
        api_key: str,
        default_currency: str,
    ) -> PaymentIntent | None:
        """Call OpenAI API with JSON mode for structured intent extraction."""
        try:
            merchant_names = [f"{m.name} (id={m.id})" for m in merchants]
            memory_context = [
                f"Memory: {mem.summary} (data={mem.structured_data})"
                for mem in memories[:3]
            ]

            messages = [
                {
                    "role": "system",
                    "content": (
                        "You are an AI Buying Agent. Extract structured purchase intent from user request. "
                        "Output valid JSON with keys: 'merchant_name', 'amount', 'currency', "
                        "'intent_type', 'is_ambiguous', 'ambiguity_reason'. "
                        f"Available Merchants: {merchant_names}. Context: {memory_context}."
                    ),
                },
                {"role": "user", "content": prompt},
            ]

            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={
                        "model": "gpt-4o-mini",
                        "messages": messages,
                        "response_format": {"type": "json_object"},
                    },
                )
                if res.status_code == 200:
                    data = res.json()
                    content = data["choices"][0]["message"]["content"]
                    parsed = json.loads(content)
                    amt = (
                        Decimal(str(parsed.get("amount")))
                        if parsed.get("amount") is not None
                        else None
                    )
                    return PaymentIntent(
                        user_id=user_id,
                        merchant_name=parsed.get("merchant_name"),
                        amount=amt,
                        currency=parsed.get("currency", default_currency),
                        transaction_type=TransactionType.PURCHASE,
                        intent_type=parsed.get("intent_type", "PURCHASE"),
                        is_ambiguous=bool(parsed.get("is_ambiguous", False)),
                        ambiguity_reason=parsed.get("ambiguity_reason"),
                        confidence=0.98,
                    )
        except Exception as e:
            logger.warning("OpenAI LLM parsing failed: %s. Falling back safely.", e)
            return None

    @classmethod
    async def _resolve_merchant_entity(
        cls,
        intent: PaymentIntent,
        merchants: list[Merchant],
        memories: list[DecisionMemory],
        db: AsyncSession,
    ) -> None:
        """Map extracted merchant name to a database Merchant, auto-creating if new."""
        if not intent.merchant_name or intent.intent_type == "COMPARISON":
            return

        target = intent.merchant_name.lower().strip()
        # Direct match
        for m in merchants:
            if (
                m.name.lower() == target
                or m.external_reference.lower() == target
                or m.name.lower() in target
                or target in m.name.lower()
            ):
                intent.merchant_id = m.id
                intent.merchant_name = m.name
                return

        # Fuzzy word match (whole words only)
        target_words = set(target.split())
        for m in merchants:
            parts = set(m.name.lower().split())
            if any(p in target_words for p in parts if len(p) > 3):
                intent.merchant_id = m.id
                intent.merchant_name = m.name
                return

        # Quality validation on merchant name candidate (Issue 2)
        words = target.split()
        has_alpha_word = any(len(w) >= 3 and w.isalpha() for w in words)
        is_sentence = len(words) > 4 or any(
            w
            in [
                "want",
                "buy",
                "pay",
                "order",
                "purchase",
                "subscription",
                "please",
                "can",
                "you",
            ]
            for w in words[:2]
        )

        if (
            len(target) < 2
            or len(target) > 50
            or len(words) > 4
            or not has_alpha_word
            or is_sentence
        ):
            intent.is_ambiguous = True
            intent.ambiguity_reason = f"Extracted entity '{intent.merchant_name}' is not a valid merchant name."
            intent.merchant_id = None
            return

        # Auto-create new real-world merchant in database on the fly
        slug = re.sub(r"[^a-z0-9]+", "_", target).strip("_")
        ref = f"m_{slug}" if slug else f"m_{uuid.uuid4().hex[:8]}"

        existing = await db.scalar(
            select(Merchant).where(Merchant.external_reference == ref)
        )
        if existing:
            intent.merchant_id = existing.id
            intent.merchant_name = existing.name
            return

        new_merchant = Merchant(
            id=uuid.uuid4(),
            name=intent.merchant_name.strip(),
            external_reference=ref,
            status=MerchantStatus.ACTIVE,
        )
        db.add(new_merchant)
        await db.flush()
        intent.merchant_id = new_merchant.id
        intent.merchant_name = new_merchant.name
        intent.is_new_merchant = True
        logger.info(
            "Auto-created new real-world merchant: %s (id=%s, ref=%s)",
            new_merchant.name,
            new_merchant.id,
            ref,
        )

    @classmethod
    async def evaluate_agent_purchase(
        cls,
        request: AgentEvaluateRequest,
        db: AsyncSession,
    ) -> AgentEvaluateResponse:
        """Complete end-to-end flow: Natural Language -> Structured Intent -> DecisionVault -> Gated Payment."""
        # 1. Interpret Natural Language Prompt
        intent = await cls.interpret_request(
            prompt=request.prompt,
            user_id=request.user_id,
            db=db,
            currency=request.currency,
        )

        # 2. Record Agent Request in Audit Log
        await AuditLogService.append_event(
            db=db,
            event_type=AuditEventType.AGENT_REQUEST_RECEIVED,
            entity_type="AGENT_REQUEST",
            user_id=request.user_id,
            event_data={
                "prompt": request.prompt,
                "intent_type": intent.intent_type,
                "is_ambiguous": intent.is_ambiguous,
                "merchant_name": intent.merchant_name,
                "amount": str(intent.amount) if intent.amount else None,
                "confidence": intent.confidence,
            },
        )

        # 3. Handle Comparison Query -> Return comparison breakdown without debiting funds
        if intent.intent_type == "COMPARISON":
            comp_data = intent.comparison_data or []
            if len(comp_data) >= 2:
                m1 = comp_data[0]
                m2 = comp_data[1]
                p1 = m1.get("estimated_annual_inr", 0)
                p2 = m2.get("estimated_annual_inr", 0)
                diff = abs(p1 - p2)
                cheaper = m1["name"] if p1 < p2 else m2["name"]
                explanation = (
                    f"{m1['name']} costs approx ₹{p1:,}/year. "
                    f"{m2['name']} costs approx ₹{p2:,}/year. "
                    f"{cheaper} is cheaper by ₹{diff:,}. "
                    "No payment has been made — let me know which one you'd like to subscribe to."
                )
            else:
                merchants_str = " vs ".join(intent.comparison_merchants or ["services"])
                explanation = f"Comparison for {merchants_str} completed. No payment has been executed."

            return AgentEvaluateResponse(
                prompt=request.prompt,
                structured_intent=intent,
                decision=DecisionOutcome.ASK_USER,
                decision_details=None,
                payment_result=None,
                comparison_data=intent.comparison_data,
                explanation=explanation,
            )

        # 3. Handle Ambiguous Intent -> Fail-Safe to ASK_USER
        if (
            intent.is_ambiguous
            or intent.merchant_id is None
            or intent.amount is None
            or intent.amount <= Decimal("0")
        ):
            reason = (
                intent.ambiguity_reason
                or "Intent could not be unambiguously resolved to a merchant and valid monetary amount."
            )
            dec_rec = Decision(
                user_id=request.user_id,
                transaction_id=None,
                request_reference=str(uuid.uuid4()),
                decision=DecisionOutcome.ASK_USER,
                reason=reason,
                evidence_metadata={
                    "reason_code": "INTENT_AMBIGUOUS",
                    "prompt": request.prompt,
                    "merchant_name": intent.merchant_name,
                },
            )
            db.add(dec_rec)
            await db.flush()

            return AgentEvaluateResponse(
                prompt=request.prompt,
                structured_intent=intent,
                decision=DecisionOutcome.ASK_USER,
                decision_details=None,
                decision_id=dec_rec.id,
                payment_result=None,
                explanation=f"Autonomous purchase paused for user confirmation: {reason}",
            )

        # 4. Authoritative DecisionVault Evaluation
        await db.flush()

        if intent.merchant_id:
            m_check = await db.get(Merchant, intent.merchant_id)
            if not m_check:
                await db.flush()
                m_check = await db.get(Merchant, intent.merchant_id)

        dec_svc = DecisionEvaluationService()
        dec_req = ActionEvaluationRequest(
            user_id=intent.user_id,
            merchant_id=intent.merchant_id,
            amount=intent.amount,
            currency=intent.currency,
            transaction_type=intent.transaction_type,
            idempotency_key=request.idempotency_key,
            metadata={"is_new_merchant": intent.is_new_merchant},
        )

        decision_resp = await dec_svc.evaluate_action(
            payload=dec_req,
            db=db,
        )

        # 5. Gated Payment Execution (ONLY on ALLOW and if auto_execute_payment is requested)
        payment_result = None
        if (
            request.auto_execute_payment
            and decision_resp.decision == DecisionOutcome.ALLOW
        ):
            pay_svc = PaymentExecutionService()
            pay_req = PaymentExecutionRequest(
                user_id=intent.user_id,
                merchant_id=intent.merchant_id,
                amount=intent.amount,
                currency=intent.currency,
                transaction_type=intent.transaction_type,
                idempotency_key=request.idempotency_key or str(uuid.uuid4()),
            )
            payment_result = await pay_svc.execute_payment(
                payload=pay_req,
                db=db,
            )

        # 6. Generate Factual Explanation from Evidence
        explanation = cls._generate_explanation(decision_resp, intent, payment_result)

        return AgentEvaluateResponse(
            prompt=request.prompt,
            structured_intent=intent,
            decision=decision_resp.decision,
            decision_details=decision_resp,
            decision_id=decision_resp.decision_id,
            payment_result=payment_result,
            explanation=explanation,
        )

    @classmethod
    def _generate_explanation(
        cls,
        decision_resp: ActionEvaluationResponse,
        intent: PaymentIntent,
        payment_result: PaymentExecutionResponse | None,
    ) -> str:
        """Synthesize auditable, factual explanation from DecisionVault evaluation evidence."""
        merchant = intent.merchant_name or "merchant"
        amt = (
            f"{intent.amount:.2f} {intent.currency}"
            if intent.amount
            else "specified amount"
        )

        if decision_resp.decision == DecisionOutcome.ALLOW:
            pay_note = ""
            if payment_result:
                pay_note = f" Payment executed via {payment_result.gateway_mode} (ID: {payment_result.payment_id})."
            return (
                f"ALLOWED: Purchase of {amt} to '{merchant}' was permitted. "
                f"Historical patterns and deterministic spend policies verified.{pay_note}"
            )

        if decision_resp.decision == DecisionOutcome.ASK_USER:
            reasons = [
                r.message or r.reason_code
                for r in decision_resp.rule_results
                if r.decision_effect.value == "ASK_USER"
            ]
            reason_str = ", ".join(reasons) if reasons else decision_resp.reason_code
            return (
                f"ASK_USER: Purchase of {amt} to '{merchant}' requires human confirmation. "
                f"Reason: {reason_str}."
            )

        if decision_resp.decision == DecisionOutcome.BLOCK:
            reasons = [
                r.message or r.reason_code
                for r in decision_resp.rule_results
                if r.decision_effect.value == "BLOCK"
            ]
            reason_str = ", ".join(reasons) if reasons else decision_resp.reason_code
            return (
                f"BLOCKED: Purchase of {amt} to '{merchant}' was rejected by DecisionVault. "
                f"Violation: {reason_str}. Zero money movement occurred."
            )

        return f"Decision: {decision_resp.decision.value} (Reason: {decision_resp.reason_code})"
