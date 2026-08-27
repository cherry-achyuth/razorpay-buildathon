# DecisionVault

> **Decision-Preserving Financial Memory for Autonomous Agents**

DecisionVault is an industry-first, security-first middleware layer that sits between autonomous AI buying agents and payment/mandate execution gateways. It ensures that every proposed financial action is rigorously evaluated against historical context, decision provenance, and deterministic financial guardrails before funds can ever be authorized or debited.

---

## 1. Project Overview & Buildathon Scope

**DecisionVault** is a financial decision memory middleware and payment security gateway built for the **Razorpay AI Buildathon**.

It provides an authoritative execution gate for autonomous AI commerce agents:
1. **Financial Memory & Provenance**: Raw transaction history in PostgreSQL is authoritative. Decision memories represent compact, explainable historical context with explicit provenance.
2. **Deterministic Financial Guardrails**: LLMs and AI agents **never** authorize money movement directly. All payment proposals are evaluated by deterministic code against mandate constraints, spending policies, duplicate detection, idempotency, and price drift thresholds.
3. **Deterministic Decisions**:
   - `ALLOW`: Permitted action satisfying all safety guardrails $\rightarrow$ unlocks Razorpay Test Mode payment execution.
   - `ASK_USER`: Ambiguous action or price drift anomaly $\rightarrow$ halts execution until explicit user confirmation.
   - `BLOCK`: Policy breach or replay attack $\rightarrow$ halts execution with zero funds debited.
4. **Razorpay Test Mode Integration**: Full test mode payment gateway integration (`POST /api/v1/payments/execute` and `POST /api/v1/payments/decisions/{id}/confirm`).
5. **Tamper-Evident SHA-256 Audit Log**: Append-only linear cryptographic audit chain recording all evaluations, compressions, and payment attempts.
6. **Decision-Preservation Benchmarking**: Dual-path evaluation comparing full history against compressed memory across adversarial boundaries.
7. **Interactive 5-Minute Demo Web Dashboard**: High-clarity dashboard served directly at `http://localhost:8000/` and `/demo`.

**What is implemented:**
- **Payment Gateway & Gate**: `PaymentExecutionService`, `RazorpayTestClient`, `POST /api/v1/payments/execute`, `POST /api/v1/payments/decisions/{decision_id}/confirm`, `GET /api/v1/payments/status`.
- **Interactive Web UI**: Fast, responsive dashboard at `/` and `/demo` with Decision Console, Memory & Provenance Inspector, Tamper-Evident Audit Viewer, Benchmark Runner, and 1-Click Scenario Launcher.
- **Evaluation Subsystem**: `DecisionPreservationService`, `FullHistoryBaselineEvaluator`, `CompressedMemoryEvaluator`, `ScenarioFactory` (Standard & Adversarial suites), `metrics.py`, and `experiments/synthetic/`.
- **Audit Subsystem**: Linear SHA-256 hash-chained log with `GET /api/v1/audit/verify` and `GET /api/v1/audit`.
- **Memory API Endpoints**: Memory building, semantic & hybrid vector retrieval, compression, and retirement.
- **Guardrails Pipeline**: 6 deterministic rules (`MandateConstraintRule`, `PolicyLimitRule`, `DuplicatePaymentRule`, `IdempotencyRule`, `PriceDriftRule`, `MerchantChangeRule`).
- **Comprehensive Testing Suite**: **183 automated tests passing in 22s** with 0 Ruff lint/format errors.

**Important Architectural Invariants:**
- ❌ **LLMs NEVER Authorize Money Movement**: Deterministic code and user confirmation remain the sole security boundaries.
- ❌ **Raw Transactions Are Never Deleted**: Compression consolidates derived memory without destroying authoritative PostgreSQL transaction ledgers.
- ❌ **No Blockchain / Kafka / ChromaDB Overhead**: PostgreSQL and pgvector provide full relational integrity and vector search without duplicate infrastructure.

