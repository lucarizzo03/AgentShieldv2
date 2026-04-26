"""
Live end-to-end run against the local AgentShield API.

Requires an agent already registered through the AgentShield dashboard or
onboarding bootstrap endpoint. Pass credentials via CLI args or env vars:

    python3.11 scripts/live_run.py <agent_id> <hmac_secret>

    or set:
        AGENTSHIELD_AGENT_ID
        AGENTSHIELD_HMAC_SECRET

Fires three real transactions:
  1. SAFE      — clean spend, low amount, trusted vendor
  2. SUSPICIOUS — over threshold, requires human approval; script auto-approves
  3. MALICIOUS  — blocked vendor / bad network / disallowed token (all blocked)

All requests are HMAC-signed using the agent's secret (production auth path).
No mocks. Real Postgres, real Redis, real SLM.
"""
import hashlib
import hmac
import json
import os
import sys
from datetime import datetime, timezone

import httpx

BASE = "http://localhost:8000/v1"

# ── colour helpers ──────────────────────────────────────────────────────────
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


# ── Load agent credentials ───────────────────────────────────────────────────
AGENT_ID = None
SECRET   = None

if len(sys.argv) == 3:
    AGENT_ID = sys.argv[1]
    SECRET   = sys.argv[2]
else:
    AGENT_ID = os.environ.get("AGENTSHIELD_AGENT_ID")
    SECRET   = os.environ.get("AGENTSHIELD_HMAC_SECRET")

if not AGENT_ID or not SECRET:
    print(f"{RED}Error: agent credentials required.{RESET}")
    print()
    print("Register your agent first via the AgentShield dashboard:")
    print(f"  {CYAN}http://localhost:5173{RESET}")
    print()
    print("Then run:")
    print(f"  {BOLD}python3.11 scripts/live_run.py <agent_id> <hmac_secret>{RESET}")
    print()
    print("Or export environment variables:")
    print(f"  export AGENTSHIELD_AGENT_ID=agt_...")
    print(f"  export AGENTSHIELD_HMAC_SECRET=sk_live_...")
    sys.exit(1)


