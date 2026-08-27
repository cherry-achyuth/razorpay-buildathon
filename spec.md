# DecisionVault — Project Specification
> **Razorpay AI Buildathon · Track 01: AI Growth & Agentic Commerce**

---

## 1. Mission Statement

DecisionVault is a **decision-preserving financial memory middleware** that sits between autonomous AI buying agents and payment execution gateways. It makes a merchant's checkout flow **transactable by an AI buyer end-to-end** while ensuring every money action is **explainable, bounded, and gated** — with a full audit trail and at least one gracefully handled failure.

---

## 2. Buildathon Track Alignment

**Track:** 01 — AI Growth & Agentic Commerce
**Goal:** Build an agent that grows revenue for a merchant on Razorpay test-mode APIs, or that makes a merchant transactable by an AI buyer end to end.

| Buildathon Requirement | DecisionVault Implementation |
|---|---|
| Every money action explainable | SHA-256 tamper-evident audit chain; reason_code + rule_results on every decision |
| Actions bounded and gated | 6 deterministic guardrail rules; LLMs never authorize money directly |
| Show the audit trail | GET /api/v1/audit + GET /api/v1/audit/verify with cryptographic chain validation |
| One failure handled gracefully | Duplicate replay attack -> BLOCK; Price drift anomaly -> ASK_USER; both with zero debits |
| Razorpay test-mode APIs | PaymentExecutionService + RazorpayTestClient; full test-mode payment gateway integration |
| Agent-readable catalog | Merchant catalog with structured metadata, queryable via REST |
| Conversational in-app checkout | POST /api/v1/agent/evaluate - natural language -> intent -> guardrails -> payment |

---

## 3. System Architecture

```
AUTONOMOUS AI BUYING AGENT
         |
         | 1. Natural Language Purchase Request
         v
+-----------------------------+
|    Multi-Tier Intent Parser  |
|  Gemini 2.5 Flash (primary) |
|  OpenAI GPT-4o-mini (alt)   |
|  Deterministic NLP (fallback)|
+-------------+---------------+
              |
              | 2. Structured PaymentIntent
              v
      DecisionVault API (FastAPI)
      POST /api/v1/decisions/evaluate
              |
              v
  [Load Financial Memory Context]
  - User scoped, ACTIVE status
  - SQL temporal filter
  - Bounded (limit 10 records)
              |
              v
  [Load Authoritative PostgreSQL/SQLite State]
  - User, Merchant, Mandate, Policy
  - Recent Transactions, Idempotency Records
              |
              v
+-----------------------------+
|   Deterministic Rule Engine  |
|  1. MandateConstraintRule   |
|  2. PolicyLimitRule         |
|  3. DuplicatePaymentRule    |
|  4. IdempotencyRule         |
|  5. PriceDriftRule          |
|  6. MerchantChangeRule      |
+-------------+---------------+
              |
              v
  [Append SHA-256 Audit Event]
              |
      +-------+----------+
      v         v         v
   ALLOW     ASK_USER   BLOCK
      |         |         |
      |   (halt, wait)    |
      v         |         v
Razorpay    <---+    Zero Debits
Test Mode            Hard Stop
Payment
```

---

## 4. Core Modules

### 4.1 AI Buying Agent (app/services/agent/buying_agent.py)
- BuyingAgentService.interpret_request() — natural language -> PaymentIntent
- BuyingAgentService.evaluate_agent_purchase() — end-to-end NL -> decision -> payment
- Provider cascade: Gemini 2.5 Flash -> OpenAI GPT-4o-mini -> Deterministic semantic parser
- Fail-safe: malformed/timed-out LLM calls fall back to deterministic parser; never block execution

### 4.2 Decision Evaluation Engine (app/services/decision_service.py)
- DecisionEvaluationService.evaluate_action() — orchestrates all 6 guardrail rules
- Returns ActionEvaluationResponse with: decision, reason_code, rule_results[], memory_context[]
- INVARIANT: LLMs never touch this path. Deterministic code only.

