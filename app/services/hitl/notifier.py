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
    reason_tags = "".join(
        f'<span style="display:inline-block;margin:0 6px 6px 0;padding:4px 10px;background:#f1f5f9;color:#475569;border-radius:4px;font-size:11px;font-family:monospace;letter-spacing:0.02em">{r}</span>'
        for r in reasons
    )
    return f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f8fafc;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f8fafc;padding:48px 0">
    <tr><td align="center">
      <table width="520" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:8px;border:1px solid #e2e8f0">

        <!-- Header -->
        <tr>
          <td style="padding:32px 40px 28px;border-bottom:1px solid #e2e8f0">
            <p style="margin:0 0 16px;font-size:12px;font-weight:600;color:#94a3b8;letter-spacing:0.1em;text-transform:uppercase">AgentShield</p>
            <p style="margin:0 0 4px;font-size:24px;font-weight:700;color:#0f172a;line-height:1.2">${amount_usd:.2f} <span style="color:#94a3b8;font-weight:400;font-size:18px">USD</span></p>
            <p style="margin:6px 0 0;font-size:14px;color:#64748b">Pending approval &mdash; payment to <strong style="color:#334155">{vendor}</strong></p>
          </td>
        </tr>

        <!-- Details -->
        <tr>
          <td style="padding:24px 40px;border-bottom:1px solid #e2e8f0">
            <table width="100%" cellpadding="0" cellspacing="0">
              <tr>
                <td style="padding:5px 0;width:96px;font-size:12px;color:#94a3b8;vertical-align:top;text-transform:uppercase;letter-spacing:0.06em;font-weight:500">Goal</td>
                <td style="padding:5px 0;font-size:13px;color:#334155;line-height:1.5">{goal}</td>
              </tr>
              <tr>
                <td style="padding:5px 0;font-size:12px;color:#94a3b8;vertical-align:top;text-transform:uppercase;letter-spacing:0.06em;font-weight:500">Item</td>
                <td style="padding:5px 0;font-size:13px;color:#334155;line-height:1.5">{item}</td>
              </tr>
              <tr>
                <td style="padding:5px 0;font-size:12px;color:#94a3b8;vertical-align:top;text-transform:uppercase;letter-spacing:0.06em;font-weight:500">Expires</td>
                <td style="padding:5px 0;font-size:13px;color:#334155">{expires_at}</td>
              </tr>
              <tr>
                <td style="padding:5px 0;font-size:12px;color:#94a3b8;vertical-align:top;text-transform:uppercase;letter-spacing:0.06em;font-weight:500">ID</td>
                <td style="padding:5px 0;font-size:11px;color:#94a3b8;font-family:monospace">{request_id}</td>
              </tr>
            </table>
          </td>
        </tr>

        <!-- Risk flags -->
        <tr>
          <td style="padding:20px 40px;border-bottom:1px solid #e2e8f0">
            <p style="margin:0 0 10px;font-size:12px;font-weight:500;color:#94a3b8;text-transform:uppercase;letter-spacing:0.08em">Risk flags</p>
            <div>{reason_tags}</div>
          </td>
        </tr>

        <!-- Buttons -->
        <tr>
          <td style="padding:28px 40px 32px">
            <table width="100%" cellpadding="0" cellspacing="0">
              <tr>
                <td style="padding-right:8px" width="50%">
                  <a href="{approve_url}" style="display:block;padding:13px 0;background:#0f172a;color:#ffffff;font-size:13px;font-weight:600;text-decoration:none;border-radius:6px;text-align:center;letter-spacing:0.02em">Approve</a>
                </td>
                <td style="padding-left:8px" width="50%">
                  <a href="{deny_url}" style="display:block;padding:13px 0;background:#ffffff;color:#dc2626;font-size:13px;font-weight:600;text-decoration:none;border-radius:6px;text-align:center;letter-spacing:0.02em;border:1px solid #fca5a5">Deny</a>
                </td>
              </tr>
            </table>
          </td>
        </tr>

      </table>

      <!-- Footer -->
      <table width="520" cellpadding="0" cellspacing="0" style="margin-top:20px">
        <tr>
          <td style="text-align:center;font-size:11px;color:#94a3b8;line-height:1.6">
            This request will expire automatically if no action is taken.<br>
            AgentShield &mdash; AI spend control
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
