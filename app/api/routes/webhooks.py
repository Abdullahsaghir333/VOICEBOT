import logging

from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import Response

from app.config import get_settings
from app.repositories.calls import CallRepository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks/twilio", tags=["twilio"])
call_repo = CallRepository()


def _voice_twiml(call_id: str) -> str:
    settings = get_settings()
    stream_url = settings.media_stream_ws_url
    base = settings.public_base_url.rstrip("/")
    stream_status = f"{base}/webhooks/twilio/stream-status?call_id={call_id}"
    # Connect + Stream: track must be inbound_track or omitted (default).
    # both_tracks is only valid with <Start>, not <Connect> — causes Twilio 31941.
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Connect>
    <Stream url="{stream_url}" track="inbound_track" statusCallback="{stream_status}" statusCallbackMethod="POST">
      <Parameter name="call_id" value="{call_id}" />
    </Stream>
  </Connect>
</Response>"""


@router.api_route("/voice", methods=["GET", "POST"])
async def twilio_voice_webhook(
    request: Request,
    call_id: str = Query(...),
):
    settings = get_settings()
    logger.info(
        "Twilio VOICE webhook (%s) call_id=%s stream=%s",
        request.method,
        call_id,
        settings.media_stream_ws_url,
    )
    return Response(content=_voice_twiml(call_id), media_type="application/xml")


@router.api_route("/stream-status", methods=["GET", "POST"])
async def twilio_stream_status(
    request: Request,
    call_id: str = Query(""),
):
    """Twilio posts here when Media Stream starts, errors, or stops (debug stream vs phone)."""
    if request.method == "POST":
        form = await request.form()
        payload = dict(form)
    else:
        payload = dict(request.query_params)
    logger.info(
        "Twilio STREAM event call_id=%s event=%s error=%s payload=%s",
        call_id,
        payload.get("StreamEvent"),
        payload.get("StreamError"),
        payload,
    )
    return Response(content="", status_code=204)


@router.post("/status")
async def twilio_status_webhook(
    request: Request,
    call_id: str = Query(...),
    CallStatus: str = Form(""),
    CallSid: str = Form(""),
    To: str = Form(""),
    From: str = Form(""),
    ErrorCode: str = Form(""),
    ErrorMessage: str = Form(""),
):
    form = await request.form()
    status_map = {
        "initiated": "queued",
        "ringing": "ringing",
        "in-progress": "in_progress",
        "completed": "completed",
        "busy": "no_answer",
        "failed": "failed",
        "no-answer": "no_answer",
        "canceled": "failed",
    }
    mapped = status_map.get(CallStatus, "in_progress")
    logger.info(
        "Twilio status call_id=%s sid=%s %s->%s to=%s from=%s err=%s %s",
        call_id,
        CallSid,
        CallStatus,
        mapped,
        To or form.get("Called", ""),
        From or form.get("Caller", ""),
        ErrorCode,
        ErrorMessage,
    )
    if CallStatus in ("busy", "failed", "no-answer") and call_id:
        detail = ErrorMessage or CallStatus
        if ErrorCode:
            detail = f"{ErrorCode}: {detail}"
        await call_repo.update_status(call_id, mapped, twilio_call_sid=CallSid or None, outcome=detail)
        return Response(content="", status_code=204)
    if mapped == "completed":
        existing = await call_repo.get_by_id(call_id)
        if existing and existing.get("status") not in ("completed",):
            await call_repo.update_status(call_id, mapped, twilio_call_sid=CallSid or None)
    else:
        await call_repo.update_status(call_id, mapped, twilio_call_sid=CallSid or None)
    return Response(content="", status_code=204)
