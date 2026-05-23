from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class AppointmentCreate(BaseModel):
    patient_name: str
    patient_phone: str
    appointment_datetime: datetime
    provider_name: str = "Dr. Smith"
    clinic_name: str = "HealthCare Plus Clinic"
    clinic_address: str = "123 Wellness Ave"
    notes: str = ""


class AppointmentResponse(AppointmentCreate):
    id: str
    status: Literal["scheduled", "confirmed", "reschedule_requested", "cancelled"] = "scheduled"
    created_at: datetime


class AppointmentUpdate(BaseModel):
    status: Literal["scheduled", "confirmed", "reschedule_requested", "cancelled"] | None = None
    appointment_datetime: datetime | None = None
    notes: str | None = None
