import logging
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Response, status
from redis.asyncio import Redis
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.v1.schemas.spend import HitlChannel, SpendRequest
from app.core.config import get_settings
from app.core.metrics import increment
from app.core.security import AuthContext, verify_agent_auth
from app.db.postgres import get_session
from app.db.redis import get_redis
from app.models.agent import Agent
from app.models.dashboard_notification import DashboardNotification
from app.models.pending_spend import PendingSpend
from app.models.spend_audit_log import SpendAuditLog
from app.models.user import User
from app.policy.checks.quantitative import (
    commit_budget_spend,
    finalize_budget_reservation,
    rollback_budget_reservation,
    transaction_fingerprint,
)
from app.policy.engine import run_financial_triangulation
from app.services.activity_log import append_agent_activity
from app.services.hitl.notifier import HitlNotifier
from app.services.idempotency import cache_idempotent_response, read_cached_idempotent_response
from app.services.slm.client import AnthropicSemanticClient

logger = logging.getLogger(__name__)
router = APIRouter(tags=["spend"])

_HIGH_RISK_REASONS = {
    "BUDGET_DAILY_LIMIT_EXCEEDED",
    "DESTINATION_BURST_DETECTED",
    "VENDOR_DOMAIN_PHISHING_PATTERN",
    "SEMANTIC_MISMATCH_HIGH",
    "GOAL_DRIFT_DETECTED",
    "GOAL_DRIFT_EVAL_UNAVAILABLE",
}

_CHECK_REASON_GROUPS = {
    "check_a_quantitative": {
        "BUDGET_DAILY_LIMIT_EXCEEDED",
        "BUDGET_WITHIN_LIMIT",
        "LOOP_PATTERN_DETECTED",
        "NO_LOOP_PATTERN",
        "DESTINATION_BURST_DETECTED",
    },
    "check_b_policy": {
        "VENDOR_MATCHED_BLOCKLIST",
        "VENDOR_DOMAIN_PHISHING_PATTERN",
        "VENDOR_ALLOWED",
        "AMOUNT_OVER_AUTO_APPROVAL_THRESHOLD",
        "AMOUNT_WITHIN_AUTO_APPROVAL_THRESHOLD",
        "STABLECOIN_NOT_ALLOWED",
        "NETWORK_NOT_ALLOWED",
        "DESTINATION_ADDRESS_MISSING",
        "DESTINATION_DENYLISTED",
        "DESTINATION_NOT_ALLOWLISTED",
    },
    "check_c_semantic": {
        "SEMANTIC_MISMATCH_HIGH",
        "SEMANTIC_ALIGNMENT_WEAK",
        "SEMANTIC_ALIGNMENT_HIGH",
    },
    "check_d_goal_drift": {
        "GOAL_DRIFT_DETECTED",
        "GOAL_WITHIN_SCOPE",
        "GOAL_DRIFT_SKIPPED_NO_SCOPES",
        "GOAL_DRIFT_EVAL_UNAVAILABLE",
    },
}


def _is_high_risk_suspicious(reasons: list[str]) -> bool:
    return bool(_HIGH_RISK_REASONS & set(reasons))