---

## 2. Architecture & Decision Flow

```text
           AUTONOMOUS AI BUYING AGENT
                      │
                      │ 1. Natural Language Purchase Request
                      ▼
        ┌─────────────────────────────┐
        │ Multi-Tier Intent Parser    │
        │ - Gemini / OpenAI / Semantic│
        │ - Entity & Currency Match   │
        └──────────────┬──────────────┘
                       │
                       │ 2. POST /api/v1/decisions/evaluate
                       ▼
               DecisionVault API
                       │
                       ▼
           [ProposedFinancialAction]
                       │
                       ▼
        ┌─────────────────────────────┐
        │  Retrieve Decision Memories │
        │  - Scoped to user_id        │
        │  - Status ACTIVE            │
        │  - SQL Temporal Filter      │
        │  - Relevance Priority Order │
        │  - Bounded (Limit 10)       │
        └──────────────┬──────────────┘
                       │
                       ▼
    [Load Authoritative State from PostgreSQL]
         (User, Merchant, Mandate, Policy,
     Recent Transactions, Idempotency Record)
                      │
                      ▼
        ┌─────────────────────────────┐
        │  Deterministic Rule Engine  │
        │  - MandateConstraintRule    │
        │  - PolicyLimitRule          │
        │  - DuplicatePaymentRule     │
        │  - IdempotencyRule          │
        │  - PriceDriftRule           │
        │  - MerchantChangeRule       │
        └──────────────┬──────────────┘
                       │
                       ▼
        ┌─────────────────────────────┐
        │ Decision & Cryptographic Log│
        │ - Record SHA-256 Hash Chain │
        └──────────────┬──────────────┘
                       │
        ┌──────────────┴──────────────┐
        ▼              ▼              ▼
     [ALLOW]       [ASK_USER]      [BLOCK]
        │              │              │
        │        (Pause for User)     │
        ▼              │              ▼
  ┌───────────┐        │        [Zero Debits]
  │ Razorpay  │        │        [Hard Stop]
  │ Test Mode │◄───────┘
  │  Payment  │ (On User Confirm)
  └───────────┘
```

---

## 3. Core Demonstration Scenarios

| # | Scenario | Proposed Action | History / Policy Context | DecisionVault Evaluation | Gateway Execution |
|---|---|---|---|---|---|
| **1** | **Routine Purchase** | ₹25.00 to CloudCompute | Standard monthly bill; ₹100 policy limit | **`ALLOW`** | Payment executed via Razorpay Test Mode |
| **2** | **Duplicate Replay Attack** | ₹25.00 to CloudCompute | Identical payment executed 0s ago | **`BLOCK`** (`DUPLICATE_PAYMENT_DETECTED`) | Zero money movement |
| **3** | **Policy Limit Violation** | ₹150.00 to CloudCompute | Policy max per transaction is ₹100.00 | **`BLOCK`** (`POLICY_TRANSACTION_LIMIT_EXCEEDED`) | Zero money movement |
| **4** | **Price Drift (+160%)** | ₹65.00 to CloudCompute | Historical median baseline is ₹25.00 | **`ASK_USER`** (`PRICE_DRIFT_DETECTED`) | Halted; unlocks only upon explicit user confirmation |
| **5** | **Memory Compression** | 90-day history | 8 raw transactions consolidated | **4.00x Compression Ratio** | Raw PostgreSQL ledgers intact; derived memory updated |
| **6** | **Audit Chain Integrity** | SHA-256 validation | Linear cryptographic hash sequence | **`VALID` (Unbroken Chain)** | Cryptographically verified |
| **7** | **Decision Preservation** | 5 benchmark cases | Full History vs Compressed Memory | **100.0% Preservation Rate** | 0 False ALLOWs (Zero safety bypasses) |
| **8** | **AI Buying Agent NLP** | Natural language prompt | "Pay my usual 25 INR subscription" | **`ALLOW`** (Intent parsed & gated) | Autonomous payment executed |

