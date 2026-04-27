import logging

from app.core.config import get_settings
from app.models.agent import Agent
from app.models.pending_spend import PendingSpend

logger = logging.getLogger(__name__)


class HitlNotifier:
    async def send_sms(self, agent: Agent, pending: PendingSpend) -> None:
        settings = get_settings()
        amount_usd = pending.payload_json.get("amount_cents", 0) / 100
        vendor = pending.payload_json.get("vendor_url_or_name", "unknown")
        message = (
            f"AgentShield: approval required.\n"
            f"${amount_usd:.2f} to {vendor}\n"
            f"Reply: APPROVE {pending.request_id} or DENY {pending.request_id}"
        )

        if settings.sms_provider.lower() == "twilio":
            from twilio.rest import Client
            client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
            client.messages.create(
                body=message,
                from_=settings.twilio_from_number,
                to=agent.hitl_phone_number,
            )
            logger.info("HITL SMS sent via Twilio", extra={"agent_id": agent.agent_id, "request_id": pending.request_id})
            return

        logger.info(
            "HITL SMS sent (stub)",
            extra={
                "agent_id": agent.agent_id,
                "request_id": pending.request_id,
                "phone": agent.hitl_phone_number,
                "body": message,
            },
        )
