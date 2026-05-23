from fastapi import APIRouter, HTTPException

from app.repositories.appointments import AppointmentRepository
from app.schemas.appointment import AppointmentCreate, AppointmentResponse, AppointmentUpdate

router = APIRouter(prefix="/appointments", tags=["appointments"])
repo = AppointmentRepository()


@router.post("", response_model=AppointmentResponse)
async def create_appointment(body: AppointmentCreate):
    doc = await repo.create(body)
    return AppointmentResponse(**doc)


@router.get("", response_model=list[AppointmentResponse])
async def list_appointments():
    docs = await repo.list_all()
    return [AppointmentResponse(**d) for d in docs]


@router.get("/{appointment_id}", response_model=AppointmentResponse)
async def get_appointment(appointment_id: str):
    doc = await repo.get_by_id(appointment_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Appointment not found")
    return AppointmentResponse(**doc)


@router.patch("/{appointment_id}", response_model=AppointmentResponse)
async def update_appointment(appointment_id: str, body: AppointmentUpdate):
    doc = await repo.update(appointment_id, body)
    if not doc:
        raise HTTPException(status_code=404, detail="Appointment not found")
    return AppointmentResponse(**doc)
