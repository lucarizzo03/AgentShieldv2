from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import JSON
from sqlmodel import Column, Field, SQLModel


class AgentActivity(SQLModel, table=True):
    __tablename__ = "agent_activity"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    agent_id: str = Field(foreign_key="agent.agent_id", index=True, max_length=128)
    user_id: UUID | None = Field(default=None, foreign_key="users.id", index=True)
    event_type: str = Field(index=True, max_length=64)
    event_payload: dict = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), index=True)
