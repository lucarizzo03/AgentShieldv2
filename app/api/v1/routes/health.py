import asyncio
import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlmodel import Session, text

from app.db.postgres import engine
from app.db.redis import redis_client

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


@router.get("/health")
async def liveness():
    return {"status": "ok"}


@router.get("/ready")
async def readiness():
    failures: dict[str, str] = {}

    def _check_postgres() -> None:
        with Session(engine) as session:
            session.exec(text("SELECT 1"))

    try:
        await asyncio.to_thread(_check_postgres)
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
