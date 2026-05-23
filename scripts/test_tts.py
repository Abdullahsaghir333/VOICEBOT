"""Test Edge TTS + FFmpeg. Run: venv\\Scripts\\python.exe scripts\\test_tts.py"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def main() -> None:
    from app.services.tts_service import synthesize_mulaw

    print("Synthesizing test audio...")
    audio = await synthesize_mulaw("Hello, this is a test from HealthCare Plus Clinic.")
    print(f"OK — generated {len(audio)} bytes of mulaw audio. FFmpeg + Edge TTS work.")


if __name__ == "__main__":
    asyncio.run(main())
