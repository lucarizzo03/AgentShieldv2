from fastapi.testclient import TestClient
from sqlmodel import SQLModel

from app.core.security import UserAuthContext, verify_user_auth
from app.db.postgres import engine
from app.main import app


def _reset_db() -> None:
    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)


def _mock_user_auth() -> UserAuthContext:
    return UserAuthContext(
        sub="auth0|settings_user",
        email="settings@example.com",
        display_name="Settings User",
        method="auth0",
    )


def test_update_agent_settings_roundtrip() -> None:
    _reset_db()
    app.dependency_overrides[verify_user_auth] = _mock_user_auth

    create_payload = {
        "agent_name": "settings-agent",
        "daily_spend_limit_usd": 500,
        "per_transaction_limit_usd": 200,
        "auto_approve_under_usd": 25,
        "blocked_vendors": ["bad.example"],
        "asset_type": "STABLECOIN",
        "allowed_networks": ["base"],
        "allowed_tokens": ["USDC"],
        "allowed_scopes": ["travel booking"],
    }

    with TestClient(app) as client:
        create_resp = client.post("/v1/agents", json=create_payload, headers={"Authorization": "Bearer mocked"})
        assert create_resp.status_code == 200, create_resp.text
        agent_id = create_resp.json()["agent_id"]

        update_payload = {
            "agent_name": "settings-agent-updated",
            "daily_spend_limit_usd": 900,
            "per_transaction_limit_usd": 300,
            "auto_approve_under_usd": 40,
            "blocked_vendors": ["evil.example", "risky.example"],
            "allowed_networks": ["base", "polygon"],
            "allowed_tokens": ["USDC", "USDT"],
            "allowed_scopes": ["travel booking", "vendor procurement"],
        }
        update_resp = client.patch(f"/v1/agents/{agent_id}", json=update_payload, headers={"Authorization": "Bearer mocked"})
        assert update_resp.status_code == 200, update_resp.text

        list_resp = client.get("/v1/agents", headers={"Authorization": "Bearer mocked"})
        assert list_resp.status_code == 200, list_resp.text
        listed = list_resp.json()["agents"][0]
        assert listed["display_name"] == "settings-agent-updated"
        assert listed["daily_spend_limit_usd"] == 900
        assert listed["per_transaction_limit_usd"] == 300
        assert listed["auto_approve_under_usd"] == 40
        assert listed["blocked_vendors"] == ["evil.example", "risky.example"]
        assert listed["allowed_networks"] == ["base", "polygon"]
        assert listed["allowed_tokens"] == ["USDC", "USDT"]
        assert listed["allowed_scopes"] == ["travel booking", "vendor procurement"]

    app.dependency_overrides.clear()
