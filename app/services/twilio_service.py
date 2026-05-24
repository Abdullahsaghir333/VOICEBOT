import logging

from twilio.rest import Client

from app.config import get_settings

logger = logging.getLogger(__name__)

# Twilio error 21626 if you add busy, no-answer, failed, or canceled here.
VALID_STATUS_CALLBACK_EVENTS = ("initiated", "ringing", "answered", "completed")


class TwilioService:
    def __init__(self) -> None:
        settings = get_settings()
        self._client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
        self._from_number = settings.twilio_phone_number
        self._stream_url = settings.media_stream_ws_url
        self._status_callback_url = (
            f"{settings.public_base_url.rstrip('/')}/webhooks/twilio/status"
        )
        self._ring_timeout = max(30, settings.twilio_call_timeout)

    def place_outbound_call(self, to_number: str, call_id: str) -> str:
        settings = get_settings()
        ring_seconds = max(30, settings.twilio_call_timeout)
        voice_url = f"{settings.public_base_url.rstrip('/')}/webhooks/twilio/voice?call_id={call_id}"
        logger.info(
            "Placing call to %s voice_url=%s stream=%s ring_seconds=%s",
            to_number,
            voice_url,
            self._stream_url,
            ring_seconds,
        )

        call = self._client.calls.create(
            to=to_number,
            from_=self._from_number,
            url=voice_url,
            method="POST",
            timeout=ring_seconds,
            status_callback=f"{self._status_callback_url}?call_id={call_id}",
            status_callback_event=list(VALID_STATUS_CALLBACK_EVENTS),
            status_callback_method="POST",
        )
        return call.sid

    def hangup_call(self, call_sid: str) -> None:
        """End an in-progress Twilio call."""
        if not call_sid:
            return
        logger.info("Hanging up Twilio call sid=%s", call_sid)
        self._client.calls(call_sid).update(status="completed")
