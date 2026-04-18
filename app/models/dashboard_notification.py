from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import Column, JSON
from sqlmodel import Field, SQLModel


class DashboardNotification(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    request_id: str = Field(index=True, max_length=64)
    agent_id: str = Field(index=True, max_length=128)
    category: str = Field(default="HITL_PENDING", max_length=32)
    priority: str = Field(default="NORMAL", max_length=16)
    status: str = Field(default="OPEN", index=True, max_length=16)
    summary: str = Field(max_length=512)
    payload_json: dict = Field(default_factory=dict, sa_column=Column(JSON))
    acknowledged_by: str | None = Field(default=None, max_length=128)
    acknowledged_at: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), index=True)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

