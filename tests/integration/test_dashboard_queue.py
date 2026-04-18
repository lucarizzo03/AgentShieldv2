from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, select

from app.db.postgres import engine
from app.db.redis import get_redis
from app.main import app
from app.models import Agent
from app.models.dashboard_notification import DashboardNotification
from app.services.slm.client import LocalSlmClient
from tests.integration.test_spend_hitl_flow import FakeRedis


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
                hitl_phone_number="+15550001111",
                hitl_phone_verified_at=datetime.now(timezone.utc),
                hitl_primary_channel="dashboard",
                hitl_sms_fallback_high_risk=True,
            )
        )
        session.commit()


def _override_slm(label: str, score: int):
    async def _mock(self, **kwargs):
        return {"alignment_label": label, "risk_score": score, "reason_codes": ["TEST"]}

    LocalSlmClient.semantic_alignment = _mock


def test_dashboard_notification_list_and_ack() -> None:
    _reset_db()
    _seed_agent()
    fake_redis = FakeRedis()
    app.dependency_overrides[get_redis] = lambda: fake_redis
    _override_slm("WEAK", 60)

    with TestClient(app) as client:
        spend_resp = client.post(
            "/v1/spend-request",
            headers={"x-agent-key": "local-dev-key", "x-agent-id": "agent_dash"},
            json={
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
            },
        )
        assert spend_resp.status_code == 202

        list_resp = client.get(
            "/v1/dashboard/agents/agent_dash/notifications?status=OPEN",
            headers={"x-agent-key": "local-dev-key", "x-agent-id": "agent_dash"},
        )
        assert list_resp.status_code == 200
        notifications = list_resp.json()["notifications"]
        assert len(notifications) == 1
        notification_id = notifications[0]["id"]

        ack_resp = client.patch(
            f"/v1/dashboard/agents/agent_dash/notifications/{notification_id}",
            headers={"x-agent-key": "local-dev-key", "x-agent-id": "agent_dash"},
            json={"action": "ACK"},
        )
        assert ack_resp.status_code == 200
        assert ack_resp.json()["status"] == "ACKED"

    with Session(engine) as session:
        notif = session.exec(select(DashboardNotification)).first()
        assert notif is not None
        assert notif.status == "ACKED"
    app.dependency_overrides.clear()

