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
from app.services.language import reply_language
from app.services.stt_filters import (
    is_incomplete_utterance,
    is_meaningful_transcript,
    normalize_phone_transcript,
    pick_best_transcript,
    question_intent_fingerprint,
)
from app.services.turn_metrics import TurnMetrics
from app.services.tts_service import chunk_mulaw, synthesize_mulaw
from app.services.twilio_service import TwilioService

logger = logging.getLogger(__name__)

# Ignore SpeechStarted (echo) for this long after TTS begins playing
BARGE_IN_LOCKOUT_SECONDS = 1.5
TTS_CHUNK_BATCH_SIZE = 12


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
        # Avoid VAD false barge-in during opening greeting (kills TTS before you hear it).
        self._barge_in_enabled = False

        self._stt_fragments: list[str] = []
        self._debounce_task: asyncio.Task | None = None
        self._queued_user_turn: str | None = None
        self._last_user_turn_normalized: str | None = None
        self._barge_in_unlock_task: asyncio.Task | None = None
        self._call_finished = False
        self._last_user_message = ""
        self._last_intent_fingerprint: str | None = None
        self._last_intent_at = 0.0

        self._call_repo = CallRepository()
        self._appt_repo = AppointmentRepository()
        self._llm = GroqConversationService()
        self._settings = get_settings()

    async def run(self) -> None:
        try:
            while not self._call_finished:
                try:
                    message = await self.twilio_ws.receive_text()
                except RuntimeError as exc:
                    # Expected when we hang up: local close runs before Twilio disconnects.
                    if self._call_finished or "not connected" in str(exc).lower():
                        logger.info("Twilio stream ended call_id=%s", self.call_id)
                        break
                    raise
                await self._handle_twilio_message(json.loads(message))
        except (ConnectionClosed, WebSocketDisconnect):
            logger.info("Twilio stream closed call_id=%s", self.call_id)
        finally:
            self._stopped = True
            self._restart_deepgram.set()
            if self._debounce_task and not self._debounce_task.done():
                self._debounce_task.cancel()
            self._cancel_barge_in_unlock_task()
            await self._cancel_pipeline_safe()
            if self._deepgram_task:
                self._deepgram_task.cancel()
                await asyncio.gather(self._deepgram_task, return_exceptions=True)
            if self._deepgram_ws:
                await asyncio.gather(self._deepgram_ws.close(), return_exceptions=True)

    async def _handle_twilio_message(self, data: dict[str, Any]) -> None:
        if self._call_finished:
            return
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
                self._deepgram_ready.clear()
                if self._deepgram_task is None or self._deepgram_task.done():
                    self._deepgram_task = asyncio.create_task(self._deepgram_loop())
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
            keepalive_task: asyncio.Task | None = None
            try:
                async with websockets.connect(url, additional_headers=headers) as dg_ws:
                    self._deepgram_ws = dg_ws
                    self._deepgram_ready.set()
                    logger.info("Deepgram connected (final-only STT) call_id=%s", self.call_id)
                    keepalive_task = asyncio.create_task(self._deepgram_keepalive(dg_ws))

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
            except ConnectionClosed as exc:
                if not self._stopped:
                    logger.warning(
                        "Deepgram closed call_id=%s (%s) — reconnecting",
                        self.call_id,
                        exc,
                    )
                    await asyncio.sleep(0.5)
            except Exception:
                logger.exception("Deepgram connection error call_id=%s", self.call_id)
                if not self._stopped:
                    await asyncio.sleep(0.5)
            finally:
                if keepalive_task:
                    keepalive_task.cancel()
                    await asyncio.gather(keepalive_task, return_exceptions=True)
                self._deepgram_ws = None

    async def _deepgram_keepalive(self, dg_ws: Any) -> None:
        """Prevent NET0001 idle timeout while the bot is speaking (no inbound audio yet)."""
        try:
            while not self._stopped and self._deepgram_ws is dg_ws:
                await asyncio.sleep(8)
                await dg_ws.send(json.dumps({"type": "KeepAlive"}))
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.debug("Deepgram keepalive stopped call_id=%s", self.call_id)

    async def _handle_deepgram_message(self, data: dict[str, Any]) -> None:
        if is_speech_started(data):
            # Only interrupt while assistant audio is playing — not during LLM or greeting setup.
            if self._barge_in_enabled and self._agent_speaking:
                await self._handle_barge_in()
            return

        transcript = parse_final_transcript(data)
        if not transcript:
            return

        if not is_meaningful_transcript(transcript):
            logger.debug("Skipping low-value STT fragment call_id=%s: %s", self.call_id, transcript)
            return

        self._stt_fragments.append(transcript)
        if self._debounce_task and not self._debounce_task.done():
            self._debounce_task.cancel()
        self._debounce_task = asyncio.create_task(self._flush_user_turn_after_debounce())

    async def _handle_barge_in(self) -> None:
        logger.info("Barge-in detected call_id=%s", self.call_id)
        self._barge_in_enabled = False
        self._interrupt.set()
        self._stt_fragments.clear()
        self._cancel_barge_in_unlock_task()
        if self._debounce_task and not self._debounce_task.done():
            self._debounce_task.cancel()
        await self._clear_twilio_playback()

        asyncio.create_task(self._cancel_pipeline_safe())

        self._agent_speaking = False
        self._processing_turn = False
        self._restart_deepgram.set()

    def _cancel_barge_in_unlock_task(self) -> None:
        if self._barge_in_unlock_task and not self._barge_in_unlock_task.done():
            self._barge_in_unlock_task.cancel()
        self._barge_in_unlock_task = None

    async def _clear_twilio_playback(self) -> None:
        if not self.stream_sid:
            return
        try:
            await self.twilio_ws.send_text(
                json.dumps({"event": "clear", "streamSid": self.stream_sid})
            )
        except Exception:
            logger.exception("Failed to send Twilio clear event")

    def _normalize_user_text(self, text: str) -> str:
        return normalize_phone_transcript(text, self.context.get("patient_name"))

    def _turn_key(self, text: str) -> str:
        return self._normalize_user_text(text).lower().strip()

    def _is_duplicate_user_turn(self, text: str) -> bool:
        key = self._turn_key(text)
        if not key:
            return True
        if self._last_user_turn_normalized == key:
            return True
        if self._queued_user_turn and key in self._turn_key(self._queued_user_turn):
            return True
        return False

    def _queue_user_turn(self, text: str) -> None:
        text = self._normalize_user_text(text)
        if self._is_duplicate_user_turn(text):
            return
        if self._queued_user_turn:
            merged = f"{self._queued_user_turn} {text}".strip()
            if self._turn_key(merged) == self._turn_key(self._queued_user_turn):
                return
            self._queued_user_turn = merged
        else:
            self._queued_user_turn = text
        logger.debug("Queued user turn while busy call_id=%s: %s", self.call_id, self._queued_user_turn)

    async def _flush_user_turn_after_debounce(self) -> None:
        """Wait for end of utterance, then run one LLM+TTS turn on the best final."""
        if self._call_finished:
            return
        delay = self._settings.stt_turn_debounce_ms / 1000.0
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            return

        fragments = self._stt_fragments
        self._stt_fragments = []
        raw = pick_best_transcript(fragments)
        if not raw:
            return

        text = self._normalize_user_text(raw)
        if text != raw:
            logger.info("STT normalized call_id=%s: %r -> %r", self.call_id, raw, text)

        if self._is_duplicate_user_turn(text):
            logger.debug("Skipping duplicate debounced turn call_id=%s: %s", self.call_id, text)
            return

        if is_incomplete_utterance(text):
            self._stt_fragments.append(text)
            self._debounce_task = asyncio.create_task(self._flush_user_turn_after_debounce())
            logger.debug("Incomplete utterance — waiting for more STT call_id=%s: %s", self.call_id, text)
            return

        intent = question_intent_fingerprint(text)
        if intent and intent == self._last_intent_fingerprint:
            if (time.perf_counter() - self._last_intent_at) < 25.0:
                logger.info("Skipping repeated %s question call_id=%s", intent, self.call_id)
                return

        if self._processing_turn:
            self._queue_user_turn(text)
            return

        self._schedule_user_turn(text)

    async def _cancel_pipeline_task(self) -> None:
        await self._cancel_pipeline_safe()

    async def _cancel_pipeline_safe(self) -> None:
        """Cancel pipeline from outside the pipeline task — avoids RecursionError."""
        task = self._pipeline_task
        if not task or task.done():
            return
        if task is asyncio.current_task():
            return
        task.cancel()
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=1.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass
        if self._pipeline_task is task:
            self._pipeline_task = None

    def _schedule_user_turn(self, text: str) -> None:
        if not self.call_id:
            return
        text = self._normalize_user_text(text)
        key = self._turn_key(text)
        if self._last_user_turn_normalized == key:
            logger.debug("Skipping duplicate user turn call_id=%s", self.call_id)
            return
        self._last_user_turn_normalized = key
        intent = question_intent_fingerprint(text)
        if intent:
            self._last_intent_fingerprint = intent
            self._last_intent_at = time.perf_counter()
        self._pipeline_task = asyncio.create_task(self._run_turn_pipeline(text))

    def _schedule_queued_turn_if_any(self) -> None:
        text = self._queued_user_turn
        if not text:
            return
        self._queued_user_turn = None
        logger.info("Running queued user turn call_id=%s: %s", self.call_id, text)
        self._schedule_user_turn(text)

    async def _maybe_run_queued_turn(self) -> None:
        if self._queued_user_turn and not self._processing_turn:
            self._schedule_queued_turn_if_any()

    async def _run_turn_pipeline(self, user_text: str, *, is_greeting: bool = False) -> None:
        if is_greeting:
            try:
                tts_start = time.perf_counter()
                await self._speak(user_text, save_to_history=True)
                tts_ms = (time.perf_counter() - tts_start) * 1000
                logger.info(
                    "Greeting played call_id=%s tts_ms=%.0f chars=%d",
                    self.call_id,
                    tts_ms,
                    len(user_text),
                )
                if self.call_id:
                    await self._call_repo.append_turn(
                        self.call_id,
                        "assistant",
                        user_text,
                        metrics={"llm_ms": 0, "tts_ms": round(tts_ms, 1), "total_ms": round(tts_ms, 1)},
                    )
            except Exception:
                logger.exception("Greeting playback error call_id=%s", self.call_id)
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
            self._last_user_message = user_text

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
            lang = reply_language(user_text, reply)
            await self._speak(reply, save_to_history=True, lang=lang)
            tts_ms = (time.perf_counter() - tts_start) * 1000
            logger.info(
                "Assistant spoke call_id=%s tts_ms=%.0f chars=%d lang=%s",
                self.call_id,
                tts_ms,
                len(reply),
                lang,
            )

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

            if outcome in appointment_reminder.TERMINAL_OUTCOMES:
                logger.info("Terminal outcome %s — ending call call_id=%s", outcome, self.call_id)
                await asyncio.sleep(1.2)
                await self._finalize_call(outcome)
                return

            if any(p in reply.lower() for p in ("goodbye", "good bye", "take care", "have a great day")):
                await asyncio.sleep(1.0)
                await self._finalize_call(outcome or "completed")
                return

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
            if not self._call_finished:
                await self._maybe_run_queued_turn()

    async def _enable_barge_in_after_delay(self, delay: float) -> None:
        """Enable barge-in after playback started (avoids echo on SpeechStarted)."""
        try:
            await asyncio.sleep(delay)
            if not self._interrupt.is_set() and not self._stopped:
                self._barge_in_enabled = True
                logger.debug("Barge-in enabled call_id=%s", self.call_id)
        except asyncio.CancelledError:
            pass
        finally:
            self._barge_in_unlock_task = None

    async def _speak(self, text: str, *, save_to_history: bool = False, lang: str = "en") -> None:
        if not text or not self.stream_sid:
            return

        self._agent_speaking = True
        self._interrupt.clear()
        self._barge_in_enabled = False
        self._cancel_barge_in_unlock_task()

        try:
            audio = await synthesize_mulaw(text, lang=lang)
            logger.debug("TTS ready call_id=%s bytes=%d lang=%s", self.call_id, len(audio), lang)
            if self._interrupt.is_set():
                await self._clear_twilio_playback()
                return

            self._barge_in_unlock_task = asyncio.create_task(
                self._enable_barge_in_after_delay(BARGE_IN_LOCKOUT_SECONDS)
            )

            chunks = chunk_mulaw(audio)
            for i in range(0, len(chunks), TTS_CHUNK_BATCH_SIZE):
                if self._interrupt.is_set():
                    await self._clear_twilio_playback()
                    return
                for frame in chunks[i : i + TTS_CHUNK_BATCH_SIZE]:
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
                await asyncio.sleep(0.016)

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
        if self._call_finished:
            return
        self._call_finished = True
        self._stopped = True
        self._queued_user_turn = None

        if self._debounce_task and not self._debounce_task.done():
            self._debounce_task.cancel()
        self._cancel_barge_in_unlock_task()

        resolved_outcome = outcome or (
            self.call_record.get("outcome") if self.call_record else "completed"
        )
        if self.call_id:
            await self._call_repo.update_status(
                self.call_id,
                "completed",
                outcome=resolved_outcome,
            )
            logger.info("Call completed call_id=%s outcome=%s", self.call_id, resolved_outcome)

        if self.call_id and (not self.call_record or not self.call_record.get("twilio_call_sid")):
            self.call_record = await self._call_repo.get_by_id(self.call_id)

        sid = self.call_record.get("twilio_call_sid") if self.call_record else None
        if sid:
            try:
                await asyncio.to_thread(TwilioService().hangup_call, sid)
            except Exception:
                logger.exception("Failed to hang up Twilio call call_id=%s sid=%s", self.call_id, sid)
        # Do not close twilio_ws here — Twilio closes the stream after hangup; run() exits cleanly.
