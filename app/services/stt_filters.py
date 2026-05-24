"""Heuristics to avoid acting on junk or partial STT fragments."""

import re

_FILLER_ONLY = re.compile(
    r"^(okay|ok|so|um|uh|hmm|yeah|yes|no|hello|hi|thanks|thank you)[\s.,!?]*$",
    re.IGNORECASE,
)

_INTENT_KEYWORDS = (
    "confirm",
    "cancel",
    "reschedule",
    "goodbye",
    "appointment",
    "doctor",
    "payment",
    "timing",
    "time",
    "when",
    "where",
    "what",
    "how",
    "detail",
    "location",
    "come",
    "kab",
    "kahan",
    "kya",
)

_INCOMPLETE_PATTERNS = re.compile(
    r"(?:\bcan you tell me$|\btell me$|\bwhat is the$|\bwhat is$|\bso can you$|\bhow about$)",
    re.IGNORECASE,
)

_PHONE_REPLACEMENTS: list[tuple[str, str]] = [
    (r"\bon the gender\b", "on the line"),
    (r"\bpayment work\b", "appointment"),
    (r"\bwhen i have to come\b", "when is my appointment"),
    (r"\bwhat time.*come\b", "what time is the appointment"),
]


def normalize_phone_transcript(text: str, patient_name: str | None = None) -> str:
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


def is_incomplete_utterance(text: str) -> bool:
    cleaned = normalize_phone_transcript(text)
    if not cleaned:
        return False
    if _INCOMPLETE_PATTERNS.search(cleaned):
        return True
    if len(cleaned.split()) <= 4 and "?" not in cleaned:
        lower = cleaned.lower()
        if any(lower.endswith(s) for s in ("tell me", "can you", "what is")):
            return True
    return False


def question_intent_fingerprint(text: str) -> str | None:
    lower = normalize_phone_transcript(text).lower()
    if any(w in lower for w in ("when", "come", "time", "date", "kab", "baje")):
        return "when"
    if any(w in lower for w in ("where", "location", "address", "kahan")):
        return "where"
    if any(w in lower for w in ("about", "detail", "what is", "kya")):
        return "about"
    if any(w in lower for w in ("confirm", "tasdeeq")):
        return "confirm"
    return None


def is_meaningful_transcript(text: str, *, min_words: int = 3) -> bool:
    cleaned = normalize_phone_transcript(text)
    if not cleaned or is_incomplete_utterance(cleaned) or _FILLER_ONLY.match(cleaned):
        return False
    lower = cleaned.lower()
    if any(k in lower for k in _INTENT_KEYWORDS):
        return len(cleaned) >= 8
    words = cleaned.split()
    return len(words) >= min_words or (len(words) >= 2 and len(cleaned) >= 14)


def pick_best_transcript(candidates: list[str]) -> str | None:
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
        if part.lower() not in merged.lower():
            merged = f"{merged} {part}"
    return merged.strip()
