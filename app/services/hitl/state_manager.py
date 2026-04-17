from datetime import datetime, timezone

from app.models.pending_spend import PendingSpend


def ensure_pending_is_resolvable(pending: PendingSpend) -> None:
    if pending.state != "WAITING_HUMAN":
        raise ValueError("Pending spend is already resolved")
    expires_at = pending.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= datetime.now(timezone.utc):
        raise ValueError("Pending spend expired")


def apply_resolution(pending: PendingSpend, decision: str, resolver_id: str) -> PendingSpend:
    pending.state = "APPROVED" if decision == "APPROVE" else "DENIED"
    pending.resolver_id = resolver_id
    pending.resolved_at = datetime.now(timezone.utc)
    return pending

