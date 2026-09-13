"""Infrastructure failures must be reported as such, not as a verdict.

A Redis or Postgres outage previously surfaced as a bare 500, which an agent
cannot distinguish from a denial.
"""
import hashlib
import hmac as _hmac
import json
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlmodel import Session, SQLModel

from app.db.postgres import engine
from app.db.redis import get_redis
from app.main import app
from app.models import Agent

AGENT_SECRET = "test-agent-secret"


class BrokenRedis:
    """Every command fails the way an unreachable Redis does."""

    async def get(self, *_args, **_kwargs):
        raise RedisConnectionError("redis is down")

    async def set(self, *_args, **_kwargs):
        raise RedisConnectionError("redis is down")

    async def eval(self, *_args, **_kwargs):
        raise RedisConnectionError("redis is down")

    async def delete(self, *_args, **_kwargs):
        raise RedisConnectionError("redis is down")

    async def expire(self, *_args, **_kwargs):
        raise RedisConnectionError("redis is down")


def _seed_agent() -> None:
    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Agent(
            agent_id="agent_dep",
            status="ACTIVE",
            daily_budget_limit_cents=100_000,
            per_txn_auto_approve_limit_cents=10_000,
            currency="USD",
            blocked_vendors=[],
            allowed_stablecoins=["USDC"],
            allowed_networks=["base"],
            allowed_destination_addresses=[],
            blocked_destination_addresses=[],
            hmac_secret=AGENT_SECRET,
        ))
        session.commit()


def _sign(body: dict) -> tuple[bytes, dict]:
    body_bytes = json.dumps(body, separators=(",", ":")).encode()
    ts = datetime.now(timezone.utc).isoformat()
    canonical = "\n".join([
        "POST", "/v1/spend-request", ts,
        hashlib.sha256(body_bytes).hexdigest(), "agent_dep",
    ])
    sig = _hmac.new(AGENT_SECRET.encode(), canonical.encode(), hashlib.sha256).hexdigest()
    return body_bytes, {
        "x-agent-id": "agent_dep",
        "x-timestamp": ts,
        "x-signature": f"sha256={sig}",
        "Content-Type": "application/json",
    }


_BODY = {
    "agent_id": "agent_dep",
    "declared_goal": "Pay hosting provider",
    "amount_cents": 1200,
    "currency": "USD",
    "asset_type": "STABLECOIN",
    "stablecoin_symbol": "USDC",
    "network": "base",
    "destination_address": "0x1234567890abcdef",
    "vendor_url_or_name": "render.com",
    "item_description": "Monthly hosting",
}


def test_redis_outage_returns_503_not_a_verdict() -> None:
    _seed_agent()
    app.dependency_overrides[get_redis] = lambda: BrokenRedis()

    content, headers = _sign(_BODY)
    with TestClient(app) as client:
        resp = client.post("/v1/spend-request", content=content, headers=headers)

    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "ENGINE_UNAVAILABLE"
    assert body["block_code"] == "ENGINE_DEPENDENCY_UNAVAILABLE"
    assert body["verdict"] is None
    assert body["next_action"] == "RETRY_WITH_BACKOFF"
    assert body["dependency"] == "redis"
    assert resp.headers["retry-after"] == "5"

    app.dependency_overrides.clear()
