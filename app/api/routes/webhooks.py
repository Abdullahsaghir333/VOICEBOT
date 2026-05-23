from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import Response

from app.config import get_settings
from app.repositories.calls import CallRepository

router = APIRouter(prefix="/webhooks/twilio", tags=["twilio"])
call_repo = CallRepository()


@router.post("/voice")
async def twilio_voice_webhook(
    request: Request,
    call_id: str = Query(...),
):
    settings = get_settings()
    stream_url = settings.media_stream_ws_url
    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Connect>
    <Stream url="{stream_url}">
      <Parameter name="call_id" value="{call_id}" />
    </Stream>
  </Connect>
</Response>"""
    return Response(content=twiml, media_type="application/xml")


@router.post("/status")
async def twilio_status_webhook(
    call_id: str = Query(...),
    CallStatus: str = Form(""),
    CallSid: str = Form(""),
):
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
    if mapped == "completed":
        # Media stream handler sets completed with transcript; avoid overwriting too early
        existing = await call_repo.get_by_id(call_id)
        if existing and existing.get("status") not in ("completed",):
            await call_repo.update_status(call_id, mapped, twilio_call_sid=CallSid or None)
    else:
        await call_repo.update_status(call_id, mapped, twilio_call_sid=CallSid or None)
    return Response(content="", status_code=204)
