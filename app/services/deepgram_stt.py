"""Deepgram live STT helpers — final transcripts only (no interim/partial LLM triggers)."""

from urllib.parse import urlencode

from app.config import get_settings


def build_listen_url() -> str:
    """
    WebSocket listen URL tuned for voice-bot use:
    - interim_results=false: never act on partial transcripts
    - vad_events=true: SpeechStarted for barge-in
    - utterance_end_ms: end-of-speech detection before final result
    """
    params = {
        "encoding": "mulaw",
        "sample_rate": "8000",
        "channels": "1",
        "model": "nova-2",
        "language": "en",
        # Final transcripts only for LLM (see parse_final_transcript). Do not set
        # utterance_end_ms here — Deepgram returns HTTP 400 unless interim_results=true.
        "interim_results": "false",
        "vad_events": "true",
        "endpointing": "400",
        "punctuate": "true",
        "smart_format": "true",
    }
    return f"wss://api.deepgram.com/v1/listen?{urlencode(params)}"


def parse_final_transcript(data: dict) -> str | None:
    """Return transcript text only for final STT results."""
    if data.get("type") != "Results":
        return None
    if not data.get("is_final", False):
        return None
    channel = data.get("channel", {})
    alts = channel.get("alternatives", [])
    if not alts:
        return None
    text = (alts[0].get("transcript") or "").strip()
    return text or None


def is_speech_started(data: dict) -> bool:
    return data.get("type") == "SpeechStarted"


def is_utterance_end(data: dict) -> bool:
    return data.get("type") in ("UtteranceEnd", "SpeechEnded")
