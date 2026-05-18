# AgentShield — Session Context

This file is the persistent working context for Claude Code sessions on this project.
When context compacts or a new session starts, run `/context-restore` to get back up to speed.
At the end of any session with meaningful changes, run `/context-save` to log what happened.

---

### 2026-05-17 — UI status fix + destination policy change

**What was done:**
- Performed a full codebase walkthrough to verify current architecture and behavior (backend, dashboard, tests, config)
- Fixed Activity page bug where resolved requests could still display flashing pending status
- Updated backend spend validation/policy to remove the Locus missing-destination exception and require destination for both FIAT and STABLECOIN requests

**Files changed (UI):**
- `dashboard/src/App.jsx`
  - Added request-level activity row selection that prefers terminal statuses over stale pending rows
  - Expanded status normalization (`EXPIRED` => blocked display, `APPROVED_EXECUTED` => safe display)
  - Prevents persistent pending pulse on resolved activity rows

**Files changed (backend):**
- `app/api/v1/schemas/spend.py`
  - `SpendRequest` now requires `destination_address` for all asset types (`FIAT` and `STABLECOIN`)
- `app/policy/checks/policy_db.py`
  - Removed `_is_locus_mpp_vendor` exception path
  - Missing destination now consistently yields `DESTINATION_ADDRESS_MISSING` in policy checks
- `app/api/v1/routes/spend.py`
  - Removed `DESTINATION_DEFERRED_MPP` from `_CHECK_REASON_GROUPS`

**Tests updated:**
- `tests/unit/test_policy_checks.py`
  - Updated Locus missing-destination test to expect suspicious + `DESTINATION_ADDRESS_MISSING`
- `tests/integration/test_full_scenarios.py`
  - Added destination to FIAT fixture payloads
  - Updated missing-destination scenarios to expect 422 validation error
- `tests/e2e/test_live_spend.py`
  - Added `destination_address` to FIAT live payloads

**Verification run:**
- `uv run pytest tests/unit/test_policy_checks.py tests/integration/test_full_scenarios.py`
- Result: **30 passed**

**Current behavior after changes:**
- `destination_address` is required at request validation for both FIAT and STABLECOIN
- Missing destination now returns 422 (instead of routing STABLECOIN to HITL)
- No special-case bypass remains for `.mpp.paywithlocus.com` vendor hosts

---

## Project Snapshot

**What it is:** AgentShield — a **pure decision engine** / spending firewall for autonomous AI agents. It never moves money. Agents submit spend intents via API; four risk checks (A: quantitative/Redis, B: policy/Postgres, C+D: semantic+goal-drift/Claude Haiku) return SAFE (200 — agent cleared to proceed), SUSPICIOUS (202 → HITL), or MALICIOUS (403). The agent acts on the verdict; AgentShield only says yes, wait, or no.

**Stack:** FastAPI + SQLModel + Alembic (Postgres/SQLite), Redis, React/Vite dashboard, Anthropic SDK (claude-haiku-4-5-20251001), SendGrid HITL email.

**Key entry points:**
- `app/main.py` — FastAPI app, lifespan, middleware
- `app/policy/engine.py` — `run_financial_triangulation` (A→B, then C+D in parallel)
- `app/api/v1/routes/spend.py` — `POST /v1/spend-request` handler
- `app/core/security.py` — HMAC-SHA256 + Auth0 Bearer auth
- `app/services/slm/client.py` — `AnthropicSemanticClient`

**Current branch:** main

---

## Session Log

### 2026-05-17 — CLAUDE.md audit + prompt injection fixes

**What was done:**
- Full codebase read to audit CLAUDE.md accuracy; found and fixed 8 stale/wrong items
- Ran complete prompt injection scan across all surfaces where user-controlled data touches prompts, HTML, logs, or external calls
- Fixed Critical: HTML/XSS injection in HITL email (`notifier.py`) — vendor, goal, item were interpolated raw into HTML
- Fixed High: semantic prompt injection in SLM client — added XML delimiters + system prompt data-boundary note + 500-char item truncation
- Fixed merge conflict after rebase onto remote main (modify/delete on `test_isolated.db`)

