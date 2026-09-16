"""Adaptive velocity baselines through the HTTP surface: executed spends feed
the baseline, and a learned outlier pauses for HITL (202) without blocking."""
import json
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.api.v1.routes import spend as spend_routes
from app.api.v1.routes.spend import _build_agent_feedback, _is_high_risk_suspicious
from app.db.postgres import engine
from app.db.redis import get_redis
from app.main import app
from app.models import PendingSpend
from app.policy.checks.quantitative import adaptive_baseline_key
from tests.integration.test_spend_hitl_flow import (
    FakePipeline,
    FakeRedis,
    _mock_semantic,
    _reset_db,
    _seed_agent,
    _sign_agent,
    _sign_webhook,
)

SPEND_BODY = {
    "agent_id": "agent_demo",
    "declared_goal": "Pay hosting provider",
    "amount_cents": 1200,
    "currency": "USD",
    "asset_type": "STABLECOIN",
    "stablecoin_symbol": "USDC",
    "network": "base",
    "destination_address": "0x1234567890abcdef",
    "vendor_url_or_name": "Render.com",
    "item_description": "Monthly hosting",
}


class ZsetRedis(FakeRedis):
    """FakeRedis plus just enough sorted-set support for the baseline store."""

    def __init__(self) -> None:
        super().__init__()
        self.zsets: dict[str, dict[str, float]] = {}
        self.expirations: dict[str, int] = {}

    async def zadd(self, key: str, mapping: dict, nx: bool = False):
        bucket = self.zsets.setdefault(key, {})
        added = 0
        for member, score in mapping.items():
            if nx and member in bucket:
                continue
            if member not in bucket:
                added += 1
            bucket[member] = float(score)
        return added

    async def zrangebyscore(self, key: str, lo, hi, withscores: bool = False):
        items = sorted(self.zsets.get(key, {}).items(), key=lambda kv: kv[1])
        items = [(m, s) for m, s in items if lo <= s <= hi]
        return items if withscores else [m for m, _ in items]

    async def zremrangebyscore(self, key: str, lo, hi):
        lo_f = float("-inf") if lo == "-inf" else float(lo)
        hi_f = float("inf") if hi == "+inf" else float(hi)
        bucket = self.zsets.get(key, {})
        doomed = [m for m, s in bucket.items() if lo_f <= s <= hi_f]
        for m in doomed:
            del bucket[m]
        return len(doomed)

    async def zremrangebyrank(self, key: str, start: int, stop: int):
        bucket = self.zsets.get(key, {})
        ordered = [m for m, _ in sorted(bucket.items(), key=lambda kv: kv[1])]
        n = len(ordered)
        start = start + n if start < 0 else start
        stop = stop + n if stop < 0 else stop
        doomed = ordered[max(start, 0):stop + 1] if stop >= start else []
        for m in doomed:
            del bucket[m]
        return len(doomed)

    async def expire(self, key: str, ttl: int):
        self.expirations[key] = ttl
        return True

    def pipeline(self, transaction: bool = True) -> "ZsetPipeline":
        return ZsetPipeline(self)


class ZsetPipeline(FakePipeline):
    def __getattr__(self, name):
        if name.startswith("z"):
            def _queue(*args, **kwargs):
                self._cmds.append((name, args, kwargs))
                return self
            return _queue
        raise AttributeError(name)

    async def execute(self) -> list:
        results = []
        for cmd in self._cmds:
            if cmd[0] == "incrby":
                results.append(await self._redis.incrby(cmd[1], cmd[2]))
            elif cmd[0] == "expire":
                results.append(await self._redis.expire(cmd[1], cmd[2]))
            else:
                results.append(await getattr(self._redis, cmd[0])(*cmd[1], **cmd[2]))
        return results


def _members(redis: ZsetRedis, key: str) -> list[dict]:
    return [json.loads(m) for m in redis.zsets.get(key, {})]


def _post_spend(client: TestClient, body: dict = SPEND_BODY):
    content, headers = _sign_agent(body)
    return client.post("/v1/spend-request", content=content, headers=headers)


def test_safe_spend_records_baseline_observation() -> None:
    _reset_db()
    _seed_agent()
    redis = ZsetRedis()
    app.dependency_overrides[get_redis] = lambda: redis
    _mock_semantic("ALIGNED")
    try:
        with TestClient(app) as client:
            resp = _post_spend(client)
        assert resp.status_code == 200
        request_id = resp.json()["request_id"]
        assert "ADAPTIVE_BASELINE_INSUFFICIENT_HISTORY" in resp.json()["reasons"]

        key = adaptive_baseline_key("agent_demo", "STABLECOIN", "USD")
        members = _members(redis, key)
        assert members == [{"amount_cents": 1200, "request_id": request_id, "vendor": "render.com"}]
        assert redis.expirations[key] > 30 * 86400
        feedback = resp.json()["agent_feedback"]
        assert feedback["checks"]["check_a_quantitative"]["context"]["adaptive_baseline"]["evaluated"] is False
    finally:
        app.dependency_overrides.clear()


