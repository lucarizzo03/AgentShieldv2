"""Outbound HITL verdict delivery.

When a SUSPICIOUS spend request is resolved by a human, AgentShield pushes the
verdict to the agent's ``agent_callback_url`` instead of waiting for the agent to
poll. The callback is signed with the agent's per-agent HMAC secret and retried
on transient failure. If delivery fails outright the verdict is still durable —
the agent can fall back to polling ``GET /v1/spend-request/{id}/status``.
"""
import asyncio
import hashlib
import hmac
import ipaddress
import json
import logging
import socket
from datetime import datetime, timezone
from urllib.parse import urlparse
from uuid import uuid4

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# 3 attempts total: initial + one retry after 5s + one retry after 15s (~20s window).
_RETRY_DELAYS_SECONDS = (5, 15)
_ATTEMPT_TIMEOUT_SECONDS = 10

_BLOCKED_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),
]


def is_ssrf_blocked(url: str) -> bool:
    """Reject callbacks aimed at private/loopback ranges.

    In ``dev`` a callback that resolves entirely to loopback is allowed, so a
    test agent running on the same machine can receive callbacks. Every other
    environment blocks loopback and private ranges.
    """
    settings = get_settings()
    try:
        hostname = urlparse(url).hostname
        if not hostname:
            return True
        resolved = socket.getaddrinfo(hostname, None)
        ips = [ipaddress.ip_address(sockaddr[0]) for *_, sockaddr in resolved]
        if not ips:
            return True
        if settings.app_env.lower() == "dev" and all(ip.is_loopback for ip in ips):
            return False
        return any(ip in net for ip in ips for net in _BLOCKED_NETWORKS)
    except Exception:
        return True


def build_callback_body(request_id: str, decision: str, resolved_at: datetime | None) -> dict:
    """Build the verdict payload pushed to the agent.

    Shape mirrors the ``GET /v1/spend-request/{id}/status`` poll response so an
    agent's handler logic is identical whether it polls or receives a callback.
    ``delivery_id`` is stable across retries so the agent can dedupe.
    """
    approved = decision == "APPROVE"
    return {
        "request_id": request_id,
        "status": "APPROVED_BY_HUMAN_EXECUTED" if approved else "DENIED_BY_HUMAN",
        "verdict": "SAFE" if approved else "MALICIOUS",
        "decision": decision,
        "resolved": True,
        "resolved_at": resolved_at.isoformat() if resolved_at else None,
        "delivery_id": f"dlv_{uuid4().hex[:18]}",
    }


def sign_callback(secret: str, path: str, timestamp: str, body: bytes) -> str:
    """HMAC-SHA256 over the canonical string AgentShield uses for webhooks:
    ``METHOD\\npath\\ntimestamp\\nsha256(body)``."""
    body_hash = hashlib.sha256(body).hexdigest()
    canonical = "\n".join(["POST", path or "/", timestamp, body_hash])
    return hmac.new(secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()


async def deliver_verdict_callback(
    callback_url: str,
    body: dict,
    secret: str,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> bool:
    """POST the verdict to the agent's callback URL, signed and retried.

    Returns ``True`` once the agent acknowledges with a 2xx. Retries on network
    errors and 5xx responses; gives up immediately on 4xx (a permanent client
    error — the agent rejected the callback). On total failure the verdict is
    still durable and the agent can fall back to polling.
    """
    request_id = body.get("request_id")
    if is_ssrf_blocked(callback_url):
        logger.warning(
            "HITL callback blocked (SSRF)", extra={"request_id": request_id, "url": callback_url}
        )
        return False

    body_bytes = json.dumps(body, separators=(",", ":")).encode()
    path = urlparse(callback_url).path

    for attempt in range(len(_RETRY_DELAYS_SECONDS) + 1):
        timestamp = datetime.now(timezone.utc).isoformat()
        signature = sign_callback(secret, path, timestamp, body_bytes)
        headers = {
            "Content-Type": "application/json",
            "x-webhook-timestamp": timestamp,
            "x-webhook-signature": f"sha256={signature}",
            "x-delivery-id": body.get("delivery_id", ""),
        }
        try:
            async with httpx.AsyncClient(transport=transport) as client:
                resp = await client.post(
                    callback_url,
                    content=body_bytes,
                    headers=headers,
                    timeout=_ATTEMPT_TIMEOUT_SECONDS,
                )
            if resp.status_code < 300:
                logger.info(
                    "HITL callback delivered",
                    extra={"request_id": request_id, "url": callback_url, "attempt": attempt + 1},
                )
                return True
            if resp.status_code < 500:
                logger.warning(
                    "HITL callback rejected by agent — not retrying",
                    extra={"request_id": request_id, "status": resp.status_code},
                )
                return False
            logger.warning(
                "HITL callback failed (server error)",
                extra={
                    "request_id": request_id,
                    "status": resp.status_code,
                    "attempt": attempt + 1,
                },
            )
        except httpx.HTTPError as exc:
            logger.warning(
                "HITL callback network error",
                extra={"request_id": request_id, "error": str(exc), "attempt": attempt + 1},
            )

        if attempt < len(_RETRY_DELAYS_SECONDS):
            await asyncio.sleep(_RETRY_DELAYS_SECONDS[attempt])

    logger.error(
        "HITL callback exhausted retries — agent must poll for the verdict",
        extra={"request_id": request_id, "url": callback_url},
    )
    return False
