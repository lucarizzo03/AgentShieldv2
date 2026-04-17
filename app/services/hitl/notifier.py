import logging

from app.models.agent import Agent
from app.models.pending_spend import PendingSpend

logger = logging.getLogger(__name__)


class HitlNotifier:
    async def send_sms(self, agent: Agent, pending: PendingSpend) -> None:
        # Placeholder integration; replace with Twilio/MessageBird webhook provider.
        logger.info(
            "HITL SMS sent",
            extra={
                "agent_id": agent.agent_id,
                "request_id": pending.request_id,
                "phone": agent.hitl_phone_number,
            },
        )

