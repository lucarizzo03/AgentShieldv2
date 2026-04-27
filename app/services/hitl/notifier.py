import logging

import httpx

from app.core.config import get_settings
from app.models.agent import Agent
from app.models.pending_spend import PendingSpend

logger = logging.getLogger(__name__)


class HitlNotifier:
    async def send_notification(self, agent: Agent, pending: PendingSpend) -> None:
        settings = get_settings()
        if not settings.sendgrid_api_key or not settings.hitl_email_to:
            logger.info(
                "HITL email skipped (SendGrid not configured)",
                extra={"agent_id": agent.agent_id, "request_id": pending.request_id},
            )
            return

        amount_usd = pending.payload_json.get("amount_cents", 0) / 100
        vendor = pending.payload_json.get("vendor_url_or_name", "unknown")
        goal = pending.payload_json.get("declared_goal", "")
        item = pending.payload_json.get("item_description", "")
        reasons = pending.verdict_snapshot.get("reasons", [])
        expires_at = str(pending.expires_at)

        subject = f"[AgentShield] Approval Required — ${amount_usd:.2f} to {vendor}"
        body = (
            f"A spend request requires your review.\n\n"
            f"Amount:     ${amount_usd:.2f} USD\n"
            f"Vendor:     {vendor}\n"
            f"Goal:       {goal}\n"
            f"Item:       {item}\n\n"
            f"Request ID: {pending.request_id}\n"
            f"Verdict:    SUSPICIOUS\n"
            f"Reasons:    {', '.join(reasons)}\n"
            f"Expires:    {expires_at}\n\n"
            f"Approve or deny from the dashboard at http://localhost:5173\n\n"
            f"Or via API:\n"
            f"  APPROVE: POST /v1/hitl/resolve/{pending.request_id}\n"
            f'           {{"decision": "APPROVE", "resolver_id": "human", "channel": "dashboard"}}\n'
            f"  DENY:    POST /v1/hitl/resolve/{pending.request_id}\n"
            f'           {{"decision": "DENY", "resolver_id": "human", "channel": "dashboard"}}\n'
        )

        payload = {
            "personalizations": [{"to": [{"email": settings.hitl_email_to}]}],
            "from": {"email": settings.hitl_email_from or settings.hitl_email_to},
            "subject": subject,
            "content": [{"type": "text/plain", "value": body}],
        }

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://api.sendgrid.com/v3/mail/send",
                json=payload,
                headers={"Authorization": f"Bearer {settings.sendgrid_api_key}"},
                timeout=10,
            )

        if resp.status_code in (200, 202):
            logger.info(
                "HITL email sent via SendGrid",
                extra={"agent_id": agent.agent_id, "request_id": pending.request_id, "to": settings.hitl_email_to},
            )
        else:
            logger.error(
                "HITL email failed",
                extra={"agent_id": agent.agent_id, "status": resp.status_code, "body": resp.text},
            )
