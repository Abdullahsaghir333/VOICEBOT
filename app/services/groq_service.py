import logging
from typing import Any

from groq import AsyncGroq

from app.config import get_settings
from app.scenarios import appointment_reminder

logger = logging.getLogger(__name__)


class GroqConversationService:
    def __init__(self) -> None:
        settings = get_settings()
        self._client = AsyncGroq(api_key=settings.groq_api_key)
        self._model = settings.groq_model

    async def generate_reply(
        self,
        *,
        scenario: str,
        context: dict[str, Any],
        history: list[dict[str, str]],
        user_message: str,
    ) -> str:
        if scenario == appointment_reminder.SCENARIO_ID:
            system = (
                appointment_reminder.SYSTEM_PROMPT
                + " "
                + appointment_reminder.build_context_block(context)
            )
        else:
            system = (
                "You are a helpful voice assistant on a phone call. "
                "Respond in 1-2 short sentences. Never use bullet points or special characters."
            )

        messages: list[dict[str, str]] = [{"role": "system", "content": system}]
        messages.extend(history)
        messages.append({"role": "user", "content": user_message})

        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                temperature=0.5,
                max_tokens=100,
            )
            return (response.choices[0].message.content or "").strip()
        except Exception:
            logger.exception("Groq request failed")
            raise
