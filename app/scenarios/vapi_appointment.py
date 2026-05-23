"""Vapi transient assistant config for appointment reminder calls."""

from typing import Any

from app.config import get_settings
from app.scenarios import appointment_reminder


def build_transient_assistant(context: dict[str, Any], *, server_url: str) -> dict[str, Any]:
    settings = get_settings()
    system = (
        appointment_reminder.SYSTEM_PROMPT
        + " "
        + appointment_reminder.build_context_block(context)
    )

    return {
        "name": "Alex — Appointment Reminder",
        "firstMessage": appointment_reminder.opening_line(context),
        "model": {
            "provider": "groq",
            "model": settings.groq_model,
            "messages": [{"role": "system", "content": system}],
            "temperature": 0.6,
        },
        "transcriber": {
            "provider": "deepgram",
            "model": "nova-2",
            "language": "en",
        },
        "voice": {
            "provider": settings.vapi_voice_provider,
            "voiceId": settings.vapi_voice_id,
        },
        "serverUrl": server_url,
        "endCallMessage": "Thank you for calling HealthCare Plus. Have a great day. Goodbye!",
        "endCallPhrases": ["goodbye", "bye", "that's all", "thank you bye"],
        "recordingEnabled": False,
        "silenceTimeoutSeconds": 30,
        "maxDurationSeconds": 600,
    }