### 4.3 Guardrail Rules (app/services/guardrails/rules/)

| Rule | File | What it guards |
|---|---|---|
| MandateConstraintRule | mandate_rule.py | UPI Autopay / e-NACH mandate limits |
| PolicyLimitRule | policy_rule.py | Per-transaction and daily spend caps |
| DuplicatePaymentRule | duplicate_rule.py | Replay attack within 5-minute window |
| IdempotencyRule | idempotency_rule.py | Exact idempotency key deduplication |
| PriceDriftRule | price_drift_rule.py | Statistical price anomaly detection (z-score) |
| MerchantChangeRule | merchant_change_rule.py | Unusual merchant switches |

### 4.4 Payment Gateway (app/services/payment/)
- PaymentExecutionService — evaluates + executes via Razorpay
- RazorpayTestClient — wraps Razorpay test-mode API
- POST /api/v1/payments/execute — full execution with decision gate
- POST /api/v1/payments/decisions/{id}/confirm — ASK_USER confirmation pathway
- GET /api/v1/payments/status — gateway status and mode

### 4.5 Financial Memory (app/services/memory/)
- Build memory from raw transactions (vector embedding via EMBEDDING_PROVIDER)
- Compress 90-day routine history -> consolidated decision memories (4x ratio)
- Semantic and hybrid vector retrieval for context injection
- Raw PostgreSQL/SQLite ledgers never deleted

### 4.6 Audit Subsystem (app/services/audit/)
- Linear SHA-256 hash chain: each event hashes (event_data + previous_hash)
- GET /api/v1/audit/verify — cryptographic chain validation endpoint
- Events: AGENT_REQUEST, DECISION_MADE, PAYMENT_EXECUTED, MEMORY_COMPRESSED, etc.

### 4.7 Decision Preservation Evaluation (app/services/evaluation/)
- FullHistoryBaselineEvaluator — evaluates against raw transaction history
- CompressedMemoryEvaluator — evaluates against compressed memory
- DecisionPreservationService — compares both paths, computes preservation rate
- Target: 100% preservation rate with 0 false ALLOWs

---

## 5. Data Models

### User (app/models/user.py)
- id (UUID), external_id, display_name, spending_limit_daily, spending_limit_monthly

### Merchant (app/models/merchant.py)
- id (UUID), name, external_reference, status (ACTIVE/INACTIVE/BLOCKED), category

### Transaction (app/models/transaction.py)
- id, user_id, merchant_id, amount, currency, status, transaction_type, created_at

### DecisionMemory (app/models/memory.py)
- id, user_id, merchant_id, summary_text, structured_data (JSON), embedding (vector), status, source_transaction_ids

### SpendingPolicy (app/models/policy.py)
- id, user_id, merchant_id, max_amount_per_transaction, max_daily_spend, allowed_transaction_types

### Mandate (app/models/mandate.py)
- id, user_id, merchant_id, mandate_type (UPI_AUTOPAY/E_NACH), max_amount, frequency, status

### AuditEvent (app/models/audit.py)
- id, event_type, entity_type, user_id, event_data (JSON), sha256_hash, previous_hash, created_at

---

## 6. API Endpoints Reference

### Agent
| Method | Path | Description |
|---|---|---|
| POST | /api/v1/agent/interpret | NL prompt -> structured PaymentIntent |
| POST | /api/v1/agent/evaluate | Full agentic flow: NL -> decision -> payment |

### Decisions
| Method | Path | Description |
|---|---|---|
| POST | /api/v1/decisions/evaluate | Evaluate proposed financial action (no payment) |

### Payments
| Method | Path | Description |
|---|---|---|
| POST | /api/v1/payments/execute | Evaluate + execute Razorpay test-mode payment |
| POST | /api/v1/payments/decisions/{id}/confirm | Confirm pending ASK_USER decision |
| GET | /api/v1/payments/status | Gateway configuration + mode |

