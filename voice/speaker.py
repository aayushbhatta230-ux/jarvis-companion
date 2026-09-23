"""Persistent, interruptible Windows SAPI text-to-speech for JARVIS."""

from __future__ import annotations

from queue import Empty, Queue
import os
from threading import Event, Lock, Thread
from time import perf_counter

import pythoncom
import win32com.client

from voice.text import sentence_chunks


class SpeakerError(RuntimeError):
	"""Raised when text-to-speech cannot complete."""


class Speaker:
	def __init__(self, rate: int = 1) -> None:
		self.rate = rate
		self.engine = None
		self.voice_name = "unavailable"
		self.queue: Queue[tuple[str, int]] = Queue()
		self.stop_event = Event()
		self.cancel_event = Event()
		self.ready = Event()
		self.speaking = Event()
		self.init_error = None
		self.engine_lock = Lock()
		self.generation = 0
		self.worker = Thread(target=self._run, name="jarvis-tts", daemon=True)
		self.worker.start()
		if not self.ready.wait(timeout=5):
			raise SpeakerError("Text-to-speech initialization timed out.")
		if self.init_error:
			raise SpeakerError("Text-to-speech could not be initialized.") from self.init_error

	def _select_voice(self):
		voices = self.engine.GetVoices()
		available = [voices.Item(index) for index in range(voices.Count)]
		preferred = os.getenv("JARVIS_VOICE", "").strip().lower()
		if preferred:
			voice = next((voice for voice in available if preferred in voice.GetDescription().lower()), None)
			if voice is not None:
				return voice
		return next(
			(voice for voice in available if any(word in voice.GetDescription().lower() for word in ("neural", "natural", "zira", "david"))),
			available[0] if available else None,
		)

	def _run(self) -> None:
		try:
			pythoncom.CoInitialize()
			self.engine = win32com.client.Dispatch("SAPI.SpVoice")
			voice = self._select_voice()
			if voice is not None:
				self.engine.Voice = voice
				self.voice_name = voice.GetDescription()
			self.engine.Rate = self.rate
			self.engine.Volume = 95
		except Exception as exc:
			self.init_error = exc
			self.ready.set()
			pythoncom.CoUninitialize()
			return
		self.ready.set()
		try:
			while not self.stop_event.is_set():
				try:
					item = self.queue.get(timeout=.2)
				except Empty:
					continue
				text, generation = item
				if generation != self.generation or self.cancel_event.is_set():
					self.queue.task_done()
					continue
				self.speaking.set()
				try:
					print(f"[TTS_START] {text[:48]}")
					with self.engine_lock:
						self.engine.Speak(text, 1)
					# Wait on the SAPI completion event directly. Polling through the
					# engine added several seconds of delay to short utterances.
					self.engine.WaitUntilDone(-1)
				except Exception as exc:
					print(f"Voice output: {exc}")
				finally:
					self.speaking.clear()
					self.queue.task_done()
		finally:
			pythoncom.CoUninitialize()

	def begin_utterance(self) -> None:
		"""Reset interruption state so a fresh turn can be spoken.

		``stop_speaking`` latches ``cancel_event`` (and bumps the generation)
		so in-flight chunks are dropped. That latch must be cleared when a new
		utterance starts, otherwise every subsequent streamed chunk is
		silently discarded and JARVIS appears to stop reading responses.
		"""
		self.cancel_event.clear()
		self.speaking.clear()

	def enqueue_chunk(self, text: str) -> None:
		"""Queue a single speakable chunk under the current generation.

		Unlike :meth:`speak`, this does not bump the generation or clear the
		cancel flag, so it can be called repeatedly as a response streams in.
		Queued chunks are still dropped automatically if an interruption bumps
		the generation or sets the cancel event.
		"""
		if not text or not text.strip():
			return
		for chunk in sentence_chunks(text):
			if chunk.strip():
				self.queue.put((chunk, self.generation))

	def speak(self, text: str, wait: bool = True) -> None:
		try:
			self.cancel_event.clear()
			generation = self.generation
			chunks = sentence_chunks(text)
			for chunk in chunks:
				self.queue.put((chunk, generation))
			if wait:
				self.wait_until_idle()
		except Exception as exc:
			raise SpeakerError("Text-to-speech failed.") from exc

	def wait_until_idle(self, timeout: float = 120.0) -> None:
		"""Block until every queued chunk has been spoken (or cancelled).

		Polls the queue's unfinished-task count so a wedged COM call can
		never stall the turn loop forever.
		"""
		started = perf_counter()
		while self.unfinished > 0 and perf_counter() - started < timeout:
			if self.cancel_event.is_set() and not self.speaking.is_set():
				break
			self.speaking.wait(0.05)
		while self.speaking.is_set() and not self.cancel_event.is_set():
			self.speaking.wait(.05)
			if perf_counter() - started > timeout:
				break
		print(f"[TTS] complete: {perf_counter() - started:.2f}s")

	@property
	def unfinished(self) -> int:
		"""Number of queued/in-progress chunks (0 when fully spoken)."""
		return getattr(self.queue, "unfinished_tasks", 0)

	def stop_speaking(self) -> None:
		"""Purge queued/current speech while keeping the worker reusable."""
		try:
			self.generation += 1
			self.cancel_event.set()
			if getattr(self, "engine", None) is not None:
				try:
					with getattr(self, "engine_lock", Lock()):
						self.engine.Speak("", 2)
				except Exception:
					pass
			while True:
				try:
					self.queue.get_nowait()
					self.queue.task_done()
				except Empty:
					break
			self.speaking.clear()
		except Exception as exc:
			raise SpeakerError("Text-to-speech could not be interrupted.") from exc

	def stop(self) -> None:
		try:
			self.stop_event.set()
			self.stop_speaking()
			self.worker.join(timeout=2)
		except Exception as exc:
			raise SpeakerError("Text-to-speech could not be stopped.") from exc
