import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import appointments, calls, vapi_webhooks, webhooks
from app.config import get_settings
from app.db.mongodb import close_mongodb, get_database
from app.services.media_stream import MediaStreamSession

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    import asyncio

    db = get_database()
    try:
        await asyncio.wait_for(db.command("ping"), timeout=8.0)
        logger.info("Connected to MongoDB")
    except asyncio.TimeoutError:
        logger.error("MongoDB ping timed out — check MONGO_URI / Atlas network access")
        raise
    yield
    await close_mongodb()


app = FastAPI(
    title="Voice AI Agent",
    description="Outbound appointment reminder — Custom pipeline (Twilio/Deepgram/Groq/Edge TTS) or Vapi",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(appointments.router, prefix="/api")
app.include_router(calls.router, prefix="/api")
app.include_router(webhooks.router)
app.include_router(vapi_webhooks.router)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    ms = (time.perf_counter() - start) * 1000
    logger.info("%s %s -> %s (%.0fms)", request.method, request.url.path, response.status_code, ms)
    return response


@app.get("/health")
async def health():
    return {"status": "ok", "service": "voicebot-api"}


@app.get("/debug/stream")
async def debug_stream():
    """Shows the WebSocket URL Twilio must connect to (check ngrok inspector for WS)."""
    settings = get_settings()
    return {
        "media_stream_ws_url": settings.media_stream_ws_url,
        "hint": "During a call, ngrok should show WebSocket GET /ws/media (101). Status-only = no voice.",
    }


@app.get("/health/tts")
async def health_tts():
    """Quick check: Edge TTS + FFmpeg (required for agent voice)."""
    try:
        from app.services.tts_service import synthesize_mulaw

        audio = await synthesize_mulaw("Test.")
        return {"status": "ok", "audio_bytes": len(audio)}
    except Exception as exc:
        logger.exception("TTS health check failed")
        return {"status": "error", "detail": str(exc), "hint": "Install FFmpeg and add to PATH"}


@app.get("/config/public")
async def public_config():
    settings = get_settings()
    return {
        "public_base_url": settings.public_base_url,
        "media_stream_ws_url": settings.media_stream_ws_url,
        "vapi_webhook_url": settings.vapi_server_url
        or f"{settings.public_base_url.rstrip('/')}/webhooks/vapi",
        "scenario": "appointment_reminder",
        "providers": {
            "custom": settings.twilio_configured,
            "vapi": settings.vapi_configured,
        },
    }


def _is_likely_twilio_peer(host: str | None) -> bool:
    """Twilio status/webhook IPs are AWS ranges; your wscat test uses your home IP."""
    if not host:
        return False
    return not host.startswith("2407:") and not host.startswith("::1") and host not in ("127.0.0.1", "localhost")


@app.websocket("/ws/media")
async def media_stream_ws(websocket: WebSocket):
    await websocket.accept()
    host = websocket.client.host if websocket.client else None
    source = "TWILIO?" if _is_likely_twilio_peer(host) else "local/test"
    logger.info("WebSocket /ws/media connected from %s (%s)", websocket.client, source)
    try:
        session = MediaStreamSession(websocket)
        await session.run()
    except WebSocketDisconnect:
        logger.info("WebSocket /ws/media disconnected")
    except Exception:
        logger.exception("WebSocket /ws/media error")


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run("app.main:app", host=settings.api_host, port=settings.api_port, reload=True)