def _build_agent_feedback(*, verdict: str, reasons: list[str], tri) -> dict:
    per_check_reasons = {
        check_name: [reason for reason in reasons if reason in known_reasons]
        for check_name, known_reasons in _CHECK_REASON_GROUPS.items()
    }
    suspicious_hits = [reason for reason in reasons if reason in _HIGH_RISK_REASONS]
    return {
        "verdict_summary": {
            "verdict": verdict,
            "hard_deny_detected": verdict == "MALICIOUS",
            "human_review_required": verdict == "SUSPICIOUS",
            "safe_to_execute": verdict == "SAFE",
        },
        "picked_up": {
            "reasons": reasons,
            "high_risk_flags": suspicious_hits,
            "checks_triggered": [check for check, check_reasons in per_check_reasons.items() if check_reasons],
        },
        "checks": {
            "check_a_quantitative": {
                "reasons": per_check_reasons["check_a_quantitative"],
                "context": tri.quantitative_result,
            },
            "check_b_policy": {
                "reasons": per_check_reasons["check_b_policy"],
                "context": tri.policy_result,
            },
            "check_c_semantic": {
                "reasons": per_check_reasons["check_c_semantic"],
                "context": tri.semantic_result,
            },
            "check_d_goal_drift": {
                "reasons": per_check_reasons["check_d_goal_drift"],
                "context": tri.goal_drift_result,
            },
        },
        "reason_counts": {
            "total": len(reasons),
            "matched_known_reasons": len(
                [reason for reason in reasons if any(reason in group for group in _CHECK_REASON_GROUPS.values())]
            ),
            "unclassified": len(
                [reason for reason in reasons if not any(reason in group for group in _CHECK_REASON_GROUPS.values())]
            ),
        },
    }


async def _record_idempotency_replay(session: AsyncSession, *, request_id: str) -> None:
    original = (await session.exec(
        select(SpendAuditLog)
        .where(SpendAuditLog.request_id == request_id)
        .order_by(SpendAuditLog.created_at.desc())
    )).first()
    if not original:
        return

    quantitative_result = deepcopy(original.quantitative_result or {})
    quantitative_result["idempotency_replay"] = True
    quantitative_result["idempotency_replay_at"] = datetime.now(timezone.utc).isoformat()

    replay_row = SpendAuditLog(
        request_id=original.request_id,
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
        quantitative_result=quantitative_result,
        policy_result=deepcopy(original.policy_result or {}),
        semantic_result=deepcopy(original.semantic_result or {}),
        goal_drift_result=deepcopy(original.goal_drift_result or {}),
        verdict=original.verdict,
        status=original.status,
    )
    session.add(replay_row)
    append_agent_activity(
        session,
        agent_id=original.agent_id,
        event_type="IDEMPOTENCY_REPLAY_RETURNED",
        event_payload={
            "request_id": original.request_id,
            "status": original.status,
            "verdict": original.verdict,
        },
    )
    await session.commit()


