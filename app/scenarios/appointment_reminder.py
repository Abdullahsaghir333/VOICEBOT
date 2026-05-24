from datetime import datetime
from typing import Any


SCENARIO_ID = "appointment_reminder"

SYSTEM_PROMPT = """You are Alex from HealthCare Plus Clinic on a live phone call for an appointment reminder.

LANGUAGE (critical):
- Caller speaks English → reply in English.
- Caller speaks Urdu (script or Roman Urdu) → reply in Urdu.
- Mixed English and Urdu → match their mix in the same reply.

ANSWERING (critical):
- When / kab / time: give full appointment DATE and TIME from your facts.
- Where / location / kahan: give clinic NAME and full ADDRESS.
- What is it about: reminder with doctor name plus date, time, and location.
- Never give vague one-word answers. Use exact facts from context; never say you lack info that is listed.

STYLE: One or two sentences, under 40 words, natural for phone audio.
After the greeting, do not repeat your full introduction.
If they already confirmed, do not ask again.

CONFIRM: thank them, ten minutes early, brief goodbye (English or Urdu).
RESCHEDULE: office will call back, goodbye.
CANCEL: acknowledge politely, goodbye.
No medical advice."""

TERMINAL_OUTCOMES = frozenset({"confirmed", "cancelled", "reschedule_requested"})


def build_context_block(context: dict[str, Any]) -> str:
    appt_dt = context.get("appointment_datetime")
    if isinstance(appt_dt, datetime):
        when = appt_dt.strftime("%A, %B %d at %I:%M %p")
    elif appt_dt:
        when = str(appt_dt)
    else:
        when = "the scheduled time"

    return (
        f"FACTS TO USE: Patient {context.get('patient_name', 'the patient')}. "
        f"Appointment {when}. Doctor {context.get('provider_name', 'Dr. Smith')}. "
        f"Clinic {context.get('clinic_name', 'HealthCare Plus Clinic')}, "
        f"address {context.get('clinic_address', '123 Wellness Ave')}. "
        f"Status {context.get('status', 'scheduled')}."
    )


def opening_line(context: dict[str, Any]) -> str:
    name = context.get("patient_name", "there")
    return (
        f"Hello, this is Alex from HealthCare Plus Clinic calling for {name}. "
        f"I am calling to remind you about your upcoming appointment."
    )


def detect_outcome(user_text: str, assistant_text: str) -> str | None:
    user = user_text.lower().strip()
    assistant = assistant_text.lower()

    if any(
        w in user
        for w in ("cancel", "cancellation", "won't make", "cannot make", "can't make", "nahi aa")
    ):
        return "cancelled"
    if any(w in user for w in ("reschedule", "different time", "another day", "change the time", "dobara")):
        return "reschedule_requested"

    strong_confirm = any(
        p in user
        for p in (
            "i confirm",
            "i confirmed",
            "okay. i confirm",
            "okay i confirm",
            "yes i confirm",
            "i'll be there",
            "i will be there",
            "see you then",
            "will be there",
            "i will come",
            "main confirm",
            "mein confirm",
            "tasdeeq",
            "theek hai main aa",
        )
    ) or user in ("confirmed", "yes confirmed", "yes, confirmed")
    if strong_confirm:
        return "confirmed"

    if user in ("yes", "yeah", "yep", "correct", "theek", "ji", "right") and any(
        p in assistant
        for p in ("thank", "shukriya", "ten minutes", "goodbye", "allah hafiz", "arrive")
    ):
        return "confirmed"

    return None
