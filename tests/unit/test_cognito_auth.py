from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.core import security


class _FakeSigningKey:
    key = "fake-signing-key"


class _FakeJWKSClient:
    def get_signing_key_from_jwt(self, token: str) -> _FakeSigningKey:
        return _FakeSigningKey()


def _configure_cognito(monkeypatch: pytest.MonkeyPatch, *, app_client_id: str = "client-abc") -> None:
    fake_settings = SimpleNamespace(
        cognito_region="us-east-1",
        cognito_user_pool_id="us-east-1_example",
        cognito_app_client_id=app_client_id,
    )
    monkeypatch.setattr(security, "get_settings", lambda: fake_settings)
    monkeypatch.setattr(security, "_cognito_jwks_client", lambda issuer: _FakeJWKSClient())


def _mock_claims(monkeypatch: pytest.MonkeyPatch, claims: dict) -> None:
    monkeypatch.setattr(security.jwt, "decode", lambda *args, **kwargs: claims)


def test_verify_cognito_bearer_accepts_valid_access_token(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_cognito(monkeypatch)
    _mock_claims(
        monkeypatch,
        {"sub": "cognito-sub-123", "token_use": "access", "client_id": "client-abc"},
    )

    ctx = security._verify_cognito_bearer("fake-token")

    assert ctx.sub == "cognito-sub-123"
    assert ctx.method == "cognito"
    assert ctx.email is None
    assert ctx.display_name is None


def test_verify_cognito_bearer_rejects_id_token(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_cognito(monkeypatch)
    _mock_claims(
        monkeypatch,
        {"sub": "cognito-sub-123", "token_use": "id", "client_id": "client-abc"},
    )

    with pytest.raises(HTTPException) as exc_info:
        security._verify_cognito_bearer("fake-token")
    assert exc_info.value.status_code == 401


def test_verify_cognito_bearer_rejects_wrong_client_id(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_cognito(monkeypatch)
    _mock_claims(
        monkeypatch,
        {"sub": "cognito-sub-123", "token_use": "access", "client_id": "some-other-client"},
    )

    with pytest.raises(HTTPException) as exc_info:
        security._verify_cognito_bearer("fake-token")
    assert exc_info.value.status_code == 401


def test_verify_cognito_bearer_service_unavailable_when_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_settings = SimpleNamespace(
        cognito_region="",
        cognito_user_pool_id="",
        cognito_app_client_id="",
    )
    monkeypatch.setattr(security, "get_settings", lambda: fake_settings)

    with pytest.raises(HTTPException) as exc_info:
        security._verify_cognito_bearer("fake-token")
    assert exc_info.value.status_code == 503
