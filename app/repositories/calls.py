from datetime import datetime
from typing import Any, Literal

from bson import ObjectId

from app.db.mongodb import get_database


def _serialize(doc: dict[str, Any]) -> dict[str, Any]:
    doc["id"] = str(doc.pop("_id"))
    return doc


class CallRepository:
    @property
    def collection(self):
        return get_database()["calls"]

    async def create(
        self,
        *,
        phone_number: str,
        scenario: str,
        appointment_id: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = datetime.utcnow()
        doc = {
            "phone_number": phone_number,
            "scenario": scenario,
            "appointment_id": appointment_id,
            "context": context or {},
            "status": "queued",
            "twilio_call_sid": None,
            "conversation": [],
            "outcome": None,
            "created_at": now,
            "updated_at": now,
        }
        result = await self.collection.insert_one(doc)
        doc["_id"] = result.inserted_id
        return _serialize(doc)

    async def get_by_id(self, call_id: str) -> dict[str, Any] | None:
        if not ObjectId.is_valid(call_id):
            return None
        doc = await self.collection.find_one({"_id": ObjectId(call_id)})
        return _serialize(doc) if doc else None

    async def get_by_twilio_sid(self, sid: str) -> dict[str, Any] | None:
        doc = await self.collection.find_one({"twilio_call_sid": sid})
        return _serialize(doc) if doc else None

    async def update_status(
        self,
        call_id: str,
        status: Literal["queued", "ringing", "in_progress", "completed", "failed", "no_answer"],
        *,
        twilio_call_sid: str | None = None,
        outcome: str | None = None,
    ) -> None:
        if not ObjectId.is_valid(call_id):
            return
        payload: dict[str, Any] = {"status": status, "updated_at": datetime.utcnow()}
        if twilio_call_sid:
            payload["twilio_call_sid"] = twilio_call_sid
        if outcome is not None:
            payload["outcome"] = outcome
        await self.collection.update_one({"_id": ObjectId(call_id)}, {"$set": payload})

    async def set_conversation(
        self,
        call_id: str,
        turns: list[dict[str, str]],
    ) -> None:
        if not ObjectId.is_valid(call_id):
            return
        conversation = [
            {"role": t["role"], "content": t["content"], "timestamp": datetime.utcnow()}
            for t in turns
        ]
        await self.collection.update_one(
            {"_id": ObjectId(call_id)},
            {"$set": {"conversation": conversation, "updated_at": datetime.utcnow()}},
        )

    async def append_turn(
        self,
        call_id: str,
        role: str,
        content: str,
        *,
        metrics: dict[str, Any] | None = None,
    ) -> None:
        if not ObjectId.is_valid(call_id):
            return
        turn: dict[str, Any] = {
            "role": role,
            "content": content,
            "timestamp": datetime.utcnow(),
        }
        if metrics:
            turn["metrics"] = metrics
        await self.collection.update_one(
            {"_id": ObjectId(call_id)},
            {
                "$push": {"conversation": turn},
                "$set": {"updated_at": datetime.utcnow()},
            },
        )

    async def list_recent(self, limit: int = 20) -> list[dict[str, Any]]:
        cursor = self.collection.find().sort("created_at", -1).limit(limit)
        return [_serialize(doc) async for doc in cursor]
