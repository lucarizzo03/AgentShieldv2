import json
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core import security
from app.core.security import UserAuthContext
from app.db.postgres import engine
from app.db.redis import get_redis
from app.main import app
from app.models import Agent
from app.models.user import User
from tests.integration.test_spend_hitl_flow import FakeRedis, _mock_semantic, _reset_db

VICTIM_AGENT_ID = "agent_victim"


def _seed_owned_agent() -> None:
    owner_id = uuid4()
    with Session(engine) as session:
        session.add(
            User(
                id=owner_id,
                auth_subject="auth0|victim",
                email="victim@example.com",
            )
        )
        session.add(
            User(
                auth_subject="auth0|attacker",
                email="attacker@example.com",
            )
        )
        session.add(
            Agent(
                agent_id=VICTIM_AGENT_ID,
                status="ACTIVE",
                daily_budget_limit_cents=100_000,
                per_txn_auto_approve_limit_cents=10_000,
                currency="USD",
                blocked_vendors=[],
                allowed_stablecoins=["USDC"],
                allowed_networks=["base"],
                allowed_destination_addresses=[],
                blocked_destination_addresses=[],
                hmac_secret="victim-secret",
                owner_user_id=owner_id,
            )
        )
        session.commit()


def _spend_body(agent_id: str) -> bytes:
    return json.dumps(
        {
            "agent_id": agent_id,
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
        separators=(",", ":"),
    ).encode()


def _mock_bearer(sub: str) -> None:
    security._verify_auth0_bearer = lambda token: UserAuthContext(
        sub=sub, email=None, display_name=None
    )


def test_bearer_cannot_spend_as_unowned_agent() -> None:
    _reset_db()
    _seed_owned_agent()
    original = security._verify_auth0_bearer
    _mock_bearer("auth0|attacker")
    app.dependency_overrides[get_redis] = lambda: FakeRedis()
    try:
        with TestClient(app) as client:
            resp = client.post(
                "/v1/spend-request",
                content=_spend_body(VICTIM_AGENT_ID),
                headers={
                    "Authorization": "Bearer mock-token",
                    "x-agent-id": VICTIM_AGENT_ID,
                    "Content-Type": "application/json",
                },
            )
        assert resp.status_code == 403
    finally:
        security._verify_auth0_bearer = original
        app.dependency_overrides.clear()


def test_bearer_without_agent_header_cannot_spend_as_unowned_agent() -> None:
    _reset_db()
    _seed_owned_agent()
    original = security._verify_auth0_bearer
    _mock_bearer("auth0|attacker")
    app.dependency_overrides[get_redis] = lambda: FakeRedis()
    try:
        with TestClient(app) as client:
            resp = client.post(
                "/v1/spend-request",
                content=_spend_body(VICTIM_AGENT_ID),
                headers={
                    "Authorization": "Bearer mock-token",
                    "Content-Type": "application/json",
                },
            )
        assert resp.status_code == 403
    finally:
        security._verify_auth0_bearer = original
        app.dependency_overrides.clear()


def test_bearer_owner_can_spend_as_own_agent() -> None:
    _reset_db()
    _seed_owned_agent()
    original = security._verify_auth0_bearer
    _mock_bearer("auth0|victim")
    _mock_semantic("ALIGNED")
    app.dependency_overrides[get_redis] = lambda: FakeRedis()
    try:
        with TestClient(app) as client:
            resp = client.post(
                "/v1/spend-request",
                content=_spend_body(VICTIM_AGENT_ID),
                headers={
                    "Authorization": "Bearer mock-token",
                    "x-agent-id": VICTIM_AGENT_ID,
                    "Content-Type": "application/json",
                },
            )
        assert resp.status_code != 403
    finally:
        security._verify_auth0_bearer = original
        app.dependency_overrides.clear()
