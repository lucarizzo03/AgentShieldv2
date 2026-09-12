from fastapi.testclient import TestClient
from sqlmodel import SQLModel

from app.core.security import AuthContext, UserAuthContext, verify_agent_auth, verify_user_auth
from app.db.postgres import engine
from app.main import app


def _reset_db() -> None:
    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)


def _user_auth(sub: str) -> UserAuthContext:
    return UserAuthContext(
        sub=sub,
        email=f"{sub}@example.com",
        display_name=sub,
        method="auth0",
    )


def _create_agent(client: TestClient, name: str) -> str:
    payload = {
        "agent_name": name,
        "daily_spend_limit_usd": 500,
        "per_transaction_limit_usd": 200,
        "auto_approve_under_usd": 25,
        "blocked_vendors": [],
        "asset_type": "STABLECOIN",
        "allowed_networks": ["base"],
        "allowed_tokens": ["USDC"],
        "allowed_scopes": ["travel booking"],
    }
    resp = client.post("/v1/agents", json=payload, headers={"Authorization": "Bearer mocked"})
    assert resp.status_code == 200, resp.text
    return resp.json()["agent_id"]


def test_owner_can_rotate_but_other_auth0_principal_cannot() -> None:
    _reset_db()
    app.dependency_overrides[verify_user_auth] = lambda: _user_auth("auth0|owner")

    with TestClient(app) as client:
        agent_id = _create_agent(client, "rotation-agent")

        app.dependency_overrides[verify_agent_auth] = lambda: AuthContext(
            principal_id="auth0|attacker", method="auth0", agent_id=agent_id
        )
        forbidden = client.post(f"/v1/agents/{agent_id}/credentials/hmac/rotate")
        assert forbidden.status_code == 403, forbidden.text

        app.dependency_overrides[verify_agent_auth] = lambda: AuthContext(
            principal_id="auth0|owner", method="auth0", agent_id=agent_id
        )
        allowed = client.post(f"/v1/agents/{agent_id}/credentials/hmac/rotate")
        assert allowed.status_code == 200, allowed.text
        assert allowed.json()["hmac_secret"].startswith("sk_live_")

    app.dependency_overrides.clear()


def test_hmac_principal_can_only_rotate_itself() -> None:
    _reset_db()
    app.dependency_overrides[verify_user_auth] = lambda: _user_auth("auth0|owner")

    with TestClient(app) as client:
        agent_id = _create_agent(client, "rotation-agent")

        app.dependency_overrides[verify_agent_auth] = lambda: AuthContext(
            principal_id="agt_other", method="hmac", agent_id="agt_other"
        )
        forbidden = client.post(f"/v1/agents/{agent_id}/credentials/hmac/rotate")
        assert forbidden.status_code == 403, forbidden.text

        app.dependency_overrides[verify_agent_auth] = lambda: AuthContext(
            principal_id=agent_id, method="hmac", agent_id=agent_id
        )
        allowed = client.post(f"/v1/agents/{agent_id}/credentials/hmac/rotate")
        assert allowed.status_code == 200, allowed.text

    app.dependency_overrides.clear()
