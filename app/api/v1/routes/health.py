import logging

from fastapi import APIRouter, Header, HTTPException, status
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy import text
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import get_settings
from app.core.metrics import histogram_snapshot, render_prometheus, snapshot
from app.db.postgres import async_engine
from app.db.redis import redis_client

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


@router.get("/health")
async def liveness():
    return {"status": "ok"}


@router.get("/ready")
async def readiness():
    failures: dict[str, str] = {}

    try:
        async with AsyncSession(async_engine) as session:
            await session.execute(text("SELECT 1"))
    except Exception as exc:
        logger.warning("Readiness: postgres unhealthy", exc_info=exc)
        failures["postgres"] = str(exc)

    try:
        await redis_client.ping()
    except Exception as exc:
        logger.warning("Readiness: redis unhealthy", exc_info=exc)
        failures["redis"] = str(exc)

    if failures:
        return JSONResponse(status_code=503, content={"status": "degraded", "failures": failures})
    return {"status": "ready"}


def _authorize_metrics(authorization: str | None) -> None:
    settings = get_settings()
    token = settings.metrics_auth_token
    if not token:
        if settings.app_env.lower() == "dev":
            return
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="metrics endpoint requires METRICS_AUTH_TOKEN outside dev",
        )
    if authorization != f"Bearer {token}":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid metrics token")


@router.get("/metrics", response_class=PlainTextResponse)
async def prometheus_metrics(authorization: str | None = Header(default=None)):
    """Prometheus exposition. Counters are per-worker; Prometheus sums targets."""
    _authorize_metrics(authorization)
    return PlainTextResponse(render_prometheus(), media_type="text/plain; version=0.0.4")


@router.get("/metrics.json")
async def metrics_json(authorization: str | None = Header(default=None)):
    _authorize_metrics(authorization)
    return {"counters": snapshot(), "latency": histogram_snapshot()}
