import hashlib
import hmac as _hmac
import ipaddress
import logging
import socket
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import HTMLResponse
from redis.asyncio import Redis
from sqlmodel import Session, select

logger = logging.getLogger(__name__)

from app.api.v1.schemas.hitl import HitlResolveRequest
from app.api.v1.schemas.spend import SpendRequest
from app.core.config import get_settings
from app.core.metrics import increment
from app.core.security import verify_hitl_auth
from app.db.postgres import get_session
from app.db.redis import get_redis
from app.models.dashboard_notification import DashboardNotification
from app.models.pending_spend import PendingSpend
from app.models.spend_audit_log import SpendAuditLog
from app.policy.checks.quantitative import commit_budget_spend
from app.services.activity_log import append_agent_activity
from app.services.hitl.state_manager import apply_resolution, ensure_pending_is_resolvable


def _email_confirm_page(decision: str) -> str:
    approved = decision == "APPROVE"
    icon = "✓" if approved else "✕"
    color = "#16a34a" if approved else "#dc2626"
    label = "Approved" if approved else "Denied"
    sub = "The agent has been notified and will proceed." if approved else "The transaction has been blocked."
    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>AgentShield — {label}</title>
</head>
<body style="margin:0;padding:0;background:#0f172a;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;min-height:100vh;display:flex;align-items:center;justify-content:center">
  <div style="text-align:center;padding:40px 24px">
    <div style="width:80px;height:80px;border-radius:50%;background:{color};display:flex;align-items:center;justify-content:center;margin:0 auto 24px;font-size:40px;color:#fff;line-height:80px">{icon}</div>
    <h1 style="margin:0 0 10px;font-size:28px;font-weight:700;color:#ffffff">{label}</h1>
    <p style="margin:0;font-size:15px;color:#94a3b8">{sub}</p>
    <p style="margin:32px 0 0;font-size:12px;color:#475569">AgentShield</p>
  </div>
</body>
</html>"""


def _email_error_page(message: str) -> str:
    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>AgentShield — Error</title>
</head>
<body style="margin:0;padding:0;background:#0f172a;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;min-height:100vh;display:flex;align-items:center;justify-content:center">
  <div style="text-align:center;padding:40px 24px">
    <h1 style="margin:0 0 10px;font-size:24px;font-weight:700;color:#ffffff">Unable to Process</h1>
    <p style="margin:0;font-size:15px;color:#94a3b8">{message}</p>
    <p style="margin:32px 0 0;font-size:12px;color:#475569">AgentShield</p>
  </div>
</body>
</html>"""

_BLOCKED_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),
]


def _is_ssrf_blocked(url: str) -> bool:
    try:
        hostname = urlparse(url).hostname
        if not hostname:
            return True
        for _family, _type, _proto, _canonname, sockaddr in socket.getaddrinfo(hostname, None):
            ip = ipaddress.ip_address(sockaddr[0])
            if any(ip in net for net in _BLOCKED_NETWORKS):
                return True
        return False
    except Exception:
        return True


router = APIRouter(tags=["hitl"])


