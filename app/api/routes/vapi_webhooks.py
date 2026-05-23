import logging
from typing import Any

from fastapi import APIRouter, Request

from app.repositories.appointments import AppointmentRepository
from app.repositories.calls import CallRepository
from app.schemas.appointment import AppointmentUpdate
from app.scenarios import appointment_reminder

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks/vapi", tags=["vapi"])
call_repo = CallRepository()
appt_repo = AppointmentRepository()


def _extract_call_id(payload: dict[str, Any]) -> str | None:
    message = payload.get("message") or payload
    call = message.get("call") or payload.get("call") or {}
    metadata = call.get("metadata") or {}
    if metadata.get("call_id"):
        return str(metadata["call_id"])
    return None


def _extract_vapi_call_id(payload: dict[str, Any]) -> str | None:
    message = payload.get("message") or payload
    call = message.get("call") or payload.get("call") or {}
    return call.get("id")


def _parse_transcript(message: dict[str, Any]) -> list[dict[str, str]]:
    artifact = message.get("artifact") or {}
    turns: list[dict[str, str]] = []

    for item in artifact.get("messages") or message.get("messages") or []:
        role = item.get("role", "")
        content = item.get("message") or item.get("content") or ""
        if not content:
            continue
        if role in ("bot", "assistant"):
            turns.append({"role": "assistant", "content": content})
        elif role in ("user", "customer"):
            turns.append({"role": "user", "content": content})

    if not turns and artifact.get("transcript"):
        turns.append({"role": "system", "content": artifact["transcript"]})

    return turns


def _map_vapi_status(status: str) -> str:
    mapping = {
        "queued": "queued",
        "ringing": "ringing",
        "in-progress": "in_progress",
        "ended": "completed",
        "failed": "failed",
        "busy": "no_answer",
        "no-answer": "no_answer",
    }
    return mapping.get(status, "in_progress")


@router.post("")
async def vapi_server_webhook(request: Request):
    """Receives Vapi server messages (status updates, end-of-call reports)."""
    payload = await request.json()
    message = payload.get("message") or payload
    msg_type = message.get("type", "")
    call_id = _extract_call_id(payload)
    vapi_call_id = _extract_vapi_call_id(payload)

    if not call_id:
        logger.warning("Vapi webhook without call_id metadata: type=%s", msg_type)
        return {"ok": True}

    if msg_type == "status-update":
        status = _map_vapi_status((message.get("status") or message.get("call", {}).get("status", "")))
        await call_repo.update_status(
            call_id,
            status,  # type: ignore[arg-type]
            vapi_call_id=vapi_call_id,
        )
        return {"ok": True}

    if msg_type in ("end-of-call-report", "hang"):
        turns = _parse_transcript(message)
        if turns:
            await call_repo.set_conversation(call_id, turns)

        summary = (message.get("analysis") or {}).get("summary") or ""
        user_text = " ".join(t["content"] for t in turns if t["role"] == "user")
        assistant_text = " ".join(t["content"] for t in turns if t["role"] == "assistant")
        outcome = appointment_reminder.detect_outcome(user_text, assistant_text or summary)

        record = await call_repo.get_by_id(call_id)
        if record and record.get("appointment_id") and outcome:
            await appt_repo.update(record["appointment_id"], AppointmentUpdate(status=outcome))  # type: ignore[arg-type]

        await call_repo.update_status(
            call_id,
            "completed",
            vapi_call_id=vapi_call_id,
            outcome=outcome or "completed",
        )
        logger.info("Vapi call completed call_id=%s outcome=%s", call_id, outcome)
        return {"ok": True}

    logger.debug("Unhandled Vapi message type=%s call_id=%s", msg_type, call_id)
    return {"ok": True}
