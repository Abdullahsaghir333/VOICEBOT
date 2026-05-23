from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class OutboundCallRequest(BaseModel):
    phone_number: str = Field(..., description="E.164 format, e.g. +15551234567")
    provider: Literal["custom", "vapi"] = Field(
        default="custom",
        description="custom = Twilio+Deepgram+Groq+Edge TTS; vapi = Vapi managed pipeline",
    )
    appointment_id: str | None = None
    scenario: str = "appointment_reminder"
    patient_name: str | None = None
    appointment_datetime: datetime | None = None
    provider_name: str | None = None
    clinic_name: str | None = None
    clinic_address: str | None = None


class ConversationTurn(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class CallResponse(BaseModel):
    id: str
    phone_number: str
    scenario: str
    provider: Literal["custom", "vapi"] = "custom"
    status: Literal["queued", "ringing", "in_progress", "completed", "failed", "no_answer"]
    twilio_call_sid: str | None = None
    vapi_call_id: str | None = None
    appointment_id: str | None = None
    conversation: list[ConversationTurn] = []
    outcome: str | None = None
    created_at: datetime
    updated_at: datetime


class CallListResponse(BaseModel):
    calls: list[CallResponse]
    total: int
