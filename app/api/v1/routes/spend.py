import logging
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Response, status
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.v1.schemas.spend import HitlChannel, SpendRequest
from app.core.config import get_settings
from app.core.metrics import increment
from app.core.security import AuthContext, ensure_agent_access, verify_agent_auth
from app.db.postgres import get_session
from app.db.redis import get_redis
from app.models.agent import Agent
from app.models.dashboard_notification import DashboardNotification
from app.models.pending_spend import PendingSpend
from app.models.spend_audit_log import SpendAuditLog
from app.models.user import User
from app.policy.checks.quantitative import (
    clear_reservation_marker,
    commit_budget_spend,
    finalize_budget_reservation,
    release_velocity_counters,
    rollback_budget_reservation,
    transaction_fingerprint,
    velocity_fingerprint,
)
from app.policy.engine import run_financial_triangulation
from app.policy.provenance import engine_provenance
from app.services.activity_log import append_agent_activity
from app.services.budget_reconciler import release_outstanding_reservation
from app.services.hitl.notifier import HitlNotifier
from app.services.idempotency import (
    cache_idempotent_response,
    claim_idempotency_slot,
    release_idempotency_slot,
)
from app.services.slm.client import get_semantic_client

logger = logging.getLogger(__name__)
router = APIRouter(tags=["spend"])

# Redis and Postgres failures are infrastructure, not verdicts.  Surfacing them
# as a 500 leaves the caller unable to tell "denied" from "engine broken", and
# invites a retry against a request that may already hold a reservation.
_DEPENDENCY_ERRORS = (RedisError, SQLAlchemyError)

# Velocity counters stay consumed when they are themselves the reason for the
# block — releasing them would immediately un-detect the loop that was found.
_VELOCITY_REASONS = {"LOOP_PATTERN_DETECTED", "DESTINATION_BURST_DETECTED"}

_HIGH_RISK_REASONS = {
    "BUDGET_DAILY_LIMIT_EXCEEDED",
    "DESTINATION_BURST_DETECTED",
    "VENDOR_DOMAIN_PHISHING_PATTERN",
    "SEMANTIC_MISMATCH_HIGH",
    "SEMANTIC_EVAL_UNAVAILABLE",
    "SEMANTIC_LABEL_SCORE_DISAGREEMENT",
    "GOAL_DRIFT_DETECTED",
    "GOAL_DRIFT_EVAL_UNAVAILABLE",
    "GOAL_DRIFT_LOW_CONFIDENCE",
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
        "SEMANTIC_EVAL_UNAVAILABLE",
        "SEMANTIC_LABEL_SCORE_DISAGREEMENT",
    },
    "check_d_goal_drift": {
        "GOAL_DRIFT_DETECTED",
        "GOAL_WITHIN_SCOPE",
        "GOAL_DRIFT_SKIPPED_NO_SCOPES",
        "GOAL_DRIFT_EVAL_UNAVAILABLE",
        "GOAL_DRIFT_LOW_CONFIDENCE",
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

    # A replay is a cached answer, not a second evaluation: counting it on the
    # original decision keeps verdict mix and block rates measuring decisions.
    original.idempotency_replay_count = (original.idempotency_replay_count or 0) + 1
    original.last_replayed_at = datetime.now(timezone.utc)
    session.add(original)
    increment("spend.idempotency.replay")
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


def _dependency_unavailable_body(exc: Exception) -> dict:
    return {
        "request_id": None,
        "status": "ENGINE_UNAVAILABLE",
        "verdict": None,
        "block_code": "ENGINE_DEPENDENCY_UNAVAILABLE",
        "reasons": ["ENGINE_DEPENDENCY_UNAVAILABLE"],
        "next_action": "RETRY_WITH_BACKOFF",
        "detail": (
            "The firewall could not reach a dependency and did not evaluate this "
            "transaction. This is not a verdict — retry with the same idempotency key."
        ),
        "dependency": "redis" if isinstance(exc, RedisError) else "postgres",
        "idempotency_replay": False,
        "idempotency_note": None,
    }


@router.post("/spend-request")
async def spend_request(
    payload: SpendRequest,
    response: Response,
    auth_context: AuthContext = Depends(verify_agent_auth),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
):
    try:
        return await _spend_request(
            payload=payload,
            response=response,
            auth_context=auth_context,
            session=session,
            redis=redis,
        )
    except _DEPENDENCY_ERRORS as exc:
        dependency = "redis" if isinstance(exc, RedisError) else "postgres"
        increment(f"spend.dependency_unavailable.{dependency}")
        logger.error(
            "Spend evaluation aborted: %s dependency unavailable",
            dependency,
            extra={"agent_id": payload.agent_id},
            exc_info=True,
        )
        try:
            await session.rollback()
        except Exception:
            logger.warning("Session rollback failed after dependency failure", exc_info=True)
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        response.headers["retry-after"] = "5"
        return _dependency_unavailable_body(exc)


async def _spend_request(
    *,
    payload: SpendRequest,
    response: Response,
    auth_context: AuthContext,
    session: AsyncSession,
    redis: Redis,
):
    await ensure_agent_access(session, auth_context, payload.agent_id)

    agent = (await session.exec(select(Agent).where(Agent.agent_id == payload.agent_id))).first()
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
    if agent.status != "ACTIVE":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Agent is not active")

    fingerprint = transaction_fingerprint(
        vendor=payload.vendor_url_or_name,
        amount_cents=payload.amount_cents,
        item_description=payload.item_description,
        asset_type=payload.asset_type,
        stablecoin_symbol=payload.stablecoin_symbol,
        network=payload.network,
        destination_address=payload.destination_address,
    )

    occupied = await claim_idempotency_slot(redis, payload.agent_id, payload.idempotency_key, fingerprint)
    if occupied is not None:
        if occupied.fingerprint is not None and occupied.fingerprint != fingerprint:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Idempotency key was already used for a different transaction. "
                    "Use a new key for a new transaction."
                ),
            )
        if occupied.state == "in_flight":
            response.headers["retry-after"] = "2"
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An identical request is still being evaluated. Retry shortly.",
            )

        cached = occupied.response or {}
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

    try:
        return await _decide_spend(
            payload=payload,
            response=response,
            agent=agent,
            session=session,
            redis=redis,
            fingerprint=fingerprint,
        )
    except Exception:
        # Never leave a claimed slot behind on failure — the agent must be able
        # to retry the same key immediately.
        try:
            await release_idempotency_slot(redis, payload.agent_id, payload.idempotency_key)
        except RedisError:
            logger.error("Could not release idempotency slot after failure", exc_info=True)
        raise


