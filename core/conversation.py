"""Continuous voice conversation orchestration for JARVIS v0.1.

The manager runs as a queue-driven worker on a background thread. Text commands
(submitted from the web UI) and captured speech (delivered by a dedicated listen
thread) are processed one turn at a time, and every state change / message is
broadcast through an :class:`core.events.EventHub` so the interface can reflect
the assistant in real time without polling.

Turns never overlap: while a turn is being classified, generated, or spoken the
microphone capture is paused. If the user talks while JARVIS is speaking, the
barge-in monitor interrupts TTS and immediately re-arms listening so the next
utterance is captured from its start.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from queue import Queue
from threading import Event, Lock, Thread
from time import perf_counter
from typing import Any
from uuid import uuid4

from core.brain import Brain, BrainError
from core.events import EventHub
from core.history import HistoryStore
from core.intent import IntentEngine
from core.planner import ActionPlanner
from core.memory import PreferenceStore
from core.settings import Settings
from voice.interpretation import TranscriptInterpreter, TranscriptQuality
from voice.listener import Listener, ListenerError, TranscriptResult
from voice.speaker import Speaker, SpeakerError
from voice.text import clean_for_speech, sentence_chunks
from tools.media import music_state
from core.openjarvis_agent import OpenJarvisAgent
from core.knowledge_graph import KnowledgeGraph

# UI/consumers only ever see this reduced state set; "thinking" is surfaced as
# Extended state set for the agent architecture
UI_STATES = ("idle", "listening", "understanding", "planning", "processing", "executing",
             "speaking", "waiting_confirmation", "interrupted", "error", "offline")


class ConversationManager:
	"""Coordinate text + voice turns, stream state/messages to subscribers."""

	VALID_STATES = {"idle", "listening", "understanding", "planning", "processing", "executing",
	                "speaking", "waiting_confirmation", "interrupted", "error"}

	def __init__(self, brain: Brain, speaker: Speaker, listener: Listener | None = None,
			 events: EventHub | None = None, settings: Settings | None = None,
			 history: HistoryStore | None = None,
			 state_callback: Callable[[str], None] | None = None,
			 allow_listen: bool | None = None) -> None:
		self.brain = brain
		self.openjarvis = OpenJarvisAgent(brain)
		self.speaker = speaker
		self.listener = listener
		from core.context import get_desktop_context
		self.desktop_context = get_desktop_context()
		self.events = events or EventHub()
		self.settings = settings or Settings()
		self.history = history or HistoryStore()
		self.state_callback = state_callback or (lambda state: None)
		self.running = True
		self.turn_id = 0
		self.state = "idle"
		self.interpreter = TranscriptInterpreter()
		self.intent_engine = IntentEngine()
		self.action_planner = ActionPlanner(self.intent_engine)
		self.preference_store = PreferenceStore()
		self.recent_context: list[str] = []
		self.request_lock = Lock()
		self.active_request_id: str | None = None
		self.completed_request_ids: set[str] = set()
		# Echo/self-hearing guard: the loudspeaker output can leak back into
		# the microphone and be transcribed as if the user had spoken it,
		# which caused JARVIS to keep re-answering itself.
		self._last_spoken_text: str = ""
		self._last_spoke_at: float = 0.0
		self._echo_guard_seconds: float = 12.0
		self._control_mode: bool = False
		# Cache the single intent classification for the current turn.
		# This avoids re-running the intent engine while building the LLM prompt.
		self._current_intent = None

		self.auto_listen = bool(self.settings.get("auto_listen")) if allow_listen is None else bool(allow_listen)
		self._inbox: Queue = Queue()
		self._pause = Event()          # set while a turn is being handled
		self._pause.set()
		self._listening = False
		self._listen_thread: Thread | None = None

		# Agent architecture: confirmation flow and context tracking
		self._pending_confirmation: dict | None = None
		self._last_file_reference: str | None = None
		self._last_search_results: list[str] = []
		self._conversation_context: dict[str, Any] = {}

		# Short-term memory + guided email draft flow.
		from core.memory import get_short_term_memory
		self.short_term = get_short_term_memory()
		self._email_flow: dict | None = None

	# ------------------------------------------------------------------ #
	# Public API (thread-safe)
	# ------------------------------------------------------------------ #

	def _refresh_screen_context(self) -> None:
		"""Capture the screen via OCR and update the shared desktop context.

		This is what actually populates ``visible_content`` for the brain's
		system prompt. Without it, the brain only sees the active window title
		and hallucinates the rest of the UI. Failures clear stale data rather
		than leaving a previous screen's contents in place.
		"""
		from core.permissions import PermissionLevel, get_permission_manager
		from vision.analyze import analyze_screen

		screen_permission = get_permission_manager().get_screen_permission()
		if screen_permission == PermissionLevel.OFF:
			self.desktop_context.recent_ocr_text = ""
			self.desktop_context.visible_content = ""
			self.desktop_context.recent_ocr_boxes = []
			return
		try:
			vision_result = analyze_screen()
			if vision_result.full_text.strip():
				self.desktop_context.update_screen(
					vision_result.full_text,
					[{"text": box.text, "bbox": box.bbox} for box in vision_result.boxes],
				)
			else:
				self.desktop_context.recent_ocr_text = ""
				self.desktop_context.visible_content = ""
				self.desktop_context.recent_ocr_boxes = []
		except Exception as exc:
			self.desktop_context.recent_ocr_text = ""
			self.desktop_context.visible_content = ""
			self.desktop_context.recent_ocr_boxes = []
			print(f"[CONTEXT] screen analysis failed: {exc}")

	def start(self) -> Thread:
		"""Begin the background worker that processes turns."""
		self._pause.clear()
		self._worker = Thread(target=self._process_loop, name="jarvis-brain", daemon=True)
		self._worker.start()
		if self.auto_listen and self.listener is not None:
			self._announce_ready()
			self._arm_listening()
		return self._worker

	def submit_text(self, text: str) -> None:
		"""Queue a typed command (no microphone involved)."""
		cleaned = (text or "").strip()
		if not cleaned:
			return
		self._inbox.put(("text", cleaned))

	def set_auto_listen(self, enabled: bool) -> None:
		"""Enable or disable continuous microphone capture from the UI."""
		enabled = bool(enabled)
		if enabled == self.auto_listen:
			return
		self.auto_listen = enabled
		try:
			if hasattr(self.settings, "set"):
				self.settings.set("auto_listen", enabled)
		except Exception as exc:  # noqa: BLE001 - settings write should not break the loop
			print(f"Settings: {exc}")
		if not enabled:
			# Cancel any in-flight listen block so capture stops promptly.
			self._pause.set()
			self._pause.clear()
			self.set_state("idle")
		else:
			if self.listener is not None:
				self._pause.clear()
				self._arm_listening()

	def stop(self) -> None:
		"""Stop workers, interrupt speech, and release the microphone."""
		self.running = False
		if getattr(self, "_worker", None) is None:
			self.speaker.stop()
			return
		try:
			self._inbox.put(None)
			self._worker.join(timeout=3)
		finally:
			self.speaker.stop_speaking()
			self.speaker.stop()
			if self.listener is not None:
				self.listener.close()

	# ------------------------------------------------------------------ #
	# Event + state helpers
	# ------------------------------------------------------------------ #

	def set_state(self, state: str) -> None:
		if state not in self.VALID_STATES:
			raise ValueError(f"Unknown conversation state: {state}")
		self.state = state
		self.state_callback(state)
		print(f"[STATE] {state.upper()}")
		self.events.emit({"type": "state", "state": state})
		if state == "idle" and getattr(self, "auto_listen", False):
			try:
				from core.proactive import check_proactive_suggestion
				sugg = check_proactive_suggestion()
				if sugg:
					self._emit_speech(True)
					self.speaker.speak(sugg, wait=True)
					self._emit_speech(False)
			except Exception as e:
				pass


	def _emit_message(self, role: str, text: str, status: str = "done", stream: bool = False) -> None:
		self.events.emit({
			"type": "message", "role": role, "text": text,
			"status": status, "stream": stream,
		})

	def _emit_notice(self, text: str) -> None:
		self.events.emit({"type": "notice", "text": text})

	def _emit_speech(self, active: bool) -> None:
		"""Tell the interface when voice output actually starts/stops so the
		core visual can animate in sync ("the brain talks")."""
		self.events.emit({"type": "speech", "active": bool(active)})

	def _request_id(self) -> str:
		request_id = str(uuid4())
		with self.request_lock:
			self.active_request_id = request_id
		return request_id

	def _finish_request(self, request_id: str | None) -> None:
		if request_id is None:
			return
		with self.request_lock:
			self.completed_request_ids.add(request_id)
			if request_id == self.active_request_id:
				self.active_request_id = None# ------------------------------------------------------------------ #
	# Worker loop + listening management
	# ------------------------------------------------------------------ #

	def _process_loop(self) -> None:
		"""Consume and process turns until stopped."""
		try:
			while self.running:
				item = self._inbox.get()
				if item is None:
					break
				kind = item[0]
				if kind == "text":
					self._handle_text(item[1])
				elif kind == "result":
					self._handle_result(item[1])
				elif kind == "no_speech":
					# Stay listening; just re-arm (no error spam to the UI).
					self._arm_listening()
				elif kind == "listen_error":
					print(f"[VOICE INPUT] {item[1]}")
					if "PortAudio" in str(item[1]) or "Hardware" in str(item[1]):
						self._emit_notice("Microphone unavailable â€” check input device.")
					self.set_state("listening")
					self._arm_listening()

		finally:
			# Only drop to idle when the microphone is not being re-armed;
			# otherwise the 'listening' state would be immediately stomped.
			if not (self.auto_listen and self.listener is not None and self.running):
				self.set_state("idle")

	def _handle_text(self, text: str) -> None:
		"""Route an explicitly typed command through the turn pipeline."""
		if not self._pause.is_set():
			self._pause.set()
		try:
			self._route_utterance(text, confidence=1.0, source="text")
		except BrainError as exc:
			self.set_state("error")
			print(f"AI: {exc}")
			self._emit_notice("The local model is unavailable. Start Ollama and pull the model.")
			self._speak_plain(str(exc))
		except Exception as exc:  # noqa: BLE001 - keep the loop alive
			self.set_state("error")
			print(f"Turn error: {exc}")
			self._emit_notice("Something went wrong. Please try again.")
		finally:
			if self.auto_listen and self.listener is not None:
				self._pause.clear()
				self._arm_listening()

	def _handle_result(self, result: TranscriptResult) -> None:
		"""Route a captured speech utterance through the turn pipeline."""
		if self._is_echo(result.text):
			print(f"[ECHO GUARD] dropped self-heard transcript: {result.text!r}")
			if self.auto_listen and self.listener is not None:
				self._arm_listening()
			return
		if not self._pause.is_set():
			self._pause.set()
		try:
			self._route_utterance(result.text, confidence=result.confidence, source="voice")
		except BrainError as exc:
			self.set_state("error")
			print(f"AI: {exc}")
			self._emit_notice("The local model is unavailable. Start Ollama and pull the model.")
			self._speak_plain(str(exc))
		except ListenerError as exc:
			print(f"Voice input: {exc}")
			self._emit_notice("I could not understand that. Please try again.")
		except Exception as exc:  # noqa: BLE001 - keep the loop alive
			self.set_state("error")
			print(f"Turn error: {exc}")
			self._emit_notice("Something went wrong. Please try again.")
		finally:
			if self.auto_listen and self.listener is not None:
				self._pause.clear()
				self._arm_listening()

	def _is_echo(self, transcript: str) -> bool:
		"""Detect the assistant hearing its own voice.

		A captured utterance is treated as echo when it closely matches what
		JARVIS said recently (the loudspeaker â†’ microphone leak) or arrives
		while speech output is still active.
		"""
		if self.speaker is not None and getattr(self.speaker, "speaking", None) is not None and self.speaker.speaking.is_set():
			return True
		if not self._last_spoken_text or not transcript:
			return False
		if perf_counter() - self._last_spoke_at > self._echo_guard_seconds:
			return False
		spoken_words = re.findall(r"\w+", self._last_spoken_text.lower())
		heard_words = re.findall(r"\w+", transcript.lower())
		if not spoken_words or not heard_words:
			return False
		spoken_set = set(spoken_words)
		overlap = sum(1 for word in heard_words if word in spoken_set)
		return overlap / len(heard_words) >= 0.75

	def _remember_spoken(self, text: str) -> None:
		self._last_spoken_text = text or ""
		self._last_spoke_at = perf_counter()

	def _arm_listening(self) -> None:
		"""Start a single listen thread unless one is already active or we are
		busy. The microphone persists across threads via the Listener, so this
		is cheap."""
		if self.listener is None or not self.auto_listen:
			return
		if self._listening or not self.running or self._pause.is_set():
			return
		# Cooldown after a real microphone error so a broken device does not
		# cause a tight re-try loop; we still recover once the device returns.
		last_error = getattr(self, "_last_listen_error", 0.0)
		if perf_counter() - last_error < 2.5:
			return
		self._listening = True
		self.set_state("listening")

		def runner() -> None:
			try:
				while self.running and self._listening and not self._pause.is_set():
					try:
						result = self.listener.listen(self._pause)
					except ListenerError as exc:
						message = str(exc)
						if "No speech was detected" in message:
							if self._pause.is_set():
								break
							# Brief back-off; the persistent stream keeps this cheap.
							self._pause.wait(0.05)
							continue
						if "Listening cancelled" in message:
							break
						if "I could not understand that" in message:
							print(f"[VOICE INPUT] {message}")
							self._pause.wait(0.05)
							continue
						self._last_listen_error = perf_counter()
						self._listening = False
						self._inbox.put(("listen_error", message))
						break
					else:
						if result is not None and result.text.strip():
							self._inbox.put(("result", result))
							break
			finally:
				self._listening = False

		self._listen_thread = Thread(target=runner, name="jarvis-listen", daemon=True)
		self._listen_thread.start()

	# ------------------------------------------------------------------ #
	# Turn pipeline (classify -> quick/action/LLM -> speak)
	# ------------------------------------------------------------------ #

	def _route_utterance(self, transcript: str, confidence: float, source: str) -> None:
		self.turn_id += 1
		turn = self.turn_id
		request_id = self._request_id()
		text = transcript.strip()
		if not text:
			self._finish_request(request_id)
			return
		print(f"[TURN {turn:03d}] {'VOICE' if source == 'voice' else 'TEXT'}: {text!r}")
		self._emit_message("user", text, status="done")
		self._current_raw_transcript = text

		# Normalize acoustic wake-word and conversational preambles for voice input
		clean_text = self.interpreter.normalize_speech_input(text) if source == "voice" else text
		effective_text = clean_text if clean_text else text

		# Handle pending confirmation first
		if self._pending_confirmation:
			confirm_response = self._handle_confirmation(text)
			if confirm_response is not None:
				self._finish_request(request_id)
				return

		# Understand the intent
		self.set_state("understanding")
		classified = self.intent_engine.infer(effective_text, self.recent_context, self.preference_store.snapshot())
		self._current_intent = classified

		# Cancellation of a pending/active action.
		if classified.intent == "control" and classified.sub_intent == "cancel":
			print(f"[TURN {turn:03d}] ACTION CANCELLED")
			self.speaker.stop_speaking()
			self._pending_confirmation = None
			self.set_state("idle")
			self._speak_plain("Never mind.")
			self._finish_request(request_id)
			return

		# Latency-sensitive social checks without a model round trip.
		quick = self._quick_response(effective_text)
		if quick is not None:
			self.set_state("speaking")
			self._emit_message("assistant", quick, status="done")
			interrupted = self._speak_with_barge_in(quick, turn)
			if interrupted:
				self._finish_request(request_id)
				self._absorb_interrupt()
				return
			self._append_context(f"Assistant: {quick}")
			self.history.append("assistant", quick)
			self._finish_request(request_id)
			return

		# Knowledge/research requests go to OpenJarvis before browser actions.
		# This prevents questions such as "search the web for..." from merely
		# opening Chrome; OpenJarvis searches, derives the answer, and returns
		# a concise result for JARVIS to display/speak. Explicit computer actions
		# such as "open Instagram" still go through the deterministic action layer.
		if self._needs_openjarvis(effective_text):
			try:
				openjarvis_response = self.openjarvis.run(effective_text)
				if openjarvis_response:
					self.set_state("speaking")
					self._emit_message("assistant", openjarvis_response, status="done")
					interrupted = self._speak_with_barge_in(openjarvis_response, turn)
					if interrupted:
						self._finish_request(request_id)
						self._absorb_interrupt()
						return
					self._append_context(f"Assistant: {openjarvis_response}")
					self.history.append("assistant", openjarvis_response)
					self._finish_request(request_id)
					return
			except Exception as exc:
				print(f"[OPENJARVIS] Error: {exc}")

		# Deterministic safe actions run after knowledge routing so commands
		# like "open Instagram" reach the existing JARVIS capability system.
		action_response = self._safe_action(effective_text, confidence, classified)
		if action_response:
			self.set_state("speaking")
			self._emit_message("assistant", action_response, status="done")
			interrupted = self._speak_with_barge_in(action_response, turn)
			if interrupted:
				self._finish_request(request_id)
				self._absorb_interrupt()
				return
			self._append_context(f"Assistant: {action_response}")
			self.history.append("assistant", action_response)
			self._finish_request(request_id)
			return


		# Only invoke the generic computer agent for computer/action intents.
		# Sending ordinary conversation through the agent adds latency and can
		# make JARVIS sound like it is narrating a tool workflow.
		agent_intents = {"app", "browser", "screen", "screen_control", "terminal", "code", "file"}
		if classified.intent in agent_intents:
			try:
				from agents import get_agent
				agent = get_agent()
				handled, agent_response = agent.handle(text)
				if handled and agent_response:
					self.set_state("speaking")
					self._emit_message("assistant", agent_response, status="done")
					interrupted = self._speak_with_barge_in(agent_response, turn)
					if interrupted:
						self._finish_request(request_id)
						self._absorb_interrupt()
						return
					self._append_context(f"Assistant: {agent_response}")
					self.history.append("assistant", agent_response)
					self._finish_request(request_id)
					return
			except Exception as e:
				print(f"[AGENT] Error: {e}")

		# Otherwise generate a response, streaming it to the UI and TTS.
		interpretation = self._interpret_turn(transcript)
		interpreted = interpretation if interpretation else text
		if interpretation:
			print(f"[TURN {turn:03d}] INTERPRETED: {interpretation!r}")
		prompt = self._companion_prompt(text, interpreted, intent=classified)
		self.set_state("processing")
		self._ready_stream()
		self._respond(prompt, turn, classified, text, request_id)# ------------------------------------------------------------------ #
	# Response generation (streamed to UI + TTS) and speech helpers
	# ------------------------------------------------------------------ #

	def _asks_detailed_explanation(self, text: str) -> bool:
		lower = (text or "").lower()
		return any(marker in lower for marker in ("explain in detail", "in detail", "detailed explanation", "step by step", "break down", "full explanation"))

	def _stream_options(self) -> dict:
		verbosity = self.settings.get("response_verbosity")
		if verbosity == "concise":
			return {"num_predict": 60}
		if verbosity == "detailed":
			return {"num_predict": 220}
		return {"num_predict": 90}

	def _push_speech(self, full_text: str) -> None:
		"""Enqueue newly-completed speakable sentences so TTS starts and
		progresses while the rest of the response is still being generated.
		"""
		if getattr(self, "_speech_buffer", None) is None:
			self._speech_buffer = ""
		self._speech_buffer = full_text
		clean = clean_for_speech(self._speech_buffer)
		confirmed = ""
		search_from = 0
		for match in re.finditer(r"[.!?]", clean):
			tail = clean[match.end():].lstrip()
			if not tail:
				continue
			preceding = re.search(r"(\S+)$", clean[: match.start()])
			if match.group(0) == "." and preceding and len(preceding.group(1).strip(".")) <= 1:
				continue
			confirmed = clean[: match.end()]
			search_from = match.end()
		chunks = [
			chunk.strip()
			for chunk in re.split(r"(?<=[.!?])\s+", confirmed[:search_from].strip())
			if chunk.strip()
		]
		already = getattr(self, "_spoken_parts", None)
		if already is None:
			self._spoken_parts = []
			already = self._spoken_parts

		max_sentences = 2 if not self._asks_detailed_explanation(getattr(self, "_current_raw_transcript", "")) else 10
		for chunk in chunks[len(already):]:
			if len(already) >= max_sentences:
				break
			if not already:
				self._emit_speech(True)
			self.speaker.enqueue_chunk(chunk)
			already.append(chunk)

	def _flush_speech(self, full_text: str) -> None:
		"""Speak whatever remains buffered once generation has finished."""
		clean = clean_for_speech(full_text or "")
		already = getattr(self, "_spoken_parts", [])
		remaining = [chunk.strip() for chunk in re.split(r"(?<=[.!?])\s+", clean) if chunk.strip()]
		max_sentences = 2 if not self._asks_detailed_explanation(getattr(self, "_current_raw_transcript", "")) else 10
		if not already and any(remaining):
			self._emit_speech(True)
		for chunk in remaining[len(already):]:
			if len(already) >= max_sentences:
				break
			if chunk:
				self.speaker.enqueue_chunk(chunk)
				already.append(chunk)
		self._speech_buffer = None
		self._spoken_parts = []

	def _needs_screen_context(self, intent, transcript: str = "") -> bool:
		"""Return True only when the model actually needs a fresh screen read.

		OCR is relatively expensive, so ordinary conversation should never
		pause for a screenshot. Screen/UI questions and computer-control
		requests are the cases where fresh visual context is useful.
		"""
		intent_name = getattr(intent, "intent", "") if intent is not None else ""
		sub_intent = getattr(intent, "sub_intent", "") if intent is not None else ""
		if intent_name in {"screen", "screen_control"}:
			return True
		lower = (transcript or "").lower()
		visual_markers = (
			"what's on my screen", "what is on my screen",
			"what do you see", "read my screen", "look at my screen",
			"what's open", "what is open", "what window is open",
			"where is the button", "find the button", "find the text",
			"click the", "click on the", "press the",
		)
		if any(marker in lower for marker in visual_markers):
			return True
		return sub_intent in {"screen", "screen_read", "screen_question", "click", "find_on_screen"}

	def _respond(self, prompt: str, turn: int, intent, transcript: str, request_id: str) -> None:
		started = perf_counter()
		print(f"[TURN {turn:03d}] LLM START")
		# Clear any latched interruption state from a previous turn so the
		# new response is actually spoken.
		try:
			self.speaker.begin_utterance()
		except Exception as exc:  # noqa: BLE001 - keep generating even if TTS hiccups
			print(f"Voice output reset: {exc}")
		self._speech_buffer = None
		self._spoken_parts = []
		monitor_stop, interrupted, monitor_thread = self._start_barge_in()
		display: list[str] = []
		# OCR is expensive. Refresh only when this turn actually needs visual
		# context; ordinary questions should go straight to the brain.
		if self._needs_screen_context(intent, transcript):
			self._refresh_screen_context()
		try:
			for chunk in self.brain.respond_stream(prompt, self._stream_options()):
				display.append(chunk)
				joined = "".join(display)
				self._emit_message("assistant", joined, status="streaming", stream=True)
				self._push_speech(joined)
				if interrupted.is_set():
					break
			response = "".join(display).strip()
		except BrainError as exc:
			self.set_state("error")
			print(f"AI: {exc}")
			self._emit_notice("The local model is unavailable. Start Ollama and pull the model.")
			self._speak_plain(str(exc))
			self._stop_barge_in(monitor_stop, interrupted, monitor_thread)
			self._finish_request(request_id)
			return
		finally:
			self._stop_barge_in(monitor_stop, interrupted, monitor_thread)

		if interrupted.is_set():
			print(f"[TURN {turn:03d}] INTERRUPTED DURING GENERATION")
			self._emit_speech(False)
			self._finish_request(request_id)
			self._absorb_interrupt()
			return
		print(f"[TURN {turn:03d}] LLM COMPLETE: {perf_counter() - started:.2f}s")
		if not response:
			response = "Hmm, I did not come up with a response. Try asking again."
		self._emit_message("assistant", response, status="done", stream=False)
		self._flush_speech(response)
		self._remember_spoken(clean_for_speech(response))
		self.set_state("speaking")
		print(f"[TURN {turn:03d}] TTS START")
		self.speaker.wait_until_idle()
		self._emit_speech(False)
		print(f"[TURN {turn:03d}] TTS COMPLETE")
		print(f"[TURN {turn:03d}] RESPONSE: {response}")
		self._append_context(f"Assistant: {response}")
		self.history.append("assistant", response)
		self._finish_request(request_id)
		self._current_intent = None
		self.set_state("idle")

	def _speak_plain(self, text: str) -> None:
		"""Speak without a barge-in monitor (used for errors/notices)."""
		self._emit_speech(True)
		try:
			self.speaker.speak(clean_for_speech(text), wait=True)
		except SpeakerError as exc:
			print(f"Voice output: {exc}")
		finally:
			self._emit_speech(False)

	def _speak_with_barge_in(self, text: str, turn: int) -> bool:
		"""Speak a short fixed response while watching for interruption."""
		print(f"[TURN {turn:03d}] SPEAKING")
		self._remember_spoken(clean_for_speech(text))
		self._emit_speech(True)
		monitor_stop, interrupted, monitor_thread = self._start_barge_in()
		try:
			self.speaker.speak(clean_for_speech(text), wait=True)
		finally:
			self._emit_speech(False)
			self._stop_barge_in(monitor_stop, interrupted, monitor_thread)
		if interrupted.is_set():
			print(f"[TURN {turn:03d}] RESPONSE CANCELLED")
			return True
		return False

	def _start_barge_in(self):
		"""Return (stop_event, interrupted_event, thread) for the monitor.

		Barge-in is opt-in via the ``barge_in`` setting (default off): on
		loudspeakers the microphone hears JARVIS's own voice, which used to
		trigger false interruptions â€” JARVIS cut itself off mid-word, then
		re-listened and answered its own echo. The UI Stop button and the
		"stop" voice command always work regardless of this setting.
		"""
		monitor_stop = Event()
		interrupted = Event()
		if not bool(self.settings.get("barge_in")) or self.listener is None:
			return monitor_stop, interrupted, None

		def monitor() -> None:
			if self.listener.monitor_speech(monitor_stop):
				print("[INTERRUPTION] user speech detected")
				interrupted.set()
				try:
					self.speaker.stop_speaking()
				except SpeakerError as exc:
					print(f"[TTS] stop failed: {exc}")

		thread = Thread(target=monitor, name="jarvis-barge-in", daemon=True)
		thread.start()
		return monitor_stop, interrupted, thread

	def _stop_barge_in(self, monitor_stop: Event, interrupted: Event, thread: Thread | None) -> None:
		monitor_stop.set()
		if thread is not None:
			thread.join(timeout=0.5)

	def _announce_ready(self) -> None:
		greeting = "JARVIS online. I am listening."
		self._emit_message("assistant", greeting, status="done")
		self.set_state("listening")# ------------------------------------------------------------------ #
	# Reasoning helpers (intent, safe actions, quick responses, context)
	# ------------------------------------------------------------------ #

	def _absorb_interrupt(self) -> None:
		"""After an interruption, immediately re-arm listening so the user's
		in-progress utterance is captured from its start rather than skipped."""
		self.set_state("interrupted")
		if self.auto_listen and self.listener is not None:
			self._pause.clear()
			self._arm_listening()

	def _ready_stream(self) -> None:
		"""Open a fresh assistant message box on the UI for streaming output."""
		self._emit_message("assistant", "", status="streaming", stream=True)

	def _interpret_turn(self, result) -> str | None:
		"""Accept a captured TranscriptResult or a plain typed string."""
		if isinstance(result, TranscriptResult):
			text, quality = result.text, result.quality
		else:
			text, quality = str(result), None
		if quality in {TranscriptQuality.HIGH, None}:
			return None
		corrected = self.interpreter.interpret(text, self.recent_context)
		print(f"[INTERPRETER] Meaning: {corrected.meaning}")
		print(f"[INTERPRETER] confidence: {corrected.confidence:.2f}")
		self._append_context(f"User: {text}")
		return corrected.meaning

	def _quick_response(self, transcript: str) -> str | None:
		"""Answer latency-sensitive social and profile checks without an LLM trip."""
		lower = transcript.lower().strip()
		normalized = lower.rstrip(" .!?")
		if any(phrase in lower for phrase in ("can you hear me", "are you there", "hello jarvis", "hi jarvis")):
			return "I'm here."
		if lower in {"hello", "hello jarvis", "hi", "hey jarvis"}:
			return "Hello."
		if any(phrase in lower for phrase in ("thank you", "thanks")):
			return "Anytime."
		if normalized in {"what is my name", "what's my name", "do you know my name"}:
			name = self.preference_store.snapshot().get("user_facts", {}).get("name", "Aayush")
			return f"You're {name}."
		return None

	def _needs_openjarvis(self, text: str) -> bool:
		"""Return True for knowledge, research, and multi-step reasoning tasks."""
		lower = (text or "").lower().strip()

		# Keep explicit browser/media navigation deterministic.
		computer_search_terms = (
			"search youtube", "search youtube music", "search instagram",
			"search google maps", "search spotify",
		)
		if any(term in lower for term in computer_search_terms):
			return False

		patterns = (
			"find and summarize", "search and summarize",
			"research", "look up and", "look up ", "compare",
			"analyze", "analyse", "summarize this", "summarise this",
			"what are the important parts", "find information about",
			"search the web", "search online", "look through my files",
			"find the file and", "calculate", "work out",
			"solve this using", "what is ", "what's ", "who is ",
			"who was ", "when did ", "where is ", "why is ",
			"how does ", "how do ", "how can ", "current ",
			"latest ", "population of ",
		)
		return any(pattern in lower for pattern in patterns)

	def _try_compound_actions(self, transcript: str, intent) -> str | None:
		"""Detect and execute compound commands split by 'and' / 'then'.

		Returns a combined result string if a compound command was detected and
		executed, or None if the transcript is a single action (so the caller
		should proceed with normal single-action handling).
		"""
		import re

		lower = transcript.lower().strip()
		# Only attempt splitting for actionable intents.
		if intent.intent not in ("app", "file", "screen_control", "browser", "terminal", "code"):
			return None

		# Split on " and " / " then " but NOT inside quoted strings.
		parts = re.split(r'\s+(?:and|then)\s+', lower, maxsplit=2)
		if len(parts) < 2:
			return None

		# Require at least two parts to look like distinct actions.
		action_verbs = ("open", "close", "write", "type", "create", "launch", "run",
						"search", "find", "show", "press", "click", "scroll", "switch")
		def _looks_like_action(text: str) -> bool:
			return any(text.strip().startswith(v) for v in action_verbs)

		if not all(_looks_like_action(p) for p in parts[:2]):
			return None

		results: list[str] = []
		for part in parts[:3]:
			part = part.strip(" .,!?")
			if not part:
				continue
			sub_intent = self.intent_engine.infer(part, self.recent_context, self.preference_store.snapshot())
			sub_result = self.action_planner.execute(part, sub_intent)
			if sub_result is None:
				continue
			if sub_result.success:
				results.append(sub_result.result or "Done.")
			elif sub_result.error == "CONFIRMATION_REQUIRED":
				results.append(f"(needs confirmation) {sub_result.result or part}")
			else:
				results.append(f"Could not {part}: {sub_result.error}")

		if not results:
			return None
		return " ".join(results)

	def _generate_and_save_content(self, transcript: str, intent, entities: dict) -> str:
		"""Generate content via the brain and save it to a file.

		This handles commands like "write an essay on mother and save it" where
		the content needs to be generated (not just extracted from the transcript).
		"""
		from tools.files import write_file
		from core.context import get_desktop_context

		topic = entities.get("content_topic", "notes")
		doc_type = entities.get("document_type", "notes")

		# Generate content via the brain
		generation_prompt = (
			f"Write a {doc_type} about {topic}. "
			f"Format it with clear headings and well-structured content. "
			f"Return only the {doc_type} content, no preamble or commentary."
		)
		try:
			content = self.brain.respond(generation_prompt)
		except Exception as exc:
			return f"I couldn't generate the {doc_type}: {exc}"

		if not content.strip():
			return f"I couldn't generate content for the {doc_type}."

		# Create a filename from the topic
		import re
		safe_topic = re.sub(r'[^\w\s-]', '', topic).strip().replace(' ', '_')[:40]
		filename = f"{safe_topic}_{doc_type}.txt"

		# Write the content to a file
		result = write_file(filename, content)
		if result.success:
			# Record in short-term memory
			self.short_term.record(
				transcript=transcript, intent="file", sub_intent="write",
				capability="file.write", arguments={"filepath": filename, "content_length": len(content)},
				result=f"Created {filename}", status="success",
				entities=entities,
			)
			get_desktop_context().add_action(f"Created {filename} with {doc_type} about {topic}")
			return f"Created '{filename}' with a {doc_type} about {topic}."
		else:
			return f"I couldn't save the {doc_type}: {result.error}"

	def _safe_action(self, transcript: str, speech_confidence: float = 1.0, intent=None) -> str | None:
		"""Execute an action and return the result, or None if AI should handle it."""
		from logs.actions import get_action_logger
		from core.context import get_desktop_context

		intent = intent or self.intent_engine.infer(transcript, self.recent_context, self.preference_store.snapshot())

		# Low confidence guard for voice commands
		if speech_confidence < 0.5 and intent.confidence < 0.6:
			return "Sorry, I didn't quite catch that."

		# Guided email draft flow (multi-turn subject/body/confirm/send).
		email_handled = self._try_email_flow(transcript, intent)
		if email_handled is not None:
			return email_handled

		# Handle permission control activations
		lower_clean = transcript.lower().strip()
		if any(phrase in lower_clean for phrase in ("full access", "full control", "access to everything", "unrestricted access", "all permissions", "control my screen", "computer control", "enable control")):
			self._control_mode = True
			from core.permissions import get_permission_manager, PermissionLevel
			msg = get_permission_manager().set_permission(PermissionLevel.FULL_CONTROL)
			return "Full computer control enabled. All screen, vision, and system capabilities are active."

		self.short_term.record(
			transcript=transcript, intent=intent.intent, sub_intent=intent.sub_intent,
			capability="", arguments={}, result=None, status="classified",
			entities=intent.extracted_entities,
		)

		# Set appropriate state
		if intent.intent in ("file", "app", "terminal", "code", "screen"):
			self.set_state("executing")
		else:
			self.set_state("processing")

		# Detect compound commands (e.g. "open notepad and write X") and split
		# them into sequential actions so both parts actually execute.
		compound_results = self._try_compound_actions(transcript, intent)
		if compound_results is not None:
			return compound_results

		# Handle content-generation commands: "write an essay on X and save it",
		# "create a study plan", etc. These need the brain to generate content
		# before writing to a file.
		if intent.intent == "file" and intent.sub_intent == "write":
			entities = intent.extracted_entities or {}
			if entities.get("needs_generation"):
				return self._generate_and_save_content(transcript, intent, entities)

		result = self.action_planner.execute(transcript, intent)
		if result is None:
			return None  # Let the AI handle it

		print(f"[INTENT] {intent.intent}/{intent.sub_intent} confidence={intent.confidence:.2f}")
		print(f"[TOOL] {result.tool} success={result.success}")

		# Handle confirmation requirement
		if not result.success and (result.error == "CONFIRMATION_REQUIRED" or result.status == "confirmation_required"):
			from core.permissions import get_permission_manager, PermissionLevel
			is_full = self._control_mode or (get_permission_manager().get_permission() == PermissionLevel.FULL_CONTROL)
			# In control mode or FULL_CONTROL, auto-confirm screen/app actions (except destructive ones)
			if is_full and intent.intent in ("screen_control", "app") and intent.sub_intent != "close":
				args = dict(result.arguments or {})
				try:
					confirmed_result = self.action_planner.execute_confirmed(result.tool, **args)
					if confirmed_result.success:
						self.short_term.record(
							transcript=transcript, intent=intent.intent, sub_intent=intent.sub_intent,
							capability=result.tool, arguments=args, result=confirmed_result.result,
							status="success", entities=intent.extracted_entities,
						)
						return f"Done. {confirmed_result.result}"
					else:
						return f"I couldn't complete that: {confirmed_result.error}"
				except Exception as exc:
					return f"I couldn't complete that: {exc}"

			self._pending_confirmation = {
				"capability": result.tool,
				"transcript": transcript,
				"intent": intent,
				"arguments": result.arguments or {},
			}
			self.short_term.record(
				transcript=transcript, intent=intent.intent, sub_intent=intent.sub_intent,
				capability=result.tool, arguments=result.arguments or {},
				result=None, status="pending_confirmation", entities=intent.extracted_entities,
			)
			self.set_state("waiting_confirmation")
			self.events.emit({
				"type": "confirmation_request",
				"capability": result.tool,
				"transcript": transcript,
				"description": f"JARVIS wants to execute '{result.tool}' for: '{transcript}'",
			})
			get_action_logger().log(
				user_input=transcript,
				intent=intent.intent,
				sub_intent=intent.sub_intent,
				capability=result.tool,
				status="pending_confirmation",
				rationale="Action requires user confirmation.",
			)
			return f"This action requires confirmation: '{result.tool}'. Shall I proceed?"

		if not result.success:
			get_action_logger().log(
				user_input=transcript,
				intent=intent.intent,
				sub_intent=intent.sub_intent,
				capability=result.tool,
				status="failure",
				error=result.error,
			)
			self.short_term.record(
				transcript=transcript, intent=intent.intent, sub_intent=intent.sub_intent,
				capability=result.tool, arguments=result.arguments or {},
				result=result.result or result.error, status="failed",
				entities=intent.extracted_entities,
			)
			return f"I couldn't complete that: {result.error}"

		# Log successful action
		get_action_logger().log(
			user_input=transcript,
			intent=intent.intent,
			sub_intent=intent.sub_intent,
			capability=result.tool,
			status="success",
			result=result.result,
		)
		get_desktop_context().add_action(f"Executed {result.tool}: {result.result[:80] if result.result else 'done'}")

		# Record into short-term memory for follow-ups ("what did you just do?").
		self.short_term.record(
			transcript=transcript, intent=intent.intent, sub_intent=intent.sub_intent,
			capability=result.tool, arguments=result.arguments or {},
			result=result.result, status="success", entities=intent.extracted_entities,
		)

		# Track context for follow-ups
		if intent.intent == "file" and intent.sub_intent in ("search", "open", "find_recent"):
			self._last_file_reference = result.result
		self._conversation_context["last_action"] = intent.sub_intent
		self._conversation_context["last_tool"] = result.tool

		# For file.read, pass the content to the LLM for analysis
		if intent.intent == "file" and intent.sub_intent == "read" and result.success and result.result:
			return self._analyze_file_content(transcript, result.result)

		# For file.write, verify the content was written correctly
		if intent.intent == "file" and intent.sub_intent == "write" and result.success:
			return self._verify_file_write(transcript, result.result, result.arguments)

		return result.result

	def _analyze_file_content(self, transcript: str, content: str) -> str:
		"""Pass file content to the LLM for analysis and return the response."""
		# Build a prompt that includes the actual file content
		prompt = (
			f"The user asked: \"{transcript}\"\n\n"
			f"The file contains the following content:\n\n"
			f"--- FILE CONTENT START ---\n"
			f"{content}\n"
			f"--- FILE CONTENT END ---\n\n"
			f"Based on the actual file content above, provide a helpful and accurate response. "
			f"Summarize the content if asked, or answer the user's question using only the information in the file. "
			f"Do not invent or guess any information that is not in the file."
		)
		try:
			return self.brain.respond(prompt)
		except Exception as e:
			return f"I read the file but couldn't analyze it: {e}"

	def _verify_file_write(self, transcript: str, result_msg: str, arguments: dict) -> str:
		"""Verify that file content was written correctly by reading it back."""
		if not arguments:
			return result_msg
		filepath = arguments.get("filepath") or arguments.get("path")
		expected_content = arguments.get("content")
		if not filepath or not expected_content:
			return result_msg
		try:
			from tools.files import read_file
			actual_content = read_file(filepath)
			if not isinstance(actual_content, dict):
				return result_msg
			if actual_content.get("content") == expected_content:
				return f"Done. I wrote the content to {filepath} and verified it."
			else:
				return f"I wrote the file, but the content doesn't match what was expected."
		except Exception:
			# If verification fails, just return the original result
			return result_msg

	def _try_email_flow(self, transcript: str, intent) -> str | None:
		"""Guided multi-turn email flow: recipient -> subject -> body -> confirm -> send.

		Returns a response string when the turn belongs to the email conversation,
		or None to let the normal pipeline handle it.
		"""
		import re as _re
		lower = transcript.lower().strip()
		flow = self._email_flow

		# Fresh "draft an email to X" request.
		if flow is None:
			if intent.intent == "email" and intent.sub_intent == "draft":
				recipient = (intent.extracted_entities or {}).get("recipient")
				if not recipient:
					m = _re.search(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", transcript)
					recipient = m.group(0) if m else None
				if not recipient:
					return "Who should I send it to? I need the email address."
				self._email_flow = {"stage": "need_subject", "to": recipient}
				return f"I've started an email to {recipient}. What should the subject be?"
			# "send it" when we already have a stored draft.
			if any(w in lower for w in ("send it", "send", "yes, send", "go ahead")):
				if self.short_term.active_draft and self.short_term.active_draft.get("body"):
					return self._send_active_email(intent)
			return None

		# Cancellation or decline mid-flow.
		if intent.intent == "control" and intent.sub_intent == "cancel":
			self._email_flow = None
			return "Cancelled the email."

		stage = flow.get("stage")
		if stage == "need_subject":
			subject = transcript.strip(" .!?")
			if not subject:
				return "What should the subject be?"
			flow["subject"] = subject
			flow["stage"] = "need_body"
			return f"Subject '{subject}' â€” what should I write?"

		if stage == "need_body":
			body = transcript.strip()
			if not body:
				return "What should I write in the body?"
			flow["body"] = body
			flow["stage"] = "ready"
			self.short_term.set_active_draft({
				"to": flow["to"], "subject": flow.get("subject", ""), "body": body,
			})
			return (f"I've drafted it to {flow['to']} with subject "
					f"'{flow.get('subject', '')}'. Do you want me to send it?")

		if stage == "ready":
			if any(w in lower for w in ("yes", "yep", "yeah", "send", "send it", "go ahead", "confirm", "proceed")):
				return self._send_active_email(intent)
			if any(w in lower for w in ("no", "don't", "cancel", "edit", "change")):
				self._email_flow = None
				return "Okay, I won't send it yet. You can edit by telling me the change."
			return "Do you want me to send it, or would you like to change the draft?"

		return None

	def _email_intent_stub(self):
		class _Stub:
			intent = "email"
			sub_intent = "send"
		return _Stub()

	def _send_active_email(self, intent) -> str:
		from core.capabilities import execute_capability
		flow = self._email_flow
		draft = flow or self.short_term.active_draft or {}
		recipient = flow["to"] if flow else (draft or {}).get("to", "")
		args = {
			"to": recipient or "",
			"subject": (draft or {}).get("subject", "") or "",
			"body": (draft or {}).get("body", "") or "",
		}
		if not args["to"]:
			return "Who should I send it to? I need the email address."
		result = execute_capability("email.send_direct", to=args["to"], subject=args["subject"], body=args["body"])
		if result.status == "confirmation_required":
			self._pending_confirmation = {
				"capability": "email.send_direct",
				"transcript": "send the drafted email",
				"intent": self._email_intent_stub(),
				"arguments": args,
			}
			self.set_state("waiting_confirmation")
			self._email_flow = None
			return ("The email will be sent from your real configured account. "
					"Confirm that you want me to send it?")
		self._email_flow = None
		if result.success:
			return result.result
		return f"Sending failed: {result.error}"

	def _handle_confirmation(self, text: str) -> str | None:
		"""Handle user response to a pending confirmation. Returns response or None."""
		from logs.actions import get_action_logger
		from core.context import get_desktop_context

		lower = text.lower().strip()
		confirm = any(word in lower for word in ("yes", "yeah", "yep", "sure", "okay", "ok", "go ahead", "do it", "send it", "confirm", "proceed", "give me proceed", "you me", "you may", "proceed with", "do that", "execute"))
		decline = any(word in lower for word in ("no", "nope", "don't", "cancel", "never mind", "stop", "don't do it"))

		if not confirm and not decline:
			self._pending_confirmation = None
			return None

		pending = self._pending_confirmation
		self._pending_confirmation = None

		if decline:
			self.set_state("idle")
			get_action_logger().log(
				user_input=text,
				intent="control",
				sub_intent="cancel",
				capability=pending["capability"],
				status="cancelled",
				rationale="User declined confirmation.",
			)
			return "Okay, I won't do that."

		# Execute the confirmed action
		self.set_state("executing")
		args = dict(pending.get("arguments") or {})
		try:
			result = self.action_planner.execute_confirmed(pending["capability"], **args)
		except TypeError:
			# capability does not accept these keywords (defensive).
			result = self.action_planner.execute_confirmed(pending["capability"])
		if result.success:
			self.set_state("speaking")
			get_action_logger().log(
				user_input=pending["transcript"],
				intent=pending["intent"].intent,
				sub_intent=pending["intent"].sub_intent,
				capability=pending["capability"],
				status="success",
				result=result.result,
				rationale="Confirmed by user.",
			)
			self.short_term.record(
				transcript=pending["transcript"], intent=pending["intent"].intent,
				sub_intent=pending["intent"].sub_intent, capability=pending["capability"],
				arguments=args, result=result.result, status="success",
			)
			get_desktop_context().add_action(f"Executed confirmed {pending['capability']}")
			return f"Done. {result.result}"
		else:
			self.set_state("error")
			get_action_logger().log(
				user_input=pending["transcript"],
				intent=pending["intent"].intent,
				sub_intent=pending["intent"].sub_intent,
				capability=pending["capability"],
				status="failure",
				error=result.error,
			)
			self.short_term.record(
				transcript=pending["transcript"], intent=pending["intent"].intent,
				sub_intent=pending["intent"].sub_intent, capability=pending["capability"],
				arguments=args, result=result.result or result.error, status="failed",
			)
			return f"I couldn't complete that: {result.error}"


	def _voice_response(self, response: str, sub_intent: str, transcript: str) -> str:
		"""Keep ordinary turns to one sentence; preserve requested explanations."""
		lower = transcript.lower()
		asks_explanation = any(marker in lower for marker in ("why", "how", "explain", "tell me about", "in detail"))
		if sub_intent in {"general_request", "general_question"} and not asks_explanation:
			chunks = sentence_chunks(response)
			return chunks[0] if chunks else response.strip()
		return response

	def _companion_prompt(
		self,
		transcript: str,
		interpreted_text: str,
		action_result: str | None = None,
		intent=None,
	) -> str:
		# Reuse the intent already classified by _route_utterance. The fallback
		# keeps this helper safe for any older caller that does not pass one.
		intent = intent or self._current_intent
		preferences = self.preference_store.snapshot()
		if intent is None:
			intent = self.intent_engine.infer(transcript, self.recent_context, preferences)

		learned = self.preference_store.learn_from_text(transcript, explicit=True)
		if learned:
			print(f"[PREFERENCES] explicit evidence: {', '.join(learned)}")
			preferences = self.preference_store.snapshot()
		context = " | ".join(self.recent_context[-6:]) or "No reliable recent context."
		interests = self.preference_store.top_interests()
		preference_text = ", ".join(f"{topic} ({score:.2f})" for topic, score in interests) or "No established interests yet."
		facts = ", ".join(f"{key}: {value}" for key, value in preferences.get("user_facts", {}).items()) or "No additional saved facts."
		media_status = f"playing={music_state.playing}, paused={music_state.paused}, source={music_state.source or 'none'}"
		verbosity = self.settings.get("response_verbosity")
		length = "one short sentence" if verbosity == "concise" else "a concise few sentences" if verbosity == "normal" else "a thorough but clear explanation"
		confirmation = "required before any consequential action" if intent.needs_confirmation else "not required for a harmless response"
		# Build reference resolution context so the brain can resolve
		# "that", "it", "the file", etc. without asking the user.
		last_action = self.short_term.describe_last_action()
		reference_line = f"Last action: {last_action}" if last_action else ""
		recent_file = self.desktop_context.current_file or self.desktop_context.last_target
		if recent_file:
			reference_line += f" | Recent file/target: {recent_file}"

		# Include the action result so the brain knows what was just executed
		# and doesn't ask the user to repeat themselves.
		action_line = f"Action just executed: {action_result}" if action_result else ""

		return (
			"Respond as a personal companion, not a command parser.\n"
			f"User transcript: {transcript}\n"
			f"Interpreted wording: {interpreted_text}\n"
			f"Likely intent: {intent.intent} / {intent.sub_intent} ({intent.confidence:.2f})\n"
			f"Reasoning note: {intent.rationale}\n"
			f"Relevant recent context: {context}\n"
			f"{reference_line}\n"
			f"{action_line}\n"
			f"Long-term preference evidence: {preference_text}\n"
			f"Saved user facts: {facts}\n"
			f"Current media state: {media_status}\n"
			f"Confirmation status: {confirmation}.\n"
			"Use the likely meaning without forcing the user to repeat an exact command. "
			"When the user says 'that', 'it', 'the file', etc., resolve it from the Last action "
			"and Recent file/target above. Never ask 'which one?' when the referent is clear. "
			f"For a simple request or greeting, answer in {length}. Do not narrate "
			"microphones, audio processing, internal states, or assistant architecture. "
			"Only give a longer answer when the user explicitly asks for an explanation."
		)

	def _append_context(self, phrase: str) -> None:
		self.recent_context.append(phrase)
		if len(self.recent_context) > 10:
			self.recent_context = self.recent_context[-10:]


