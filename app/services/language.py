"""Lightweight English / Urdu detection for replies and TTS voice selection."""

import re

_URDU_SCRIPT = re.compile(r"[\u0600-\u06FF]")

_ROMAN_URDU_HINTS = (
    "aap",
    "ap",
    "kab",
    "kahan",
    "kitne",
    "baje",
    "hai",
    "hain",
    "mein",
    "main",
    "ka",
    "ki",
    "ke",
    "ko",
    "se",
    "shukriya",
    "theek",
    "tasdeeq",
    "waqt",
    "bata",
    "batao",
    "kya",
    "kaun",
    "jana",
    "aaon",
)


def detect_language(text: str) -> str:
    if not text or not text.strip():
        return "en"
    if _URDU_SCRIPT.search(text):
        return "ur"
    lower = text.lower()
    if sum(1 for w in _ROMAN_URDU_HINTS if w in lower) >= 2:
        return "ur"
    return "en"


def reply_language(user_message: str, assistant_text: str = "") -> str:
    if detect_language(user_message) == "ur":
        return "ur"
    if assistant_text and detect_language(assistant_text) == "ur":
        return "ur"
    return "en"
