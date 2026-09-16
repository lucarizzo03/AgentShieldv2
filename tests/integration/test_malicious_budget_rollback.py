"""
MALICIOUS verdict — budget reservation rollback.

Check A atomically reserves the amount against the agent's daily budget key
(and writes an outstanding-reservation marker) before the rest of the engine
runs.  When the final verdict is MALICIOUS the spend never executes, so the
reservation must be released: the budget counter goes back to its prior value
and the marker is dropped so the reconciler does not touch it.

    • Hard-deny (policy) MALICIOUS after a successful reservation  -> rolled back
    • Semantic-mismatch MALICIOUS after a successful reservation   -> rolled back
    • MALICIOUS because the budget itself was exceeded (no reserve) -> untouched
    • Rollback failure in Redis is logged and does not change the 403 response
    • SAFE contrast: the reservation is kept, only the marker is cleared
"""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.db.postgres import engine
from app.db.redis import get_redis
from app.main import app
from app.models.spend_audit_log import SpendAuditLog
from app.policy.checks.quantitative import RESERVATION_MARKER_PREFIX

from tests.integration.test_full_scenarios import (
    _STABLECOIN,
    FakeRedis,
    _mock_semantic,
    _reset_db,
    _seed_agent,
    _sign_agent,
)

AGENT_ID = "test_agent_001"


def _budget_key() -> str:
    date_key = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return f"budget:daily:{AGENT_ID}:STABLECOIN:USD:{date_key}"


def _marker_keys(redis: FakeRedis) -> list[str]:
    return [k for k in redis._values if k.startswith(RESERVATION_MARKER_PREFIX)]


class _FailingRollbackRedis(FakeRedis):
    """Redis whose budget-release script blows up, to exercise the error path."""

    async def eval(self, script, numkeys, *args):
        if "DECRBY" in script:
            raise ConnectionError("redis down during rollback")
        return await super().eval(script, numkeys, *args)


