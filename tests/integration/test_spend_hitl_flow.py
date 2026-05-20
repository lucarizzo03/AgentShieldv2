import hashlib
import hmac as _hmac
import json
from collections import defaultdict
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, select

from app.core.config import get_settings
from app.db.postgres import engine
from app.db.redis import get_redis
from app.main import app
from app.api.v1.schemas.spend import HitlChannel, SpendPendingResponse
from app.models import Agent, PendingSpend
from app.models.dashboard_notification import DashboardNotification
from app.services.slm.client import AnthropicSemanticClient

AGENT_SECRET = "test-agent-secret"
WEBHOOK_SECRET = get_settings().webhook_hmac_secret


class FakeRedis:
    def __init__(self) -> None:
        self._values: dict[str, str] = {}
        self._counter = defaultdict(int)

    async def get(self, key: str):
        return self._values.get(key)

    async def set(self, key: str, value, ex=None, nx=False):
        if nx and key in self._values:
            return False
        self._values[key] = str(value)
        return True

    async def incr(self, key: str):
        self._counter[key] += 1
        self._values[key] = str(self._counter[key])
        return self._counter[key]

    async def incrby(self, key: str, amount: int):
        current = int(self._values.get(key, 0))
        new_val = current + int(amount)
        self._counter[key] = new_val
        self._values[key] = str(new_val)
        return new_val

    async def decrby(self, key: str, amount: int):
        current = int(self._values.get(key, 0))
        new_val = current - int(amount)
        self._counter[key] = new_val
        self._values[key] = str(new_val)
        return new_val

    async def eval(self, script: str, numkeys: int, *args):
        keys = list(args[:numkeys])
        argv = list(args[numkeys:])
        key = keys[0]
        if len(argv) == 3:
            # _CHECK_AND_RESERVE_BUDGET: argv = [amount_cents, limit_cents, ttl_seconds]
            amount = int(argv[0])
            limit = int(argv[1])
            current = int(self._values.get(key, 0))
            projected = current + amount
            if projected > limit:
                return [0, current, projected]
            new_val = current + amount
            self._counter[key] = new_val
            self._values[key] = str(new_val)
            return [1, current, projected]
        else:
            # _INCR_WITH_TTL: argv = [ttl_seconds]
            current = int(self._values.get(key, 0))
            new_val = current + 1
            self._counter[key] = new_val
            self._values[key] = str(new_val)
            return new_val

    async def expire(self, key: str, ttl: int):
        return True

    async def delete(self, key: str):
        self._values.pop(key, None)
        self._counter.pop(key, None)
        return True

    def pipeline(self) -> "FakePipeline":
        return FakePipeline(self)


class FakePipeline:
    def __init__(self, redis: "FakeRedis") -> None:
        self._redis = redis
        self._cmds: list = []

    async def __aenter__(self) -> "FakePipeline":
        return self

    async def __aexit__(self, *_) -> None:
        pass

    def incrby(self, key: str, amount: int) -> "FakePipeline":
        self._cmds.append(("incrby", key, amount))
        return self

    def expire(self, key: str, ttl: int) -> "FakePipeline":
        self._cmds.append(("expire", key, ttl))
        return self

    async def execute(self) -> list:
        results = []
        for cmd in self._cmds:
            if cmd[0] == "incrby":
                results.append(await self._redis.incrby(cmd[1], cmd[2]))
            elif cmd[0] == "expire":
                results.append(await self._redis.expire(cmd[1], cmd[2]))
        return results


def _mock_semantic(label: str, score: int = 10) -> None:
    async def _impl(self, **kwargs):
        return {"alignment_label": label, "risk_score": score, "reason_codes": ["TEST"]}
    AnthropicSemanticClient.semantic_alignment = _impl


def _reset_db() -> None:
    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)


def _seed_agent(**kwargs) -> None:
    defaults = {
        "agent_id": "agent_demo",
        "status": "ACTIVE",
        "daily_budget_limit_cents": 100_000,
        "per_txn_auto_approve_limit_cents": 10_000,
        "currency": "USD",
        "blocked_vendors": [],
        "allowed_stablecoins": ["USDC", "USDT"],
        "allowed_networks": ["base", "ethereum"],
        "allowed_destination_addresses": [],
        "blocked_destination_addresses": [],
        "hmac_secret": AGENT_SECRET,
    }
    defaults.update(kwargs)
    with Session(engine) as session:
        session.add(Agent(**defaults))
        session.commit()


