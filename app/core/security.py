from fastapi import Header, HTTPException, status

from app.core.config import get_settings


async def verify_agent_auth(x_agent_key: str | None = Header(default=None)) -> None:
    settings = get_settings()
    if x_agent_key is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing agent key")

    # Greenfield default: any non-empty key in dev, replace with HMAC/JWT in production.
    if settings.app_env != "dev" and len(x_agent_key.strip()) < 12:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid agent key")


async def verify_hitl_webhook_signature(x_webhook_signature: str | None = Header(default=None)) -> None:
    if x_webhook_signature is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing webhook signature")

