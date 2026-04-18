import logging

from app.core.config import get_settings
from app.models.agent import Agent
from app.models.pending_spend import PendingSpend

logger = logging.getLogger(__name__)


class HitlNotifier:
    async def send_sms(self, agent: Agent, pending: PendingSpend) -> None:
        settings = get_settings()
        message = (
            "AgentShield approval required.\n"
            f"Request ID: {pending.request_id}\n"
            f"Amount: {pending.payload_json.get('amount_cents')} {pending.payload_json.get('currency')}\n"
            f"Vendor: {pending.payload_json.get('vendor_url_or_name')}\n"
            "Reply with: APPROVE <request_id> or DENY <request_id>"
        )

        if settings.sms_provider.lower() != "stub":
            raise RuntimeError(
                "Unsupported SMS provider. Use SMS_PROVIDER=stub or implement a new provider adapter."
            )

        # Default stub logger mode for local/dev and provider-agnostic wiring.
        logger.info(
            "HITL SMS sent",
            extra={
                "agent_id": agent.agent_id,
                "request_id": pending.request_id,
                "phone": agent.hitl_phone_number,
                "body": message,
            },
        )
