import logging

from twilio.rest import Client

from app.config import get_settings

logger = logging.getLogger(__name__)


class TwilioService:
    def __init__(self) -> None:
        settings = get_settings()
        self._client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
        self._from_number = settings.twilio_phone_number
        self._voice_webhook_url = f"{settings.public_base_url.rstrip('/')}/webhooks/twilio/voice"

    def place_outbound_call(self, to_number: str, call_id: str) -> str:
        call = self._client.calls.create(
            to=to_number,
            from_=self._from_number,
            url=f"{self._voice_webhook_url}?call_id={call_id}",
            method="POST",
            status_callback=f"{self._voice_webhook_url.replace('/voice', '/status')}?call_id={call_id}",
            status_callback_event=["initiated", "ringing", "answered", "completed"],
            status_callback_method="POST",
        )
        return call.sid
