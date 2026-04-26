"""
Three comprehensive scenario tests covering every decision path in AgentShield.

  Test 1 — SAFE path
    • Stablecoin transaction that clears all three checks and executes immediately
    • Idempotency: replaying the same key returns the cached response, not a second execution
    • FIAT transaction routes to StripeAdapter
    • Suspended agent is rejected before checks run

  Test 2 — SUSPICIOUS / HITL path
    • Over-threshold spend creates PendingSpend + DashboardNotification
    • All DB state checked (PendingSpend, DashboardNotification, SpendAuditLog)
    • APPROVE via dashboard executes payment + transitions all records
    • DENY via dashboard holds funds + records DENIED_BY_HUMAN audit
    • Double-resolve attempt returns 409
    • SMS resolution (verified phone, high-risk flag)
    • SMS from wrong phone returns 403

  Test 3 — MALICIOUS / hard-deny path
    • Vendor on blocklist → VENDOR_MATCHED_BLOCKLIST
    • Daily budget exceeded → BUDGET_DAILY_LIMIT_EXCEEDED
    • Network not in allowed list → NETWORK_NOT_ALLOWED
    • Stablecoin token not in allowed list → STABLECOIN_NOT_ALLOWED
    • Destination address on denylist → DESTINATION_DENYLISTED
    • SLM returns MISMATCH / high risk score → SEMANTIC_MISMATCH_HIGH
    • All produce 403, BLOCKED audit log, no payment
"""
from collections import defaultdict
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, select

from app.db.postgres import engine
from app.db.redis import get_redis
from app.main import app
from app.models.agent import Agent
from app.models.dashboard_notification import DashboardNotification
from app.models.pending_spend import PendingSpend
from app.models.spend_audit_log import SpendAuditLog
from app.services.slm.client import LocalSlmClient


# ---------------------------------------------------------------------------
# Shared test infrastructure
# ---------------------------------------------------------------------------

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
        self._counter[key] += amount
        self._values[key] = str(self._counter[key])
        return self._counter[key]

    async def expire(self, key, ttl):
        return True

    async def delete(self, key):
        self._values.pop(key, None)
        self._counter.pop(key, None)
        return True


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
        hitl_phone_number="+15555550100",
        hitl_phone_verified_at=None,
        hitl_primary_channel="dashboard",
        hitl_sms_fallback_high_risk=True,
    )
    defaults.update(overrides)
    with Session(engine) as session:
        session.add(Agent(**defaults))
        session.commit()


def _mock_slm(label: str, score: int):
    async def _impl(self, **kwargs):
        return {"alignment_label": label, "risk_score": score, "reason_codes": [f"TEST_{label}"]}
    LocalSlmClient.semantic_alignment = _impl


# Shared request payloads
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

DEV_HEADERS = {"x-agent-key": "local-dev-key"}
WEBHOOK_HEADERS = {"x-webhook-signature": "sig_ok"}


# ===========================================================================
# TEST 1 — SAFE PATH
# ===========================================================================

