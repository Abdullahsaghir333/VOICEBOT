"""
Custom voice pipeline (WebSocket only):
  Twilio -> Deepgram (STT, final only) -> Groq (LLM) -> Edge TTS -> Twilio

Async, non-blocking, with VAD barge-in and per-turn latency logging.
"""

import asyncio
import base64
import json
import logging
import time
from typing import Any

import websockets
from fastapi import WebSocketDisconnect
from websockets.exceptions import ConnectionClosed

from app.config import get_settings
from app.repositories.appointments import AppointmentRepository
from app.repositories.calls import CallRepository
from app.scenarios import appointment_reminder
from app.services.deepgram_stt import (
    build_listen_url,
    is_speech_started,
    parse_final_transcript,
)
from app.services.groq_service import GroqConversationService
from app.services.turn_metrics import TurnMetrics
from app.services.tts_service import chunk_mulaw, synthesize_mulaw

logger = logging.getLogger(__name__)


class MediaStreamSession:
    """Twilio Media Stream <-> Deepgram (final STT) <-> Groq <-> Edge TTS."""

    def __init__(self, twilio_ws: Any) -> None:
        self.twilio_ws = twilio_ws
        self.stream_sid: str | None = None
        self.call_id: str | None = None
        self.call_record: dict[str, Any] | None = None
        self.context: dict[str, Any] = {}
        self.scenario: str = appointment_reminder.SCENARIO_ID
        self.history: list[dict[str, str]] = []

        self._deepgram_ws: Any = None
        self._deepgram_ready = asyncio.Event()
        self._deepgram_task: asyncio.Task | None = None
        self._pipeline_task: asyncio.Task | None = None
        self._stopped = False
        self._restart_deepgram = asyncio.Event()
        self._interrupt = asyncio.Event()

        self._agent_speaking = False
        self._processing_turn = False

        self._call_repo = CallRepository()
        self._appt_repo = AppointmentRepository()
        self._llm = GroqConversationService()
        self._settings = get_settings()

    async def run(self) -> None:
        self._deepgram_task = asyncio.create_task(self._deepgram_loop())
        try:
            while True:
                message = await self.twilio_ws.receive_text()
                await self._handle_twilio_message(json.loads(message))
        except (ConnectionClosed, WebSocketDisconnect):
            logger.info("Twilio stream closed call_id=%s", self.call_id)
        finally:
            self._stopped = True
            self._restart_deepgram.set()
            if self._pipeline_task and not self._pipeline_task.done():
                self._pipeline_task.cancel()
            if self._deepgram_task:
                self._deepgram_task.cancel()
                await asyncio.gather(self._deepgram_task, return_exceptions=True)
            if self._deepgram_ws:
                await asyncio.gather(self._deepgram_ws.close(), return_exceptions=True)

    async def _handle_twilio_message(self, data: dict[str, Any]) -> None:
        try:
            event = data.get("event")
            if event == "start":
                start = data.get("start", {})
                self.stream_sid = start.get("streamSid")
                params = start.get("customParameters") or {}
                self.call_id = params.get("call_id")
                await self._load_call_context()
                if self.call_id:
                    await self._call_repo.update_status(self.call_id, "in_progress")
                try:
                    await asyncio.wait_for(self._deepgram_ready.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    logger.warning("Deepgram not ready in 5s — continuing greeting anyway")
                greeting = appointment_reminder.opening_line(self.context)
                logger.info("Starting greeting call_id=%s", self.call_id)
                self._pipeline_task = asyncio.create_task(
                    self._run_turn_pipeline(greeting, is_greeting=True)
                )
            elif event == "media":
                payload = data.get("media", {}).get("payload")
                if payload and self._deepgram_ws:
                    try:
                        await self._deepgram_ws.send(base64.b64decode(payload))
                    except Exception:
                        logger.debug("Deepgram send skipped (reconnecting) call_id=%s", self.call_id)
            elif event == "stop":
                await self._finalize_call()
        except Exception:
            logger.exception("Twilio message handler error call_id=%s", self.call_id)

    async def _deepgram_loop(self) -> None:
        if not self._settings.deepgram_key:
            logger.error("Deepgram API key not configured")
            return

        headers = {"Authorization": f"Token {self._settings.deepgram_key}"}
        url = build_listen_url()

        while not self._stopped:
            try:
                async with websockets.connect(url, additional_headers=headers) as dg_ws:
                    self._deepgram_ws = dg_ws
                    self._deepgram_ready.set()
                    logger.info("Deepgram connected (final-only STT) call_id=%s", self.call_id)

                    while not self._stopped:
                        if self._restart_deepgram.is_set():
                            self._restart_deepgram.clear()
                            logger.info("Deepgram restart after barge-in call_id=%s", self.call_id)
                            break

                        try:
                            raw = await asyncio.wait_for(dg_ws.recv(), timeout=0.25)
                        except asyncio.TimeoutError:
                            continue

                        try:
                            await self._handle_deepgram_message(json.loads(raw))
                        except Exception:
                            logger.exception("Deepgram message error call_id=%s", self.call_id)

            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Deepgram connection error call_id=%s", self.call_id)
                if not self._stopped:
                    await asyncio.sleep(0.5)
            finally:
                self._deepgram_ws = None

    async def _handle_deepgram_message(self, data: dict[str, Any]) -> None:
        if is_speech_started(data):
            if self._agent_speaking or self._processing_turn:
                await self._handle_barge_in()
            return

        transcript = parse_final_transcript(data)
        if not transcript:
            return

        if self._processing_turn:
            logger.debug("Ignoring overlapping final transcript during pipeline")
            return

        await self._on_user_speech(transcript)

    async def _handle_barge_in(self) -> None:
        logger.info("Barge-in detected call_id=%s", self.call_id)
        self._interrupt.set()
        await self._clear_twilio_playback()

        if self._pipeline_task and not self._pipeline_task.done():
            self._pipeline_task.cancel()
            await asyncio.gather(self._pipeline_task, return_exceptions=True)
            self._pipeline_task = None

        self._agent_speaking = False
        self._processing_turn = False
        self._restart_deepgram.set()

    async def _clear_twilio_playback(self) -> None:
        if not self.stream_sid:
            return
        try:
            await self.twilio_ws.send_text(
                json.dumps({"event": "clear", "streamSid": self.stream_sid})
            )
        except Exception:
            logger.exception("Failed to send Twilio clear event")

    async def _on_user_speech(self, text: str) -> None:
        if not self.call_id:
            return
        self._pipeline_task = asyncio.create_task(self._run_turn_pipeline(text))

    async def _run_turn_pipeline(self, user_text: str, *, is_greeting: bool = False) -> None:
        if is_greeting:
            try:
                self._agent_speaking = True
                tts_start = time.perf_counter()
                await self._speak(user_text, save_to_history=True)
                tts_ms = (time.perf_counter() - tts_start) * 1000
                if self.call_id:
                    await self._call_repo.append_turn(
                        self.call_id,
                        "assistant",
                        user_text,
                        metrics={"llm_ms": 0, "tts_ms": round(tts_ms, 1), "total_ms": round(tts_ms, 1)},
                    )
            except Exception:
                logger.exception("Greeting playback error call_id=%s", self.call_id)
            finally:
                self._agent_speaking = False
            return

        self._processing_turn = True
        metrics = TurnMetrics(user_text=user_text)
        metrics.mark_speech_end()
        metrics.mark_pipeline_start()

        try:
            if self.call_id:
                logger.info("User said (%s): %s", self.call_id, user_text)
                await self._call_repo.append_turn(self.call_id, "user", user_text)
            self.history.append({"role": "user", "content": user_text})

            if self._interrupt.is_set():
                return

            llm_start = time.perf_counter()
            reply = await self._llm.generate_reply(
                scenario=self.scenario,
                context=self.context,
                history=self.history[:-1],
                user_message=user_text,
            )
            llm_ms = (time.perf_counter() - llm_start) * 1000

            if self._interrupt.is_set():
                return

            tts_start = time.perf_counter()
            await self._speak(reply, save_to_history=True)
            tts_ms = (time.perf_counter() - tts_start) * 1000

            metric_payload = metrics.finish(
                assistant_text=reply,
                stt_ms=0.0,
                llm_ms=llm_ms,
                tts_ms=tts_ms,
            )

            if self.call_id:
                await self._call_repo.append_turn(
                    self.call_id,
                    "assistant",
                    reply,
                    metrics=metric_payload,
                )

            outcome = appointment_reminder.detect_outcome(user_text, reply)
            if outcome:
                await self._apply_outcome(outcome)
            if any(p in reply.lower() for p in ("goodbye", "good bye", "take care", "have a great day")):
                await asyncio.sleep(1.0)
                await self._finalize_call(outcome or "completed")

        except asyncio.CancelledError:
            logger.info("Pipeline cancelled (barge-in) call_id=%s", self.call_id)
        except Exception:
            logger.exception("Pipeline error call_id=%s", self.call_id)
            if self.call_id:
                fallback = "Sorry, I had a brief technical issue. Could you repeat that?"
                await self._speak(fallback, save_to_history=True)
                await self._call_repo.append_turn(self.call_id, "assistant", fallback)
        finally:
            self._processing_turn = False
            self._interrupt.clear()

    async def _speak(self, text: str, *, save_to_history: bool = False) -> None:
        if not text or not self.stream_sid:
            return

        self._agent_speaking = True
        try:
            audio = await synthesize_mulaw(text)
            if self._interrupt.is_set():
                await self._clear_twilio_playback()
                return

            for frame in chunk_mulaw(audio):
                if self._interrupt.is_set():
                    await self._clear_twilio_playback()
                    return
                payload = base64.b64encode(frame).decode("ascii")
                await self.twilio_ws.send_text(
                    json.dumps(
                        {
                            "event": "media",
                            "streamSid": self.stream_sid,
                            "media": {"payload": payload},
                        }
                    )
                )
                await asyncio.sleep(0.02)

            if save_to_history and not self._interrupt.is_set():
                self.history.append({"role": "assistant", "content": text})
        except Exception:
            logger.exception("TTS playback error call_id=%s", self.call_id)
        finally:
            self._agent_speaking = False

    async def _load_call_context(self) -> None:
        if not self.call_id:
            return
        self.call_record = await self._call_repo.get_by_id(self.call_id)
        if not self.call_record:
            return
        self.scenario = self.call_record.get("scenario", appointment_reminder.SCENARIO_ID)
        self.context = dict(self.call_record.get("context") or {})
        appt_id = self.call_record.get("appointment_id")
        if appt_id:
            appt = await self._appt_repo.get_by_id(appt_id)
            if appt:
                self.context.update(
                    {
                        "patient_name": appt.get("patient_name"),
                        "appointment_datetime": appt.get("appointment_datetime"),
                        "provider_name": appt.get("provider_name"),
                        "clinic_name": appt.get("clinic_name"),
                        "clinic_address": appt.get("clinic_address"),
                        "status": appt.get("status"),
                    }
                )

    async def _apply_outcome(self, outcome: str) -> None:
        if not self.call_record:
            return
        appt_id = self.call_record.get("appointment_id")
        if appt_id and outcome in ("confirmed", "cancelled", "reschedule_requested"):
            from app.schemas.appointment import AppointmentUpdate

            await self._appt_repo.update(appt_id, AppointmentUpdate(status=outcome))  # type: ignore[arg-type]
        if self.call_id:
            await self._call_repo.update_status(self.call_id, "in_progress", outcome=outcome)

    async def _finalize_call(self, outcome: str | None = None) -> None:
        if self.call_id:
            await self._call_repo.update_status(
                self.call_id,
                "completed",
                outcome=outcome or (self.call_record.get("outcome") if self.call_record else "completed"),
            )
