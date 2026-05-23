import logging
from typing import Any

import httpx

from app.config import get_settings
from app.scenarios.vapi_appointment import build_transient_assistant

logger = logging.getLogger(__name__)

VAPI_BASE = "https://api.vapi.ai"


class VapiService:
    def __init__(self) -> None:
        self._settings = get_settings()

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._settings.vapi_api_key}",
            "Content-Type": "application/json",
        }

    @property
    def server_url(self) -> str:
        base = self._settings.vapi_server_url or f"{self._settings.public_base_url.rstrip('/')}/webhooks/vapi"
        return base

    async def create_outbound_call(
        self,
        *,
        phone_number: str,
        call_id: str,
        scenario: str,
        context: dict[str, Any],
    ) -> str:
        payload: dict[str, Any] = {
            "phoneNumberId": self._settings.vapi_phone_number_id,
            "customer": {"number": phone_number},
            "metadata": {
                "call_id": call_id,
                "scenario": scenario,
            },
        }

        if self._settings.vapi_assistant_id:
            payload["assistantId"] = self._settings.vapi_assistant_id
        else:
            payload["assistant"] = build_transient_assistant(context, server_url=self.server_url)

        async with httpx.AsyncClient(timeout=45.0) as client:
            response = await client.post(
                f"{VAPI_BASE}/call",
                headers=self._headers(),
                json=payload,
            )
            if response.status_code >= 400:
                logger.error("Vapi create call failed: %s", response.text)
                response.raise_for_status()
            data = response.json()
            return data.get("id") or data.get("call", {}).get("id", "")

    async def get_call(self, vapi_call_id: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{VAPI_BASE}/call/{vapi_call_id}",
                headers=self._headers(),
            )
            response.raise_for_status()
            return response.json()
