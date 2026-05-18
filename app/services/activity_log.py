from datetime import datetime, timezone
from uuid import UUID

from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.agent_activity import AgentActivity


def append_agent_activity(
    session: AsyncSession,
    *,
    agent_id: str,
    event_type: str,
    event_payload: dict | None = None,
    user_id: UUID | None = None,
) -> None:
    activity = AgentActivity(
        agent_id=agent_id,
        user_id=user_id,
        event_type=event_type,
        event_payload=event_payload or {},
        created_at=datetime.now(timezone.utc),
    )
    session.add(activity)