**Files changed:**
- `CLAUDE.md` — updated architecture diagram (added Check D), auth section (Auth0 Bearer replacing "JWT Bearer", removed dev bypass row, HITL auth detail), Redis key map (removed deleted OTP key), dashboard routes (Integration→Docs, Auth0 login views, correct localStorage key), added full API endpoints table, updated HITL flow (status poll URL, callback mechanism), added `agent_callback_url` SSRF gotcha
- `app/services/hitl/notifier.py` — added `html.escape()` on vendor/goal/item before HTML interpolation; newline-strip for plain text body and subject line
- `app/services/slm/client.py` — added `_xml_escape()` helper and `_MAX_ITEM_LEN=500`; updated all 9 few-shot examples to XML `<transaction>` format; added data-boundary note to system prompt; `semantic_alignment()` now truncates item to 500 chars and builds user message as XML
- `tests/unit/test_engine.py` — `test_engine_semantic_aligned_safe` updated to use weather API scenario ($0.02) instead of $5 flight (Claude correctly flags $5 flight as `AMOUNT_UNREASONABLY_LOW` with new stricter prompt)

**Key decisions / gotchas discovered:**
- `html.escape()` is stdlib — zero new dependencies for the HTML injection fix
- XML tag injection (breaking out of `<item>` via `</item>` in user data) requires `_xml_escape()` separate from json.dumps — json.dumps does not escape `<` or `>`
- Changing the system prompt format invalidates the Anthropic prompt cache once (ephemeral cache); acceptable one-time cost
- The test's default `amount_cents=500` for a flight is semantically wrong with the more careful new prompt — fixed by switching the semantic test to a cheap API call scenario that's in the few-shot examples
- Remote had deleted `test_isolated.db` in a cleanup commit; merge conflict was modify/delete, resolved by accepting the deletion

**Current state / next steps:**
- All 56 tests passing after changes
- Issues #3 (allowed_scopes prompt injection, medium) and #4 (log injection, low) not yet fixed — discussed but not implemented
- Branch is up to date with origin/main

---

### 2026-05-17 — decision engine framing + docs sweep

**What was done:**
- Clarified across entire codebase that AgentShield is a pure decision engine — no payment adapters exist, never did
- Swept all "payment executed" language out of every doc and UI file
- Rewrote CLAUDE.md critical gotchas (were stale/wrong), removed SMS/payment adapter sections
- Confirmed no `services/payment/` directory exists — old ARCHITECTURE.md references were fiction
- Discussed legal requirements: Privacy Policy + ToS sufficient for current stage (free, pre-revenue); no MSB risk since no money moves through the system
- Explained SESSION_CONTEXT.md is shared — Codex can read it directly; `/context-save` and `/context-restore` are Claude Code-only skills

**Files changed:**
- `README.md` — 5 instances of "payment executed" → "agent cleared to proceed"
- `CLAUDE.md` — project overview rewritten; payment adapters section removed; critical gotchas fully rewritten (accurate now)
- `ARCHITECTURE.md` — opening paragraph rewritten; payment adapter note added; HITL wording corrected
- `dashboard/src/DocsPage.jsx` — code example comment + HITL step description corrected

**No code changes — documentation and framing only**

**Key facts confirmed this session:**
- `destination_address` now required for ALL asset types (Codex change — was optional for STABLECOIN)
- `_is_locus_mpp_vendor` exception removed (Codex change)
- `DESTINATION_DEFERRED_MPP` reason code gone
- README note about optional destination_address is now stale — both are required

**Current state / next steps:**
- All docs accurate as of this session
- README still says `destination_address` optional for STABLECOIN — needs one-line fix to reflect Codex's schema change
- No open bugs

---

### 2026-05-17 (continued)

**What was done:**
- Full codebase review: read all key source files (`engine.py`, `security.py`, `spend.py`, `quantitative.py`, `semantic.py`, `goal_drift.py`, `policy_db.py`, all schemas/models/config)
- Rewrote `README.md` to reflect actual code behavior