async def _resolve_pending(
    *,
    request_id: str,
    payload: HitlResolveRequest,
    session: Session,
    redis: Redis,
):
    pending = session.exec(
        select(PendingSpend).where(PendingSpend.request_id == request_id).with_for_update()
    ).first()
    if not pending:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pending request not found")

    try:
        ensure_pending_is_resolvable(pending)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    apply_resolution(pending, payload.decision, payload.resolver_id)

    if payload.decision == "APPROVE":
        increment("hitl.decision.approve")
        original = SpendRequest.model_validate(pending.payload_json)
        session.add(SpendAuditLog(
            request_id=request_id,
            agent_id=original.agent_id,
            declared_goal=original.declared_goal,
            amount_cents=original.amount_cents,
            currency=original.currency,
            asset_type=original.asset_type,
            stablecoin_symbol=original.stablecoin_symbol,
            network=original.network,
            destination_address=original.destination_address,
            vendor_url_or_name=original.vendor_url_or_name,
            item_description=original.item_description,
            quantitative_result=pending.verdict_snapshot.get("quantitative_result", {}),
            policy_result=pending.verdict_snapshot.get("policy_result", {}),
            semantic_result=pending.verdict_snapshot.get("semantic_result", {}),
            verdict="SAFE",
            status="APPROVED_BY_HUMAN_EXECUTED",
        ))
        append_agent_activity(
            session,
            agent_id=original.agent_id,
            event_type="HITL_APPROVED",
            event_payload={"request_id": request_id, "resolver_id": payload.resolver_id},
        )
    else:
        increment("hitl.decision.deny")
        original = pending.payload_json
        session.add(SpendAuditLog(
            request_id=request_id,
            agent_id=original["agent_id"],
            declared_goal=original["declared_goal"],
            amount_cents=original["amount_cents"],
            currency=original["currency"],
            asset_type=original["asset_type"],
            stablecoin_symbol=original.get("stablecoin_symbol"),
            network=original.get("network"),
            destination_address=original.get("destination_address"),
            vendor_url_or_name=original["vendor_url_or_name"],
            item_description=original["item_description"],
            quantitative_result=pending.verdict_snapshot.get("quantitative_result", {}),
            policy_result=pending.verdict_snapshot.get("policy_result", {}),
            semantic_result=pending.verdict_snapshot.get("semantic_result", {}),
            verdict="MALICIOUS",
            status="DENIED_BY_HUMAN",
        ))
        append_agent_activity(
            session,
            agent_id=original["agent_id"],
            event_type="HITL_DENIED",
            event_payload={"request_id": request_id, "resolver_id": payload.resolver_id},
        )

    notification = session.exec(
        select(DashboardNotification).where(DashboardNotification.request_id == request_id)
    ).first()
    if notification and notification.status in {"OPEN", "ACKED"}:
        notification.status = "RESOLVED"
        notification.acknowledged_by = payload.resolver_id
        notification.acknowledged_at = datetime.now(timezone.utc)
        notification.updated_at = datetime.now(timezone.utc)
        session.add(notification)

    session.add(pending)
    session.commit()

    if payload.decision == "APPROVE":
        try:
            await commit_budget_spend(
                redis=redis,
                agent_id=original.agent_id,
                asset_type=original.asset_type,
                amount_cents=original.amount_cents,
            )
        except Exception:
            logger.critical(
                "Budget commit failed after HITL approval — manual recovery required",
                extra={"agent_id": original.agent_id, "amount_cents": original.amount_cents, "request_id": request_id},
                exc_info=True,
            )

    callback_url = pending.payload_json.get("agent_callback_url")
    if callback_url:
        if _is_ssrf_blocked(callback_url):
            logger.warning("HITL callback blocked (SSRF)", extra={"request_id": request_id, "url": callback_url})
        else:
            callback_body = {
                "request_id": request_id,
                "decision": payload.decision,
                "status": "APPROVED_BY_HUMAN_EXECUTED" if payload.decision == "APPROVE" else "DENIED_BY_HUMAN",
                "verdict": "SAFE" if payload.decision == "APPROVE" else "MALICIOUS",
                "resolved_at": pending.resolved_at.isoformat() if pending.resolved_at else None,
            }
            try:
                async with httpx.AsyncClient() as client:
                    await client.post(callback_url, json=callback_body, timeout=10)
                logger.info("HITL callback delivered", extra={"request_id": request_id, "url": callback_url})
            except Exception as exc:
                logger.warning("HITL callback failed", extra={"request_id": request_id, "url": callback_url, "error": str(exc)})

    return {
        "request_id": request_id,
        "status": "RESOLVED",
        "decision": payload.decision,
        "resolved_at": pending.resolved_at,
    }


@router.post("/hitl/resolve/{request_id}")
async def resolve_hitl_request(
    request_id: str,
    payload: HitlResolveRequest,
    _: None = Depends(verify_hitl_auth),
    session: Session = Depends(get_session),
    redis: Redis = Depends(get_redis),
):
    return await _resolve_pending(request_id=request_id, payload=payload, session=session, redis=redis)



@router.get("/hitl/email-resolve/{request_id}", response_class=HTMLResponse)
async def email_resolve(
    request_id: str,
    decision: str,
    token: str,
    session: Session = Depends(get_session),
    redis: Redis = Depends(get_redis),
):
    settings = get_settings()
    decision = decision.upper()
    if decision not in ("APPROVE", "DENY"):
        return HTMLResponse(_email_error_page("Invalid decision."), status_code=400)

    expected = _hmac.new(
        settings.webhook_hmac_secret.encode(),
        f"{request_id}:{decision}".encode(),
        hashlib.sha256,
    ).hexdigest()
    if not _hmac.compare_digest(token, expected):
        return HTMLResponse(_email_error_page("This link is invalid or has expired."), status_code=403)

    payload = HitlResolveRequest(decision=decision, resolver_id="email-link", channel="email")
    try:
        await _resolve_pending(request_id=request_id, payload=payload, session=session, redis=redis)
    except HTTPException as exc:
        msg = "This request has already been resolved." if exc.status_code == 409 else exc.detail
        return HTMLResponse(_email_error_page(msg), status_code=exc.status_code)

    return HTMLResponse(_email_confirm_page(decision))

