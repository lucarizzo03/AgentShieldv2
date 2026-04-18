from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class PhoneVerificationStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phone_number: str = Field(min_length=8, max_length=32, pattern=r"^\+[1-9]\d{7,31}$")


class PhoneVerificationStartResponse(BaseModel):
    agent_id: str
    status: Literal["OTP_SENT"]
    expires_in_seconds: int


class PhoneVerificationConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phone_number: str = Field(min_length=8, max_length=32, pattern=r"^\+[1-9]\d{7,31}$")
    code: str = Field(min_length=4, max_length=8, pattern=r"^\d{4,8}$")


class PhoneVerificationConfirmResponse(BaseModel):
    agent_id: str
    status: Literal["PHONE_VERIFIED"]
    phone_number: str
    verified_at: datetime


class HitlPreferencesUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hitl_primary_channel: Literal["dashboard"] = "dashboard"
    hitl_sms_fallback_high_risk: bool = True


class HitlPreferencesUpdateResponse(BaseModel):
    agent_id: str
    hitl_primary_channel: Literal["dashboard"]
    hitl_sms_fallback_high_risk: bool