class TestMaliciousBudgetRollback:

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

    def _audit(self, request_id: str) -> SpendAuditLog:
        with Session(engine) as session:
            log = session.exec(
                select(SpendAuditLog).where(SpendAuditLog.request_id == request_id)
            ).first()
        assert log is not None
        return log

    def test_hard_deny_releases_reservation_and_marker(self):
        self.redis._values[_budget_key()] = "1000"
        payload = {**_STABLECOIN, "vendor_url_or_name": "badvendor.com", "idempotency_key": "rb-vendor-001"}

        resp = self._send(payload)

        assert resp.status_code == 403, resp.text
        assert resp.json()["verdict"] == "MALICIOUS"
        audit = self._audit(resp.json()["request_id"])
        # Check A did reserve before the policy check denied the spend...
        assert audit.quantitative_result["budget_reserved"] is True
        assert audit.quantitative_result["budget_exceeded"] is False
        # ...and the reservation was released afterwards.
        assert self.redis._values[_budget_key()] == "1000"
        assert _marker_keys(self.redis) == []

    def test_hard_deny_with_no_prior_spend_returns_budget_to_zero(self):
        payload = {**_STABLECOIN, "network": "polygon", "idempotency_key": "rb-network-001"}

        resp = self._send(payload)

        assert resp.status_code == 403, resp.text
        assert self.redis._values.get(_budget_key(), "0") == "0"
        assert _marker_keys(self.redis) == []

    def test_semantic_mismatch_releases_reservation(self):
        _mock_semantic("MISMATCH", 90)
        self.redis._values[_budget_key()] = "1000"
        payload = {**_STABLECOIN, "idempotency_key": "rb-semantic-001"}

        resp = self._send(payload)

        assert resp.status_code == 403, resp.text
        assert "SEMANTIC_MISMATCH_HIGH" in resp.json()["reasons"]
        audit = self._audit(resp.json()["request_id"])
        assert audit.quantitative_result["budget_reserved"] is True
        assert self.redis._values[_budget_key()] == "1000"
        assert _marker_keys(self.redis) == []

    def test_repeated_blocked_requests_do_not_accumulate_budget(self):
        self.redis._values[_budget_key()] = "1000"
        for i in range(3):
            payload = {**_STABLECOIN, "vendor_url_or_name": "badvendor.com", "idempotency_key": f"rb-repeat-{i}"}
            assert self._send(payload).status_code == 403
        assert self.redis._values[_budget_key()] == "1000"
        assert _marker_keys(self.redis) == []

    def test_budget_exceeded_denial_does_not_decrement_budget(self):
        _reset_db()
        _seed_agent(daily_budget_limit_cents=1_000)
        self.redis._values[_budget_key()] = "900"
        payload = {**_STABLECOIN, "amount_cents": 200, "idempotency_key": "rb-budget-001"}

        resp = self._send(payload)

        assert resp.status_code == 403, resp.text
        assert "BUDGET_DAILY_LIMIT_EXCEEDED" in resp.json()["reasons"]
        audit = self._audit(resp.json()["request_id"])
        assert audit.quantitative_result["budget_reserved"] is False
        # Nothing was reserved, so nothing may be released: 900 must not become 700.
        assert self.redis._values[_budget_key()] == "900"
        assert _marker_keys(self.redis) == []

    def test_rollback_failure_is_logged_and_still_blocks(self, caplog):
        self.redis = _FailingRollbackRedis()
        app.dependency_overrides[get_redis] = lambda: self.redis
        self.redis._values[_budget_key()] = "1000"
        payload = {**_STABLECOIN, "vendor_url_or_name": "badvendor.com", "idempotency_key": "rb-fail-001"}

        with caplog.at_level("ERROR"):
            resp = self._send(payload)

        assert resp.status_code == 403, resp.text
        assert resp.json()["verdict"] == "MALICIOUS"
        assert self._audit(resp.json()["request_id"]).status == "BLOCKED"
        assert any("Budget rollback failed after MALICIOUS verdict" in r.message for r in caplog.records)
        # Rollback never ran, so the reservation leaks (this is exactly what the log flags).
        assert self.redis._values[_budget_key()] == str(1000 + _STABLECOIN["amount_cents"])

    def test_safe_verdict_keeps_reservation_and_clears_marker(self):
        self.redis._values[_budget_key()] = "1000"
        payload = {**_STABLECOIN, "idempotency_key": "rb-safe-001"}

        resp = self._send(payload)

        assert resp.status_code == 200, resp.text
        assert self.redis._values[_budget_key()] == str(1000 + _STABLECOIN["amount_cents"])
        assert _marker_keys(self.redis) == []


@pytest.mark.parametrize(
    "override, reason",
    [
        ({"vendor_url_or_name": "badvendor.com"}, "VENDOR_MATCHED_BLOCKLIST"),
        ({"stablecoin_symbol": "USDT"}, "STABLECOIN_NOT_ALLOWED"),
        ({"destination_address": "0xdeadbeefdeadbeef0000000000000000deadbeef"}, "DESTINATION_DENYLISTED"),
    ],
)
def test_every_hard_deny_reason_releases_reservation(override, reason):
    _reset_db()
    _seed_agent()
    redis = FakeRedis()
    redis._values[_budget_key()] = "500"
    app.dependency_overrides[get_redis] = lambda: redis
    _mock_semantic("ALIGNED")
    try:
        payload = {**_STABLECOIN, **override, "idempotency_key": f"rb-param-{reason}"}
        content, headers = _sign_agent(payload)
        with TestClient(app) as client:
            resp = client.post("/v1/spend-request", content=content, headers=headers)
        assert resp.status_code == 403, resp.text
        assert reason in resp.json()["reasons"]
        assert redis._values[_budget_key()] == "500"
        assert _marker_keys(redis) == []
    finally:
        app.dependency_overrides.clear()
