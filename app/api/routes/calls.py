from fastapi import APIRouter, HTTPException

from app.config import get_settings
from app.repositories.calls import CallRepository
from app.schemas.call import CallListResponse, CallResponse, ConversationTurn, OutboundCallRequest
from app.services.call_context import resolve_call_context
from app.services.twilio_service import TwilioService
from app.services.vapi_service import VapiService

router = APIRouter(prefix="/calls", tags=["calls"])
call_repo = CallRepository()


def _to_response(doc: dict) -> CallResponse:
    turns = [ConversationTurn(**t) for t in doc.get("conversation", [])]
    return CallResponse(
        id=doc["id"],
        phone_number=doc["phone_number"],
        scenario=doc["scenario"],
        provider=doc.get("provider", "custom"),
        status=doc["status"],
        twilio_call_sid=doc.get("twilio_call_sid"),
        vapi_call_id=doc.get("vapi_call_id"),
        appointment_id=doc.get("appointment_id"),
        conversation=turns,
        outcome=doc.get("outcome"),
        created_at=doc["created_at"],
        updated_at=doc["updated_at"],
    )


@router.get("/providers")
async def list_providers():
    settings = get_settings()
    return {
        "providers": [
            {
                "id": "custom",
                "name": "Custom pipeline",
                "description": "Twilio telephony + Deepgram STT + Groq LLM + Edge TTS",
                "configured": settings.twilio_configured,
                "requires_ngrok": True,
            },
            {
                "id": "vapi",
                "name": "Vapi",
                "description": "Vapi-managed voice stack (Groq + Deepgram configured in assistant)",
                "configured": settings.vapi_configured,
                "requires_ngrok": True,
                "webhook_path": "/webhooks/vapi",
            },
        ]
    }


@router.post("/outbound", response_model=CallResponse)
async def trigger_outbound_call(body: OutboundCallRequest):
    settings = get_settings()

    if body.provider == "custom" and not settings.twilio_configured:
        raise HTTPException(status_code=503, detail="Twilio is not configured for custom pipeline")
    if body.provider == "vapi" and not settings.vapi_configured:
        raise HTTPException(status_code=503, detail="Vapi is not configured (VAPI_API_KEY, VAPI_PHONE_NUMBER_ID)")

    try:
        appointment_id, context = await resolve_call_context(body)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    call_doc = await call_repo.create(
        phone_number=body.phone_number,
        scenario=body.scenario,
        provider=body.provider,
        appointment_id=appointment_id,
        context=context,
    )

    try:
        if body.provider == "vapi":
            vapi_id = await VapiService().create_outbound_call(
                phone_number=body.phone_number,
                call_id=call_doc["id"],
                scenario=body.scenario,
                context=context,
            )
            await call_repo.update_status(call_doc["id"], "ringing", vapi_call_id=vapi_id)
            call_doc["vapi_call_id"] = vapi_id
            call_doc["status"] = "ringing"
        else:
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