@router.post("/spend-request")
async def spend_request(
    payload: SpendRequest,
    response: Response,
    auth_context: AuthContext = Depends(verify_agent_auth),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
):
    if auth_context.agent_id and auth_context.agent_id != payload.agent_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Authenticated agent_id does not match request payload agent_id",
        )

    agent = (await session.exec(select(Agent).where(Agent.agent_id == payload.agent_id))).first()
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
    if agent.status != "ACTIVE":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Agent is not active")

    cached = await read_cached_idempotent_response(redis, payload.agent_id, payload.idempotency_key)
    if cached:
        response.status_code = int(cached.get("_http_status", 200))
        replay_body = dict(cached["body"])
        replay_body["idempotency_replay"] = True
        replay_body["idempotency_note"] = "Returned cached decision for this idempotency key. No new evaluation was performed."
        if replay_body.get("request_id"):
            await _record_idempotency_replay(session, request_id=str(replay_body["request_id"]))
        response.headers["x-idempotency-replay"] = "true"
        if replay_body.get("request_id"):
            response.headers["x-original-request-id"] = str(replay_body["request_id"])
        return replay_body

    request_id = f"req_{uuid4().hex[:18]}"
    fingerprint = transaction_fingerprint(
        vendor=payload.vendor_url_or_name,
        amount_cents=payload.amount_cents,
        item_description=payload.item_description,
        asset_type=payload.asset_type,
        stablecoin_symbol=payload.stablecoin_symbol,
        network=payload.network,
        destination_address=payload.destination_address,
    )

    settings = get_settings()
    tri = await run_financial_triangulation(
        redis=redis,
        semantic_client=AnthropicSemanticClient(),
        agent=agent,
        amount_cents=payload.amount_cents,
        vendor_url_or_name=payload.vendor_url_or_name,
        item_description=payload.item_description,
        declared_goal=payload.declared_goal,
        asset_type=payload.asset_type,
        stablecoin_symbol=payload.stablecoin_symbol,
        network=payload.network,
        destination_address=payload.destination_address,
        fingerprint=fingerprint,
    )

    now = datetime.now(timezone.utc)
    if tri.verdict == "SAFE":
        increment("spend.verdict.safe")
        audit = SpendAuditLog(
            request_id=request_id,
            agent_id=payload.agent_id,
            declared_goal=payload.declared_goal,
            amount_cents=payload.amount_cents,
            currency=payload.currency,
            asset_type=payload.asset_type,
            stablecoin_symbol=payload.stablecoin_symbol,
            network=payload.network,
            destination_address=payload.destination_address,
            vendor_url_or_name=payload.vendor_url_or_name,
            item_description=payload.item_description,
            quantitative_result=tri.quantitative_result,
            policy_result=tri.policy_result,
            semantic_result=tri.semantic_result,
            goal_drift_result=tri.goal_drift_result,
            verdict="SAFE",
            status="APPROVED_EXECUTED",
        )
        session.add(audit)
        append_agent_activity(
            session,
            agent_id=payload.agent_id,
            event_type="SPEND_SAFE_APPROVED",
            event_payload={
                "request_id": request_id,
                "amount_cents": payload.amount_cents,
                "currency": payload.currency,
                "vendor_url_or_name": payload.vendor_url_or_name,
                "reasons": tri.reasons,
            },
        )
        await session.commit()
        try:
            if tri.quantitative_result.get("budget_reserved", False):
                # Reservation was made atomically during the budget check — just refresh TTL.
                await finalize_budget_reservation(redis, payload.agent_id, payload.asset_type, payload.amount_cents)
            else:
                await commit_budget_spend(redis, payload.agent_id, payload.asset_type, payload.amount_cents)
        except Exception:
            logger.critical(
                "Budget commit failed after payment execution — manual recovery required",
                extra={"agent_id": payload.agent_id, "amount_cents": payload.amount_cents, "request_id": request_id},
                exc_info=True,
            )
        body = {
            "request_id": request_id,
            "status": "APPROVED_EXECUTED",
            "verdict": "SAFE",
            "approved_amount_cents": payload.amount_cents,
            "currency": payload.currency,
            "reasons": tri.reasons,
            "agent_feedback": _build_agent_feedback(verdict="SAFE", reasons=tri.reasons, tri=tri),
            "idempotency_replay": False,
            "idempotency_note": None,
        }
        await cache_idempotent_response(redis, payload.agent_id, payload.idempotency_key, {"_http_status": 200, "body": body})
        return body

    if tri.verdict == "MALICIOUS":
        increment("spend.verdict.malicious")
        audit = SpendAuditLog(
            request_id=request_id,
            agent_id=payload.agent_id,
            declared_goal=payload.declared_goal,
            amount_cents=payload.amount_cents,
            currency=payload.currency,
            asset_type=payload.asset_type,
            stablecoin_symbol=payload.stablecoin_symbol,
            network=payload.network,
            destination_address=payload.destination_address,
            vendor_url_or_name=payload.vendor_url_or_name,
            item_description=payload.item_description,
            quantitative_result=tri.quantitative_result,
            policy_result=tri.policy_result,
            semantic_result=tri.semantic_result,
            goal_drift_result=tri.goal_drift_result,
            verdict="MALICIOUS",
            status="BLOCKED",
        )
        session.add(audit)
        append_agent_activity(
            session,
            agent_id=payload.agent_id,
            event_type="SPEND_BLOCKED",
            event_payload={
                "request_id": request_id,
                "amount_cents": payload.amount_cents,
                "currency": payload.currency,
                "vendor_url_or_name": payload.vendor_url_or_name,
                "reasons": tri.reasons,
            },
        )
        await session.commit()
        if tri.quantitative_result.get("budget_reserved", False):
            try:
                await rollback_budget_reservation(redis, payload.agent_id, payload.asset_type, payload.amount_cents)
            except Exception:
                logger.error(
                    "Budget rollback failed after MALICIOUS verdict",
                    extra={"agent_id": payload.agent_id, "amount_cents": payload.amount_cents, "request_id": request_id},
                    exc_info=True,
                )
        body = {
            "request_id": request_id,
            "status": "BLOCKED",
            "verdict": "MALICIOUS",
            "block_code": "POLICY_HARD_DENY",
            "reasons": tri.reasons,
            "next_action": "DO_NOT_RETRY",
            "agent_feedback": _build_agent_feedback(verdict="MALICIOUS", reasons=tri.reasons, tri=tri),
            "idempotency_replay": False,
            "idempotency_note": None,
        }
        response.status_code = status.HTTP_403_FORBIDDEN
        await cache_idempotent_response(redis, payload.agent_id, payload.idempotency_key, {"_http_status": 403, "body": body})
        return body

    increment("spend.verdict.suspicious")

    pending = PendingSpend(
        request_id=request_id,
        agent_id=payload.agent_id,
        payload_json=payload.model_dump(mode="json"),
        verdict_snapshot={
            "verdict": tri.verdict,
            "reasons": tri.reasons,
            "quantitative_result": tri.quantitative_result,
            "policy_result": tri.policy_result,
            "semantic_result": tri.semantic_result,
            "goal_drift_result": tri.goal_drift_result,
        },
        state="WAITING_HUMAN",
        hitl_channel=HitlChannel.EMAIL_DASHBOARD.value,
        hitl_contact=None,
        expires_at=now + timedelta(seconds=settings.hitl_default_timeout_seconds),
    )
    notification = DashboardNotification(
        request_id=request_id,
        agent_id=payload.agent_id,
        category="HITL_PENDING",
        priority="HIGH" if _is_high_risk_suspicious(tri.reasons) else "NORMAL",
        status="OPEN",
        summary=(
            f"HITL review required for {payload.amount_cents} {payload.currency} "
            f"to {payload.vendor_url_or_name}"
        ),
        payload_json={
            "request_id": request_id,
            "verdict": "SUSPICIOUS",
            "reasons": tri.reasons,
            "declared_goal": payload.declared_goal,
            "amount_cents": payload.amount_cents,
            "currency": payload.currency,
            "vendor_url_or_name": payload.vendor_url_or_name,
            "item_description": payload.item_description,
            "asset_type": payload.asset_type,
            "stablecoin_symbol": payload.stablecoin_symbol,
            "network": payload.network,
            "destination_address": payload.destination_address,
            "quantitative_result": tri.quantitative_result,
            "policy_result": tri.policy_result,
            "semantic_result": tri.semantic_result,
            "goal_drift_result": tri.goal_drift_result,
            "expires_at": (now + timedelta(seconds=settings.hitl_default_timeout_seconds)).isoformat(),
        },
    )
    audit = SpendAuditLog(
        request_id=request_id,
        agent_id=payload.agent_id,
        declared_goal=payload.declared_goal,
        amount_cents=payload.amount_cents,
        currency=payload.currency,
        asset_type=payload.asset_type,
        stablecoin_symbol=payload.stablecoin_symbol,
        network=payload.network,
        destination_address=payload.destination_address,
        vendor_url_or_name=payload.vendor_url_or_name,
        item_description=payload.item_description,
        quantitative_result=tri.quantitative_result,
        policy_result=tri.policy_result,
        semantic_result=tri.semantic_result,
        goal_drift_result=tri.goal_drift_result,
        verdict="SUSPICIOUS",
        status="PENDING_HITL",
    )
    session.add(pending)
    session.add(notification)
    session.add(audit)
    append_agent_activity(
        session,
        agent_id=payload.agent_id,
        event_type="HITL_PENDING_CREATED",
        event_payload={
            "request_id": request_id,
            "amount_cents": payload.amount_cents,
            "currency": payload.currency,
            "vendor_url_or_name": payload.vendor_url_or_name,
            "reasons": tri.reasons,
            "expires_at": pending.expires_at.isoformat(),
        },
    )
    await session.commit()
    if tri.quantitative_result.get("budget_reserved", False):
        try:
            await rollback_budget_reservation(redis, payload.agent_id, payload.asset_type, payload.amount_cents)
        except Exception:
            logger.error(
                "Budget rollback failed after SUSPICIOUS verdict",
                extra={"agent_id": payload.agent_id, "amount_cents": payload.amount_cents, "request_id": request_id},
                exc_info=True,
            )
    owner_email: str | None = None
    if agent.owner_user_id:
        owner = (await session.exec(select(User).where(User.id == agent.owner_user_id))).first()
        if owner:
            owner_email = owner.email
    await HitlNotifier().send_notification(agent=agent, pending=pending, recipient_email=owner_email)

    body = {
        "request_id": request_id,
        "status": "PENDING_HITL",
        "verdict": "SUSPICIOUS",
        "hitl": {
            "state": "WAITING_HUMAN_REVIEW",
            "channel": HitlChannel.EMAIL_DASHBOARD.value,
            "requested_at": now,
            "expires_at": pending.expires_at,
        },
        "reasons": tri.reasons,
        "next_action": "AGENT_MUST_WAIT",
        "status_poll_url": f"{settings.api_public_url}/v1/spend-request/{request_id}/status",
        "poll_interval_seconds": 5,
        "agent_feedback": _build_agent_feedback(verdict="SUSPICIOUS", reasons=tri.reasons, tri=tri),
        "idempotency_replay": False,
        "idempotency_note": None,
    }
    response.status_code = status.HTTP_202_ACCEPTED
    await cache_idempotent_response(redis, payload.agent_id, payload.idempotency_key, {"_http_status": 202, "body": body})
    return body


