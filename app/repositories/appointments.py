from datetime import datetime
from typing import Any

from bson import ObjectId
from pymongo import ReturnDocument

from app.db.mongodb import get_database
from app.schemas.appointment import AppointmentCreate, AppointmentUpdate


def _serialize(doc: dict[str, Any]) -> dict[str, Any]:
    doc["id"] = str(doc.pop("_id"))
    return doc


class AppointmentRepository:
    @property
    def collection(self):
        return get_database()["appointments"]

    async def create(self, data: AppointmentCreate) -> dict[str, Any]:
        now = datetime.utcnow()
        doc = {
            **data.model_dump(),
            "status": "scheduled",
            "created_at": now,
            "updated_at": now,
        }
        result = await self.collection.insert_one(doc)
        doc["_id"] = result.inserted_id
        return _serialize(doc)

    async def get_by_id(self, appointment_id: str) -> dict[str, Any] | None:
        if not ObjectId.is_valid(appointment_id):
            return None
        doc = await self.collection.find_one({"_id": ObjectId(appointment_id)})
        return _serialize(doc) if doc else None

    async def list_all(self, limit: int = 50) -> list[dict[str, Any]]:
        cursor = self.collection.find().sort("appointment_datetime", 1).limit(limit)
        return [_serialize(doc) async for doc in cursor]

    async def update(self, appointment_id: str, data: AppointmentUpdate) -> dict[str, Any] | None:
        if not ObjectId.is_valid(appointment_id):
            return None
        payload = {k: v for k, v in data.model_dump(exclude_unset=True).items() if v is not None}
        if not payload:
            return await self.get_by_id(appointment_id)
        payload["updated_at"] = datetime.utcnow()
        result = await self.collection.find_one_and_update(
            {"_id": ObjectId(appointment_id)},
            {"$set": payload},
            return_document=ReturnDocument.AFTER,
        )
        return _serialize(result) if result else None