def test_hitl_approval_records_observation_but_denial_does_not() -> None:
    _reset_db()
    _seed_agent()
    redis = ZsetRedis()
    app.dependency_overrides[get_redis] = lambda: redis
    _mock_semantic("WEAK", 40)
    key = adaptive_baseline_key("agent_demo", "STABLECOIN", "USD")
    try:
        with TestClient(app) as client:
            approve_id = _post_spend(client).json()["request_id"]
            deny_body = {**SPEND_BODY, "item_description": "Second hosting invoice"}
            deny_id = _post_spend(client, deny_body).json()["request_id"]
            assert _members(redis, key) == []

            for request_id, decision in ((deny_id, "DENY"), (approve_id, "APPROVE")):
                body = {"decision": decision, "resolver_id": "ops_user_1", "channel": "dashboard"}
                content, headers = _sign_webhook(body, f"/v1/hitl/resolve/{request_id}")
                resp = client.post(f"/v1/hitl/resolve/{request_id}", content=content, headers=headers)
                assert resp.status_code == 200

        members = _members(redis, key)
        assert [m["request_id"] for m in members] == [approve_id]
        assert members[0]["amount_cents"] == 1200
        with Session(engine) as session:
            states = {
                p.request_id: p.state
                for p in session.exec(select(PendingSpend)).all()
            }
        assert states == {approve_id: "APPROVED", deny_id: "DENIED"}
    finally:
        app.dependency_overrides.clear()


def test_learned_outlier_pauses_for_hitl_with_202() -> None:
    _reset_db()
    _seed_agent(per_txn_auto_approve_limit_cents=10_000_000, daily_budget_limit_cents=10_000_000)
    redis = ZsetRedis()
    app.dependency_overrides[get_redis] = lambda: redis
    _mock_semantic("ALIGNED")
    key = adaptive_baseline_key("agent_demo", "STABLECOIN", "USD")
    now = datetime.now(timezone.utc).timestamp()
    history = {
        json.dumps({"request_id": f"h-{d}-{h}", "amount_cents": 1200, "vendor": "render.com"}):
            now - d * 86400 - h * 3600
        for d in range(1, 5)
        for h in range(6)
    }
    redis.zsets[key] = history
    try:
        with TestClient(app) as client:
            normal = _post_spend(client)
            assert normal.status_code == 200
            assert "ADAPTIVE_BASELINE_NORMAL" in normal.json()["reasons"]

            outlier = _post_spend(client, {**SPEND_BODY, "amount_cents": 120_000})
        assert outlier.status_code == 202
        body = outlier.json()
        assert body["verdict"] == "SUSPICIOUS"
        assert "ADAPTIVE_AMOUNT_OUTLIER" in body["reasons"]
        feedback = body["agent_feedback"]
        assert "ADAPTIVE_AMOUNT_OUTLIER" in feedback["picked_up"]["high_risk_flags"]
        assert "check_a_quantitative" in feedback["picked_up"]["checks_triggered"]
        assert "ADAPTIVE_AMOUNT_OUTLIER" in feedback["checks"]["check_a_quantitative"]["reasons"]
        signal = feedback["checks"]["check_a_quantitative"]["context"]["adaptive_baseline"]["signals"]["amount"]
        assert signal["outlier"] is True

        # The paused spend is not learned from; only the executed one was.
        learned = [m["request_id"] for m in _members(redis, key) if not m["request_id"].startswith("h-")]
        assert learned == [normal.json()["request_id"]]
        with Session(engine) as session:
            pending = session.exec(
                select(PendingSpend).where(PendingSpend.request_id == body["request_id"])
            ).first()
            assert pending is not None and pending.state == "WAITING_HUMAN"
    finally:
        app.dependency_overrides.clear()


def test_baseline_failure_does_not_fail_the_spend(monkeypatch) -> None:
    _reset_db()
    _seed_agent()
    redis = ZsetRedis()

    async def _boom(*_args, **_kwargs):
        raise RuntimeError("redis down")

    monkeypatch.setattr(spend_routes, "record_adaptive_observation", _boom)
    app.dependency_overrides[get_redis] = lambda: redis
    _mock_semantic("ALIGNED")
    try:
        with TestClient(app) as client:
            resp = _post_spend(client)
        assert resp.status_code == 200
        assert resp.json()["status"] == "APPROVED_EXECUTED"
    finally:
        app.dependency_overrides.clear()


def test_adaptive_outlier_reasons_are_high_risk_and_grouped_under_check_a() -> None:
    class _Tri:
        quantitative_result = {}
        policy_result = {}
        semantic_result = {}
        goal_drift_result = {}

    outliers = [
        "ADAPTIVE_AMOUNT_OUTLIER",
        "ADAPTIVE_DAILY_SPEND_OUTLIER",
        "ADAPTIVE_HOURLY_RATE_OUTLIER",
        "ADAPTIVE_VENDOR_DIVERSITY_OUTLIER",
    ]
    for reason in outliers:
        assert _is_high_risk_suspicious([reason]) is True
    assert _is_high_risk_suspicious(["ADAPTIVE_BASELINE_NORMAL"]) is False
    assert _is_high_risk_suspicious(["ADAPTIVE_BASELINE_INSUFFICIENT_HISTORY"]) is False

    reasons = ["BUDGET_WITHIN_LIMIT", *outliers, "ADAPTIVE_BASELINE_NORMAL"]
    feedback = _build_agent_feedback(verdict="SUSPICIOUS", reasons=reasons, tri=_Tri())
    assert feedback["checks"]["check_a_quantitative"]["reasons"] == reasons
    assert feedback["picked_up"]["high_risk_flags"] == outliers
    assert feedback["reason_counts"]["matched_known_reasons"] == len(reasons)
