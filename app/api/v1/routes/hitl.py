import hashlib
import hmac as _hmac
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse
from redis.asyncio import Redis
from sqlmodel import Session, select

from app.api.v1.schemas.hitl import HitlResolveRequest
from app.api.v1.schemas.spend import SpendRequest
from app.core.config import get_settings
from app.core.metrics import increment
from app.core.security import verify_hitl_webhook_signature
from app.db.postgres import get_session
from app.db.redis import get_redis
from app.models.dashboard_notification import DashboardNotification
from app.models.pending_spend import PendingSpend
from app.models.spend_audit_log import SpendAuditLog
from app.policy.checks.quantitative import commit_budget_spend
from app.services.hitl.sms_parser import parse_sms_decision
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

router = APIRouter(tags=["hitl"])


async def _resolve_pending(
    *,
    request_id: str,
    payload: HitlResolveRequest,
    session: Session,
    redis: Redis,
):
    pending = session.exec(select(PendingSpend).where(PendingSpend.request_id == request_id)).first()
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
        await commit_budget_spend(
            redis=redis,
            agent_id=original.agent_id,
            asset_type=original.asset_type,
            amount_cents=original.amount_cents,
        )
        audit = session.exec(
            select(SpendAuditLog).where(SpendAuditLog.request_id == request_id)
        ).first()
        if audit:
            audit.status = "APPROVED_BY_HUMAN_EXECUTED"
            audit.verdict = "SAFE"
        else:
            audit = SpendAuditLog(
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
            )
        session.add(audit)
    else:
        increment("hitl.decision.deny")
        original = pending.payload_json
        audit = session.exec(
            select(SpendAuditLog).where(SpendAuditLog.request_id == request_id)
        ).first()
        if audit:
            audit.status = "DENIED_BY_HUMAN"
            audit.verdict = "MALICIOUS"
        else:
            audit = SpendAuditLog(
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
            )
        session.add(audit)

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
    _: None = Depends(verify_hitl_webhook_signature),
    session: Session = Depends(get_session),
    redis: Redis = Depends(get_redis),
):
    return await _resolve_pending(request_id=request_id, payload=payload, session=session, redis=redis)


@router.post("/hitl/sms/inbound")
async def inbound_hitl_sms(
    request: Request,
    _: None = Depends(verify_hitl_webhook_signature),
    session: Session = Depends(get_session),
    redis: Redis = Depends(get_redis),
):
    form = await request.form()
    body = str(form.get("Body", "")).strip()
    from_phone = str(form.get("From", "")).strip()
    message_sid = str(form.get("MessageSid", "")).strip() or None

    parsed = parse_sms_decision(body)
    if not parsed:
        return Response(
            content=(
                "<Response><Message>"
                "Invalid command. Reply with APPROVE &lt;request_id&gt; or DENY &lt;request_id&gt;."
                "</Message></Response>"
            ),
            media_type="application/xml",
        )

    decision, request_id = parsed
    pending = session.exec(select(PendingSpend).where(PendingSpend.request_id == request_id)).first()
    if not pending:
        return Response(
            content="<Response><Message>Request ID not found.</Message></Response>",
            media_type="application/xml",
        )

    if (pending.hitl_contact or "").strip() != from_phone:
        return Response(
            content="<Response><Message>Phone number not authorized for this request.</Message></Response>",
            media_type="application/xml",
            status_code=status.HTTP_403_FORBIDDEN,
        )

    payload = HitlResolveRequest(
        decision=decision,
        resolver_id=f"sms:{from_phone}",
        channel="sms",
        provider_message_id=message_sid,
    )
    try:
        await _resolve_pending(request_id=request_id, payload=payload, session=session, redis=redis)
    except HTTPException as exc:
        return Response(
            content=f"<Response><Message>Unable to resolve request: {exc.detail}</Message></Response>",
            media_type="application/xml",
            status_code=exc.status_code,
        )

    return Response(
        content=f"<Response><Message>{decision} recorded for {request_id}.</Message></Response>",
        media_type="application/xml",
    )


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