### Memories
| Method | Path | Description |
|---|---|---|
| POST | /api/v1/memories/build/{tx_id} | Build decision memory from transaction |
| POST | /api/v1/memories/compress | Compress 90-day history into canonical memories |
| POST | /api/v1/memories/search | Semantic / hybrid vector retrieval |
| GET | /api/v1/memories | List active memories for user |

### Audit
| Method | Path | Description |
|---|---|---|
| GET | /api/v1/audit | Retrieve audit log |
| GET | /api/v1/audit/verify | Cryptographic SHA-256 chain validation |

### Evaluation
| Method | Path | Description |
|---|---|---|
| POST | /api/v1/evaluations/decision-preservation | Full-history vs compressed-memory benchmark |

### Demo & Dashboard
| Path | Description |
|---|---|
| POST /api/v1/demo/seed | Seed canonical demo data (idempotent) |
| GET / | Interactive buildathon demo dashboard |
| GET /docs | FastAPI Swagger UI |

---

## 7. Canonical Demo Scenarios

| # | Scenario | Input | Decision | Gateway |
|---|---|---|---|---|
| 1 | Routine Purchase | 25 INR to CloudCompute | ALLOW | Payment executed |
| 2 | Duplicate Replay Attack | Same 25 INR, 0s later | BLOCK | Zero debits |
| 3 | Policy Limit Violation | 150 INR (limit 100) | BLOCK | Zero debits |
| 4 | Price Drift (+160%) | 65 INR (baseline 25) | ASK_USER | Halted -> confirm |
| 5 | Memory Compression | 90-day, 8 transactions | 4x ratio | Ledger intact |
| 6 | Audit Chain Integrity | SHA-256 validation | VALID | Verified |
| 7 | Decision Preservation | 5 adversarial cases | 100% rate, 0 false ALLOWs | - |
| 8 | AI Buying Agent NLP | "Pay my usual 25 INR subscription" | ALLOW | Payment executed |

---

## 8. Environment Configuration

| Variable | Description | Required |
|---|---|---|
| DATABASE_URL | SQLite or PostgreSQL connection URL | YES |
| GEMINI_API_KEY | Google Gemini 2.5 Flash (primary LLM) | YES (provided) |
| OPENAI_API_KEY | OpenAI GPT-4o-mini (alt LLM) | Optional |
| RAZORPAY_KEY_ID | Razorpay test-mode key ID | For live test-mode |
| RAZORPAY_KEY_SECRET | Razorpay test-mode secret | For live test-mode |
| RAZORPAY_MOCK_FALLBACK | Use mock if keys absent (true) | Default: true |
| EMBEDDING_PROVIDER | deterministic or openai | Default: deterministic |
| GROQ_API_KEY | NOT USED — Groq is not integrated | N/A |

---

## 9. Quality Gates

| Gate | Target | Command |
|---|---|---|
| Unit + integration tests passing | All green | uv run pytest -v |
| Ruff lint errors | 0 | uv run ruff check . |
| Ruff format errors | 0 | uv run ruff format --check . |
| Server starts without errors | Health 200 OK | curl http://127.0.0.1:8000/health |
| DB seeded, all 8 scenarios runnable | Demo passes | uv run python scripts/seed_demo.py |
| Decision preservation rate | 100% | POST /api/v1/evaluations/decision-preservation |
| Audit chain valid | VALID | GET /api/v1/audit/verify |

---

## 10. Architecture Invariants (Never Violate)

1. LLMs NEVER authorize money movement. Deterministic code + user confirmation are the sole security boundaries.
2. Raw transactions are NEVER deleted. Compression builds derived memories without touching the authoritative ledger.
3. Every decision is cryptographically logged. SHA-256 hash chain provides tamper-evident provenance.
4. Fail-safe by default. Any ambiguous, malformed, or timed-out LLM output -> ASK_USER, never ALLOW.
5. No blockchain, Kafka, or ChromaDB overhead. PostgreSQL/SQLite + pgvector provide all necessary functionality.