class TestSafePath:

    def setup_method(self):
        _reset_db()
        _seed_agent()
        self.redis = FakeRedis()
        app.dependency_overrides[get_redis] = lambda: self.redis
        _mock_slm("ALIGNED", 10)

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_safe_stablecoin_executes_immediately(self):
        """Clean stablecoin spend clears all three checks and returns 200 with payment."""
        with TestClient(app) as client:
            resp = client.post("/v1/spend-request", headers=DEV_HEADERS, json=_STABLECOIN)

        assert resp.status_code == 200, resp.text
        body = resp.json()

        # Top-level response shape
        assert body["status"] == "APPROVED_EXECUTED"
        assert body["verdict"] == "SAFE"
        assert body["approved_amount_cents"] == 2_000
        assert body["currency"] == "USD"

        # Payment block present and populated
        pay = body["payment"]
        assert pay["provider"] == "tempo"
        assert pay["provider_txn_id"].startswith("tp_txn_")
        assert pay["onchain_tx_hash"].startswith("0x")
        assert pay["stablecoin_symbol"] == "USDC"
        assert pay["network"] == "base"

        # All three checks left clean reason codes
        reasons = body["reasons"]
        assert "BUDGET_WITHIN_LIMIT" in reasons
        assert "VENDOR_ALLOWED" in reasons
        assert "SEMANTIC_ALIGNMENT_HIGH" in reasons

        # Audit log written correctly
        with Session(engine) as session:
            log = session.exec(
                select(SpendAuditLog).where(SpendAuditLog.agent_id == "test_agent_001")
            ).first()
        assert log is not None
        assert log.status == "APPROVED_EXECUTED"
        assert log.verdict == "SAFE"
        assert log.amount_cents == 2_000
        assert log.payment_provider == "tempo"
        assert log.onchain_tx_hash is not None

    def test_idempotency_returns_cached_response_without_second_execution(self):
        """Replaying with the same idempotency key returns the original response
        without creating a second audit record or executing payment again."""
        with TestClient(app) as client:
            r1 = client.post("/v1/spend-request", headers=DEV_HEADERS, json=_STABLECOIN)
            r2 = client.post("/v1/spend-request", headers=DEV_HEADERS, json=_STABLECOIN)

        assert r1.status_code == 200
        assert r2.status_code == 200

        # Cached response returns identical payment txn id
        assert (
            r1.json()["payment"]["provider_txn_id"]
            == r2.json()["payment"]["provider_txn_id"]
        ), "Idempotent replay must return cached txn id, not a new one"

        # Only one audit record despite two HTTP calls
        with Session(engine) as session:
            logs = session.exec(
                select(SpendAuditLog).where(SpendAuditLog.agent_id == "test_agent_001")
            ).all()
        assert len(logs) == 1, f"Expected 1 audit record, got {len(logs)}"

    def test_safe_fiat_transaction_uses_stripe_adapter(self):
        """FIAT asset type routes to StripeAdapter and returns no onchain_tx_hash."""
        fiat_payload = dict(
            agent_id="test_agent_001",
            declared_goal="Pay monthly SaaS subscription",
            amount_cents=1_500,
            currency="USD",
            asset_type="FIAT",
            vendor_url_or_name="github.com",
            item_description="GitHub Teams plan",
            idempotency_key="test-fiat-001",
        )
        with TestClient(app) as client:
            resp = client.post("/v1/spend-request", headers=DEV_HEADERS, json=fiat_payload)

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "APPROVED_EXECUTED"
        assert body["payment"]["provider"] == "stripe"
        assert body["payment"]["onchain_tx_hash"] is None

    def test_suspended_agent_is_rejected_before_checks(self):
        """A non-ACTIVE agent gets 403 immediately — no checks run."""
        with Session(engine) as session:
            agent = session.exec(select(Agent).where(Agent.agent_id == "test_agent_001")).first()
            agent.status = "SUSPENDED"
            session.add(agent)
            session.commit()

        with TestClient(app) as client:
            resp = client.post("/v1/spend-request", headers=DEV_HEADERS, json=_STABLECOIN)

        assert resp.status_code == 403
        assert "not active" in resp.json()["detail"].lower()

    def test_unknown_agent_returns_404(self):
        """Requests for a non-existent agent_id return 404."""
        payload = {**_STABLECOIN, "agent_id": "agt_does_not_exist"}
        with TestClient(app) as client:
            resp = client.post("/v1/spend-request", headers=DEV_HEADERS, json=payload)
        assert resp.status_code == 404


# ===========================================================================
# TEST 2 — SUSPICIOUS / HITL PATH
# ===========================================================================

