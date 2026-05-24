"""Run: venv\\Scripts\\python.exe scripts\\pipeline_check.py"""

import asyncio
import json
import sys
from pathlib import Path

# project root on path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


async def main() -> int:
    import httpx
    import websockets
    from websockets.exceptions import ConnectionClosed

    from app.config import get_settings
    from app.services.deepgram_stt import build_listen_url
    from app.services.groq_service import GroqConversationService
    from app.services.tts_service import synthesize_mulaw
    from app.services.twilio_service import TwilioService, VALID_STATUS_CALLBACK_EVENTS

    settings = get_settings()
    api = settings.fastapi_url.rstrip("/")
    results: list[tuple[str, str, str]] = []

    def ok(name: str, detail: str = "") -> None:
        results.append((name, "PASS", detail))

    def fail(name: str, detail: str) -> None:
        results.append((name, "FAIL", detail))

    print("=== VOICEBOT pipeline check ===\n")
    print(f"API_URL={api}")
    print(f"PUBLIC_BASE_URL={settings.public_base_url}")
    print(f"WS_URL={settings.media_stream_ws_url}")
    print(f"Twilio callbacks={list(VALID_STATUS_CALLBACK_EVENTS)}\n")

    # 1) Local API
    try:
        r = httpx.get(f"{api}/health", timeout=5)
        if r.status_code == 200:
            ok("Local API /health", r.text[:80])
        else:
            fail("Local API /health", f"HTTP {r.status_code}")
    except Exception as e:
        fail("Local API /health", f"{e} — run run_api.bat")

    try:
        r = httpx.get(f"{api}/api/calls/status", timeout=5)
        if r.is_success:
            d = r.json()
            ready = d.get("ready")
            ok("Pipeline status", f"ready={ready}")
            if not ready:
                fail("Pipeline config", str(d))
        else:
            fail("Pipeline status", r.text)
    except Exception as e:
        fail("Pipeline status", str(e))

    try:
        r = httpx.get(f"{api}/health/tts", timeout=30)
        d = r.json()
        if d.get("status") == "ok":
            ok("Edge TTS + FFmpeg", f"{d.get('audio_bytes')} bytes")
        else:
            fail("Edge TTS + FFmpeg", str(d))
    except Exception as e:
        fail("Edge TTS + FFmpeg", str(e))

    # 2) Public ngrok (voice webhook)
    pub = settings.public_base_url.rstrip("/")
    try:
        r = httpx.get(f"{pub}/health", timeout=15, follow_redirects=True)
        if r.status_code == 200:
            ok("ngrok /health", pub)
        else:
            fail("ngrok /health", f"HTTP {r.status_code} — is ngrok running on 8001?")
    except Exception as e:
        fail("ngrok /health", f"{e}")

    # 3) Twilio account
    try:
        if not settings.twilio_account_sid or not settings.twilio_auth_token:
            fail("Twilio credentials", "missing SID/token")
        else:
            acc = TwilioService()._client.api.accounts(settings.twilio_account_sid).fetch()
            ok("Twilio API", f"account {acc.status}")
    except Exception as e:
        fail("Twilio API", str(e))

    # 4) Deepgram WebSocket
    dg_url = build_listen_url()
    try:
        headers = {"Authorization": f"Token {settings.deepgram_key}"}
        async with websockets.connect(dg_url, additional_headers=headers) as ws:
            await ws.send(json.dumps({"type": "KeepAlive"}))
            ok("Deepgram WebSocket", settings.deepgram_model)
    except Exception as e:
        fail("Deepgram WebSocket", str(e))

    # 5) Groq
    try:
        reply = await GroqConversationService().generate_reply(
            scenario="appointment_reminder",
            context={
                "patient_name": "Test",
                "appointment_datetime": "2026-05-25T15:00:00",
                "provider_name": "Dr. Smith",
                "clinic_name": "Clinic",
                "clinic_address": "123 St",
            },
            history=[],
            user_message="What time is my appointment?",
        )
        if reply and len(reply) > 10:
            ok("Groq LLM", f"{len(reply)} chars: {reply[:60]}...")
        else:
            fail("Groq LLM", f"short reply: {reply!r}")
    except Exception as e:
        fail("Groq LLM", str(e))

    # 6) Local WebSocket /ws/media (simulates Twilio connect)
    ws_local = settings.media_stream_ws_url.replace(
        settings.public_base_url.rstrip("/"),
        api,
    ).replace("https://", "ws://").replace("http://", "ws://")
    if "localhost" not in ws_local and "127.0.0.1" not in ws_local:
        ws_local = api.replace("http://", "ws://").replace("https://", "wss://") + "/ws/media"

    try:
        async with websockets.connect(ws_local) as ws:
            ok("WebSocket /ws/media (local)", "accepted")
            await ws.close()
    except Exception as e:
        fail("WebSocket /ws/media (local)", str(e))

    # 7) ngrok WebSocket (optional — may need browser interstitial on free tier)
    ws_pub = settings.media_stream_ws_url
    try:
        async with websockets.connect(
            ws_pub,
            additional_headers={"ngrok-skip-browser-warning": "true"},
        ) as ws:
            ok("WebSocket /ws/media (ngrok)", ws_pub)
            await ws.close()
    except ConnectionClosed:
        ok("WebSocket /ws/media (ngrok)", "connected then closed")
    except Exception as e:
        fail("WebSocket /ws/media (ngrok)", str(e))

    print("\n=== Results ===")
    fails = 0
    for name, status, detail in results:
        mark = "OK" if status == "PASS" else "XX"
        print(f"  [{mark}] {name}: {detail}")
        if status == "FAIL":
            fails += 1

    print()
    if fails == 0:
        print("All checks passed. Pipeline is healthy.")
        print("If calls still show busy: Twilio trial + Pakistan carrier (not app code).")
    else:
        print(f"{fails} check(s) failed — fix those before testing calls.")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
