"""
Three comprehensive scenario tests covering every decision path in AgentShield.

  Test 1 — SAFE path
    • Stablecoin transaction that clears all three checks and executes immediately
    • Idempotency: replaying the same key returns the cached response, not a second execution
    • Suspended agent is rejected before checks run

  Test 2 — SUSPICIOUS / HITL path
    • Over-threshold spend creates PendingSpend + DashboardNotification
    • All DB state checked (PendingSpend, DashboardNotification, SpendAuditLog)
    • APPROVE via dashboard transitions all records
    • DENY via dashboard holds funds + records DENIED_BY_HUMAN audit
    • Double-resolve attempt returns 409

  Test 3 — MALICIOUS / hard-deny path
    • Vendor on blocklist → VENDOR_MATCHED_BLOCKLIST
    • Daily budget exceeded → BUDGET_DAILY_LIMIT_EXCEEDED
    • Network not in allowed list → NETWORK_NOT_ALLOWED
    • Stablecoin token not in allowed list → STABLECOIN_NOT_ALLOWED
    • Destination address on denylist → DESTINATION_DENYLISTED
    • mocked MISMATCH label → SEMANTIC_MISMATCH_HIGH
    • All produce 403, BLOCKED audit log
"""
import hashlib
import hmac as _hmac
import json
from collections import defaultdict
from datetime import datetime, timezone

import pytest  # noqa: F401
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, select

from app.core.config import get_settings
from app.db.postgres import engine
from app.db.redis import get_redis
from app.main import app
from app.models.agent import Agent
from app.models.dashboard_notification import DashboardNotification
from app.models.pending_spend import PendingSpend
from app.models.spend_audit_log import SpendAuditLog
from app.services.slm.client import AnthropicSemanticClient

AGENT_SECRET = "test-agent-secret"
WEBHOOK_SECRET = get_settings().webhook_hmac_secret


class FakeRedis:
    def __init__(self):
        self._values: dict[str, str] = {}
        self._counter = defaultdict(int)

    async def get(self, key):
        return self._values.get(key)

    async def set(self, key, value, ex=None, nx=False):
        if nx and key in self._values:
            return False
        self._values[key] = str(value)
        return True

    async def incr(self, key):
        self._counter[key] += 1
        self._values[key] = str(self._counter[key])
        return self._counter[key]

    async def incrby(self, key, amount):
        current = int(self._values.get(key, 0))
        new_val = current + int(amount)
        self._counter[key] = new_val
        self._values[key] = str(new_val)
        return new_val

    async def decrby(self, key, amount):
        current = int(self._values.get(key, 0))
        new_val = current - int(amount)
        self._counter[key] = new_val
        self._values[key] = str(new_val)
        return new_val

    async def eval(self, script, numkeys, *args):
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

    async def expire(self, key, ttl):
        return True

    async def delete(self, key):
        self._values.pop(key, None)
        self._counter.pop(key, None)
        return True

    def pipeline(self):
        return FakePipeline(self)


class FakePipeline:
    def __init__(self, redis: "FakeRedis"):
        self._redis = redis
        self._cmds: list = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        pass

    def incrby(self, key, amount):
        self._cmds.append(("incrby", key, amount))
        return self

    def expire(self, key, ttl):
        self._cmds.append(("expire", key, ttl))
        return self

    async def execute(self):
        results = []
        for cmd in self._cmds:
            if cmd[0] == "incrby":
                results.append(await self._redis.incrby(cmd[1], cmd[2]))
            elif cmd[0] == "expire":
                results.append(await self._redis.expire(cmd[1], cmd[2]))
        return results


def _reset_db():
    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)


def _seed_agent(**overrides) -> None:
    defaults = dict(
        agent_id="test_agent_001",
        status="ACTIVE",
        daily_budget_limit_cents=500_000,
        per_txn_auto_approve_limit_cents=10_000,
        hitl_required_over_cents=5_000,
        currency="USD",
        blocked_vendors=["badvendor.com"],
        allowed_stablecoins=["USDC"],
        allowed_networks=["base", "ethereum"],
        allowed_destination_addresses=[],
        blocked_destination_addresses=["0xdeadbeefdeadbeef0000000000000000deadbeef"],
        hmac_secret=AGENT_SECRET,
    )
    defaults.update(overrides)
    with Session(engine) as session:
        session.add(Agent(**defaults))
        session.commit()


def _sign_agent(body: dict, agent_id: str = "test_agent_001", path: str = "/v1/spend-request") -> tuple[bytes, dict]:
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


