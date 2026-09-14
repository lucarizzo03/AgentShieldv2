import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

from redis.asyncio import Redis
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import get_settings
from app.core.metrics import increment
from app.db.postgres import async_engine
from app.db.redis import redis_client
from app.models.spend_audit_log import SpendAuditLog
from app.policy.checks.quantitative import (
    RESERVATION_MARKER_PREFIX,
    reservation_marker_key,
    rollback_budget_reservation,
)

logger = logging.getLogger(__name__)

_RECONCILE_LOCK_KEY = "lock:budget:reconciler"


async def release_outstanding_reservation(redis: Redis, reservation_id: str) -> bool:
    """Releases the budget a request reserved, using the marker written at
    reserve time rather than a recomputed key.  Returns whether anything was
    released; a missing marker means the reservation already reached a terminal
    state."""
    marker_key = reservation_marker_key(reservation_id)
    raw = await redis.get(marker_key)
    if not raw:
        return False
    try:
        marker = json.loads(raw)
        budget_key = marker["budget_key"]
        amount_cents = int(marker["amount_cents"])
    except (ValueError, KeyError, TypeError):
        logger.error("Unparseable budget reservation marker %s: %r", marker_key, raw)
        await redis.delete(marker_key)
        return False

    await rollback_budget_reservation(redis, budget_key, amount_cents, marker_key)
    return True


async def reconcile_once() -> int:
    """Releases reservations left behind by requests that never reached a
    decision — a worker restart or an unhandled error between reserve and
    rollback.  Returns the number of reservations released.

    A marker whose request did record an audit row is dropped without touching
    the counter: that path already finalized or rolled back the reservation
    itself.  Markers younger than the grace period are left alone because the
    request may still be in flight.
    """
    settings = get_settings()
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=settings.budget_reservation_grace_seconds)
    released = 0

    async for marker_key in redis_client.scan_iter(match=f"{RESERVATION_MARKER_PREFIX}*", count=100):
        raw = await redis_client.get(marker_key)
        if not raw:
            continue
        try:
            marker = json.loads(raw)
            reserved_at = datetime.fromisoformat(marker["reserved_at"])
        except (ValueError, KeyError, TypeError):
            logger.error("Dropping unparseable budget reservation marker %s", marker_key)
            await redis_client.delete(marker_key)
            continue
        if reserved_at > cutoff:
            continue

        request_id = marker_key.removeprefix(RESERVATION_MARKER_PREFIX)
        async with AsyncSession(async_engine) as session:
            decided = (await session.exec(
                select(SpendAuditLog).where(SpendAuditLog.request_id == request_id)
            )).first()

        if decided:
            await redis_client.delete(marker_key)
            continue

        await rollback_budget_reservation(
            redis_client, marker["budget_key"], int(marker["amount_cents"]), marker_key
        )
        released += 1
        increment("budget.reservation.reconciled")
        logger.warning(
            "Released abandoned budget reservation",
            extra={
                "request_id": request_id,
                "agent_id": marker.get("agent_id"),
                "amount_cents": marker.get("amount_cents"),
            },
        )

    return released


async def run_budget_reconciler() -> None:
    """Background task: release abandoned budget reservations.

    Guarded by the same short-lived Redis lock pattern as the HITL expiry
    sweeper so only one worker reconciles per interval.
    """
    interval = get_settings().budget_reconcile_interval_seconds
    logger.info("Budget reservation reconciler started (interval=%ds)", interval)
    while True:
        await asyncio.sleep(interval)
        try:
            acquired = await redis_client.set(_RECONCILE_LOCK_KEY, "1", ex=interval, nx=True)
            if not acquired:
                continue
            try:
                released = await reconcile_once()
            finally:
                await redis_client.delete(_RECONCILE_LOCK_KEY)
            if released:
                logger.warning("Reconciled %d abandoned budget reservation(s)", released)
        except Exception:
            logger.exception("Budget reservation reconciliation failed")
