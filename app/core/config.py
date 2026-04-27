from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", case_sensitive=False)

    app_env: str = "dev"
    postgres_dsn: str = Field(default="sqlite:///./agentshield.db")
    redis_dsn: str = Field(default="redis://localhost:6379/0")
    slm_base_url: str = Field(default="http://localhost:11434")
    slm_model_name: str = Field(default="llama3:8b")
    hitl_sms_sender: str = Field(default="AgentShield")
    hitl_default_timeout_seconds: int = Field(default=600)
    loop_window_seconds: int = Field(default=60)
    loop_threshold: int = Field(default=5)
    api_auth_header: str = Field(default="x-agent-key")
    signature_tolerance_seconds: int = Field(default=300)
    jwt_algorithm: str = Field(default="HS256")
    jwt_secret: str = Field(default="dev-jwt-secret-change-me")
    jwt_audience: str = Field(default="agentshield-api")
    agent_hmac_secret: str = Field(default="dev-agent-hmac-secret-change-me")
    webhook_hmac_secret: str = Field(default="dev-webhook-hmac-secret-change-me")
    sms_provider: str = Field(default="stub")
    twilio_account_sid: str = Field(default="")
    twilio_auth_token: str = Field(default="")
    twilio_from_number: str = Field(default="")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

