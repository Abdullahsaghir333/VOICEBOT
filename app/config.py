from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",  # project secrets (see .env.custom.example)
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

    # Deepgram (STT) — DEEPGRAM_API_KEY or STT= in .ENV
    deepgram_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("DEEPGRAM_API_KEY", "STT"),
    )
    stt: str = ""

    # Groq (LLM)
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"

    # Edge TTS (custom Twilio pipeline only)
    edge_tts_voice: str = "en-US-JennyNeural"

    # Vapi (managed voice AI platform — alternative outbound path)
    vapi_api_key: str = ""
    vapi_phone_number_id: str = ""
    vapi_assistant_id: str = ""  # optional; if empty, uses transient assistant per call
    vapi_server_url: str = ""  # optional; defaults to PUBLIC_BASE_URL/webhooks/vapi
    vapi_voice_provider: str = "openai"
    vapi_voice_id: str = "alloy"

    # App
    api_host: str = "0.0.0.0"
    api_port: int = 8001
    fastapi_url: str = "http://127.0.0.1:8001"

    @property
    def deepgram_key(self) -> str:
        return self.deepgram_api_key or self.stt

    @property
    def vapi_configured(self) -> bool:
        return bool(self.vapi_api_key and self.vapi_phone_number_id)

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