def _sign_agent(body: dict, agent_id: str = "agent_demo", path: str = "/v1/spend-request") -> tuple[bytes, dict]:
    body_bytes = json.dumps(body, separators=(",", ":")).encode()
    ts = datetime.now(timezone.utc).isoformat()
    body_hash = hashlib.sha256(body_bytes).hexdigest()
    canonical = "\n".join(["POST", path, ts, body_hash, agent_id])
    sig = _hmac.new(AGENT_SECRET.encode(), canonical.encode(), hashlib.sha256).hexdigest()
    return body_bytes, {
        "x-agent-id": agent_id,
        "x-timestamp": ts,
        "x-signature": f"sha256={sig}",
        "Content-Type": "application/json",
    }


def _sign_webhook(body: dict, path: str) -> tuple[bytes, dict]:
    body_bytes = json.dumps(body, separators=(",", ":")).encode()
    ts = datetime.now(timezone.utc).isoformat()
    body_hash = hashlib.sha256(body_bytes).hexdigest()
    canonical = "\n".join(["POST", path, ts, body_hash])
    sig = _hmac.new(WEBHOOK_SECRET.encode(), canonical.encode(), hashlib.sha256).hexdigest()
    return body_bytes, {
        "x-webhook-timestamp": ts,
        "x-webhook-signature": f"sha256={sig}",
        "Content-Type": "application/json",
    }


