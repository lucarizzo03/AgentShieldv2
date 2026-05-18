import asyncio
import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlmodel.ext.asyncio.session import AsyncSession

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
