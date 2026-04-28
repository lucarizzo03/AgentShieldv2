"""
Live end-to-end run against the local AgentShield API.

Requires an agent already registered through the AgentShield dashboard.
Pass credentials via CLI args or env vars:

    python3 scripts/live_run.py <agent_id> <hmac_secret>

    or set:
        AGENTSHIELD_AGENT_ID
        AGENTSHIELD_HMAC_SECRET

Fires three scenarios:
  1. SAFE      — clean spend, low amount, trusted vendor
  2. SUSPICIOUS — semantic mismatch, requires human approval via dashboard/email
  3. MALICIOUS  — blocked network / disallowed token (hard-denied)

All requests are HMAC-signed. No mocks. Real Postgres, real Redis, real SLM.
"""
import hashlib
import hmac
import json
import os
import sys
import time
from datetime import datetime, timezone

import httpx

BASE = "http://localhost:8000/v1"

GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

def ok(msg):     print(f"{GREEN}✓ {msg}{RESET}")
def warn(msg):   print(f"{YELLOW}⚠ {msg}{RESET}")
def fail(msg):   print(f"{RED}✗ {msg}{RESET}")
def info(msg):   print(f"{CYAN}  {msg}{RESET}")
def header(msg): print(f"\n{BOLD}{'─'*60}\n  {msg}\n{'─'*60}{RESET}")


# ── credentials ─────────────────────────────────────────────────────────────
AGENT_ID = sys.argv[1] if len(sys.argv) == 3 else os.environ.get("AGENTSHIELD_AGENT_ID")
SECRET   = sys.argv[2] if len(sys.argv) == 3 else os.environ.get("AGENTSHIELD_HMAC_SECRET")

if not AGENT_ID or not SECRET:
    print(f"{RED}Error: agent credentials required.{RESET}")
    print(f"\nRegister an agent at {CYAN}http://localhost:5173{RESET} then run:")
    print(f"  {BOLD}python3 scripts/live_run.py <agent_id> <hmac_secret>{RESET}")
    sys.exit(1)


# ── signing ──────────────────────────────────────────────────────────────────
def sign(method: str, path: str, body: dict) -> dict:
    ts        = datetime.now(timezone.utc).isoformat()
    body_json = json.dumps(body, separators=(",", ":"))
    body_hash = hashlib.sha256(body_json.encode()).hexdigest()
    canonical = "\n".join([method.upper(), path, ts, body_hash, AGENT_ID])
    sig       = hmac.new(SECRET.encode(), canonical.encode(), hashlib.sha256).hexdigest()
    return {"Content-Type": "application/json", "x-agent-id": AGENT_ID, "x-timestamp": ts, "x-signature": sig}

def post(path: str, body: dict) -> httpx.Response:
    return httpx.post(f"{BASE}{path}", content=json.dumps(body, separators=(",", ":")), headers=sign("POST", f"/v1{path}", body), timeout=90.0)


# ── verify agent ─────────────────────────────────────────────────────────────
header("Verifying agent credentials")
r = httpx.get(f"{BASE}/agents", timeout=10.0)
if r.status_code != 200:
    fail(f"Could not reach API: {r.status_code}")
    sys.exit(1)
agent = next((a for a in r.json().get("agents", []) if a["agent_id"] == AGENT_ID), None)
if not agent:
    fail(f"Agent '{AGENT_ID}' not found.")
    sys.exit(1)
ok(f"Agent: {agent.get('display_name')}  ({AGENT_ID})")


# ── STEP 1: SAFE ─────────────────────────────────────────────────────────────
header("STEP 1 — SAFE  ($1 · delta.com · USDC on base)")
r = post("/spend-request", {
    "agent_id": AGENT_ID,
    "declared_goal": "Book flight JFK to LAX for team offsite",
    "amount_cents": 100,
    "currency": "USD",
    "asset_type": "STABLECOIN",
    "stablecoin_symbol": "USDC",
    "network": "base",
    "destination_address": "0x742d35Cc6634C0532925a3b8D4C9A6b52E7A1f1",
    "vendor_url_or_name": "delta.com",
    "item_description": "Economy seat JFK-LAX Aug 1",
    "idempotency_key": f"live-safe-{int(time.time())}",
})
body = r.json()
info(f"HTTP {r.status_code}")
if r.status_code == 200 and body.get("verdict") == "SAFE":
    ok(f"Verdict: SAFE → APPROVED_EXECUTED")
    info(f"reasons : {', '.join(body.get('reasons', []))}")
elif r.status_code == 202:
    warn(f"Verdict: SUSPICIOUS → PENDING_HITL")
    info(f"reasons : {', '.join(body.get('reasons', []))}")