def _mock_semantic(label: str, score: int = 10):
    async def _impl(self, **kwargs):
        return {"alignment_label": label, "risk_score": score, "reason_codes": [f"TEST_{label}"]}
    AnthropicSemanticClient.semantic_alignment = _impl


_STABLECOIN = dict(
    agent_id="test_agent_001",
    declared_goal="Book flight JFK to LAX for company offsite",
    amount_cents=2_000,
    currency="USD",
    asset_type="STABLECOIN",
    stablecoin_symbol="USDC",
    network="base",
    destination_address="0x742d35Cc6634C0532925a3b8D4C9A6b52E7A1f1",
    vendor_url_or_name="delta.com",
    item_description="Flight booking",
    idempotency_key="test-safe-001",
)


# ===========================================================================
# TEST 1 — SAFE PATH
# ===========================================================================

class TestSafePath:

    def setup_method(self):
        _reset_db()
        _seed_agent()
        self.redis = FakeRedis()
        app.dependency_overrides[get_redis] = lambda: self.redis
        _mock_semantic("ALIGNED")

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_safe_stablecoin_executes_immediately(self):
        content, headers = _sign_agent(_STABLECOIN)
        with TestClient(app) as client:
            resp = client.post("/v1/spend-request", content=content, headers=headers)

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "APPROVED_EXECUTED"
        assert body["verdict"] == "SAFE"
        assert body["approved_amount_cents"] == 2_000

        reasons = body["reasons"]
        assert "BUDGET_WITHIN_LIMIT" in reasons
        assert "VENDOR_ALLOWED" in reasons
        assert "SEMANTIC_ALIGNMENT_HIGH" in reasons
        assert "agent_feedback" in body
        assert body["agent_feedback"]["verdict_summary"]["safe_to_execute"] is True
        assert "check_a_quantitative" in body["agent_feedback"]["checks"]

        with Session(engine) as session:
            log = session.exec(
                select(SpendAuditLog).where(SpendAuditLog.agent_id == "test_agent_001")
            ).first()
        assert log is not None
        assert log.status == "APPROVED_EXECUTED"
        assert log.verdict == "SAFE"

    def test_idempotency_returns_cached_response_without_second_execution(self):
        content, headers = _sign_agent(_STABLECOIN)
        with TestClient(app) as client:
            r1 = client.post("/v1/spend-request", content=content, headers=headers)
            content2, headers2 = _sign_agent(_STABLECOIN)
            r2 = client.post("/v1/spend-request", content=content2, headers=headers2)

        assert r1.status_code == 200
        assert r2.status_code == 200
        assert r1.json()["request_id"] == r2.json()["request_id"]
        assert r1.json()["idempotency_replay"] is False
        assert r2.json()["idempotency_replay"] is True
        assert r2.headers["x-idempotency-replay"] == "true"
        assert r2.headers["x-original-request-id"] == r2.json()["request_id"]

        with Session(engine) as session:
            logs = session.exec(
                select(SpendAuditLog).where(SpendAuditLog.agent_id == "test_agent_001")
            ).all()
        assert len(logs) == 1, f"Expected 1 audit record, got {len(logs)}"

    def test_suspended_agent_is_rejected_before_checks(self):
        with Session(engine) as session:
            agent = session.exec(select(Agent).where(Agent.agent_id == "test_agent_001")).first()
            agent.status = "SUSPENDED"
            session.add(agent)
            session.commit()

        content, headers = _sign_agent(_STABLECOIN)
        with TestClient(app) as client:
            resp = client.post("/v1/spend-request", content=content, headers=headers)

        assert resp.status_code == 403
        assert "not active" in resp.json()["detail"].lower()

    def test_mismatched_agent_id_is_rejected(self):
        payload = {**_STABLECOIN, "agent_id": "agt_does_not_exist"}
        content, headers = _sign_agent(payload)
        with TestClient(app) as client:
            resp = client.post("/v1/spend-request", content=content, headers=headers)
        assert resp.status_code == 403


# ===========================================================================
# TEST 2 — SUSPICIOUS / HITL PATH
# ===========================================================================