---

## 4. Local Setup & Installation

### Prerequisites
- Python 3.12 or higher
- `uv` package manager installed (`curl -LsSf https://astral.sh/uv/install.sh | sh` or `winget install astral-sh.uv`)

### Step 1: Clone and Synchronize Dependencies
```bash
uv sync --all-extras
```

### Step 2: Configure Environment
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```

### Step 3: Run Database Migrations
```bash
uv run alembic upgrade head
```

### Step 4: Run Tests & Verification
```bash
uv run pytest -v
uv run ruff check .
uv run ruff format --check .
```

### Step 5: Seed 30-Day Demo Data (Optional CLI)
```bash
uv run python scripts/seed_demo.py
```

### Step 6: Start the API Server & Dashboard
```bash
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```
Open `http://localhost:8000/` or `http://localhost:8000/demo` in your browser.

---

## 5. API Endpoints Reference

### AI Buying Agent & NLP
- `POST /api/v1/agent/interpret`: Converts natural language purchase prompt into a structured payment intent.
- `POST /api/v1/agent/evaluate`: End-to-end agentic purchase: interprets prompt, evaluates through DecisionVault, and executes gated payment on `ALLOW`.

### Demo Seeder
- `POST /api/v1/demo/seed`: Idempotently seeds standard demo principals, 30-day transaction history, baseline decision memories, and valid audit trail.

### Decision Evaluation
- `POST /api/v1/decisions/evaluate`: Evaluates a proposed financial action without executing payment. Returns `decision` (`ALLOW`, `ASK_USER`, `BLOCK`), `reason_code`, structured `rule_results`, and `memory_context` evidence.

### Decision Memory Layer
- `POST /api/v1/memories/build/{transaction_id}`: Converts a raw transaction into a canonical financial event, computes vector embedding, and persists decision memory with source provenance.
- `POST /api/v1/memories/compress`: Deterministically compresses redundant routine transactions into consolidated decision memories with full provenance.
- `POST /api/v1/memories/search`: Retrieves candidate memories ranked by vector cosine similarity score (`SEMANTIC`) or tiered hybrid relevance (`HYBRID`).
- `GET /api/v1/memories?user_id=...`: Retrieves bounded decision memories ordered by relevance priority.

### Payment Execution & Razorpay Test Mode Gate
- `POST /api/v1/payments/execute`: Evaluates financial action against deterministic guardrails and executes payment via Razorpay Test Mode if `ALLOW`.
- `POST /api/v1/payments/decisions/{decision_id}/confirm`: Processes explicit user confirmation for pending `ASK_USER` decisions.
- `GET /api/v1/payments/status`: Returns Razorpay Test Mode gateway configuration and simulation mode status.

### Audit & Evaluation Endpoints
- `GET /api/v1/audit/verify`: Cryptographically validates the linear SHA-256 hash chain.
- `GET /api/v1/audit?user_id=...`: Retrieves audit log records.
- `POST /api/v1/evaluations/decision-preservation`: Runs comparative evaluation between full transaction history and compressed decision memory.

### Interactive Buildathon Web Dashboard & Demo
Start the server and open:
```
http://localhost:8000/
```
The demo UI provides:
1. **Decision & Payment Console**: Propose actions, interact with AI Buying Agent, observe real-time guardrail evaluations, and execute Razorpay Test Mode payments.
2. **Memory & Provenance View**: Inspect raw PostgreSQL ledgers vs derived decision memories with source linking and trigger live compression.
3. **Audit Chain Inspector**: Verify unbroken SHA-256 chain integrity in real-time.
4. **Benchmark Runner**: Run standard and adversarial decision preservation suites.
5. **1-Click Canonical Demo Launcher**: Execute all 8 canonical buildathon scenarios with a single click.

### Live Automated Demonstration Script
```bash
uv run python tests/manual/live_final_demo.py
```
