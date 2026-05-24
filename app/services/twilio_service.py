import logging

from twilio.rest import Client

from app.config import get_settings

logger = logging.getLogger(__name__)


class TwilioService:
    def __init__(self) -> None:
        settings = get_settings()
        self._client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
        self._from_number = settings.twilio_phone_number
        self._stream_url = settings.media_stream_ws_url
        self._status_callback_url = (
            f"{settings.public_base_url.rstrip('/')}/webhooks/twilio/status"
        )
        self._ring_timeout = settings.twilio_call_timeout

    def place_outbound_call(self, to_number: str, call_id: str) -> str:
        settings = get_settings()
        voice_url = f"{settings.public_base_url.rstrip('/')}/webhooks/twilio/voice?call_id={call_id}"
        logger.info(
            "Placing call to %s voice_url=%s stream=%s ring_timeout=%ss",
            to_number,
            voice_url,
            self._stream_url,
            self._ring_timeout,
        )

        call = self._client.calls.create(
            to=to_number,
            from_=self._from_number,
            url=voice_url,
            method="POST",
            timeout=self._ring_timeout,
            status_callback=f"{self._status_callback_url}?call_id={call_id}",
            status_callback_event=["initiated", "ringing", "answered", "completed"],
            status_callback_method="POST",
        )
        return call.sid