def test_safe_spend_request_approved() -> None:
    _reset_db()
    _seed_agent()
    fake_redis = FakeRedis()
    app.dependency_overrides[get_redis] = lambda: fake_redis
    _mock_semantic("ALIGNED")

    body = {
        "agent_id": "agent_demo",
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
    content, headers = _sign_agent(body)
    with TestClient(app) as client:
        resp = client.post("/v1/spend-request", content=content, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "APPROVED_EXECUTED"
    app.dependency_overrides.clear()


def test_suspicious_spend_goes_to_hitl_and_approves() -> None:
    _reset_db()
    _seed_agent(per_txn_auto_approve_limit_cents=1000)
    fake_redis = FakeRedis()
    app.dependency_overrides[get_redis] = lambda: fake_redis
    _mock_semantic("ALIGNED")

    spend_body = {
        "agent_id": "agent_demo",
        "declared_goal": "Buy API credits for website launch",
        "amount_cents": 5000,
        "currency": "USD",
        "asset_type": "STABLECOIN",
        "stablecoin_symbol": "USDC",
        "network": "base",
        "destination_address": "0x1234567890abcdef",
        "vendor_url_or_name": "tempo",
        "item_description": "Agent credit top-up",
    }
    with TestClient(app) as client:
        content, headers = _sign_agent(spend_body)
        spend_resp = client.post("/v1/spend-request", content=content, headers=headers)
        assert spend_resp.status_code == 202
        pending_payload = SpendPendingResponse.model_validate(spend_resp.json())
        assert pending_payload.hitl.channel == HitlChannel.EMAIL_DASHBOARD
        request_id = spend_resp.json()["request_id"]

        with Session(engine) as session:
            notif = session.exec(
                select(DashboardNotification).where(DashboardNotification.request_id == request_id)
            ).first()
            assert notif is not None
            assert notif.status == "OPEN"

        resolve_body = {"decision": "APPROVE", "resolver_id": "ops_user_1", "channel": "dashboard"}
        r_content, r_headers = _sign_webhook(resolve_body, f"/v1/hitl/resolve/{request_id}")
        resolve_resp = client.post(
            f"/v1/hitl/resolve/{request_id}", content=r_content, headers=r_headers
        )
    assert resolve_resp.status_code == 200

    with Session(engine) as session:
        pending = session.exec(select(PendingSpend).where(PendingSpend.request_id == request_id)).first()
        assert pending is not None
        assert pending.state == "APPROVED"
        notif = session.exec(
            select(DashboardNotification).where(DashboardNotification.request_id == request_id)
        ).first()
        assert notif is not None
        assert notif.status == "RESOLVED"
    app.dependency_overrides.clear()


def test_malicious_spend_blocked() -> None:
    _reset_db()
    _seed_agent(blocked_vendors=["badmarket"])
    fake_redis = FakeRedis()
    app.dependency_overrides[get_redis] = lambda: fake_redis
    _mock_semantic("ALIGNED")

    body = {
        "agent_id": "agent_demo",
        "declared_goal": "Purchase security tooling",
        "amount_cents": 1000,
        "currency": "USD",
        "asset_type": "STABLECOIN",
        "stablecoin_symbol": "USDC",
        "network": "base",
        "destination_address": "0x1234567890abcdef",
        "vendor_url_or_name": "badmarket.vip",
        "item_description": "Tool subscription",
    }
    content, headers = _sign_agent(body)
    with TestClient(app) as client:
        resp = client.post("/v1/spend-request", content=content, headers=headers)
    assert resp.status_code == 403
    assert resp.json()["status"] == "BLOCKED"
    app.dependency_overrides.clear()


def test_suspicious_spend_pushes_verdict_callback_on_resolve(monkeypatch) -> None:
    """When the spend request carries agent_callback_url, resolving the HITL
    request schedules a signed verdict callback to the agent."""
    _reset_db()
    _seed_agent(per_txn_auto_approve_limit_cents=1000)
    fake_redis = FakeRedis()
    app.dependency_overrides[get_redis] = lambda: fake_redis
    _mock_semantic("ALIGNED")

    delivered: dict = {}

    async def _fake_deliver(callback_url, body, secret, **kwargs):
        delivered["url"] = callback_url
        delivered["body"] = body
        delivered["secret"] = secret
        return True

    monkeypatch.setattr("app.api.v1.routes.hitl.deliver_verdict_callback", _fake_deliver)

    spend_body = {
        "agent_id": "agent_demo",
        "declared_goal": "Buy API credits for website launch",
        "amount_cents": 5000,
        "currency": "USD",
        "asset_type": "STABLECOIN",
        "stablecoin_symbol": "USDC",
        "network": "base",
        "destination_address": "0x1234567890abcdef",
        "vendor_url_or_name": "tempo",
        "item_description": "Agent credit top-up",
        "agent_callback_url": "http://127.0.0.1:9099/agentshield/callback",
    }
    with TestClient(app) as client:
        content, headers = _sign_agent(spend_body)
        spend_resp = client.post("/v1/spend-request", content=content, headers=headers)
        assert spend_resp.status_code == 202
        request_id = spend_resp.json()["request_id"]

        resolve_body = {"decision": "APPROVE", "resolver_id": "ops_user_1", "channel": "dashboard"}
        r_content, r_headers = _sign_webhook(resolve_body, f"/v1/hitl/resolve/{request_id}")
        resolve_resp = client.post(
            f"/v1/hitl/resolve/{request_id}", content=r_content, headers=r_headers
        )
        assert resolve_resp.status_code == 200

    # Background task runs after the response — verdict pushed to the agent,
    # signed with the agent's own HMAC secret.
    assert delivered["url"] == "http://127.0.0.1:9099/agentshield/callback"
    assert delivered["secret"] == AGENT_SECRET
    assert delivered["body"]["request_id"] == request_id
    assert delivered["body"]["decision"] == "APPROVE"
    assert delivered["body"]["status"] == "APPROVED_BY_HUMAN_EXECUTED"
    assert delivered["body"]["verdict"] == "SAFE"
    assert delivered["body"]["resolved"] is True
    app.dependency_overrides.clear()


def test_suspicious_spend_without_callback_url_skips_callback(monkeypatch) -> None:
    """No agent_callback_url means no callback is attempted — polling-only path."""
    _reset_db()
    _seed_agent(per_txn_auto_approve_limit_cents=1000)
    fake_redis = FakeRedis()
    app.dependency_overrides[get_redis] = lambda: fake_redis
    _mock_semantic("ALIGNED")

    called = False

    async def _fake_deliver(*args, **kwargs):
        nonlocal called
        called = True
        return True

    monkeypatch.setattr("app.api.v1.routes.hitl.deliver_verdict_callback", _fake_deliver)

    spend_body = {
        "agent_id": "agent_demo",
        "declared_goal": "Buy API credits for website launch",
        "amount_cents": 5000,
        "currency": "USD",
        "asset_type": "STABLECOIN",
        "stablecoin_symbol": "USDC",
        "network": "base",
        "destination_address": "0x1234567890abcdef",
        "vendor_url_or_name": "tempo",
        "item_description": "Agent credit top-up",
    }
    with TestClient(app) as client:
        content, headers = _sign_agent(spend_body)
        spend_resp = client.post("/v1/spend-request", content=content, headers=headers)
        request_id = spend_resp.json()["request_id"]

        resolve_body = {"decision": "DENY", "resolver_id": "ops_user_1", "channel": "dashboard"}
        r_content, r_headers = _sign_webhook(resolve_body, f"/v1/hitl/resolve/{request_id}")
        resolve_resp = client.post(
            f"/v1/hitl/resolve/{request_id}", content=r_content, headers=r_headers
        )
        assert resolve_resp.status_code == 200

    assert called is False
    app.dependency_overrides.clear()
