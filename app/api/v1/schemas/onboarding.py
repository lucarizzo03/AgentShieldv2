from pydantic import BaseModel, ConfigDict, Field


class OnboardingBootstrapRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_name: str = Field(min_length=2, max_length=128)
    email: str = Field(min_length=5, max_length=256)
    agent_name: str = Field(min_length=3, max_length=128)
    daily_spend_limit_usd: int = Field(default=500, ge=1, le=1_000_000)
    per_transaction_limit_usd: int = Field(default=100, ge=1, le=1_000_000)
    auto_approve_under_usd: int = Field(default=25, ge=1, le=1_000_000)
    allowed_networks: list[str] = Field(default_factory=lambda: ["base"])
    allowed_tokens: list[str] = Field(default_factory=lambda: ["USDC"])
    blocked_vendors: list[str] = Field(default_factory=lambda: ["badvendor.example"])


class OnboardingBootstrapResponse(BaseModel):
    user_name: str
    email: str
    agent_id: str
    display_name: str
    hmac_secret: str
    next_steps: list[str]
    quickstart_curl: str


class OnboardingChecklistResponse(BaseModel):
    agent_id: str
    agent_created: bool
    first_transaction_submitted: bool
    human_decision_made: bool
    ready_for_live: bool
