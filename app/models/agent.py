from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import Column, JSON
from sqlmodel import Field, SQLModel


class Agent(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    agent_id: str = Field(index=True, unique=True, min_length=3, max_length=128)
    display_name: str = Field(default="Unnamed Agent", max_length=128)
    status: str = Field(default="ACTIVE", max_length=16)
    daily_budget_limit_cents: int = Field(default=100_000)
    per_txn_auto_approve_limit_cents: int = Field(default=10_000)
    currency: str = Field(default="USD", max_length=3)
    blocked_vendors: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    allowed_stablecoins: list[str] = Field(default_factory=lambda: ["USDC", "USDT"], sa_column=Column(JSON))
    allowed_networks: list[str] = Field(
        default_factory=lambda: ["ethereum", "base", "solana"], sa_column=Column(JSON)
    )
    allowed_destination_addresses: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    blocked_destination_addresses: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    hitl_phone_number: str | None = Field(default=None, max_length=64)
    hitl_phone_verified_at: datetime | None = Field(default=None)
    hitl_primary_channel: str = Field(default="dashboard", max_length=16)
    hitl_sms_fallback_high_risk: bool = Field(default=True)
    hitl_required_over_cents: int | None = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

