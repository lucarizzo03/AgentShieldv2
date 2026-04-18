import json

from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, select

from app.db.postgres import engine
from app.db.redis import get_redis
from app.main import app
from app.models import Agent
from tests.integration.test_spend_hitl_flow import FakeRedis


def _reset_db() -> None:
    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)


def _seed_agent() -> None:
    with Session(engine) as session:
        session.add(
            Agent(
                agent_id="agent_contact",
                status="ACTIVE",
                daily_budget_limit_cents=100_000,
                per_txn_auto_approve_limit_cents=10_000,
                currency="USD",
            )
        )
        session.commit()


def test_phone_start_verify_and_preferences_update() -> None:
    _reset_db()
    _seed_agent()
    fake_redis = FakeRedis()
    app.dependency_overrides[get_redis] = lambda: fake_redis

    with TestClient(app) as client:
        start_resp = client.post(
            "/v1/agents/agent_contact/contact/phone/start",
            headers={"x-agent-key": "local-dev-key", "x-agent-id": "agent_contact"},
            json={"phone_number": "+15555550123"},
        )
        assert start_resp.status_code == 200
        assert start_resp.json()["status"] == "OTP_SENT"

        otp_payload = json.loads(fake_redis._values["otp:phone:agent_contact"])
        verify_resp = client.post(
            "/v1/agents/agent_contact/contact/phone/verify",
            headers={"x-agent-key": "local-dev-key", "x-agent-id": "agent_contact"},
            json={"phone_number": "+15555550123", "code": otp_payload["code"]},
        )
        assert verify_resp.status_code == 200
        assert verify_resp.json()["status"] == "PHONE_VERIFIED"

        pref_resp = client.patch(
            "/v1/agents/agent_contact/preferences/hitl",
            headers={"x-agent-key": "local-dev-key", "x-agent-id": "agent_contact"},
            json={"hitl_primary_channel": "dashboard", "hitl_sms_fallback_high_risk": False},
        )
        assert pref_resp.status_code == 200
        assert pref_resp.json()["hitl_primary_channel"] == "dashboard"
        assert pref_resp.json()["hitl_sms_fallback_high_risk"] is False

    with Session(engine) as session:
        agent = session.exec(select(Agent).where(Agent.agent_id == "agent_contact")).first()
        assert agent is not None
        assert agent.hitl_phone_number == "+15555550123"
        assert agent.hitl_phone_verified_at is not None
        assert agent.hitl_primary_channel == "dashboard"
        assert agent.hitl_sms_fallback_high_risk is False
    app.dependency_overrides.clear()

