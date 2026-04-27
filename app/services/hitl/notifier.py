import hashlib
import hmac as _hmac
import logging
from datetime import datetime

import httpx

from app.core.config import get_settings
from app.models.agent import Agent
from app.models.pending_spend import PendingSpend

logger = logging.getLogger(__name__)


def _signed_url(public_url: str, secret: str, request_id: str, decision: str) -> str:
    token = _hmac.new(secret.encode(), f"{request_id}:{decision}".encode(), hashlib.sha256).hexdigest()
    return f"{public_url}/v1/hitl/email-resolve/{request_id}?decision={decision}&token={token}"


def _build_html(
    amount_usd: float,
    vendor: str,
    goal: str,
    item: str,
    reasons: list[str],
    expires_at: str,
    request_id: str,
    approve_url: str,
    deny_url: str,
) -> str:
    reason_pills = "".join(
        f'<span style="display:inline-block;margin:2px 4px 2px 0;padding:3px 10px;background:#fef3c7;color:#92400e;border-radius:12px;font-size:12px;font-family:monospace">{r}</span>'
        for r in reasons
    )
    return f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f4f4f5;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f4f5;padding:40px 0">
    <tr><td align="center">
      <table width="560" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 8px 24px rgba(0,0,0,0.10)">

        <!-- Header -->
        <tr>
          <td style="background:#0f172a;padding:28px 36px">
            <p style="margin:0;font-size:13px;color:#94a3b8;letter-spacing:0.08em;text-transform:uppercase">AgentShield</p>
            <h1 style="margin:6px 0 0;font-size:22px;font-weight:700;color:#ffffff">Approval Required</h1>
          </td>
        </tr>

        <!-- Amount -->
        <tr>
          <td style="padding:32px 36px 24px;border-bottom:1px solid #f1f5f9">
            <p style="margin:0 0 4px;font-size:13px;color:#94a3b8;text-transform:uppercase;letter-spacing:0.06em">Amount</p>
            <p style="margin:0;font-size:36px;font-weight:700;color:#0f172a">${amount_usd:.2f} <span style="font-size:18px;color:#64748b">USD</span></p>
            <p style="margin:8px 0 0;font-size:16px;color:#334155">to <strong>{vendor}</strong></p>
          </td>
        </tr>

        <!-- Details -->
        <tr>
          <td style="padding:24px 36px;border-bottom:1px solid #f1f5f9">
            <table width="100%" cellpadding="0" cellspacing="0">
              <tr>
                <td style="padding:6px 0;width:120px;font-size:13px;color:#94a3b8;vertical-align:top">Goal</td>
                <td style="padding:6px 0;font-size:14px;color:#1e293b">{goal}</td>
              </tr>
              <tr>
                <td style="padding:6px 0;font-size:13px;color:#94a3b8;vertical-align:top">Item</td>
                <td style="padding:6px 0;font-size:14px;color:#1e293b">{item}</td>
              </tr>
              <tr>
                <td style="padding:6px 0;font-size:13px;color:#94a3b8;vertical-align:top">Request ID</td>
                <td style="padding:6px 0;font-size:13px;color:#1e293b;font-family:monospace">{request_id}</td>
              </tr>
              <tr>
                <td style="padding:6px 0;font-size:13px;color:#94a3b8;vertical-align:top">Expires</td>
                <td style="padding:6px 0;font-size:13px;color:#1e293b">{expires_at}</td>
              </tr>
            </table>
          </td>
        </tr>

        <!-- Reasons -->
        <tr>
          <td style="padding:20px 36px;border-bottom:1px solid #f1f5f9">
            <p style="margin:0 0 10px;font-size:13px;color:#94a3b8;text-transform:uppercase;letter-spacing:0.06em">Risk Flags</p>
            <div>{reason_pills}</div>
          </td>
        </tr>

        <!-- CTA -->
        <tr>
          <td style="padding:28px 36px">
            <p style="margin:0 0 20px;font-size:14px;color:#475569">Tap to decide — the agent is paused until you respond:</p>
            <table cellpadding="0" cellspacing="0">
              <tr>
                <td style="padding-right:12px">
                  <a href="{approve_url}" style="display:inline-block;padding:14px 32px;background:#16a34a;color:#ffffff;font-size:15px;font-weight:600;text-decoration:none;border-radius:8px">Approve</a>
                </td>
                <td>
                  <a href="{deny_url}" style="display:inline-block;padding:14px 32px;background:#dc2626;color:#ffffff;font-size:15px;font-weight:600;text-decoration:none;border-radius:8px">Deny</a>
                </td>
              </tr>
            </table>
            <p style="margin:20px 0 0;font-size:12px;color:#94a3b8">Each link is single-use and tied to this request only.</p>
          </td>
        </tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""


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
        raw_expires = pending.expires_at
        if isinstance(raw_expires, datetime):
            expires_at = raw_expires.strftime("%b %d, %Y at %I:%M %p UTC")
        else:
            expires_at = str(raw_expires)

        approve_url = _signed_url(settings.api_public_url, settings.webhook_hmac_secret, pending.request_id, "APPROVE")
        deny_url = _signed_url(settings.api_public_url, settings.webhook_hmac_secret, pending.request_id, "DENY")

        subject = f"[AgentShield] Approval Required — ${amount_usd:.2f} to {vendor}"
        html = _build_html(amount_usd, vendor, goal, item, reasons, expires_at, pending.request_id, approve_url, deny_url)
        plain = (
            f"Approval required: ${amount_usd:.2f} to {vendor}\n"
            f"Goal: {goal}\nItem: {item}\n"
            f"Request ID: {pending.request_id}\n"
            f"Flags: {', '.join(reasons)}\n"
            f"Expires: {expires_at}\n\n"
            f"APPROVE: {approve_url}\n"
            f"DENY:    {deny_url}\n"
        )

        payload = {
            "personalizations": [{"to": [{"email": settings.hitl_email_to}]}],
            "from": {"email": settings.hitl_email_from or settings.hitl_email_to},
            "subject": subject,
            "content": [
                {"type": "text/plain", "value": plain},
                {"type": "text/html", "value": html},
            ],
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