# ── HMAC signing ────────────────────────────────────────────────────────────
def sign_request(method: str, path: str, body: dict, agent_id: str, secret: str) -> dict:
    timestamp = datetime.now(timezone.utc).isoformat()
    body_json = json.dumps(body, separators=(",", ":"))
    body_hash = hashlib.sha256(body_json.encode()).hexdigest()
    canonical = "\n".join([method.upper(), path, timestamp, body_hash, agent_id])
    signature = hmac.new(secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()
    return {
        "Content-Type": "application/json",
        "x-agent-id": agent_id,
        "x-timestamp": timestamp,
        "x-signature": signature,
    }


def post(path: str, body: dict, headers: dict) -> httpx.Response:
    return httpx.post(f"{BASE}{path}", content=json.dumps(body, separators=(",", ":")), headers=headers, timeout=90.0)


# ── Verify agent exists ──────────────────────────────────────────────────────
header("Verifying agent credentials")

r = httpx.get(f"{BASE}/agents", timeout=10.0)
if r.status_code != 200:
    fail(f"Could not reach API: {r.status_code} {r.text}")
    sys.exit(1)

agents = r.json().get("agents", [])
agent = next((a for a in agents if a["agent_id"] == AGENT_ID), None)
if not agent:
    fail(f"Agent '{AGENT_ID}' not found. Register it via the dashboard first.")
    sys.exit(1)
ok(f"Agent found: {AGENT_ID}")
info(f"display_name : {agent.get('display_name', 'n/a')}")
info(f"status       : {agent.get('status', 'n/a')}")
info(f"hitl_channel : {agent.get('hitl_primary_channel', 'n/a')}")


# ── Step 1: SAFE transaction ─────────────────────────────────────────────────
header("STEP 1 — SAFE transaction  ($25 · delta.com · USDC on base)")

safe_body = {
    "agent_id": AGENT_ID,
    "declared_goal": "Book flight JFK to LAX for team offsite",
    "amount_cents": 2_500,
    "currency": "USD",
    "asset_type": "STABLECOIN",
    "stablecoin_symbol": "USDC",
    "network": "base",
    "destination_address": "0x742d35Cc6634C0532925a3b8D4C9A6b52E7A1f1",
    "vendor_url_or_name": "delta.com",
    "item_description": "Economy seat JFK-LAX Aug 1",
    "idempotency_key": "live-safe-001",
}

headers = sign_request("POST", "/v1/spend-request", safe_body, AGENT_ID, SECRET)
r = post("/spend-request", safe_body, headers)

info(f"HTTP {r.status_code}")
body = r.json()

if r.status_code == 200 and body.get("verdict") == "SAFE":
    ok("Verdict: SAFE → APPROVED_EXECUTED")
    info(f"provider     : {body['payment']['provider']}")
    info(f"txn_id       : {body['payment']['provider_txn_id']}")
    info(f"onchain_hash : {body['payment']['onchain_tx_hash']}")
    info(f"reasons      : {', '.join(body['reasons'])}")
elif r.status_code == 202:
    warn("Verdict: SUSPICIOUS → PENDING_HITL  (SLM flagged; check reasons)")
    info(f"reasons    : {', '.join(body.get('reasons', []))}")
    info(f"request_id : {body['request_id']}")
else:
    fail(f"Unexpected response: {r.status_code}")
    info(json.dumps(body, indent=2))


# ── Step 2: SUSPICIOUS transaction + auto-approve ───────────────────────────
header("STEP 2 — SUSPICIOUS transaction  ($75 · over auto-approve threshold · aws.amazon.com)")

susp_body = {
    "agent_id": AGENT_ID,
    "declared_goal": "Pay monthly cloud hosting bill",
    "amount_cents": 7_500,
    "currency": "USD",
    "asset_type": "STABLECOIN",
    "stablecoin_symbol": "USDC",
    "network": "base",
    "destination_address": "0x742d35Cc6634C0532925a3b8D4C9A6b52E7A1f1",
    "vendor_url_or_name": "aws.amazon.com",
    "item_description": "AWS EC2 monthly invoice",
    "idempotency_key": f"live-susp-{datetime.now().strftime('%H%M%S')}",
}

headers = sign_request("POST", "/v1/spend-request", susp_body, AGENT_ID, SECRET)
r = post("/spend-request", susp_body, headers)

info(f"HTTP {r.status_code}")
body = r.json()

if r.status_code == 202:
    ok("Verdict: SUSPICIOUS → PENDING_HITL  (agent is now waiting)")
    REQUEST_ID = body["request_id"]
    info(f"request_id  : {REQUEST_ID}")
    info(f"channel     : {body['hitl']['channel']}")
    info(f"expires_at  : {body['hitl']['expires_at']}")
    info(f"reasons     : {', '.join(body['reasons'])}")
    info(f"next_action : {body['next_action']}")

    print(f"\n  → Auto-approving via HITL endpoint…")
    resolve_body = {
        "decision": "APPROVE",
        "resolver_id": "live-operator-1",
        "channel": "dashboard",
        "resolution_note": "Verified with team lead — legitimate cloud bill",
    }
    rr = httpx.post(
        f"{BASE}/hitl/resolve/{REQUEST_ID}",
        json=resolve_body,
        headers={"x-webhook-signature": "sig_ok", "Content-Type": "application/json"},
    )
    rb = rr.json()
    if rr.status_code == 200 and rb["payment"]["executed"]:
        ok("APPROVED — payment executed")
        info(f"provider    : {rb['payment']['provider']}")
        info(f"txn_id      : {rb['payment']['provider_txn_id']}")
        info(f"resolved_at : {rb['resolved_at']}")
    else:
        fail(f"Resolve failed: {rr.status_code} {rr.text}")

elif r.status_code == 200:
    warn("Got SAFE instead of SUSPICIOUS — amount may be within auto-approve threshold for this agent")
    info(f"reasons : {', '.join(body.get('reasons', []))}")
elif r.status_code == 403:
    warn("SLM hard-denied this transaction (tinyllama false positive) — HITL path blocked by semantic check")
    info(f"reasons : {', '.join(body.get('reasons', []))}")
    info("Tip: lower HITL threshold or retune SLM prompt if this keeps happening")
else:
    fail(f"Unexpected: {r.status_code}")
    info(json.dumps(body, indent=2))


# ── Step 3: MALICIOUS transactions ──────────────────────────────────────────
header("STEP 3 — MALICIOUS transactions  (hard-deny conditions)")

malicious_cases = [
    {
        "label": "Blocked vendor (scamsite.io — must be in agent blocklist)",
        "expected_reason": "VENDOR_MATCHED_BLOCKLIST",
        "body": {
            "agent_id": AGENT_ID,
            "declared_goal": "Buy software tools",
            "amount_cents": 1_000,
            "currency": "USD",
            "asset_type": "STABLECOIN",
            "stablecoin_symbol": "USDC",
            "network": "base",
            "destination_address": "0x742d35Cc6634C0532925a3b8D4C9A6b52E7A1f1",
            "vendor_url_or_name": "scamsite.io",
            "item_description": "Developer tools subscription",
            "idempotency_key": f"live-mal-vendor-{datetime.now().strftime('%H%M%S')}",
        },
    },
    {
        "label": "Network not allowed (polygon)",
        "expected_reason": "NETWORK_NOT_ALLOWED",
        "body": {
            "agent_id": AGENT_ID,
            "declared_goal": "Pay contractor via polygon network",
            "amount_cents": 1_000,
            "currency": "USD",
            "asset_type": "STABLECOIN",
            "stablecoin_symbol": "USDC",
            "network": "polygon",
            "destination_address": "0x742d35Cc6634C0532925a3b8D4C9A6b52E7A1f1",
            "vendor_url_or_name": "contractor-payments.com",
            "item_description": "Contractor invoice #42",
            "idempotency_key": "live-mal-network",
        },
    },
    {
        "label": "Token not allowed (USDT)",
        "expected_reason": "STABLECOIN_NOT_ALLOWED",
        "body": {
            "agent_id": AGENT_ID,
            "declared_goal": "Pay for API access",
            "amount_cents": 500,
            "currency": "USD",
            "asset_type": "STABLECOIN",
            "stablecoin_symbol": "USDT",
            "network": "base",
            "destination_address": "0x742d35Cc6634C0532925a3b8D4C9A6b52E7A1f1",
            "vendor_url_or_name": "api-provider.com",
            "item_description": "API credits",
            "idempotency_key": "live-mal-token",
        },
    },
]

for case in malicious_cases:
    b = case["body"]
    h = sign_request("POST", "/v1/spend-request", b, AGENT_ID, SECRET)
    r = post("/spend-request", b, h)
    rb = r.json()
    reasons = rb.get("reasons", [])
    if r.status_code == 403 and case["expected_reason"] in reasons:
        ok(f"{case['label']} → BLOCKED  ({case['expected_reason']})")
    elif r.status_code == 403:
        # Still blocked, but by a different check (e.g. SLM or policy)
        actual = ", ".join(reasons) or "unknown"
        warn(f"{case['label']} → BLOCKED (expected {case['expected_reason']}, got: {actual})")
    else:
        fail(f"{case['label']} — not blocked: {r.status_code}, reasons: {reasons}")


# ── Summary ──────────────────────────────────────────────────────────────────
header("RUN COMPLETE")
print(f"  Agent    : {AGENT_ID}")
print(f"  Dashboard: http://localhost:5173\n")