**Files changed:**
- `README.md` — comprehensive update

**Corrections made to README (were wrong, now fixed):**
- Check C MISMATCH → was documented as "hard deny", actual code: `suspicious` (HITL), never `hard_deny`
- Check D API unavailable → was "fail open (pass)", actual code: `GOAL_DRIFT_EVAL_UNAVAILABLE` → suspicious
- Check execution order → C and D run **in parallel** via `asyncio.gather` (not sequentially A→B→C→D); C+D are skipped entirely if A or B hard-denies
- Budget behavior → atomically reserved during Check A Lua script, then finalized (SAFE) or rolled back (SUSPICIOUS/MALICIOUS); not "only committed on payment"
- Vendor blocklist → hostname/word-boundary matching, not simple substring; old example about `"pay"` blocking `"paypal.com"` was wrong
- Dev bypass → all shortcuts removed, section rewritten

**Additions to README:**
- `USDC.e` and `USDC.b` as supported stablecoin symbols
- `destination_address` is optional for STABLECOIN (only `stablecoin_symbol` + `network` required)
- `agent_callback_url` field in spend request schema
- `agent_feedback` object in all responses (per-check breakdown)
- `status_poll_url` and `poll_interval_seconds` in 202 response
- HITL resolve accepts Auth0 Bearer OR webhook HMAC
- Agent default limits: `$1,000/day`, `$100/txn`, networks: ethereum/base/solana
- SQLite fallback when POSTGRES_DSN not set; `DATABASE_URL`/`REDIS_URL` env aliases

**Current state / next steps:**
- README accurate and complete as of this session
- No code changes — documentation only
- Activity page `dotPulse` bug found (flashing PENDING on resolved rows) — Codex fixed it externally, not in this session

---

### 2026-05-17 — ARCHITECTURE.md + context system

**What was done:**
- Created `/context-save` and `/context-restore` skills (`~/.claude/skills/`) with full instructions
- Created `SESSION_CONTEXT.md` (this file) in project root as persistent session log
- Rewrote `ARCHITECTURE.md` from scratch — was heavily stale

**Files changed:**
- `SESSION_CONTEXT.md` — created
- `~/.claude/skills/context-save/SKILL.md` — created
- `~/.claude/skills/context-restore/SKILL.md` — created
- `ARCHITECTURE.md` — full rewrite

**Key corrections made to ARCHITECTURE.md (were wrong, now fixed):**
- "Ollama at localhost:11434" → Anthropic API (`claude-haiku-4-5-20251001`)
- "3 parallel checks" → 4 checks: A→B sequential, then C+D in parallel; C+D skipped if A or B hard-denies
- Semantic MISMATCH → was "hard deny", now correct: suspicious (HITL)
- Goal drift API unavailable → was "fail open", now correct: suspicious (`GOAL_DRIFT_EVAL_UNAVAILABLE`)
- Vendor matching → was "substring-based", now correct: hostname/word-boundary matching
- Budget → was "committed on payment only", now correct: atomically reserved in Check A Lua script, finalized/rolled back per verdict
- Auth → removed stale JWT HS256 + dev bypass descriptions; correct: Auth0 RS256 + HMAC-SHA256 only
- Removed all SMS/OTP/Twilio references (that system doesn't exist)
- Agent model → removed phone/SMS fields, added `allowed_scopes`, `owner_user_id`
- SpendAuditLog → removed stale payment fields, added `goal_drift_result`, `EXPIRED` status
- Endpoint list → removed non-existent routes, added real ones (`PATCH /scopes`, `/status`, `/email-resolve`)
- `TriangulationResult` → added missing `goal_drift_result` field
- Added expiry sweeper background task to lifecycle diagram
- Added activity feed deduplication logic explanation
- Updated all env vars (removed SLM/JWT vars, added Anthropic/Auth0/SendGrid)

**Current state / next steps:**
- All documentation (README + ARCHITECTURE.md + SESSION_CONTEXT.md) accurate as of this session
- No open bugs or WIP tasks from this session

---
