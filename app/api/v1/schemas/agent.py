from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AgentCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_name: str = Field(min_length=3, max_length=128)
    daily_spend_limit_usd: int = Field(ge=1, le=1_000_000)
    per_transaction_limit_usd: int = Field(ge=1, le=1_000_000)
    auto_approve_under_usd: int = Field(ge=1, le=1_000_000)
    blocked_vendors: list[str] = Field(min_length=1)
    asset_type: Literal["STABLECOIN", "FIAT"]
    allowed_networks: list[str] = Field(default_factory=list)
    allowed_tokens: list[str] = Field(default_factory=list)


class AgentCreateResponse(BaseModel):
    agent_id: str
    hmac_secret: str
    display_name: str
    created_at: datetime


class AgentSummary(BaseModel):
    agent_id: str
    display_name: str
    status: str
    hitl_primary_channel: str


class AgentListResponse(BaseModel):
    agents: list[AgentSummary]

