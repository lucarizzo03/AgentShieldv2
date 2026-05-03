from functools import lru_cache

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", case_sensitive=False, extra="ignore")

    app_env: str = "dev"
    postgres_dsn: str = Field(
        default="sqlite:///./agentshield.db",
        validation_alias=AliasChoices("POSTGRES_DSN", "DATABASE_URL"),
    )
    redis_dsn: str = Field(
        default="redis://localhost:6379/0",
        validation_alias=AliasChoices("REDIS_DSN", "REDIS_URL"),
    )
    slm_model_name: str = Field(default="llama3:8b")
    hitl_default_timeout_seconds: int = Field(default=600)
    loop_window_seconds: int = Field(default=60)
    loop_threshold: int = Field(default=5)
    api_auth_header: str = Field(default="x-agent-key")
    signature_tolerance_seconds: int = Field(default=300)
    agent_hmac_secret: str = Field(default="dev-agent-hmac-secret-change-me")
    webhook_hmac_secret: str = Field(default="dev-webhook-hmac-secret-change-me")
    anthropic_api_key: str = Field(default="")
    sendgrid_api_key: str = Field(default="")
    hitl_email_from: str = Field(default="")
    hitl_email_to: str = Field(default="")
    api_public_url: str = Field(default="http://localhost:8000")
    auth0_domain: str = Field(default="")
    auth0_audience: str = Field(default="")
    auth0_issuer: str = Field(default="")
    dev_user_token: str = Field(default="dev-user-token")
    dev_user_sub: str = Field(default="dev-user-001")
    dev_user_email: str = Field(default="dev-user@example.com")

    @field_validator("postgres_dsn", mode="before")
    @classmethod
    def normalize_postgres_dsn(cls, value: str) -> str:
        if not isinstance(value, str):
            return value
        dsn = value.strip()
        if dsn.startswith("postgres://"):
            return "postgresql+psycopg://" + dsn[len("postgres://") :]
        if dsn.startswith("postgresql+psycopg2://"):
            return "postgresql+psycopg://" + dsn[len("postgresql+psycopg2://") :]
        if dsn.startswith("postgresql://"):
            return "postgresql+psycopg://" + dsn[len("postgresql://") :]
        return dsn


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

