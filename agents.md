# DecisionVault — Agents Guide
> How Antigravity AI should implement, verify, and extend DecisionVault for the Razorpay AI Buildathon

---

## Overview

This file tells Antigravity (and any AI coding agent) exactly how to work on this project.
It defines agent roles, implementation rules, verification steps, and the exact commands to run at each stage.

---

## Agent Roles

### Agent 1 — Backend Implementation Agent
**Responsible for:** All Python/FastAPI backend code in `app/`

Rules:
- Never bypass the deterministic guardrail pipeline. LLMs (Gemini/OpenAI) are ONLY allowed in `buying_agent.py` for intent parsing — never for payment decisions.
- Every new service method must have a matching unit test in `tests/unit/`.
- All new API routes must be registered in `app/api/v1/router.py`.
- Run `uv run ruff check .` and `uv run ruff format .` before declaring any backend task complete.
- Run `uv run pytest -v` — ALL tests must pass (no skips, no failures).
- Use `uv add <package>` to add dependencies, never edit `pyproject.toml` by hand without `uv`.
- Database changes require a migration: `uv run alembic revision --autogenerate -m "description"` + `uv run alembic upgrade head`.
- The DATABASE_URL in .env must match the actual filesystem path (currently e:/cherry/project/decisionvault.db).

### Agent 2 — Demo & Verification Agent
**Responsible for:** End-to-end scenario verification and buildathon demo quality

Rules:
- Always seed the database first: `POST /api/v1/demo/seed` or `uv run python scripts/seed_demo.py`.
- Verify ALL 8 canonical scenarios from spec.md Section 7 pass before marking demo complete.
- The audit chain must return VALID from `GET /api/v1/audit/verify`.
- Decision preservation benchmark must return >= 100% at `POST /api/v1/evaluations/decision-preservation`.
- The web dashboard at `http://localhost:8000/` must be accessible and functional.
- Use `uv run python tests/manual/live_final_demo.py` for the live automated demo.

### Agent 3 — Frontend / Dashboard Agent
**Responsible for:** Static dashboard in `app/static/` (index.html + assets)

Rules:
- The dashboard is served at `GET /` and `GET /demo` via FastAPI StaticFiles.
- Must work without any separate build step — plain HTML/CSS/JS or Jinja2 only.
- Must display: Decision Console, Memory Inspector, Audit Chain viewer, Benchmark runner, 1-Click Demo Launcher.
- All API calls from dashboard must use relative paths (e.g., `/api/v1/...`).

### Agent 4 — Test & Quality Agent
**Responsible for:** Maintaining and extending the test suite in `tests/`

Rules:
- New guardrail rules require tests in `tests/unit/guardrails/`.
- New API routes require tests in `tests/integration/`.
- Test database must use SQLite (aiosqlite) — never PostgreSQL in tests.
- Fixture: `conftest.py` in `tests/` provides `async_client`, `db_session`, and seeded test data.
- Run full suite: `uv run pytest -v --tb=short` — target: all green.
- Coverage target: >= 80% on `app/services/`.

---

## Implementation Rules (Apply to ALL Agents)

### Financial Safety Rules (CRITICAL — Never Violate)
1. **LLMs never authorize payments.** `buying_agent.py` parses intent only. `decision_service.py` and guardrail rules are always deterministic.
2. **Fail-safe on LLM errors.** Catch ALL exceptions from Gemini/OpenAI calls. Return `None` → trigger deterministic fallback.
3. **Idempotency on every payment.** Every `POST /payments/execute` call must include an `idempotency_key`.
4. **Zero-debit on BLOCK/ASK_USER.** If decision is not `ALLOW`, no Razorpay API call is made.
5. **Append-only audit log.** Never UPDATE or DELETE audit events. Append only.

