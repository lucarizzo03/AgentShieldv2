import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_non_dev_rejects_default_webhook_secret() -> None:
    with pytest.raises(ValidationError):
        Settings(
            app_env="prod",
            webhook_hmac_secret="dev-webhook-hmac-secret-change-me",
        )


def test_dev_allows_default_webhook_secret() -> None:
    settings = Settings(
        app_env="dev",
        webhook_hmac_secret="dev-webhook-hmac-secret-change-me",
    )
    assert settings.webhook_hmac_secret == "dev-webhook-hmac-secret-change-me"


def test_non_dev_allows_non_default_webhook_secret() -> None:
    settings = Settings(
        app_env="prod",
        webhook_hmac_secret="replace-with-strong-secret",
    )
    assert settings.webhook_hmac_secret == "replace-with-strong-secret"
