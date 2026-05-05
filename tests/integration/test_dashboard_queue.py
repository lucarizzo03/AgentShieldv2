import hashlib
import hmac as _hmac
import json
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, select

from app.core.security import UserAuthContext, verify_user_auth
from app.db.postgres import engine
from app.db.redis import get_redis
from app.main import app
from app.models import Agent
from app.models.dashboard_notification import DashboardNotification
from app.services.slm.client import AnthropicSemanticClient
from tests.integration.test_spend_hitl_flow import FakeRedis

AGENT_SECRET = "test-agent-secret"


def _reset_db() -> None:
    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)


def _seed_agent() -> None:
    with Session(engine) as session:
        session.add(
            Agent(
                agent_id="agent_dash",
                status="ACTIVE",
                daily_budget_limit_cents=100_000,
                per_txn_auto_approve_limit_cents=1000,
                currency="USD",
                hmac_secret=AGENT_SECRET,
            )
        )
        session.commit()


def _sign_agent(body: dict, agent_id: str = "agent_dash", path: str = "/v1/spend-request") -> tuple[bytes, dict]:
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


def _mock_semantic(label: str, score: int = 10) -> None:
    async def _impl(self, **kwargs):
        return {"alignment_label": label, "risk_score": score, "reason_codes": ["TEST"]}
    AnthropicSemanticClient.semantic_alignment = _impl


def _mock_user_auth():
    return UserAuthContext(
        sub="agent:agent_dash",
        email=None,
        display_name=None,
        method="auth0",
        agent_id="agent_dash",
    )


def test_dashboard_notification_list_and_ack() -> None:
    _reset_db()
    _seed_agent()
    fake_redis = FakeRedis()
    app.dependency_overrides[get_redis] = lambda: fake_redis
    app.dependency_overrides[verify_user_auth] = _mock_user_auth
    _mock_semantic("WEAK", 60)

    spend_body = {
        "agent_id": "agent_dash",
        "declared_goal": "Purchase required service",
        "amount_cents": 5000,
        "currency": "USD",
        "asset_type": "STABLECOIN",
        "stablecoin_symbol": "USDC",
        "network": "base",
        "destination_address": "0x1111111111111111",
        "vendor_url_or_name": "service.example",
        "item_description": "Subscription",
    }

    with TestClient(app) as client:
        content, headers = _sign_agent(spend_body)
        spend_resp = client.post("/v1/spend-request", content=content, headers=headers)
        assert spend_resp.status_code == 202

        list_resp = client.get(
            "/v1/dashboard/agents/agent_dash/notifications?status=OPEN",
            headers={"Authorization": "Bearer mock-token"},
        )
        assert list_resp.status_code == 200
        notifications = list_resp.json()["notifications"]
        assert len(notifications) == 1
        notification_id = notifications[0]["id"]

        ack_resp = client.patch(
            f"/v1/dashboard/agents/agent_dash/notifications/{notification_id}",
            headers={"Authorization": "Bearer mock-token"},
            json={"action": "ACK"},
        )
        assert ack_resp.status_code == 200
        assert ack_resp.json()["status"] == "ACKED"

    with Session(engine) as session:
        notif = session.exec(select(DashboardNotification)).first()
        assert notif is not None
        assert notif.status == "ACKED"

    app.dependency_overrides.clear()
