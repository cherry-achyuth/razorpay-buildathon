# DecisionVault
> **AI Financial Safety Guard for Autonomous Commerce**

DecisionVault is a financial memory middleware that sits between autonomous AI buying agents and Razorpay payment execution. Before any payment runs, it reads the user's spending history, compresses it into smart memories, and runs deterministic safety rules. The AI never touches money directly — every payment is gated, explainable, and auditable.

Built for the **Razorpay AI Buildathon**.

---

## How It Works

```
User types: "Pay my usual Netflix subscription"
                      │
                      ▼
         ┌─────────────────────────┐
         │  Gemini AI parses intent│  → Merchant: Netflix, Amount: ₹649
         └────────────┬────────────┘
                      │
                      ▼
         ┌─────────────────────────┐
         │  DecisionVault Guardrails│  → Checks history, policies, drift
         │  - Price Drift Rule      │
         │  - Policy Limit Rule     │
         │  - Duplicate Detection   │
         │  - New Merchant Guard    │
         └────────────┬────────────┘
                      │
          ┌───────────┼───────────┐
          ▼           ▼           ▼
       ALLOW       ASK_USER     BLOCK
          │           │           │
    Razorpay     Pause for    Zero money
    Test Mode    user confirm  movement
    executes
```

---

## 5 Core Demo Scenarios

| # | Try This Prompt | Decision | What It Proves |
|---|---|---|---|
| 1 | `"Pay my usual Netflix subscription"` | ✅ **ALLOW** ₹649 | Memory baseline: resolves amount from history automatically |
| 2 | `"Pay 1500 INR to Netflix"` | ⚠️ **ASK_USER** | Price drift: ₹1,500 is 131% above the ₹649 baseline |
| 3 | `"Order food from Swiggy Instamart"` | ⚠️ **ASK_USER** | New merchant guard: first-time counterparty always requires confirmation |
| 4 | `"Compare Netflix vs Amazon Prime for a year"` | 📊 **Comparison Table** | AI intelligence: structured cost comparison without executing any payment |
| 5 | `"Pay 5000 INR to Unknown Shady Mart"` | 🚫 **BLOCK** | Hard cap: exceeds ₹3,000 ceiling + unverified merchant |

---

## Merchant Baselines (Seeded with Real Published Prices)

| Merchant | Plan | Monthly | Baseline Used |
|---|---|---|---|
| Netflix | Premium 4K (India) | ₹649 | ₹649/month |
| Amazon Prime | Monthly subscription | ₹299 | ₹299/month |
| Spotify | Premium Individual | ₹119 | ₹119/month |
| CloudCompute Global | Standard 2vCPU VPS | ₹850 | ₹850/month |
| BigBasket | bbdaily grocery basket | ₹350 | ₹350/order |
| Unknown Shady Mart | — | — | No history (always ASK_USER) |

New merchants typed by the user (e.g. "Swiggy Instamart") are auto-created, quality-validated, and flagged for first-purchase confirmation. After a confirmed payment, memory is built automatically.

---

## Key Features

- **AI-Powered Intent Parsing** — Gemini Flash reads natural language and extracts merchant, amount, currency. Falls back to deterministic parser if AI is unavailable.
- **Financial Memory** — 21 raw transactions compressed into 5 semantic memories. Raw ledger always intact.
- **Deterministic Guardrails** — 6 rules run on every payment proposal. LLMs have zero authority over money movement.
- **Price Drift Detection** — Flags payments more than 25% above the user's historical median. Fires ASK_USER with specific numbers.
- **New Merchant Safety** — Auto-creates merchants from AI extraction with quality validation (max 4 words, min 3 alpha chars). First payment always requires human confirmation.
- **Anti-Ratcheting** — Confirmed price baseline updates are subject to a 7-day cooldown window to prevent gradual manipulation.
- **Tamper-Evident Audit Chain** — Every decision, payment, and memory event is SHA-256 hash-chained and cryptographically verifiable.
- **Comparison Queries** — Ask "compare X vs Y" and get a structured cost table. No payment executed.
- **Razorpay Test Mode** — Real gateway integration. ALLOW decisions execute via Razorpay sandbox.

---

## Quick Start

### Prerequisites
- Python 3.12+
- [`uv`](https://github.com/astral-sh/uv) package manager

### Setup
```bash
# 1. Install dependencies
uv sync --all-extras

# 2. Configure environment
cp .env.example .env
# Add your GEMINI_API_KEY and RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET to .env

# 3. Run database migrations
uv run alembic upgrade head

# 4. Start the server
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Open **http://localhost:8000/** in your browser.

### Seed Demo Data
Click **"⚡ Seed Demo Data"** in the UI, or run:
```bash
uv run python scripts/seed_demo.py
```
This populates 6 merchants, realistic transaction history, compressed memories, and a valid audit chain.

---

## Running Tests
```bash
uv run pytest -v          # 199 tests, 0 failures
uv run ruff check .       # 0 lint errors
uv run ruff format --check .  # 0 format errors
```

---

## API Reference

| Endpoint | What it does |
|---|---|
| `POST /api/v1/agent/evaluate` | Full pipeline: natural language → guardrails → gated Razorpay payment |
| `POST /api/v1/agent/interpret` | Parse natural language into structured PaymentIntent only |
| `POST /api/v1/decisions/evaluate` | Run guardrails on a structured payment proposal |
| `POST /api/v1/payments/execute` | Execute payment via Razorpay Test Mode (ALLOW only) |
| `POST /api/v1/payments/decisions/{id}/confirm` | Confirm or reject a pending ASK_USER decision |
| `GET /api/v1/memories?user_id=...` | Retrieve compressed decision memories for a user |
| `POST /api/v1/memories/compress` | Trigger memory compression on transaction history |
| `GET /api/v1/audit/verify` | Cryptographically verify the full SHA-256 audit chain |
| `POST /api/v1/demo/seed` | Seed fresh demo data (idempotent) |
| `GET /api/v1/payments/status` | Razorpay gateway configuration status |

Full interactive API docs: **http://localhost:8000/docs**

---

## Project Structure

```
app/
├── api/v1/routes/       # FastAPI route handlers
├── services/
│   ├── agent/           # Gemini AI buying agent + intent parser
│   ├── guardrails/      # 6 deterministic payment rules
│   ├── memory/          # Memory compression + vector search
│   ├── payment/         # Razorpay Test Mode client
│   ├── audit/           # SHA-256 hash-chain audit log
│   └── decision_service.py
├── models/              # SQLAlchemy ORM models
├── schemas/             # Pydantic request/response schemas
└── static/              # Frontend dashboard (HTML/CSS/JS)
scripts/
└── seed_demo.py         # Demo data seeder
migrations/              # Alembic database migrations
tests/
├── unit/                # Guardrail and service unit tests
├── integration/         # Full API route integration tests
└── manual/              # Live end-to-end demo scripts
```

---

## Tech Stack

- **Backend**: FastAPI, SQLAlchemy 2.0 (async), Alembic, Pydantic v2
- **Database**: SQLite (dev) / PostgreSQL (prod) with vector support
- **AI**: Google Gemini Flash (primary), deterministic semantic parser (fallback)
- **Payments**: Razorpay Test Mode
- **Testing**: pytest-asyncio, httpx, 199 tests
- **Quality**: Ruff (lint + format), 0 errors
