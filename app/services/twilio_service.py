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

    def _build_twiml(self, call_id: str) -> str:
        """Inline TwiML — avoids extra HTTP fetch to /voice (ngrok issues)."""
        return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Connect>
    <Stream url="{self._stream_url}" track="both_tracks">
      <Parameter name="call_id" value="{call_id}" />
    </Stream>
  </Connect>
</Response>"""

    def place_outbound_call(self, to_number: str, call_id: str) -> str:
        twiml = self._build_twiml(call_id)
        logger.info("Placing call to %s stream=%s", to_number, self._stream_url)

        call = self._client.calls.create(
            to=to_number,
            from_=self._from_number,
            twiml=twiml,
            status_callback=f"{self._status_callback_url}?call_id={call_id}",
            status_callback_event=["initiated", "ringing", "answered", "completed"],
            status_callback_method="POST",
        )
        return call.sid
