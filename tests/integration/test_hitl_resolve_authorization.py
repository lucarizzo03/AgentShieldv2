"""A dashboard operator may only resolve requests belonging to their own agents.

`/v1/hitl/resolve/{request_id}` accepts any authenticated Cognito bearer token, so
without an ownership check any signed-up user could approve someone else's
pending spend and release their money.
"""

import json
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core import security
from app.core.security import UserAuthContext
from app.db.postgres import engine
from app.db.redis import get_redis
from app.main import app
from app.models.user import User
from tests.integration.test_spend_hitl_flow import (
    AGENT_SECRET,
    FakeRedis,
    _mock_semantic,
    _reset_db,
    _seed_agent,
    _sign_agent,
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


def _seed_owner_and_attacker() -> None:
    owner_id = uuid4()
    with Session(engine) as session:
        session.add(User(id=owner_id, auth_subject="cognito|owner", email="owner@example.com"))
        session.add(User(auth_subject="cognito|attacker", email="attacker@example.com"))
        session.commit()
    _seed_agent(owner_user_id=owner_id, hmac_secret=AGENT_SECRET)


def _mock_bearer(sub: str) -> None:
    security._verify_cognito_bearer = lambda token: UserAuthContext(
        sub=sub, email=None, display_name=None
    )


def _park_request(client: TestClient) -> str:
    content, headers = _sign_agent(SPEND_BODY)
    resp = client.post("/v1/spend-request", content=content, headers=headers)
    assert resp.status_code == 202, resp.text
    return resp.json()["request_id"]


def _resolve_as_bearer(client: TestClient, request_id: str):
    return client.post(
        f"/v1/hitl/resolve/{request_id}",
        content=json.dumps(
            {"decision": "APPROVE", "resolver_id": "ops_user_1", "channel": "dashboard"},
            separators=(",", ":"),
        ).encode(),
        headers={"Authorization": "Bearer mock-token", "Content-Type": "application/json"},
    )


def _setup() -> None:
    _reset_db()
    _seed_owner_and_attacker()
    app.dependency_overrides[get_redis] = lambda: FakeRedis()
    _mock_semantic("WEAK", 40)


def test_operator_cannot_resolve_another_users_pending_request() -> None:
    original = security._verify_cognito_bearer
    _setup()
    try:
        with TestClient(app) as client:
            request_id = _park_request(client)
            _mock_bearer("cognito|attacker")
            resp = _resolve_as_bearer(client, request_id)
        assert resp.status_code == 403, resp.text
    finally:
        security._verify_cognito_bearer = original
        app.dependency_overrides.clear()


def test_owner_can_resolve_their_own_pending_request() -> None:
    original = security._verify_cognito_bearer
    _setup()
    try:
        with TestClient(app) as client:
            request_id = _park_request(client)
            _mock_bearer("cognito|owner")
            resp = _resolve_as_bearer(client, request_id)
        assert resp.status_code == 200, resp.text
        assert resp.json()["decision"] == "APPROVE"
    finally:
        security._verify_cognito_bearer = original
        app.dependency_overrides.clear()


def test_checklist_requires_ownership() -> None:
    original = security._verify_cognito_bearer
    _setup()
    try:
        with TestClient(app) as client:
            unauthenticated = client.get("/v1/onboarding/agents/agent_demo/checklist")
            assert unauthenticated.status_code == 401, unauthenticated.text

            _mock_bearer("cognito|attacker")
            forbidden = client.get(
                "/v1/onboarding/agents/agent_demo/checklist",
                headers={"Authorization": "Bearer mock-token"},
            )
            assert forbidden.status_code == 403, forbidden.text

            _mock_bearer("cognito|owner")
            allowed = client.get(
                "/v1/onboarding/agents/agent_demo/checklist",
                headers={"Authorization": "Bearer mock-token"},
            )
            assert allowed.status_code == 200, allowed.text
            assert allowed.json()["agent_id"] == "agent_demo"
    finally:
        security._verify_cognito_bearer = original
        app.dependency_overrides.clear()


def test_unknown_agent_checklist_does_not_leak_existence() -> None:
    original = security._verify_cognito_bearer
    _setup()
    try:
        _mock_bearer("cognito|owner")
        with TestClient(app) as client:
            resp = client.get(
                f"/v1/onboarding/agents/agent_{uuid4().hex[:12]}/checklist",
                headers={"Authorization": "Bearer mock-token"},
            )
        assert resp.status_code == 403, resp.text
    finally:
        security._verify_cognito_bearer = original
        app.dependency_overrides.clear()
