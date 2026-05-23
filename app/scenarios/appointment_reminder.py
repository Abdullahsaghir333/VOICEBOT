from datetime import datetime
from typing import Any


SCENARIO_ID = "appointment_reminder"

# Short, voice-first system prompt (no markdown — TTS reads symbols aloud)
SYSTEM_PROMPT = """You are Alex from HealthCare Plus Clinic on a live phone call for appointment reminder and confirmation.

Respond in 1-2 short sentences only. Never use bullet points, markdown, lists, emojis, or special characters.

Confirm who you are speaking with before sharing appointment details. Then share date, time, provider, and location. Ask if they confirm, need to reschedule, or cancel.

If they confirm, thank them and remind them to arrive ten minutes early. If reschedule, say the office will call back — do not invent new times. If cancel, acknowledge politely. Never give medical advice. Speak plain conversational English."""


def build_context_block(context: dict[str, Any]) -> str:
    appt_dt = context.get("appointment_datetime")
    if isinstance(appt_dt, datetime):
        when = appt_dt.strftime("%A, %B %d at %I:%M %p")
    elif appt_dt:
        when = str(appt_dt)
    else:
        when = "the scheduled time"

    return (
        f"Patient: {context.get('patient_name', 'the patient')}. "
        f"Appointment: {when}. "
        f"Provider: {context.get('provider_name', 'Dr. Smith')}. "
        f"Location: {context.get('clinic_name', 'HealthCare Plus Clinic')}, "
        f"{context.get('clinic_address', '')}. "
        f"Status: {context.get('status', 'scheduled')}."
    )


def opening_line(context: dict[str, Any]) -> str:
    name = context.get("patient_name", "there")
    return (
        f"Hello, this is Alex from HealthCare Plus Clinic. "
        f"May I speak with {name}? "
        f"I am calling with a quick reminder about your upcoming appointment."
    )


def detect_outcome(user_text: str, assistant_text: str) -> str | None:
    combined = f"{user_text} {assistant_text}".lower()
    if any(w in combined for w in ("cancel", "cancellation", "won't make it", "cannot make")):
        return "cancelled"
    if any(w in combined for w in ("reschedule", "different time", "another day", "change the time")):
        return "reschedule_requested"
    if any(w in combined for w in ("confirm", "confirmed", "see you then", "i'll be there", "will be there")):
        return "confirmed"
    return None
