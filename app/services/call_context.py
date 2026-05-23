from datetime import datetime

from app.repositories.appointments import AppointmentRepository
from app.schemas.call import OutboundCallRequest


async def resolve_call_context(body: OutboundCallRequest) -> tuple[str | None, dict]:
    appointment_id = body.appointment_id

    if appointment_id:
        appt = await AppointmentRepository().get_by_id(appointment_id)
        if not appt:
            raise ValueError("Appointment not found")
        context = {
            "patient_name": appt["patient_name"],
            "appointment_datetime": appt["appointment_datetime"],
            "provider_name": appt["provider_name"],
            "clinic_name": appt["clinic_name"],
            "clinic_address": appt["clinic_address"],
            "status": appt["status"],
        }
        return appointment_id, context

    context = {
        "patient_name": body.patient_name or "Guest",
        "appointment_datetime": body.appointment_datetime or datetime.utcnow(),
        "provider_name": body.provider_name or "Dr. Smith",
        "clinic_name": body.clinic_name or "HealthCare Plus Clinic",
        "clinic_address": body.clinic_address or "123 Wellness Ave",
        "status": "scheduled",
    }
    return None, context