async def _decide_spend(
    *,
    payload: SpendRequest,
    response: Response,
    agent: Agent,
    session: AsyncSession,
    redis: Redis,
    fingerprint: str,
) -> dict:
    request_id = f"req_{uuid4().hex[:18]}"
    settings = get_settings()
    try:
        tri = await run_financial_triangulation(
            redis=redis,
            semantic_client=get_semantic_client(),
            agent=agent,
            amount_cents=payload.amount_cents,
            vendor_url_or_name=payload.vendor_url_or_name,
            item_description=payload.item_description,
            declared_goal=payload.declared_goal,
            asset_type=payload.asset_type,
            stablecoin_symbol=payload.stablecoin_symbol,
            network=payload.network,
            destination_address=payload.destination_address,
            currency=payload.currency,
            fingerprint=velocity_fingerprint(
                vendor=payload.vendor_url_or_name,
                asset_type=payload.asset_type,
                stablecoin_symbol=payload.stablecoin_symbol,
                network=payload.network,
                destination_address=payload.destination_address,
            ),
            reservation_id=request_id,
        )
    except Exception:
        # The reservation is taken first, so a failure anywhere later in the
        # evaluation would otherwise consume budget for a request that never
        # produced a decision.
        await _release_reservation_best_effort(redis, request_id)
        raise

    try:
        return await _record_decision(
            payload=payload,
            response=response,
            agent=agent,
            session=session,
            redis=redis,
            fingerprint=fingerprint,
            request_id=request_id,
            settings=settings,
            tri=tri,
        )
    except Exception:
        await _release_reservation_best_effort(redis, request_id)
        raise


async def _release_reservation_best_effort(redis: Redis, request_id: str) -> None:
    try:
        released = await release_outstanding_reservation(redis, request_id)
    except Exception:
        logger.error(
            "Could not release budget reservation after failed evaluation; "
            "the reconciler will pick it up",
            extra={"request_id": request_id},
            exc_info=True,
        )
        return
    if released:
        increment("budget.reservation.released_on_error")


async def _unwind_velocity(redis: Redis, tri) -> None:
    if _VELOCITY_REASONS & set(tri.reasons):
        return
    try:
        await release_velocity_counters(
            redis,
            tri.quantitative_result.get("loop_key"),
            tri.quantitative_result.get("burst_key"),
        )
    except Exception:
        logger.error("Velocity counter release failed", exc_info=True)


async def _record_decision(
    *,
    payload: SpendRequest,
    response: Response,
    agent: Agent,
    session: AsyncSession,
    redis: Redis,
    fingerprint: str,
    request_id: str,
    settings,
    tri,
) -> dict:
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
            engine_provenance=engine_provenance(),
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
                await finalize_budget_reservation(redis, tri.quantitative_result["budget_key"])
            else:
                await commit_budget_spend(
                    redis, payload.agent_id, payload.asset_type, payload.amount_cents,
                    agent.daily_budget_limit_cents, agent.currency,
                )
            await clear_reservation_marker(redis, tri.quantitative_result.get("reservation_marker_key"))
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
        await cache_idempotent_response(
            redis, payload.agent_id, payload.idempotency_key, {"_http_status": 200, "body": body}, fingerprint
        )
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
            engine_provenance=engine_provenance(),
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
                await rollback_budget_reservation(
                    redis,
                    tri.quantitative_result["budget_key"],
                    payload.amount_cents,
                    tri.quantitative_result.get("reservation_marker_key"),
                )
            except Exception:
                logger.error(
                    "Budget rollback failed after MALICIOUS verdict",
                    extra={"agent_id": payload.agent_id, "amount_cents": payload.amount_cents, "request_id": request_id},
                    exc_info=True,
                )
        await _unwind_velocity(redis, tri)
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
        await cache_idempotent_response(
            redis, payload.agent_id, payload.idempotency_key, {"_http_status": 403, "body": body}, fingerprint
        )
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
        engine_provenance=engine_provenance(),
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
            await rollback_budget_reservation(
                redis,
                tri.quantitative_result["budget_key"],
                payload.amount_cents,
                tri.quantitative_result.get("reservation_marker_key"),
            )
        except Exception:
            logger.error(
                "Budget rollback failed after SUSPICIOUS verdict",
                extra={"agent_id": payload.agent_id, "amount_cents": payload.amount_cents, "request_id": request_id},
                exc_info=True,
            )
    await _unwind_velocity(redis, tri)
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
    await cache_idempotent_response(
        redis, payload.agent_id, payload.idempotency_key, {"_http_status": 202, "body": body}, fingerprint
    )
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

    await ensure_agent_access(session, auth_context, audit.agent_id)

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

