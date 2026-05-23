import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Target: user end-of-speech -> bot starts speaking
TARGET_RESPONSE_MS = 1500


@dataclass
class TurnMetrics:
    user_text: str = ""
    assistant_text: str = ""
    stt_ms: float = 0.0
    llm_ms: float = 0.0
    tts_ms: float = 0.0
    total_ms: float = 0.0
    _speech_end_at: float | None = field(default=None, repr=False)
    _pipeline_start_at: float | None = field(default=None, repr=False)

    def mark_speech_end(self) -> None:
        self._speech_end_at = time.perf_counter()

    def mark_pipeline_start(self) -> None:
        self._pipeline_start_at = time.perf_counter()

    def finish(self, *, assistant_text: str, stt_ms: float, llm_ms: float, tts_ms: float) -> dict[str, Any]:
        self.assistant_text = assistant_text
        self.stt_ms = stt_ms
        self.llm_ms = llm_ms
        self.tts_ms = tts_ms
        if self._speech_end_at and self._pipeline_start_at:
            self.total_ms = (time.perf_counter() - self._speech_end_at) * 1000
        else:
            self.total_ms = stt_ms + llm_ms + tts_ms

        payload = {
            "stt_ms": round(self.stt_ms, 1),
            "llm_ms": round(self.llm_ms, 1),
            "tts_ms": round(self.tts_ms, 1),
            "total_ms": round(self.total_ms, 1),
            "target_ms": TARGET_RESPONSE_MS,
            "within_target": self.total_ms <= TARGET_RESPONSE_MS,
        }
        logger.info(
            "turn_latency user=%r stt=%.0fms llm=%.0fms tts=%.0fms total=%.0fms target=%dms ok=%s",
            self.user_text[:80],
            payload["stt_ms"],
            payload["llm_ms"],
            payload["tts_ms"],
            payload["total_ms"],
            TARGET_RESPONSE_MS,
            payload["within_target"],
        )
        return payload
