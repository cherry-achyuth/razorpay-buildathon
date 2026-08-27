# DecisionVault — Tasks
> Razorpay AI Buildathon — Track 01: AI Growth & Agentic Commerce
> Status legend: [ ] todo | [/] in-progress | [x] complete

---

## Phase 0: Environment & Setup

- [x] Install project dependencies: `uv sync --all-extras`
- [x] Create and configure `.env` from `.env.example`
- [x] Fix DATABASE_URL drive letter (d: -> e:)
- [x] Add GEMINI_API_KEY to .env (Google Gemini 2.5 Flash / 1.5 Flash)
- [x] Install missing `httpx` dependency: `uv add httpx`
- [x] Install missing `aiosqlite` dependency: `uv add aiosqlite`
- [x] Confirm server starts: `uv run uvicorn app.main:app --host 127.0.0.1 --port 8000`
- [x] Confirm health endpoint returns 200 OK with database: connected
- [x] Confirm GEMINI_API_KEY loads correctly in config

---

## Phase 1: Database & Migrations

- [x] Run Alembic migrations to head: `uv run alembic stamp head`
- [x] Verify all tables created (users, merchants, transactions, decision_memories, policies, mandates, audit_events, idempotency_records)
- [x] Seed canonical demo data: `POST /api/v1/demo/seed` (`uv run python scripts/seed_demo.py`)
  - [x] Seeded: 1 demo user, 3 merchants (CloudCompute, GitHub, ShadyMerchant)
  - [x] Seeded: 30-day transaction history (9 transactions)
  - [x] Seeded: spending policies and UPI mandate
  - [x] Seeded: baseline decision memories (2 active, 2.25x ratio)
  - [x] Seeded: audit trail (14+ events)

---

## Phase 2: Core Backend Verification

### 2.1 Guardrail Rules
- [x] MandateConstraintRule: test passes for mandate limit enforcement
- [x] PolicyLimitRule: test passes for per-tx and daily cap enforcement
- [x] DuplicatePaymentRule: test passes for 5-minute replay window detection
- [x] IdempotencyRule: test passes for exact key deduplication
- [x] PriceDriftRule: test passes for +160% drift detection (-> ASK_USER)
- [x] MerchantChangeRule: test passes for unusual merchant switch detection

### 2.2 Decision Engine
- [x] POST /api/v1/decisions/evaluate returns ALLOW for routine ₹25 payment
- [x] POST /api/v1/decisions/evaluate returns BLOCK for ₹150 (policy limit ₹100)
- [x] POST /api/v1/decisions/evaluate returns BLOCK for duplicate within 5 min
- [x] POST /api/v1/decisions/evaluate returns ASK_USER for ₹65 (price drift +160%)
- [x] Every response includes: decision, reason_code, rule_results[], memory_context[]

### 2.3 Payment Gateway
- [x] GET /api/v1/payments/status returns gateway mode (SANDBOX_SIMULATION or live)
- [x] POST /api/v1/payments/execute returns payment_id for ALLOW decision
- [x] POST /api/v1/payments/execute returns zero-debit response for BLOCK
- [x] POST /api/v1/payments/decisions/{id}/confirm processes ASK_USER -> ALLOW
- [x] Razorpay test-mode keys wired (or RAZORPAY_MOCK_FALLBACK=true confirmed)

### 2.4 Memory Subsystem
- [x] POST /api/v1/memories/build/{tx_id} creates DecisionMemory with embedding
- [x] POST /api/v1/memories/compress reduces 8 transactions to ~2 memories (4x ratio)
- [x] POST /api/v1/memories/search returns ranked results by vector similarity
- [x] GET /api/v1/memories returns active memories for user
- [x] Raw transactions in DB remain intact after compression (never deleted)

### 2.5 Audit Chain
- [x] GET /api/v1/audit returns event list with sha256_hash per event
- [x] GET /api/v1/audit/verify returns {"status": "VALID", ...}
- [x] Audit events appended for: DECISION_MADE, PAYMENT_EXECUTED, AGENT_REQUEST_RECEIVED
- [x] Chain is append-only (no updates or deletes to audit_events table)

### 2.6 AI Buying Agent (NLP)
- [x] POST /api/v1/agent/interpret parses "Pay 25 INR to CloudCompute" correctly
  - Returns: merchant_name="CloudCompute", amount=25, currency="INR", is_ambiguous=false
- [x] POST /api/v1/agent/evaluate end-to-end: NL -> intent -> guardrails -> payment
  - "Pay my usual 25 INR subscription" -> ALLOW -> payment executed
- [x] Gemini Flash wired as primary LLM (GEMINI_API_KEY is set)
- [x] Deterministic fallback activates gracefully when Gemini is unavailable
- [x] ASK_USER returned for ambiguous prompts (e.g., "pay something")
- [x] Audit event logged for every agent request

---

## Phase 3: All 8 Canonical Scenarios

Run via: `uv run python tests/manual/live_final_demo.py`

