from datetime import datetime
from typing import Any


SCENARIO_ID = "appointment_reminder"

SYSTEM_PROMPT = """You are Alex from HealthCare Plus Clinic on a live phone call for an appointment reminder.

Keep every reply to one or two short sentences, under 28 words, for phone audio.

Answer the caller's latest question first using only the appointment facts you have.
If they ask about payment or cost, say this call is only to confirm the visit and any billing is handled at the clinic front desk when they arrive.
If they ask for details, timing, date, doctor, or location, state those facts clearly from your context.
If speech seems garbled or unclear, politely ask them to repeat once.

After your opening greeting, do not repeat your full introduction.
Do not say you lack information that is in your appointment facts.
If they already confirmed the appointment, do not ask them to confirm again; thank them and answer any new question or say goodbye.

If they want to confirm, thank them and remind them to arrive ten minutes early.
If they want to reschedule, say the office will call back to reschedule.
If they cancel, acknowledge politely.
Never give medical advice. Plain conversational English only."""


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
        f"{context.get('clinic_address', '123 Wellness Ave')}. "
        f"Purpose: appointment reminder and confirmation only, not payment collection on this call. "
        f"Status: {context.get('status', 'scheduled')}."
    )


def opening_line(context: dict[str, Any]) -> str:
    name = context.get("patient_name", "there")
    return (
        f"Hello, this is Alex from HealthCare Plus Clinic calling for {name}. "
        f"I have a quick reminder about your upcoming appointment."
    )


def detect_outcome(user_text: str, assistant_text: str) -> str | None:
    combined = f"{user_text} {assistant_text}".lower()
    if any(w in combined for w in ("cancel", "cancellation", "won't make it", "cannot make")):
        return "cancelled"
    if any(w in combined for w in ("reschedule", "different time", "another day", "change the time")):
        return "reschedule_requested"
    if any(
        w in combined
        for w in (
            "confirm",
            "confirmed",
            "i confirm",
            "i confirmed",
            "see you then",
            "i'll be there",
            "will be there",
            "i will come",
        )
    ):
        return "confirmed"
    return None