else:
    fail(f"Unexpected: {r.status_code}")
    info(json.dumps(body, indent=2))


# ── STEP 2: SUSPICIOUS + wait for human ──────────────────────────────────────
header("STEP 2 — SUSPICIOUS  ($5 · Uber Eats · mismatched goal)")
r = post("/spend-request", {
    "agent_id": AGENT_ID,
    "declared_goal": "Book flight to NYC conference",
    "amount_cents": 500,
    "currency": "USD",
    "asset_type": "STABLECOIN",
    "stablecoin_symbol": "USDC",
    "network": "base",
    "destination_address": "0x742d35Cc6634C0532925a3b8D4C9A6b52E7A1f1",
    "vendor_url_or_name": "Uber Eats",
    "item_description": "Large dinner order",
    "idempotency_key": f"live-susp-{int(time.time())}",
    "dev_slm_preset": "WEAK",
})
body = r.json()
info(f"HTTP {r.status_code}")
if r.status_code == 202:
    ok("Verdict: SUSPICIOUS → PENDING_HITL  (agent waiting)")
    REQUEST_ID = body["request_id"]
    info(f"request_id  : {REQUEST_ID}")
    info(f"expires_at  : {body['hitl']['expires_at']}")
    info(f"reasons     : {', '.join(body.get('reasons', []))}")
    print(f"\n  {YELLOW}→ Waiting for human decision — approve or deny in dashboard/email…{RESET}")
    while True:
        time.sleep(4)
        poll_headers = sign("GET", f"/v1/spend-request/{REQUEST_ID}/status", {})
        pr = httpx.get(f"{BASE}/spend-request/{REQUEST_ID}/status", headers=poll_headers, timeout=10.0)
        poll = pr.json()
        print(f"  -> {poll.get('status')}")
        if poll.get("resolved"):
            decision = poll.get("decision", "unknown")
            if decision == "APPROVE":
                ok(f"Approved by human → APPROVED_BY_HUMAN_EXECUTED")
            else:
                warn(f"Denied by human → DENIED_BY_HUMAN")
            break
elif r.status_code == 200:
    warn("Got SAFE instead of SUSPICIOUS — amount within auto-approve threshold")
    info(f"reasons : {', '.join(body.get('reasons', []))}")
elif r.status_code == 403:
    fail("BLOCKED (hard deny)")
    info(f"reasons : {', '.join(body.get('reasons', []))}")
else:
    fail(f"Unexpected: {r.status_code}")
    info(json.dumps(body, indent=2))


# ── STEP 3: MALICIOUS ────────────────────────────────────────────────────────
header("STEP 3 — MALICIOUS  (hard-deny conditions)")
malicious_cases = [
    {
        "label": "Network not allowed (polygon)",
        "expected": "NETWORK_NOT_ALLOWED",
        "body": {
            "agent_id": AGENT_ID, "declared_goal": "Pay contractor",
            "amount_cents": 1000, "currency": "USD",
            "asset_type": "STABLECOIN", "stablecoin_symbol": "USDC", "network": "polygon",
            "destination_address": "0x742d35Cc6634C0532925a3b8D4C9A6b52E7A1f1",
            "vendor_url_or_name": "contractor.com", "item_description": "Invoice #42",
            "idempotency_key": f"live-mal-net-{int(time.time())}",
        },
    },
    {
        "label": "Token not allowed (USDT)",
        "expected": "STABLECOIN_NOT_ALLOWED",
        "body": {
            "agent_id": AGENT_ID, "declared_goal": "Pay for API access",
            "amount_cents": 500, "currency": "USD",
            "asset_type": "STABLECOIN", "stablecoin_symbol": "USDT", "network": "base",
            "destination_address": "0x742d35Cc6634C0532925a3b8D4C9A6b52E7A1f1",
            "vendor_url_or_name": "api-provider.com", "item_description": "API credits",
            "idempotency_key": f"live-mal-tok-{int(time.time())}",
        },
    },
]
for case in malicious_cases:
    r = post("/spend-request", case["body"])
    rb = r.json()
    reasons = rb.get("reasons", [])
    if r.status_code == 403 and case["expected"] in reasons:
        ok(f"{case['label']} → BLOCKED  ({case['expected']})")
    elif r.status_code == 403:
        warn(f"{case['label']} → BLOCKED (expected {case['expected']}, got: {', '.join(reasons)})")
    else:
        fail(f"{case['label']} — not blocked: {r.status_code}")


# ── done ─────────────────────────────────────────────────────────────────────
header("RUN COMPLETE")
print(f"  Agent    : {AGENT_ID}")
print(f"  Dashboard: http://localhost:5173\n")
