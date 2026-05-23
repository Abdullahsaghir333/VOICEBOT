import audioop
import io
import logging

import edge_tts
from pydub import AudioSegment

from app.config import get_settings

logger = logging.getLogger(__name__)

# Twilio Media Streams: 8 kHz mono μ-law
TWILIO_SAMPLE_RATE = 8000


async def synthesize_mulaw(text: str) -> bytes:
    """Convert text to μ-law 8 kHz audio for Twilio Media Streams."""
    settings = get_settings()
    communicate = edge_tts.Communicate(text, voice=settings.edge_tts_voice)

    mp3_buffer = io.BytesIO()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            mp3_buffer.write(chunk["data"])

    mp3_buffer.seek(0)
    segment = AudioSegment.from_mp3(mp3_buffer)
    segment = segment.set_frame_rate(TWILIO_SAMPLE_RATE).set_channels(1)
    pcm = segment.raw_data
    return audioop.lin2ulaw(pcm, segment.sample_width)


def chunk_mulaw(audio: bytes, chunk_size: int = 160) -> list[bytes]:
    """Split μ-law audio into ~20 ms frames (160 bytes @ 8 kHz)."""
    return [audio[i : i + chunk_size] for i in range(0, len(audio), chunk_size)]
