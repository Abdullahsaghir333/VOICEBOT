from fastapi import APIRouter, HTTPException

from app.config import get_settings
from app.repositories.calls import CallRepository
from app.schemas.call import CallListResponse, CallResponse, ConversationTurn, OutboundCallRequest
from app.services.call_context import resolve_call_context
from app.services.twilio_service import TwilioService

router = APIRouter(prefix="/calls", tags=["calls"])
call_repo = CallRepository()


def _to_response(doc: dict) -> CallResponse:
    turns = [ConversationTurn(**t) for t in doc.get("conversation", [])]
    return CallResponse(
        id=doc["id"],
        phone_number=doc["phone_number"],
        scenario=doc["scenario"],
        status=doc["status"],
        twilio_call_sid=doc.get("twilio_call_sid"),
        appointment_id=doc.get("appointment_id"),
        conversation=turns,
        outcome=doc.get("outcome"),
        created_at=doc["created_at"],
        updated_at=doc["updated_at"],
    )


@router.get("/status")
async def pipeline_status():
    """Whether the voice pipeline is ready to place calls."""
    settings = get_settings()
    return {
        "pipeline": "Twilio + Deepgram + Groq + Edge TTS",
        "twilio_configured": settings.twilio_configured,
        "deepgram_configured": bool(settings.deepgram_key),
        "groq_configured": bool(settings.groq_api_key),
        "public_base_url": settings.public_base_url,
        "media_stream_ws_url": settings.media_stream_ws_url,
        "ready": settings.twilio_configured
        and bool(settings.deepgram_key)
        and bool(settings.groq_api_key),
    }


@router.post("/outbound", response_model=CallResponse)
async def trigger_outbound_call(body: OutboundCallRequest):
    settings = get_settings()

    if not settings.twilio_configured:
        raise HTTPException(status_code=503, detail="Twilio is not configured (TWILIO_ACCOUNT_SID, TWILIO_PHONE_NUMBER)")
    if not settings.deepgram_key:
        raise HTTPException(status_code=503, detail="Deepgram is not configured (DEEPGRAM_API_KEY)")
    if not settings.groq_api_key:
        raise HTTPException(status_code=503, detail="Groq is not configured (GROQ_API_KEY)")

    try:
        appointment_id, context = await resolve_call_context(body)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    call_doc = await call_repo.create(
        phone_number=body.phone_number,
        scenario=body.scenario,
        appointment_id=appointment_id,
        context=context,
    )

    try:
        sid = TwilioService().place_outbound_call(body.phone_number, call_doc["id"])
        await call_repo.update_status(call_doc["id"], "ringing", twilio_call_sid=sid)
        call_doc["twilio_call_sid"] = sid
        call_doc["status"] = "ringing"
    except Exception as exc:
        await call_repo.update_status(call_doc["id"], "failed", outcome=str(exc))
        raise HTTPException(status_code=502, detail=f"Failed to place call: {exc}") from exc

    return _to_response(call_doc)


@router.get("", response_model=CallListResponse)
async def list_calls():
    docs = await call_repo.list_recent()
    calls = [_to_response(d) for d in docs]
    return CallListResponse(calls=calls, total=len(calls))


@router.get("/{call_id}", response_model=CallResponse)
async def get_call(call_id: str):
    doc = await call_repo.get_by_id(call_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Call not found")
    return _to_response(doc)