class TestSuspiciousHitlPath:

    def setup_method(self):
        _reset_db()
        _seed_agent()
        self.redis = FakeRedis()
        app.dependency_overrides[get_redis] = lambda: self.redis
        _mock_semantic("WEAK", 60)

    def teardown_method(self):
        app.dependency_overrides.clear()

    def _over_threshold_spend(self, client, idempotency_key="susp-001"):
        body = {**_STABLECOIN, "amount_cents": 8_000, "idempotency_key": idempotency_key}
        content, headers = _sign_agent(body)
        return client.post("/v1/spend-request", content=content, headers=headers)

    def test_suspicious_returns_202_with_correct_state(self):
        with TestClient(app) as client:
            resp = self._over_threshold_spend(client)

        assert resp.status_code == 202, resp.text
        body = resp.json()
        assert body["status"] == "PENDING_HITL"
        assert body["verdict"] == "SUSPICIOUS"
        assert body["next_action"] == "AGENT_MUST_WAIT"
        assert "AMOUNT_OVER_AUTO_APPROVAL_THRESHOLD" in body["reasons"]
        assert "agent_feedback" in body
        assert body["agent_feedback"]["verdict_summary"]["human_review_required"] is True

        request_id = body["request_id"]
        with Session(engine) as session:
            pending = session.exec(
                select(PendingSpend).where(PendingSpend.request_id == request_id)
            ).first()
            assert pending is not None
            assert pending.state == "WAITING_HUMAN"

            notif = session.exec(
                select(DashboardNotification).where(DashboardNotification.request_id == request_id)
            ).first()
            assert notif is not None
            assert notif.status == "OPEN"

            audit = session.exec(
                select(SpendAuditLog).where(SpendAuditLog.request_id == request_id)
            ).first()
            assert audit is not None
            assert audit.status == "PENDING_HITL"
            assert audit.verdict == "SUSPICIOUS"

    def test_approve_transitions_all_records(self):
        with TestClient(app) as client:
            spend = self._over_threshold_spend(client)
            assert spend.status_code == 202
            request_id = spend.json()["request_id"]

            resolve_body = {"decision": "APPROVE", "resolver_id": "ops_user_1", "channel": "dashboard"}
            r_content, r_headers = _sign_webhook(resolve_body, f"/v1/hitl/resolve/{request_id}")
            resolve = client.post(f"/v1/hitl/resolve/{request_id}", content=r_content, headers=r_headers)

        assert resolve.status_code == 200, resolve.text
        assert resolve.json()["decision"] == "APPROVE"

        with Session(engine) as session:
            pending = session.exec(
                select(PendingSpend).where(PendingSpend.request_id == request_id)
            ).first()
            assert pending.state == "APPROVED"

            notif = session.exec(
                select(DashboardNotification).where(DashboardNotification.request_id == request_id)
            ).first()
            assert notif.status == "RESOLVED"

            all_logs = session.exec(
                select(SpendAuditLog).where(SpendAuditLog.agent_id == "test_agent_001")
            ).all()
            statuses = {log.status for log in all_logs}
            assert "APPROVED_BY_HUMAN_EXECUTED" in statuses

    def test_deny_records_denial(self):
        with TestClient(app) as client:
            spend = self._over_threshold_spend(client, idempotency_key="susp-deny-001")
            assert spend.status_code == 202
            request_id = spend.json()["request_id"]

            resolve_body = {"decision": "DENY", "resolver_id": "ops_user_2", "channel": "dashboard"}
            r_content, r_headers = _sign_webhook(resolve_body, f"/v1/hitl/resolve/{request_id}")
            resolve = client.post(f"/v1/hitl/resolve/{request_id}", content=r_content, headers=r_headers)

        assert resolve.status_code == 200
        assert resolve.json()["decision"] == "DENY"

        with Session(engine) as session:
            pending = session.exec(
                select(PendingSpend).where(PendingSpend.request_id == request_id)
            ).first()
            assert pending.state == "DENIED"

            all_logs = session.exec(
                select(SpendAuditLog).where(SpendAuditLog.agent_id == "test_agent_001")
            ).all()
            assert "DENIED_BY_HUMAN" in {log.status for log in all_logs}

    def test_double_resolve_returns_409(self):
        with TestClient(app) as client:
            spend = self._over_threshold_spend(client, idempotency_key="susp-dbl-001")
            request_id = spend.json()["request_id"]
            resolve_body = {"decision": "APPROVE", "resolver_id": "ops_user_1", "channel": "dashboard"}

            r1_content, r1_headers = _sign_webhook(resolve_body, f"/v1/hitl/resolve/{request_id}")
            r1 = client.post(f"/v1/hitl/resolve/{request_id}", content=r1_content, headers=r1_headers)
            r2_content, r2_headers = _sign_webhook(resolve_body, f"/v1/hitl/resolve/{request_id}")
            r2 = client.post(f"/v1/hitl/resolve/{request_id}", content=r2_content, headers=r2_headers)

        assert r1.status_code == 200
        assert r2.status_code == 409


