from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", ".ENV"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Public URL (ngrok / deployed host) — required for Twilio webhooks & media stream
    public_base_url: str = "http://localhost:8000"

    # MongoDB
    mongodb_uri: str = Field(
        default="mongodb://localhost:27017",
        validation_alias=AliasChoices("MONGODB_URI", "MONGO_URI"),
    )
    mongodb_db_name: str = "voicebot"

    # Twilio (accepts common TWILLIO typo in .ENV files)
    twilio_account_sid: str = Field(
        default="",
        validation_alias=AliasChoices("TWILIO_ACCOUNT_SID", "TWILLIO_ACCOUNT_SID"),
    )
    twilio_auth_token: str = Field(
        default="",
        validation_alias=AliasChoices("TWILIO_AUTH_TOKEN", "TWILLIO_AUTH_TOKEN"),
    )
    twilio_phone_number: str = Field(
        default="",
        validation_alias=AliasChoices("TWILIO_PHONE_NUMBER", "TWILLIO_PHONE_NUMBER"),
    )
    # Seconds the callee's phone rings before no-answer (60–600). Twilio API "timeout".
    twilio_call_timeout: int = Field(default=60, ge=60, le=600)

    # Deepgram (STT) — DEEPGRAM_API_KEY or STT= in .ENV
    deepgram_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("DEEPGRAM_API_KEY", "STT"),
    )
    stt: str = ""

    # Groq (LLM)
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"

    # Live STT turn control (custom media stream)
    stt_turn_debounce_ms: int = Field(default=1100, ge=300, le=3000)
    stt_endpointing_ms: int = Field(default=700, ge=300, le=2000)
    deepgram_model: str = "nova-2-phonecall"

    # Edge TTS
    edge_tts_voice: str = "en-US-JennyNeural"
    edge_tts_voice_urdu: str = "ur-PK-UzmaNeural"

    # App
    api_host: str = "0.0.0.0"
    api_port: int = 8001
    fastapi_url: str = "http://127.0.0.1:8001"

    @property
    def deepgram_key(self) -> str:
        return self.deepgram_api_key or self.stt

    @property
    def twilio_configured(self) -> bool:
        return bool(self.twilio_account_sid and self.twilio_phone_number)

    @property
    def media_stream_ws_url(self) -> str:
        base = self.public_base_url.rstrip("/")
        if base.startswith("https://"):
            return base.replace("https://", "wss://", 1) + "/ws/media"
        if base.startswith("http://"):
            return base.replace("http://", "ws://", 1) + "/ws/media"
        return f"wss://{base}/ws/media"


@lru_cache
def get_settings() -> Settings:
    return Settings()
