import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import appointments, calls, vapi_webhooks, webhooks
from app.config import get_settings
from app.db.mongodb import close_mongodb, get_database
from app.services.media_stream import MediaStreamSession

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db = get_database()
    await db.command("ping")
    logger.info("Connected to MongoDB")
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


@app.get("/health")
async def health():
    return {"status": "ok", "service": "voicebot-api"}


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


@app.websocket("/ws/media")
async def media_stream_ws(websocket: WebSocket):
    await websocket.accept()
    session = MediaStreamSession(websocket)
    await session.run()


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run("app.main:app", host=settings.api_host, port=settings.api_port, reload=True)
