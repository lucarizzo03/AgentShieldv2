import hashlib
import hmac
import json
import time
import urllib.request
import urllib.parse
from datetime import datetime, timezone

AGENT_ID = "${AGENTSHIELD_AGENT_ID}"
SECRET   = "${AGENTSHIELD_HMAC_SECRET}"
BASE     = "http://127.0.0.1:8000/v1"

WEATHER_URL = "https://openweather.mpp.paywithlocus.com/openweather/current-weather"
LAT, LON    = 40.7128, -74.0060  # NYC


def signed_request(method, path, body_dict=None):
    body_bytes = json.dumps(body_dict, separators=(",", ":")).encode() if body_dict else b""
    ts = datetime.now(timezone.utc).isoformat()
    body_hash = hashlib.sha256(body_bytes).hexdigest()
    msg = "\n".join([method.upper(), path, ts, body_hash, AGENT_ID])
    sig = hmac.new(SECRET.encode(), msg.encode(), hashlib.sha256).hexdigest()
    req = urllib.request.Request(
        BASE + path,
        data=body_bytes or None,
        method=method,
        headers={
            "Content-Type": "application/json",
            "x-agent-id": AGENT_ID,
            "x-timestamp": ts,
            "x-signature": sig,
        },
    )
    try:
        r = urllib.request.urlopen(req)
        return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


# --- Step 1: ask AgentShield ---
body = {
    "agent_id": AGENT_ID,
    "declared_goal": "Get current weather for NYC",
    "amount_cents": 2,
    "currency": "USD",
    "vendor_url_or_name": "openweather.mpp.paywithlocus.com",
    "item_description": "Current weather API request for NYC",
    "asset_type": "STABLECOIN",
    "stablecoin_symbol": "USDC",
    "network": "base",
    "destination_address": "0x742d35Cc6634C0532925a3b8D4C9A6b52E7A1f1",
    "idempotency_key": f"weather-nyc-{int(time.time())}",
}

status, resp = signed_request("POST", "/spend-request", body)
print(f"AgentShield: [{status}] verdict={resp.get('verdict')} status={resp.get('status')}")
print(f"Reasons: {resp.get('reasons')}")

if resp.get("status") == "BLOCKED":
    print("Transaction blocked. Exiting.")
    exit(1)

if resp.get("status") == "PENDING_HITL":
    request_id = resp["request_id"]
    print(f"\nAwaiting human approval — check dashboard or email ({request_id})")
    while True:
        time.sleep(4)
        _, poll = signed_request("GET", f"/spend-request/{request_id}/status")
        print(f"  -> {poll.get('status')}")
        if poll.get("resolved"):
            if poll.get("decision") != "APPROVE":
                print("Denied by human. Exiting.")
                exit(1)
            print("Approved!")
            break

# --- Step 2: make the real API call ---
print("\nCalling weather API...")
params = urllib.parse.urlencode({"lat": LAT, "lon": LON, "units": "metric"})
weather_req = urllib.request.Request(f"{WEATHER_URL}?{params}")
weather_res = urllib.request.urlopen(weather_req)
data = json.loads(weather_res.read())
print(json.dumps(data, indent=2))