@router.get("/spend-request/{request_id}/status")
async def get_spend_request_status(
    request_id: str,
    auth_context: AuthContext = Depends(verify_agent_auth),
    session: AsyncSession = Depends(get_session),
):
    audit = (await session.exec(
        select(SpendAuditLog)
        .where(SpendAuditLog.request_id == request_id)
        .order_by(SpendAuditLog.created_at.desc())
    )).first()
    if not audit:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found")

    if auth_context.agent_id and auth_context.agent_id != audit.agent_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    if audit.status == "APPROVED_BY_HUMAN_EXECUTED":
        return {
            "request_id": request_id,
            "status": "APPROVED_BY_HUMAN_EXECUTED",
            "verdict": "SAFE",
            "decision": "APPROVE",
            "resolved": True,
        }
    elif audit.status == "DENIED_BY_HUMAN":
        return {
            "request_id": request_id,
            "status": "DENIED_BY_HUMAN",
            "verdict": "MALICIOUS",
            "decision": "DENY",
            "resolved": True,
        }
    elif audit.status == "EXPIRED":
        return {
            "request_id": request_id,
            "status": "EXPIRED",
            "verdict": "SUSPICIOUS",
            "resolved": True,
        }
    else:
        pending = (await session.exec(select(PendingSpend).where(PendingSpend.request_id == request_id))).first()
        if not pending:
            return {
                "request_id": request_id,
                "status": "EXPIRED",
                "verdict": "SUSPICIOUS",
                "resolved": True,
            }
        return {
            "request_id": request_id,
            "status": "PENDING_HITL",
            "verdict": "SUSPICIOUS",
            "resolved": False,
            "expires_at": pending.expires_at,
        }

