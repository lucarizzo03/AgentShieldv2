"""HITL approvals must be validated against the agent's *current* state.

A pending request can sit in the queue for minutes or hours; by the time a
human clicks approve, the agent may have been deactivated, had its policy
tightened, or spent the rest of its daily budget elsewhere.
"""

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.db.postgres import engine
from app.db.redis import get_redis
from app.main import app
from app.models import Agent, PendingSpend
from app.policy.checks.quantitative import daily_budget_key
from tests.integration.test_spend_hitl_flow import (
    FakeRedis,
    _mock_semantic,
    _reset_db,
    _seed_agent,
    _sign_agent,
    _sign_webhook,
)

SPEND_BODY = {
    "agent_id": "agent_demo",
    "declared_goal": "Buy API credits for website launch",
    "amount_cents": 1200,
    "currency": "USD",
    "asset_type": "STABLECOIN",
    "stablecoin_symbol": "USDC",
    "network": "base",
    "destination_address": "0x1234567890abcdef",
    "vendor_url_or_name": "tempo",
    "item_description": "Agent credit top-up",
}


def _update_agent(**changes) -> None:
    with Session(engine) as session:
        agent = session.exec(select(Agent).where(Agent.agent_id == "agent_demo")).first()
        assert agent is not None
        for field, value in changes.items():
            setattr(agent, field, value)
        session.add(agent)
        session.commit()


def _pending_state(request_id: str) -> str:
    with Session(engine) as session:
        pending = session.exec(
            select(PendingSpend).where(PendingSpend.request_id == request_id)
        ).first()
        assert pending is not None
        return pending.state


def _park_request(client: TestClient) -> str:
    content, headers = _sign_agent(SPEND_BODY)
    resp = client.post("/v1/spend-request", content=content, headers=headers)
    assert resp.status_code == 202, resp.text
    return resp.json()["request_id"]


def _approve(client: TestClient, request_id: str):
    body = {"decision": "APPROVE", "resolver_id": "ops_user_1", "channel": "dashboard"}
    content, headers = _sign_webhook(body, f"/v1/hitl/resolve/{request_id}")
    return client.post(f"/v1/hitl/resolve/{request_id}", content=content, headers=headers)


def _setup() -> FakeRedis:
    _reset_db()
    _seed_agent()
    fake_redis = FakeRedis()
    app.dependency_overrides[get_redis] = lambda: fake_redis
    _mock_semantic("WEAK", 40)
    return fake_redis


def test_approval_rejected_when_budget_exhausted_since_evaluation() -> None:
    fake_redis = _setup()
    try:
        with TestClient(app) as client:
            request_id = _park_request(client)
            # Another spend drained the daily budget while the request waited.
            fake_redis._values[daily_budget_key("agent_demo", "STABLECOIN")] = "99900"
            resp = _approve(client, request_id)

        assert resp.status_code == 409
        assert "daily budget" in resp.json()["detail"]
        assert _pending_state(request_id) == "WAITING_HUMAN"
    finally:
        app.dependency_overrides.clear()


def test_approval_rejected_when_policy_tightened_since_evaluation() -> None:
    _setup()
    try:
        with TestClient(app) as client:
            request_id = _park_request(client)
            _update_agent(blocked_vendors=["tempo"])
            resp = _approve(client, request_id)

        assert resp.status_code == 409
        assert "policy changed" in resp.json()["detail"]
        assert _pending_state(request_id) == "WAITING_HUMAN"
    finally:
        app.dependency_overrides.clear()


def test_approval_rejected_when_agent_deactivated() -> None:
    _setup()
    try:
        with TestClient(app) as client:
            request_id = _park_request(client)
            _update_agent(status="SUSPENDED")
            resp = _approve(client, request_id)

        assert resp.status_code == 409
        assert "no longer active" in resp.json()["detail"]
        assert _pending_state(request_id) == "WAITING_HUMAN"
    finally:
        app.dependency_overrides.clear()


def test_approval_commits_budget_when_state_still_valid() -> None:
    fake_redis = _setup()
    try:
        with TestClient(app) as client:
            request_id = _park_request(client)
            resp = _approve(client, request_id)

        assert resp.status_code == 200
        assert _pending_state(request_id) == "APPROVED"
        # The reservation was released when the request was parked, so the
        # approval itself is what books the spend.
        assert fake_redis._values[daily_budget_key("agent_demo", "STABLECOIN")] == "1200"
    finally:
        app.dependency_overrides.clear()


def test_amount_over_hitl_threshold_escalates_instead_of_blocking() -> None:
    _reset_db()
    _seed_agent(hitl_required_over_cents=1_000)
    app.dependency_overrides[get_redis] = lambda: FakeRedis()
    _mock_semantic("ALIGNED")
    try:
        with TestClient(app) as client:
            content, headers = _sign_agent(SPEND_BODY)
            resp = client.post("/v1/spend-request", content=content, headers=headers)

        assert resp.status_code == 202, resp.text
        assert _pending_state(resp.json()["request_id"]) == "WAITING_HUMAN"
    finally:
        app.dependency_overrides.clear()