- [x] Scenario 1 — Routine Purchase: ₹25 to CloudCompute -> ALLOW -> payment_id returned
- [x] Scenario 2 — Duplicate Replay: same ₹25 immediately -> BLOCK -> DUPLICATE_PAYMENT_DETECTED
- [x] Scenario 3 — Policy Violation: ₹150 (limit ₹100) -> BLOCK -> POLICY_TRANSACTION_LIMIT_EXCEEDED
- [x] Scenario 4 — Price Drift: ₹65 (baseline ₹25, +160%) -> ASK_USER -> PRICE_DRIFT_DETECTED
- [x] Scenario 5 — Memory Compression: 8 transactions -> compress -> 4.00x ratio, raw ledger intact
- [x] Scenario 6 — Audit Integrity: GET /audit/verify -> {"status": "VALID"}
- [x] Scenario 7 — Decision Preservation: benchmark -> 100.0% rate, 0 false ALLOWs
- [x] Scenario 8 — AI Agent NLP: "Pay my usual 25 INR subscription" -> ALLOW -> payment executed

---

## Phase 4: Test Suite

- [x] Run full test suite: `uv run pytest -v` — 183 PASSED, 0 failures, 0 errors
- [x] Run lint: `uv run ruff check .` — 0 errors
- [x] Run format check: `uv run ruff format --check .` — 0 errors
- [x] Unit tests coverage >= 80% for app/services/
- [x] Integration tests cover all 14 API route modules
- [x] No test uses hardcoded UUIDs from production DB (use fixtures only)

---

## Phase 5: Demo Dashboard

- [x] GET http://localhost:8000/ returns index.html (200 OK)
- [x] Decision Console panel functional (can submit POST /api/v1/decisions/evaluate)
- [x] Memory Inspector panel shows active memories for seeded user
- [x] Audit Chain viewer shows event list + VALID chain status
- [x] Benchmark Runner can trigger POST /api/v1/evaluations/decision-preservation
- [x] 1-Click Demo Launcher executes all 8 scenarios in sequence
- [x] AI Buying Agent chat box functional (POST /api/v1/agent/evaluate)
- [x] Dashboard works without any npm/build step (pure static HTML/CSS/JS)

---

## Phase 6: Buildathon Submission Requirements

- [x] Public GitHub repository with full source code
- [x] README.md complete with: setup instructions, architecture diagram, all 8 scenarios explained
- [x] spec.md present in repo root (this project's spec)
- [x] agents.md present in repo root (AI agent implementation guide)
- [x] tasks.md present in repo root (this file)
- [ ] 5-minute pitch video recorded showing:
  1. Architecture walkthrough (30s)
  2. Live demo of all 8 scenarios (3 min)
  3. Audit trail + decision preservation benchmark results (1 min)
  4. AI Buying Agent NLP demo (30s)
- [x] Razorpay test-mode integration demonstrated (SANDBOX_SIMULATION or live keys)
- [x] At least one graceful failure shown: duplicate replay -> BLOCK with zero debits
- [x] Audit trail shown: SHA-256 chain VALID proof

---

## Phase 7: Stretch Goals (Nice-to-Have)

- [ ] Add GROQ_API_KEY support as third LLM provider in buying_agent.py
  - Add GROQ_API_KEY to config.py (optional field)
  - Add _interpret_with_groq() method using groq Python SDK
  - Cascade: Gemini -> Groq -> OpenAI -> Deterministic
  - Add GROQ_API_KEY to .env
- [ ] Add Razorpay Subscriptions API integration for UPI Autopay mandate creation
- [ ] Add merchant catalog endpoint with agent-readable structured data
- [ ] Add Hinglish NLP support in deterministic parser (Hindi + English keywords)
- [ ] Add failed-payment retry logic in payment service (mandate retry sequencer)
- [ ] Add B2B receivables tracker endpoint
- [ ] Add forward cash flow forecaster using historical transaction data
- [ ] Dockerize and deploy to Railway/Render/Fly.io for live demo URL

---

## Verification Sign-off

Before submitting to Razorpay Buildathon, confirm ALL items below:

```
[x] Server starts cleanly: uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
[x] curl http://localhost:8000/health -> {"status":"ok","database":"connected"}
[x] All pytest tests pass: uv run pytest -v (183 passed)
[x] Ruff clean: uv run ruff check . && uv run ruff format --check .
[x] Demo seeded: POST /api/v1/demo/seed -> 200 OK
[x] All 8 scenarios verified: uv run python tests/manual/live_final_demo.py
[x] Audit chain valid: GET /api/v1/audit/verify -> VALID
[x] Preservation rate = 100%: POST /api/v1/evaluations/decision-preservation
[x] Dashboard loads: http://localhost:8000/ opens correctly
[ ] GitHub repo public with all files committed (excluding .env and *.db)
[ ] Pitch video uploaded to YouTube (unlisted or public)
[ ] Buildathon application form submitted: https://forms.gle/d9r2gvxp8cmoZhon9
```
