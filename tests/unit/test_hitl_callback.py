import hashlib
import hmac
import json
from datetime import datetime, timezone

import httpx
import pytest

from app.core.config import get_settings
from app.services.hitl.callback import (
    build_callback_body,
    deliver_verdict_callback,
    is_ssrf_blocked,
    sign_callback,
)

CALLBACK_URL = "http://127.0.0.1:9099/callback"
SECRET = "test-agent-hmac-secret"


@pytest.fixture
def dev_settings(monkeypatch):
    """Force APP_ENV=dev so loopback callback URLs pass the SSRF check."""
    monkeypatch.setenv("APP_ENV", "dev")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def fast_retries(monkeypatch):
    """Collapse retry backoff to zero so retry tests run instantly."""
    monkeypatch.setattr("app.services.hitl.callback._RETRY_DELAYS_SECONDS", (0, 0))


def _handler_sequence(statuses):
    """MockTransport handler returning the given status codes in order,
    recording every request received."""
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(statuses[min(len(calls) - 1, len(statuses) - 1)])

    return handler, calls


# ── build_callback_body ──────────────────────────────────────────────────────

def test_build_callback_body_approve():
    resolved = datetime(2026, 5, 20, 12, 0, tzinfo=timezone.utc)
    body = build_callback_body("req_abc", "APPROVE", resolved)
    assert body["request_id"] == "req_abc"
    assert body["status"] == "APPROVED_BY_HUMAN_EXECUTED"
    assert body["verdict"] == "SAFE"
    assert body["decision"] == "APPROVE"
    assert body["resolved"] is True
    assert body["resolved_at"] == resolved.isoformat()
    assert body["delivery_id"].startswith("dlv_")


def test_build_callback_body_deny_without_resolved_at():
    body = build_callback_body("req_xyz", "DENY", None)
    assert body["status"] == "DENIED_BY_HUMAN"
    assert body["verdict"] == "MALICIOUS"
    assert body["decision"] == "DENY"
    assert body["resolved"] is True
    assert body["resolved_at"] is None


def test_build_callback_body_carries_poll_response_keys():
    """Agent handler logic is identical to polling — same keys the
    GET /v1/spend-request/{id}/status response carries."""
    body = build_callback_body("req_1", "APPROVE", None)
    assert {"request_id", "status", "verdict", "decision", "resolved"}.issubset(body)


# ── sign_callback ────────────────────────────────────────────────────────────

def test_sign_callback_matches_webhook_canonical_scheme():
    ts = "2026-05-20T12:00:00+00:00"
    payload = b'{"hello":"world"}'
    body_hash = hashlib.sha256(payload).hexdigest()
    canonical = "\n".join(["POST", "/callback", ts, body_hash])
    expected = hmac.new(SECRET.encode(), canonical.encode(), hashlib.sha256).hexdigest()
    assert sign_callback(SECRET, "/callback", ts, payload) == expected


def test_sign_callback_empty_path_defaults_to_slash():
    ts = "2026-05-20T12:00:00+00:00"
    assert sign_callback(SECRET, "", ts, b"{}") == sign_callback(SECRET, "/", ts, b"{}")


def test_sign_callback_differs_by_secret():
    ts = "2026-05-20T12:00:00+00:00"
    assert sign_callback(SECRET, "/cb", ts, b"{}") != sign_callback("other", "/cb", ts, b"{}")


# ── is_ssrf_blocked ──────────────────────────────────────────────────────────

def test_ssrf_blocks_private_range_even_in_dev(dev_settings):
    # Private (non-loopback) ranges stay blocked — only loopback gets the dev pass.
    assert is_ssrf_blocked("http://10.0.0.5/cb") is True


def test_ssrf_allows_public_address(dev_settings):
    assert is_ssrf_blocked("http://8.8.8.8/cb") is False


def test_ssrf_allows_loopback_in_dev(dev_settings):
    assert is_ssrf_blocked(CALLBACK_URL) is False


def test_ssrf_blocks_loopback_in_prod(monkeypatch):
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("WEBHOOK_HMAC_SECRET", "prod-secret-not-default")
    get_settings.cache_clear()
    try:
        assert is_ssrf_blocked(CALLBACK_URL) is True
    finally:
        get_settings.cache_clear()


# ── deliver_verdict_callback ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_deliver_succeeds_on_first_attempt(dev_settings):
    handler, calls = _handler_sequence([200])
    body = build_callback_body("req_1", "APPROVE", None)
    ok = await deliver_verdict_callback(
        CALLBACK_URL, body, SECRET, transport=httpx.MockTransport(handler)
    )
    assert ok is True
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_deliver_retries_on_5xx_then_succeeds(dev_settings, fast_retries):
    handler, calls = _handler_sequence([503, 503, 200])
    body = build_callback_body("req_2", "APPROVE", None)
    ok = await deliver_verdict_callback(
        CALLBACK_URL, body, SECRET, transport=httpx.MockTransport(handler)
    )
    assert ok is True
    assert len(calls) == 3


@pytest.mark.asyncio
async def test_deliver_gives_up_after_three_attempts(dev_settings, fast_retries):
    handler, calls = _handler_sequence([503])
    body = build_callback_body("req_3", "DENY", None)
    ok = await deliver_verdict_callback(
        CALLBACK_URL, body, SECRET, transport=httpx.MockTransport(handler)
    )
    assert ok is False
    assert len(calls) == 3


@pytest.mark.asyncio
async def test_deliver_does_not_retry_on_4xx(dev_settings, fast_retries):
    handler, calls = _handler_sequence([400])
    body = build_callback_body("req_4", "APPROVE", None)
    ok = await deliver_verdict_callback(
        CALLBACK_URL, body, SECRET, transport=httpx.MockTransport(handler)
    )
    assert ok is False
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_deliver_blocked_by_ssrf_makes_no_request(dev_settings):
    handler, calls = _handler_sequence([200])
    body = build_callback_body("req_5", "APPROVE", None)
    ok = await deliver_verdict_callback(
        "http://10.0.0.9/callback", body, SECRET, transport=httpx.MockTransport(handler)
    )
    assert ok is False
    assert len(calls) == 0


@pytest.mark.asyncio
async def test_deliver_signs_request_with_agent_secret(dev_settings):
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["content"] = request.content
        captured["timestamp"] = request.headers.get("x-webhook-timestamp")
        captured["signature"] = request.headers.get("x-webhook-signature")
        captured["delivery_id"] = request.headers.get("x-delivery-id")
        return httpx.Response(200)

    body = build_callback_body("req_6", "APPROVE", None)
    ok = await deliver_verdict_callback(
        CALLBACK_URL, body, SECRET, transport=httpx.MockTransport(handler)
    )
    assert ok is True

    expected = sign_callback(SECRET, "/callback", captured["timestamp"], captured["content"])
    assert captured["signature"] == f"sha256={expected}"
    assert captured["delivery_id"] == body["delivery_id"]
    # The bytes delivered are exactly the bytes that were signed.
    assert json.loads(captured["content"]) == body
