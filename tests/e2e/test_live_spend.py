"""
Live end-to-end tests hitting the deployed AgentShield API.
Uses real HMAC signing with the test agent credentials.
"""
import hashlib
import hmac
import json
from datetime import datetime, timezone

import httpx
import pytest

API_URL = "https://agentshieldv2-backend-production.up.railway.app"
AGENT_ID = "agt_19e9fd8fc3eb498cb8"
HMAC_SECRET = "sk_live_kgD4T0goXzWf4pAPPHZp_7xI"


def _sign(method: str, path: str, body: bytes) -> dict:
    timestamp = datetime.now(timezone.utc).isoformat()
    body_hash = hashlib.sha256(body).hexdigest()
    canonical = "\n".join([method.upper(), path, timestamp, body_hash, AGENT_ID])
    signature = hmac.new(HMAC_SECRET.encode(), canonical.encode(), hashlib.sha256).hexdigest()
    return {
        "x-agent-id": AGENT_ID,
        "x-timestamp": timestamp,
        "x-signature": signature,
        "content-type": "application/json",
    }


def _post(path: str, payload: dict) -> httpx.Response:
    body = json.dumps(payload).encode()
    headers = _sign("POST", path, body)
    return httpx.post(f"{API_URL}{path}", content=body, headers=headers, timeout=30)


# ---------------------------------------------------------------------------
# SAFE — clearly aligned low-amount FIAT transaction
# ---------------------------------------------------------------------------

def test_live_safe_verdict() -> None:
    r = _post("/v1/spend-request", {
        "agent_id": AGENT_ID,
        "declared_goal": "Book flight JFK to LAX",
        "amount_cents": 100,
        "currency": "USD",
        "vendor_url_or_name": "delta.com",
        "item_description": "Economy seat JFK-LAX",
        "asset_type": "FIAT",
        "destination_address": "fiat-destination-acct-0001",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["verdict"] == "SAFE"
    assert body["status"] == "APPROVED_EXECUTED"
    assert "request_id" in body


# ---------------------------------------------------------------------------
# MALICIOUS — vendor matches blocklist (need to add one or use phishing domain)
# ---------------------------------------------------------------------------

def test_live_malicious_phishing_vendor() -> None:
    r = _post("/v1/spend-request", {
        "agent_id": AGENT_ID,
        "declared_goal": "Track a flight",
        "amount_cents": 200,
        "currency": "USD",
        "vendor_url_or_name": "https://xK9mQpZr2aBcDeFgHiJkLmNoPqRsTuV.payments.io",
        "item_description": "Flight tracking service",
        "asset_type": "FIAT",
        "destination_address": "fiat-destination-acct-0001",
    })
    assert r.status_code == 403
    body = r.json()
    assert body["verdict"] == "MALICIOUS"
    assert "VENDOR_DOMAIN_PHISHING_PATTERN" in body["reasons"]


# ---------------------------------------------------------------------------
# MALICIOUS — stablecoin not allowed
# ---------------------------------------------------------------------------

def test_live_malicious_stablecoin_not_allowed() -> None:
    r = _post("/v1/spend-request", {
        "agent_id": AGENT_ID,
        "declared_goal": "Pay contractor for logo design",
        "amount_cents": 5000,
        "currency": "USD",
        "vendor_url_or_name": "contractor.eth",
        "item_description": "Logo design invoice",
        "asset_type": "STABLECOIN",
        "stablecoin_symbol": "USDT",
        "network": "ethereum",
        "destination_address": "0xabc1234567890abcdef",
    })
    assert r.status_code == 403
    body = r.json()
    assert body["verdict"] == "MALICIOUS"


# ---------------------------------------------------------------------------
# SUSPICIOUS — semantic mismatch (office supplies goal, crypto vendor)
# ---------------------------------------------------------------------------

def test_live_suspicious_semantic_mismatch() -> None:
    r = _post("/v1/spend-request", {
        "agent_id": AGENT_ID,
        "declared_goal": "Buy office supplies",
        "amount_cents": 150,
        "currency": "USD",
        "vendor_url_or_name": "binance.com",
        "item_description": "Token purchase",
        "asset_type": "FIAT",
        "destination_address": "fiat-destination-acct-0001",
    })
    assert r.status_code == 202
    body = r.json()
    assert body["verdict"] == "SUSPICIOUS"
    assert body["next_action"] == "AGENT_MUST_WAIT"
    assert "request_id" in body


# ---------------------------------------------------------------------------
# Idempotency — same key returns cached result
# ---------------------------------------------------------------------------

def test_live_idempotency_replay() -> None:
    payload = {
        "agent_id": AGENT_ID,
        "declared_goal": "Book flight JFK to LAX",
        "amount_cents": 100,
        "currency": "USD",
        "vendor_url_or_name": "delta.com",
        "item_description": "Economy seat JFK-LAX",
        "asset_type": "FIAT",
        "destination_address": "fiat-destination-acct-0001",
        "idempotency_key": "idem-test-live-001",
    }
    r1 = _post("/v1/spend-request", payload)
    r2 = _post("/v1/spend-request", payload)

    assert r1.status_code == r2.status_code
    assert r2.json()["idempotency_replay"] is True
    assert r2.json()["request_id"] == r1.json()["request_id"]


# ---------------------------------------------------------------------------
# Status poll — valid request_id returns status
# ---------------------------------------------------------------------------

def test_live_status_poll_after_safe() -> None:
    r = _post("/v1/spend-request", {
        "agent_id": AGENT_ID,
        "declared_goal": "Book flight JFK to LAX",
        "amount_cents": 100,
        "currency": "USD",
        "vendor_url_or_name": "delta.com",
        "item_description": "Economy seat JFK-LAX",
        "asset_type": "FIAT",
        "destination_address": "fiat-destination-acct-0001",
    })
    assert r.status_code == 200
    request_id = r.json()["request_id"]

    path = f"/v1/spend-request/{request_id}/status"
    body = b""
    headers = _sign("GET", path, body)
    status_r = httpx.get(f"{API_URL}{path}", headers=headers, timeout=30)

    assert status_r.status_code == 200
    assert status_r.json()["request_id"] == request_id
    assert status_r.json()["resolved"] is True


# ---------------------------------------------------------------------------
# Auth — bad signature is rejected
# ---------------------------------------------------------------------------

def test_live_bad_signature_rejected() -> None:
    payload = {
        "agent_id": AGENT_ID,
        "declared_goal": "Book flight",
        "amount_cents": 500,
        "currency": "USD",
        "vendor_url_or_name": "delta.com",
        "item_description": "Seat",
        "asset_type": "FIAT",
        "destination_address": "fiat-destination-acct-0001",
    }
    body = json.dumps(payload).encode()
    timestamp = datetime.now(timezone.utc).isoformat()
    headers = {
        "x-agent-id": AGENT_ID,
        "x-timestamp": timestamp,
        "x-signature": "invalidsignature",
        "content-type": "application/json",
    }
    r = httpx.post(f"{API_URL}/v1/spend-request", content=body, headers=headers, timeout=30)
    assert r.status_code == 401
