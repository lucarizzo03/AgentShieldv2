from collections import defaultdict

from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, select

from app.db.postgres import engine
from app.db.redis import get_redis
from app.main import app
from app.models import Agent, PendingSpend
from app.services.slm.client import LocalSlmClient


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
        self._counter[key] += amount
        self._values[key] = str(self._counter[key])
        return self._counter[key]

    async def expire(self, key: str, ttl: int):
        return True

    async def delete(self, key: str):
        self._values.pop(key, None)
        self._counter.pop(key, None)
        return True


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
        "hitl_phone_number": "+15555550100",
    }
    defaults.update(kwargs)
    with Session(engine) as session:
        session.add(Agent(**defaults))
        session.commit()


def _override_slm(label: str, score: int):
    async def _mock(self, **kwargs):
        return {"alignment_label": label, "risk_score": score, "reason_codes": ["TEST"]}

    LocalSlmClient.semantic_alignment = _mock


def test_safe_spend_request_approved() -> None:
    _reset_db()
    _seed_agent()
    fake_redis = FakeRedis()
    app.dependency_overrides[get_redis] = lambda: fake_redis
    _override_slm("ALIGNED", 10)

    with TestClient(app) as client:
        resp = client.post(
            "/v1/spend-request",
            headers={"x-agent-key": "local-dev-key"},
            json={
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
            },
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "APPROVED_EXECUTED"
    app.dependency_overrides.clear()


def test_suspicious_spend_goes_to_hitl_and_approves() -> None:
    _reset_db()
    _seed_agent(per_txn_auto_approve_limit_cents=1000)
    fake_redis = FakeRedis()
    app.dependency_overrides[get_redis] = lambda: fake_redis
    _override_slm("WEAK", 60)

    with TestClient(app) as client:
        spend_resp = client.post(
            "/v1/spend-request",
            headers={"x-agent-key": "local-dev-key"},
            json={
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
            },
        )
        assert spend_resp.status_code == 202
        request_id = spend_resp.json()["request_id"]
        resolve_resp = client.post(
            f"/v1/hitl/resolve/{request_id}",
            headers={"x-webhook-signature": "sig_ok"},
            json={
                "decision": "APPROVE",
                "resolver_id": "ops_user_1",
                "channel": "sms",
            },
        )
    assert resolve_resp.status_code == 200
    assert resolve_resp.json()["payment"]["executed"] is True
    with Session(engine) as session:
        pending = session.exec(select(PendingSpend).where(PendingSpend.request_id == request_id)).first()
        assert pending is not None
        assert pending.state == "APPROVED"
    app.dependency_overrides.clear()


def test_malicious_spend_blocked() -> None:
    _reset_db()
    _seed_agent(blocked_vendors=["badmarket"])
    fake_redis = FakeRedis()
    app.dependency_overrides[get_redis] = lambda: fake_redis
    _override_slm("ALIGNED", 10)

    with TestClient(app) as client:
        resp = client.post(
            "/v1/spend-request",
            headers={"x-agent-key": "local-dev-key"},
            json={
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
            },
        )
    assert resp.status_code == 403
    assert resp.json()["status"] == "BLOCKED"
    app.dependency_overrides.clear()