class TestSuspiciousHitlPath:

    def setup_method(self):
        _reset_db()
        _seed_agent()
        self.redis = FakeRedis()
        app.dependency_overrides[get_redis] = lambda: self.redis
        _mock_slm("WEAK", 60)

    def teardown_method(self):
        app.dependency_overrides.clear()

    def _over_threshold_spend(self, client, idempotency_key="susp-001"):
        """Submit a spend that exceeds hitl_required_over_cents (5000) but not daily budget."""
        return client.post(
            "/v1/spend-request",
            headers=DEV_HEADERS,
            json={**_STABLECOIN, "amount_cents": 8_000, "idempotency_key": idempotency_key},
        )

    def test_suspicious_returns_202_with_correct_state(self):
        """Over-threshold spend produces 202 with all HITL fields populated."""
        with TestClient(app) as client:
            resp = self._over_threshold_spend(client)

        assert resp.status_code == 202, resp.text
        body = resp.json()

        assert body["status"] == "PENDING_HITL"
        assert body["verdict"] == "SUSPICIOUS"
        assert body["next_action"] == "AGENT_MUST_WAIT"
        assert "AMOUNT_OVER_AUTO_APPROVAL_THRESHOLD" in body["reasons"]

        hitl = body["hitl"]
        assert hitl["channel"] == "dashboard"
        assert hitl["state"] == "WAITING_HUMAN_REVIEW"
        assert hitl["expires_at"] is not None

        request_id = body["request_id"]

        with Session(engine) as session:
            # PendingSpend created
            pending = session.exec(
                select(PendingSpend).where(PendingSpend.request_id == request_id)
            ).first()
            assert pending is not None
            assert pending.state == "WAITING_HUMAN"
            assert pending.hitl_channel == "dashboard"
            assert pending.hitl_contact is None

            # DashboardNotification created and open
            notif = session.exec(
                select(DashboardNotification).where(DashboardNotification.request_id == request_id)
            ).first()
            assert notif is not None
            assert notif.status == "OPEN"
            assert notif.category == "HITL_PENDING"
            assert notif.agent_id == "test_agent_001"

            # Audit log shows PENDING_HITL
            audit = session.exec(
                select(SpendAuditLog).where(SpendAuditLog.request_id == request_id)
            ).first()
            assert audit is not None
            assert audit.status == "PENDING_HITL"
            assert audit.verdict == "SUSPICIOUS"

    def test_approve_executes_payment_and_transitions_all_records(self):
        """Approving a pending request executes payment and updates PendingSpend,
        DashboardNotification, and creates an APPROVED_BY_HUMAN_EXECUTED audit record."""
        with TestClient(app) as client:
            spend = self._over_threshold_spend(client)
            assert spend.status_code == 202
            request_id = spend.json()["request_id"]

            resolve = client.post(
                f"/v1/hitl/resolve/{request_id}",
                headers=WEBHOOK_HEADERS,
                json={"decision": "APPROVE", "resolver_id": "ops_user_1", "channel": "dashboard"},
            )

        assert resolve.status_code == 200, resolve.text
        body = resolve.json()
        assert body["status"] == "RESOLVED"
        assert body["decision"] == "APPROVE"
        assert body["payment"]["executed"] is True
        assert body["payment"]["provider"] == "tempo"

        with Session(engine) as session:
            pending = session.exec(
                select(PendingSpend).where(PendingSpend.request_id == request_id)
            ).first()
            assert pending.state == "APPROVED"
            assert pending.resolver_id == "ops_user_1"
            assert pending.resolved_at is not None

            notif = session.exec(
                select(DashboardNotification).where(DashboardNotification.request_id == request_id)
            ).first()
            assert notif.status == "RESOLVED"
            assert notif.acknowledged_by == "ops_user_1"

            all_logs = session.exec(
                select(SpendAuditLog).where(SpendAuditLog.agent_id == "test_agent_001")
            ).all()
            statuses = {log.status for log in all_logs}
            assert "PENDING_HITL" in statuses
            assert "APPROVED_BY_HUMAN_EXECUTED" in statuses

    def test_deny_holds_funds_and_records_denial(self):
        """Denying a pending request holds funds and records DENIED_BY_HUMAN."""
        with TestClient(app) as client:
            spend = self._over_threshold_spend(client, idempotency_key="susp-deny-001")
            assert spend.status_code == 202
            request_id = spend.json()["request_id"]

            resolve = client.post(
                f"/v1/hitl/resolve/{request_id}",
                headers=WEBHOOK_HEADERS,
                json={"decision": "DENY", "resolver_id": "ops_user_2", "channel": "dashboard"},
            )

        assert resolve.status_code == 200
        body = resolve.json()
        assert body["decision"] == "DENY"
        assert body["payment"]["executed"] is False
        assert body["payment"]["provider"] is None

        with Session(engine) as session:
            pending = session.exec(
                select(PendingSpend).where(PendingSpend.request_id == request_id)
            ).first()
            assert pending.state == "DENIED"

            all_logs = session.exec(
                select(SpendAuditLog).where(SpendAuditLog.agent_id == "test_agent_001")
            ).all()
            statuses = {log.status for log in all_logs}
            assert "DENIED_BY_HUMAN" in statuses

    def test_double_resolve_returns_409_conflict(self):
        """A second resolution attempt on an already-resolved request returns 409."""
        with TestClient(app) as client:
            spend = self._over_threshold_spend(client, idempotency_key="susp-dbl-001")
            request_id = spend.json()["request_id"]
            payload = {"decision": "APPROVE", "resolver_id": "ops_user_1", "channel": "dashboard"}

            r1 = client.post(f"/v1/hitl/resolve/{request_id}", headers=WEBHOOK_HEADERS, json=payload)
            r2 = client.post(f"/v1/hitl/resolve/{request_id}", headers=WEBHOOK_HEADERS, json=payload)

        assert r1.status_code == 200
        assert r2.status_code == 409, "Already-resolved request must return 409"

    def test_sms_resolution_with_verified_phone(self):
        """When phone is verified and high-risk flag is set, suspicious spend routes to SMS.
        Inbound SMS from the correct number resolves it."""
        _reset_db()
        _seed_agent(
            hitl_phone_number="+15555550100",
            hitl_phone_verified_at=datetime.now(timezone.utc),
            hitl_sms_fallback_high_risk=True,
            hitl_required_over_cents=1_000,
        )
        _mock_slm("WEAK", 60)

        with TestClient(app) as client:
            spend = client.post(
                "/v1/spend-request",
                headers=DEV_HEADERS,
                json={**_STABLECOIN, "amount_cents": 8_000, "idempotency_key": "sms-approve-001"},
            )
            assert spend.status_code == 202
            body = spend.json()
            assert body["hitl"]["channel"] == "sms", "Expected SMS channel for high-risk + verified phone"
            request_id = body["request_id"]

            sms = client.post(
                "/v1/hitl/sms/inbound",
                headers=WEBHOOK_HEADERS,
                data={"From": "+15555550100", "Body": f"APPROVE {request_id}", "MessageSid": "SM001"},
            )

        assert sms.status_code == 200
        assert "APPROVE recorded" in sms.text

        with Session(engine) as session:
            pending = session.exec(
                select(PendingSpend).where(PendingSpend.request_id == request_id)
            ).first()
            assert pending.state == "APPROVED"

    def test_sms_from_wrong_phone_is_rejected(self):
        """Inbound SMS from an unrecognized number must return 403 and not resolve."""
        _reset_db()
        _seed_agent(
            hitl_phone_number="+15555550100",
            hitl_phone_verified_at=datetime.now(timezone.utc),
            hitl_required_over_cents=1_000,
        )
        _mock_slm("WEAK", 60)

        with TestClient(app) as client:
            spend = client.post(
                "/v1/spend-request",
                headers=DEV_HEADERS,
                json={**_STABLECOIN, "amount_cents": 8_000, "idempotency_key": "sms-badphone-001"},
            )
            request_id = spend.json()["request_id"]

            sms = client.post(
                "/v1/hitl/sms/inbound",
                headers=WEBHOOK_HEADERS,
                data={"From": "+19998887777", "Body": f"APPROVE {request_id}", "MessageSid": "SM002"},
            )

        assert sms.status_code == 403

        with Session(engine) as session:
            pending = session.exec(
                select(PendingSpend).where(PendingSpend.request_id == request_id)
            ).first()
            assert pending.state == "WAITING_HUMAN", "State must not change on unauthorized SMS"

    def test_unverified_phone_always_routes_to_dashboard(self):
        """Phone number set but not verified → dashboard channel, no SMS, even for high-risk."""
        with TestClient(app) as client:
            resp = self._over_threshold_spend(client, idempotency_key="susp-unverified-001")

        assert resp.status_code == 202
        body = resp.json()
        assert body["hitl"]["channel"] == "dashboard"
        assert body["hitl"]["state"] == "WAITING_HUMAN_REVIEW"


