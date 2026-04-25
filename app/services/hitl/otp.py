import hmac
import json
import logging
import secrets

from redis.asyncio import Redis

logger = logging.getLogger(__name__)

OTP_TTL_SECONDS = 300
MAX_VERIFY_ATTEMPTS = 5


def _otp_key(agent_id: str) -> str:
    return f"otp:phone:{agent_id}"


def _attempt_key(agent_id: str) -> str:
    return f"otp:phone:attempts:{agent_id}"


def generate_otp_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


async def send_otp(redis: Redis, agent_id: str, phone_number: str) -> dict:
    code = generate_otp_code()
    payload = {"phone_number": phone_number, "code": code}
    await redis.set(_otp_key(agent_id), json.dumps(payload), ex=OTP_TTL_SECONDS)
    await redis.delete(_attempt_key(agent_id))
    logger.info(
        "OTP generated for phone verification",
        extra={"agent_id": agent_id, "phone_number": phone_number},
    )
    return {"expires_in_seconds": OTP_TTL_SECONDS}


async def verify_otp(redis: Redis, agent_id: str, phone_number: str, code: str) -> bool:
    raw = await redis.get(_otp_key(agent_id))
    if not raw:
        return False
    payload = json.loads(raw)
    if payload.get("phone_number") != phone_number:
        return False
    if not hmac.compare_digest(str(payload.get("code", "")), str(code)):
        attempts = await redis.incr(_attempt_key(agent_id))
        await redis.expire(_attempt_key(agent_id), OTP_TTL_SECONDS)
        if attempts >= MAX_VERIFY_ATTEMPTS:
            await redis.delete(_otp_key(agent_id))
            await redis.delete(_attempt_key(agent_id))
        return False
    await redis.delete(_otp_key(agent_id))
    await redis.delete(_attempt_key(agent_id))
    return True