### Code Quality Rules
- Python 3.12+. Use type hints everywhere.
- All async functions use `async def` + `await`. No sync DB calls in async context.
- Pydantic v2 schemas for all request/response models.
- SQLAlchemy 2.0 async ORM style (no legacy `session.execute(text(...))` without types).
- No hardcoded UUIDs or secrets in source code. Use `.env` and `get_settings()`.
- Line length: 88 chars (Ruff default). Docstrings required on all public methods.

### Git / File Rules
- Never commit `.env` — it is in `.gitignore`.
- Never commit `decisionvault.db`, `*.db` files — they are in `.gitignore`.
- New files must follow existing module structure (see spec.md Section 4).

---

## Verification Checklist (Run Before Submission)

### Step 1: Environment
```bash
# Confirm server starts cleanly
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 &
curl http://127.0.0.1:8000/health
# Expected: {"status":"ok","database":"connected",...}
```

### Step 2: Seed Demo Data
```bash
curl -X POST http://127.0.0.1:8000/api/v1/demo/seed
# Expected: 200 OK with seeded entity counts
```

### Step 3: Run All Tests
```bash
uv run pytest -v
# Expected: All tests PASS, 0 failures, 0 errors
```

### Step 4: Lint & Format
```bash
uv run ruff check .
uv run ruff format --check .
# Expected: No errors
```

### Step 5: Verify 8 Canonical Scenarios
```bash
uv run python tests/manual/live_final_demo.py
# Expected: All 8 scenarios pass
```

### Step 6: Audit Chain Integrity
```bash
curl http://127.0.0.1:8000/api/v1/audit/verify
# Expected: {"status":"VALID",...}
```

### Step 7: Decision Preservation Benchmark
```bash
curl -X POST http://127.0.0.1:8000/api/v1/evaluations/decision-preservation \
  -H "Content-Type: application/json" \
  -d "{}"
# Expected: preservation_rate >= 1.0, false_allow_count = 0
```

### Step 8: AI Agent NLP Test
```bash
curl -X POST http://127.0.0.1:8000/api/v1/agent/evaluate \
  -H "Content-Type: application/json" \
  -d "{\"prompt\": \"Pay my usual 25 INR subscription to CloudCompute\", \"user_id\": \"<seeded-user-uuid>\", \"currency\": \"INR\"}"
# Expected: decision = ALLOW or ASK_USER (not BLOCK for valid routine payment)
```

### Step 9: Dashboard Accessible
- Open http://localhost:8000/ in browser
- Confirm all 5 panels load: Decision Console, Memory Inspector, Audit Chain, Benchmark, 1-Click Demo

---

## Common Issues & Fixes

| Issue | Fix |
|---|---|
| `No module named 'httpx'` | `uv add httpx` |
| `No module named 'aiosqlite'` | `uv add aiosqlite` |
| `unable to open database file` | Check DATABASE_URL drive letter in .env (must be `e:` not `d:`) |
| `GEMINI_API_KEY not set` | Add `GEMINI_API_KEY="..."` to .env |
| Venv linked to wrong Python | `uv venv --python 3.12` then `uv sync` |
| Alembic migration fails | Ensure DATABASE_URL points to correct path; run `uv run alembic upgrade head` |
| Tests fail with import errors | Run `uv sync --all-extras` to install dev dependencies |

---

## Key File Locations

| What | Path |
|---|---|
| Main app entry | app/main.py |
| Config settings | app/core/config.py |
| All API routes | app/api/v1/routes/ |
| AI buying agent | app/services/agent/buying_agent.py |
| Decision engine | app/services/decision_service.py |
| Guardrail rules | app/services/guardrails/rules/ |
| Payment gateway | app/services/payment/service.py |
| Razorpay client | app/services/payment/client.py |
| Financial memory | app/services/memory/ |
| Audit service | app/services/audit/ |
| Evaluation | app/services/evaluation/ |
| DB models | app/models/ |
| Pydantic schemas | app/schemas/ |
| Demo dashboard | app/static/index.html |
| Environment | .env |
| Spec | spec.md |
| Tasks | tasks.md |
| Tests | tests/ |
| Scripts | scripts/ |
| Migrations | migrations/ |