# ===========================================================================
# TEST 3 — MALICIOUS / HARD-DENY PATH
# ===========================================================================

class TestMaliciousPath:

    def setup_method(self):
        _reset_db()
        _seed_agent()
        self.redis = FakeRedis()
        app.dependency_overrides[get_redis] = lambda: self.redis

    def teardown_method(self):
        app.dependency_overrides.clear()

    def _send(self, payload, slm_label="ALIGNED", slm_score=5):
        _mock_slm(slm_label, slm_score)
        with TestClient(app) as client:
            return client.post("/v1/spend-request", headers=DEV_HEADERS, json=payload)

    def _assert_blocked(self, resp, expected_reason: str):
        assert resp.status_code == 403, f"Expected 403, got {resp.status_code}: {resp.text}"
        body = resp.json()
        assert body["status"] == "BLOCKED"
        assert body["verdict"] == "MALICIOUS"
        assert body["next_action"] == "DO_NOT_RETRY"
        assert expected_reason in body["reasons"], (
            f"Expected reason {expected_reason!r} not found in {body['reasons']}"
        )
        # Audit log written with BLOCKED status
        with Session(engine) as session:
            log = session.exec(
                select(SpendAuditLog).where(SpendAuditLog.request_id == body["request_id"])
            ).first()
        assert log is not None, "Audit log must be written even for blocked transactions"
        assert log.status == "BLOCKED"
        assert log.verdict == "MALICIOUS"
        # No payment fields set
        assert log.payment_provider is None
        assert log.payment_txn_id is None
        return body

    def test_vendor_on_blocklist_is_hard_denied(self):
        payload = {**_STABLECOIN, "vendor_url_or_name": "badvendor.com", "idempotency_key": "mal-vendor-001"}
        resp = self._send(payload)
        self._assert_blocked(resp, "VENDOR_MATCHED_BLOCKLIST")

    def test_vendor_partial_match_in_url_is_hard_denied(self):
        """Blocklist match is substring — vendor inside a URL should still match."""
        payload = {**_STABLECOIN, "vendor_url_or_name": "https://badvendor.com/checkout", "idempotency_key": "mal-vendor-url-001"}
        resp = self._send(payload)
        self._assert_blocked(resp, "VENDOR_MATCHED_BLOCKLIST")

    def test_daily_budget_exceeded_is_hard_denied(self):
        """Injecting a near-limit budget value into Redis causes the next spend to exceed it."""
        _reset_db()
        _seed_agent(daily_budget_limit_cents=1_000)
        date_key = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self.redis._values[f"budget:daily:test_agent_001:STABLECOIN:{date_key}"] = "900"

        payload = {**_STABLECOIN, "amount_cents": 200, "idempotency_key": "mal-budget-001"}
        resp = self._send(payload)
        self._assert_blocked(resp, "BUDGET_DAILY_LIMIT_EXCEEDED")

    def test_network_not_in_allowed_list_is_hard_denied(self):
        """Attempting to send on a network the agent has not allowed."""
        payload = {**_STABLECOIN, "network": "polygon", "idempotency_key": "mal-network-001"}
        resp = self._send(payload)
        self._assert_blocked(resp, "NETWORK_NOT_ALLOWED")

    def test_token_not_in_allowed_list_is_hard_denied(self):
        """Attempting to use a stablecoin the agent has not allowed."""
        payload = {**_STABLECOIN, "stablecoin_symbol": "USDT", "idempotency_key": "mal-token-001"}
        resp = self._send(payload)
        self._assert_blocked(resp, "STABLECOIN_NOT_ALLOWED")

    def test_destination_on_denylist_is_hard_denied(self):
        """Explicitly denylisted destination address is hard-blocked."""
        payload = {
            **_STABLECOIN,
            "destination_address": "0xdeadbeefdeadbeef0000000000000000deadbeef",
            "idempotency_key": "mal-denylist-001",
        }
        resp = self._send(payload)
        self._assert_blocked(resp, "DESTINATION_DENYLISTED")

    def test_slm_mismatch_label_is_hard_denied(self):
        """SLM returning MISMATCH alignment triggers SEMANTIC_MISMATCH_HIGH hard deny."""
        payload = {**_STABLECOIN, "idempotency_key": "mal-slm-mismatch-001"}
        resp = self._send(payload, slm_label="MISMATCH", slm_score=90)
        self._assert_blocked(resp, "SEMANTIC_MISMATCH_HIGH")

    def test_slm_high_risk_score_alone_is_hard_denied(self):
        """risk_score >= 85 hard-denies even if label is not MISMATCH."""
        payload = {**_STABLECOIN, "idempotency_key": "mal-slm-score-001"}
        resp = self._send(payload, slm_label="WEAK", slm_score=90)
        self._assert_blocked(resp, "SEMANTIC_MISMATCH_HIGH")

    def test_multiple_hard_deny_conditions_still_returns_single_malicious(self):
        """When multiple hard-deny conditions fire together the verdict is still MALICIOUS
        and all reason codes are present."""
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