# ===========================================================================
# TEST 3 — MALICIOUS / HARD-DENY PATH
# ===========================================================================

class TestMaliciousPath:

    def setup_method(self):
        _reset_db()
        _seed_agent()
        self.redis = FakeRedis()
        app.dependency_overrides[get_redis] = lambda: self.redis
        _mock_semantic("ALIGNED")

    def teardown_method(self):
        app.dependency_overrides.clear()

    def _send(self, payload):
        content, headers = _sign_agent(payload)
        with TestClient(app) as client:
            return client.post("/v1/spend-request", content=content, headers=headers)

    def _assert_blocked(self, resp, expected_reason: str):
        assert resp.status_code == 403, f"Expected 403, got {resp.status_code}: {resp.text}"
        body = resp.json()
        assert body["status"] == "BLOCKED"
        assert body["verdict"] == "MALICIOUS"
        assert body["next_action"] == "DO_NOT_RETRY"
        assert expected_reason in body["reasons"]
        assert "agent_feedback" in body
        assert body["agent_feedback"]["verdict_summary"]["hard_deny_detected"] is True
        with Session(engine) as session:
            log = session.exec(
                select(SpendAuditLog).where(SpendAuditLog.request_id == body["request_id"])
            ).first()
        assert log is not None
        assert log.status == "BLOCKED"
        assert log.verdict == "MALICIOUS"

    def test_vendor_on_blocklist_is_hard_denied(self):
        payload = {**_STABLECOIN, "vendor_url_or_name": "badvendor.com", "idempotency_key": "mal-vendor-001"}
        self._assert_blocked(self._send(payload), "VENDOR_MATCHED_BLOCKLIST")

    def test_vendor_partial_match_in_url_is_hard_denied(self):
        payload = {**_STABLECOIN, "vendor_url_or_name": "https://badvendor.com/checkout", "idempotency_key": "mal-vendor-url-001"}
        self._assert_blocked(self._send(payload), "VENDOR_MATCHED_BLOCKLIST")

    def test_daily_budget_exceeded_is_hard_denied(self):
        _reset_db()
        _seed_agent(daily_budget_limit_cents=1_000)
        date_key = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self.redis._values[f"budget:daily:test_agent_001:STABLECOIN:{date_key}"] = "900"
        payload = {**_STABLECOIN, "amount_cents": 200, "idempotency_key": "mal-budget-001"}
        self._assert_blocked(self._send(payload), "BUDGET_DAILY_LIMIT_EXCEEDED")

    def test_network_not_in_allowed_list_is_hard_denied(self):
        payload = {**_STABLECOIN, "network": "polygon", "idempotency_key": "mal-network-001"}
        self._assert_blocked(self._send(payload), "NETWORK_NOT_ALLOWED")

    def test_token_not_in_allowed_list_is_hard_denied(self):
        payload = {**_STABLECOIN, "stablecoin_symbol": "USDT", "idempotency_key": "mal-token-001"}
        self._assert_blocked(self._send(payload), "STABLECOIN_NOT_ALLOWED")

    def test_destination_on_denylist_is_hard_denied(self):
        payload = {
            **_STABLECOIN,
            "destination_address": "0xdeadbeefdeadbeef0000000000000000deadbeef",
            "idempotency_key": "mal-denylist-001",
        }
        self._assert_blocked(self._send(payload), "DESTINATION_DENYLISTED")

    def test_semantic_mismatch_is_hard_denied(self):
        _mock_semantic("MISMATCH", 90)
        payload = {**_STABLECOIN, "idempotency_key": "mal-mismatch-001"}
        self._assert_blocked(self._send(payload), "SEMANTIC_MISMATCH_HIGH")

    def test_multiple_hard_deny_conditions_all_present(self):
        payload = {
            **_STABLECOIN,
            "vendor_url_or_name": "badvendor.com",
            "network": "polygon",
            "idempotency_key": "mal-multi-001",
        }
        resp = self._send(payload)
        assert resp.status_code == 403
        reasons = resp.json()["reasons"]
        assert "VENDOR_MATCHED_BLOCKLIST" in reasons
        assert "NETWORK_NOT_ALLOWED" in reasons
