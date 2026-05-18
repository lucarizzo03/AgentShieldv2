import hashlib
import hmac
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

import jwt
from fastapi import Header, HTTPException, Request, status
from fastapi.concurrency import run_in_threadpool
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import get_settings
from app.db.postgres import async_engine
from app.models.agent import Agent


@dataclass(slots=True)
class AuthContext:
    principal_id: str
    method: str
    agent_id: str | None = None
    claims: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class UserAuthContext:
    sub: str
    email: str | None
    display_name: str | None
    method: str = "auth0"
    agent_id: str | None = None
    claims: dict[str, Any] = field(default_factory=dict)


def _normalize_signature(signature: str) -> str:
    return signature.removeprefix("sha256=").strip().lower()


def _body_sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _validate_timestamp(timestamp: str, tolerance_seconds: int) -> None:
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid signature timestamp format",
        ) from exc
    now = datetime.now(timezone.utc)
    skew = abs((now - parsed.astimezone(timezone.utc)).total_seconds())
    if skew > tolerance_seconds:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Signature timestamp outside allowed tolerance",
        )


def _verify_hmac(secret: str, message: str, signature: str) -> bool:
    expected = hmac.new(secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, _normalize_signature(signature))


def _auth0_issuer() -> str:
    settings = get_settings()
    if settings.auth0_issuer:
        issuer = settings.auth0_issuer.strip()
        if not issuer.startswith("https://"):
            issuer = f"https://{issuer}"
        return issuer.rstrip("/") + "/"
    if settings.auth0_domain:
        domain = settings.auth0_domain.rstrip("/")
        if domain.startswith("https://"):
            return domain + "/"
        return f"https://{domain}/"
    return ""


@lru_cache(maxsize=1)
def _auth0_jwks_client(issuer: str) -> jwt.PyJWKClient:
    return jwt.PyJWKClient(f"{issuer.rstrip('/')}/.well-known/jwks.json")


def _verify_auth0_bearer(token: str) -> UserAuthContext:
    settings = get_settings()
    issuer = _auth0_issuer()
    if not issuer or not settings.auth0_audience:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Auth0 is not configured for this environment",
        )
    try:
        signing_key = _auth0_jwks_client(issuer).get_signing_key_from_jwt(token).key
        claims = jwt.decode(
            token,
            signing_key,
            algorithms=["RS256"],
            audience=settings.auth0_audience,
            issuer=issuer,
        )
    except jwt.InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Auth0 token",
        ) from exc
    sub = claims.get("sub")
    if not isinstance(sub, str) or not sub:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Auth0 token missing subject",
        )
    email = claims.get("email")
    display_name = claims.get("name") or claims.get("nickname")
    return UserAuthContext(
        sub=sub,
        email=email if isinstance(email, str) else None,
        display_name=display_name if isinstance(display_name, str) else None,
        method="auth0",
        claims=claims,
    )


async def _load_agent_hmac_secret(agent_id: str) -> str:
    async with AsyncSession(async_engine) as session:
        agent = (await session.exec(select(Agent).where(Agent.agent_id == agent_id))).first()
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unknown agent_id",
        )
    if not agent.hmac_secret:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Agent has no HMAC secret — rotate credentials first",
        )
    return agent.hmac_secret


async def verify_agent_auth(
    request: Request,
    authorization: str | None = Header(default=None),
    x_agent_id: str | None = Header(default=None),
    x_timestamp: str | None = Header(default=None),
    x_signature: str | None = Header(default=None),
) -> AuthContext:
    settings = get_settings()

    # Auth0 Bearer — accepted from dashboard operators and dev test buttons.
    # agent_id is taken from x-agent-id (unauthenticated claim; the spend route
    # validates it exists and is active before running checks).
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
        user_ctx = await run_in_threadpool(_verify_auth0_bearer, token)
        return AuthContext(principal_id=user_ctx.sub, method="auth0", agent_id=x_agent_id)

    # HMAC-SHA256 — signed by real agent SDK.
    if x_agent_id and x_timestamp and x_signature:
        _validate_timestamp(x_timestamp, settings.signature_tolerance_seconds)
        body_hash = _body_sha256(await request.body())
        canonical_message = "\n".join(
            [
                request.method.upper(),
                request.url.path,
                x_timestamp,
                body_hash,
                x_agent_id,
            ]
        )
        expected_secret = await _load_agent_hmac_secret(x_agent_id)

        if not _verify_hmac(expected_secret, canonical_message, x_signature):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid HMAC signature",
            )
        return AuthContext(principal_id=x_agent_id, method="hmac", agent_id=x_agent_id)

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Missing authentication. Provide an Auth0 Bearer token or HMAC signature headers (x-agent-id, x-timestamp, x-signature).",
    )


async def verify_user_auth(
    authorization: str | None = Header(default=None),
) -> UserAuthContext:
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
        return await run_in_threadpool(_verify_auth0_bearer, token)
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Missing user authentication. Provide Auth0 Bearer token.",
    )


async def verify_hitl_webhook_signature(
    request: Request,
    x_webhook_signature: str | None = Header(default=None),
    x_webhook_timestamp: str | None = Header(default=None),
) -> None:
    settings = get_settings()

    if not x_webhook_signature or not x_webhook_timestamp:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing webhook signature headers",
        )

    _validate_timestamp(x_webhook_timestamp, settings.signature_tolerance_seconds)
    body_hash = _body_sha256(await request.body())
    canonical_message = "\n".join(
        [
            request.method.upper(),
            request.url.path,
            x_webhook_timestamp,
            body_hash,
        ]
    )
    if not _verify_hmac(settings.webhook_hmac_secret, canonical_message, x_webhook_signature):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid webhook signature",
        )


async def verify_hitl_auth(
    request: Request,
    authorization: str | None = Header(default=None),
    x_webhook_signature: str | None = Header(default=None),
    x_webhook_timestamp: str | None = Header(default=None),
) -> None:
    """Accept either Auth0 Bearer (dashboard operators) or webhook HMAC (external integrations)."""
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
        await run_in_threadpool(_verify_auth0_bearer, token)
        return

    if x_webhook_signature and x_webhook_timestamp:
        settings = get_settings()
        _validate_timestamp(x_webhook_timestamp, settings.signature_tolerance_seconds)
        body_hash = _body_sha256(await request.body())
        canonical_message = "\n".join(
            [
                request.method.upper(),
                request.url.path,
                x_webhook_timestamp,
                body_hash,
            ]
        )
        if not _verify_hmac(settings.webhook_hmac_secret, canonical_message, x_webhook_signature):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid webhook signature",
            )
        return

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Provide an Auth0 Bearer token or webhook HMAC signature headers (x-webhook-signature + x-webhook-timestamp)",
    )
