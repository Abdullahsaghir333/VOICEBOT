"""Heuristics to avoid acting on junk or partial STT fragments."""

import re

# Very short filler-only lines (not worth a full LLM+TTS turn)
_FILLER_ONLY = re.compile(
    r"^(okay|ok|so|um|uh|hmm|yeah|yes|no|hello|hi|thanks|thank you)[\s.,!?]*$",
    re.IGNORECASE,
)

# Short phrases that are valid intents even with few words
_INTENT_KEYWORDS = (
    "confirm",
    "cancel",
    "reschedule",
    "goodbye",
    "bye",
    "appointment",
    "doctor",
    "payment",
    "timing",
    "time",
    "when",
    "where",
    "what",
    "who",
    "how",
    "detail",
)

# Common phone-line STT mishears (8 kHz mulaw)
_PHONE_REPLACEMENTS: list[tuple[str, str]] = [
    (r"\bon the gender\b", "on the line"),
    (r"\bi am on the gender\b", "yes I am on the line"),
    (r"\bpayment work\b", "appointment"),
    (r"\bwhat is the payment work\b", "what is the appointment about"),
    (r"\bwhat is the payment\b", "what is the appointment"),
    (r"\btiming is about\b", "timing"),
    (r"\bthe what is the timing\b", "what is the timing"),
    (r"\bissue is about\b", "appointment is about"),
    (r"\bthat's the issue\b", "that's the appointment"),
]


def normalize_phone_transcript(text: str, patient_name: str | None = None) -> str:
    """Light cleanup for telephony STT before LLM."""
    cleaned = " ".join(text.split()).strip()
    if not cleaned:
        return cleaned

    result = cleaned
    for pattern, replacement in _PHONE_REPLACEMENTS:
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)

    if patient_name:
        first = patient_name.split()[0]
        if first and re.search(r"\bgender\b", result, re.IGNORECASE):
            if first.lower() not in result.lower():
                result = re.sub(r"\bgender\b", first, result, flags=re.IGNORECASE)

    return result.strip()


def is_meaningful_transcript(text: str, *, min_words: int = 3) -> bool:
    """Skip noise/filler finals; allow short but intent-heavy utterances."""
    cleaned = normalize_phone_transcript(text)
    if not cleaned:
        return False
    if _FILLER_ONLY.match(cleaned):
        return False

    lower = cleaned.lower()
    if any(k in lower for k in _INTENT_KEYWORDS):
        return len(cleaned) >= 6

    words = cleaned.split()
    if len(words) >= min_words:
        return True
    return len(words) >= 2 and len(cleaned) >= 14


def pick_best_transcript(candidates: list[str]) -> str | None:
    """Merge STT finals from one debounce window (Deepgram often splits one sentence)."""
    meaningful = [
        normalize_phone_transcript(c) for c in candidates if is_meaningful_transcript(c)
    ]
    meaningful = [m for m in meaningful if m]
    if not meaningful:
        return None
    if len(meaningful) == 1:
        return meaningful[0]
    merged = meaningful[0]
    for part in meaningful[1:]:
        if part.lower() in merged.lower():
            continue
        merged = f"{merged} {part}"
    return merged.strip()
