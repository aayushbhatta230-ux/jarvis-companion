"""Microphone capture and speech-to-text for JARVIS v0.1.

The audio input stream is opened once and kept alive on a dedicated capture
thread, so each utterance reuses the same device instead of paying the
Windows audio-pipeline warm-up cost on every turn. Captured frames land in a
bounded buffer that both ``listen`` (speech detection + STT) and
``monitor_speech`` (barge-in) consume. The buffer is cleared at the start of
each pass so stale or echoed audio is never mistaken for a new utterance.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import os
from threading import Condition, Event, Lock, Thread
from time import perf_counter

import numpy as np
import sounddevice as sd
import speech_recognition as sr

try:
	import webrtcvad
except ImportError:
	webrtcvad = None

from voice.interpretation import TranscriptInterpreter, TranscriptQuality


class ListenerError(RuntimeError):
	"""Raised when audio capture or transcription cannot complete."""


@dataclass
class TranscriptResult:
	text: str
	confidence: float
	duration: float
	audio_quality: str
	speech_detected: bool
	quality: TranscriptQuality | None = None


class Listener:
	def __init__(self, sample_rate: int = 16_000, silence_seconds: float = 0.75,
			 speech_seconds: float = 0.12, max_seconds: float = 20.0,
			 wait_seconds: float = 6.0,
			 start_threshold: float = 0.0, end_threshold: float = 0.0,
			 min_speech_duration: float = 0.15,
			 noise_floor: float = 0.005, pre_roll_ms: int = 400,
			 post_roll_ms: int = 450, sensitivity: float = 1.0) -> None:
		self.sample_rate = sample_rate
		self.silence_seconds = silence_seconds
		self.speech_seconds = speech_seconds
		self.max_seconds = max_seconds
		self.wait_seconds = wait_seconds
		self.start_threshold = start_threshold
		self.end_threshold = end_threshold
		self.min_speech_duration = min_speech_duration
		self.noise_floor = noise_floor
		self.pre_roll_ms = pre_roll_ms
		self.post_roll_ms = post_roll_ms
		self.sensitivity = max(0.4, min(2.5, float(sensitivity)))
		self.recognizer = sr.Recognizer()
		self.interpreter = TranscriptInterpreter()
		self._last_noise_floor = noise_floor

		self._block_size = 320
		self._buffer: deque[np.ndarray] = deque(maxlen=600)
		self._cv = Condition()
		self._capture_lock = Lock()
		self._capture_thread: Thread | None = None
		self._capture_started = Event()
		self._capture_stop = Event()
		self._capture_error: BaseException | None = None
		self._capture_stream: sd.InputStream | None = None

	def close(self) -> None:
		"""Stop the persistent capture thread and release the microphone."""
		self._capture_stop.set()
		thread = self._capture_thread
		if thread is not None and thread.is_alive():
			thread.join(timeout=2)
		with self._cv:
			self._buffer.clear()
		self._capture_started.clear()

	def _ensure_capture(self) -> bool:
		"""Start (or restart) the persistent capture thread.

		Returns True if the capture stream is now active, False if the
		microphone is still unavailable. A previously stored error is NOT
		treated as permanent — transient failures (device briefly busy,
		manager restart, etc.) are retried so the listener can recover
		without requiring a full JARVIS restart.
		"""
		with self._capture_lock:
			if self._capture_started.is_set():
				return True
			# Clear any stale error so we get a fresh attempt.
			self._capture_error = None
			self._capture_stop.clear()
			if self._capture_thread is None or not self._capture_thread.is_alive():
				self._capture_thread = Thread(
					target=self._capture_loop, name="jarvis-audio", daemon=True
				)
				self._capture_thread.start()
		# Wait outside the lock so _capture_loop can acquire _capture_lock!
		if not self._capture_started.wait(timeout=3.0):
			return False
		return True

	def _capture_loop(self) -> None:
		try:
			with sd.InputStream(
				samplerate=self.sample_rate, channels=1, dtype="float32",
				blocksize=self._block_size,
			) as stream:
				with self._capture_lock:
					self._capture_stream = stream
					self._capture_error = None
					self._capture_started.set()
				while not self._capture_stop.is_set():
					try:
						block, _ = stream.read(self._block_size)
					except Exception:
						continue
					with self._cv:
						self._buffer.append(block.copy())
						self._cv.notify()
		except Exception as exc:
			with self._capture_lock:
				if self._capture_error is None:
					self._capture_error = exc
				self._capture_stream = None
		finally:
			self._capture_started.clear()

	def _read_block(self, cancel_event: Event | None = None) -> np.ndarray:
		while True:
			if cancel_event is not None and cancel_event.is_set():
				raise ListenerError("Listening cancelled.")
			if not self._capture_started.is_set():
				raise ListenerError(
					"No speech was detected. Please try again."
				)
			if self._capture_error is not None:
				raise ListenerError(
					"Microphone unavailable. Check the Windows input device and permissions."
				) from self._capture_error
			with self._cv:
				if self._buffer:
					return self._buffer.popleft()
				self._cv.wait(0.05)
	def listen(self, cancel_event: Event | None = None) -> TranscriptResult:
		"""Wait for speech, stop after silence, then transcribe the utterance.

		Uses the persistent capture buffer (reopening the device only if it
		was never started or after a microphone error). The buffer is cleared
		first, so buffered echo or stale audio cannot trigger a false start.
		"""
		if not self._ensure_capture():
			# Fallback: capture a short audio snippet with sounddevice and transcribe using SpeechRecognition.
			try:
				# Record a brief segment (wait_seconds) and convert to AudioData.
				samples = sd.rec(int(self.wait_seconds * self.sample_rate), samplerate=self.sample_rate,
						channels=1, dtype='float32')
				sd.wait()
				# Convert float32 [-1,1] to int16 PCM bytes.
				pcm = (samples.flatten() * 32767).astype(np.int16).tobytes()
				audio = sr.AudioData(pcm, self.sample_rate, 2)
				text = self.recognizer.recognize_google(audio).strip()
				return TranscriptResult(
					text=text,
					confidence=0.0,
					duration=self.wait_seconds,
					audio_quality="fallback",
					speech_detected=bool(text),
					quality=None,
				)
			except Exception as exc:
				raise ListenerError(
					"Microphone unavailable. Check the Windows input device and permissions."
				) from exc
		with self._cv:
			self._buffer.clear()
		capture_started = perf_counter()
		block_size = self._block_size
		calibration_blocks = max(1, int(0.12 * self.sample_rate / block_size))
		blocks: list[np.ndarray] = []
		pre_roll: deque[np.ndarray] = deque(maxlen=max(1, int(self.pre_roll_ms / 1000 * self.sample_rate / block_size)))
		noise_levels: list[float] = []
		speech_started = False
		silence_blocks = 0
		start_time = None
		end_time = None
		try:
			while True:
				if cancel_event is not None and cancel_event.is_set():
					raise ListenerError("Listening cancelled.")
				block = self._read_block(cancel_event)
				level = float(np.sqrt(np.mean(np.square(block))))
				if len(noise_levels) < calibration_blocks:
					noise_levels.append(level)
					continue
				threshold = self._adaptive_threshold(noise_levels, level)
				if not speech_started:
					pre_roll.append(block.copy())
					if level >= threshold:
						blocks = list(pre_roll)
						pre_roll.clear()
						speech_started = True
						start_time = perf_counter()
					else:
						if perf_counter() - capture_started >= self.wait_seconds:
							raise ListenerError("No speech was detected. Please try again.")
					if not speech_started:
						continue
				blocks.append(block.copy())
				if level < threshold:
					silence_blocks += 1
				else:
					silence_blocks = 0
					if start_time and perf_counter() - start_time >= self.min_speech_duration:
						end_time = perf_counter()
				if silence_blocks >= max(1, int(self.silence_seconds * self.sample_rate / block_size)):
					# Keep the tail: the final word often trails into the silence
					# that ends the utterance; STT needs that trailing context or the
					# final word gets dropped.
					tail_blocks = max(1, int(self.post_roll_ms / 1000 * self.sample_rate / block_size))
					for _ in range(tail_blocks):
						try:
							blocks.append(self._read_block(cancel_event).copy())
						except ListenerError:
							break
					break
				if start_time and perf_counter() - start_time >= self.max_seconds:
					break
		except ListenerError:
			raise
		except Exception as exc:
			raise ListenerError(
				"Microphone unavailable. Check the Windows input device and permissions."
			) from exc
		if not speech_started or not blocks:
			raise ListenerError("No speech was detected. Please try again.")
		recording = np.concatenate(blocks, axis=0)
		duration = perf_counter() - capture_started
		transcript = self._transcribe(recording)
		assessment = self.interpreter.assess_quality(transcript)
		print(f"[STT QUALITY] confidence: {assessment.label.value if assessment.label else 'unknown'}")
		return TranscriptResult(
				text=transcript,
				confidence=assessment.confidence,
				duration=duration,
				audio_quality="good" if assessment.label in {TranscriptQuality.HIGH, TranscriptQuality.MEDIUM} else "noisy",
				speech_detected=True,
				quality=assessment.label,
		)

	def monitor_speech(self, stop_event: Event) -> bool:
		"""Detect a sustained human-speech-like onset while TTS is playing.

		WebRTC VAD is preferred when installed. The fallback combines sustained
		energy with zero-crossing activity; Windows SAPI does not expose an echo
		reference, so this remains best-effort on speakers that feed audio back.

		Because the microphone cannot distinguish JARVIS's own loudspeaker
		output from a real interruption, two safeguards are applied:
		a short refractory window right after monitoring starts (TTS
		onset/room reverb) and a strict sustained-speech requirement
		(energy well above the floor plus several consecutive VAD-positive
		blocks). This makes false self-interruptions rare.
		"""
		self._ensure_capture()
		if webrtcvad is None and os.getenv("JARVIS_BARGE_IN_FALLBACK", "0") != "1":
			return False
		with self._cv:
			self._buffer.clear()
		block_size = self._block_size
		block_seconds = block_size / self.sample_rate
		# ~0.9s refractory: the first moments of a sentence are dominated
		# by the assistant's own voice onset and room echo.
		refractory_blocks = max(1, int(0.9 / block_seconds))
		levels: list[float] = []
		streak = 0
		required_streak = 6  # ~120ms of continuous speech-like audio
		vad = webrtcvad.Vad(2) if webrtcvad is not None else None
		blocks_seen = 0
		try:
			while not stop_event.is_set():
				block = self._read_block()
				blocks_seen += 1
				if blocks_seen <= refractory_blocks:
					# Calibrate on ambient+TTS tail, but never trigger.
					if len(levels) < 12:
						levels.append(float(np.sqrt(np.mean(np.square(block)))))
					continue
				level = float(np.sqrt(np.mean(np.square(block))))
				if len(levels) < 12:
					levels.append(level)
					continue
				noise = max(self.noise_floor, float(np.median(levels)) * 3.0)
				pcm = self._as_pcm_bytes(block)
				if vad is not None:
					candidate = level >= noise and vad.is_speech(pcm, self.sample_rate)
				else:
					crossings = np.count_nonzero(np.diff(np.signbit(block.reshape(-1)))) / block_size
					candidate = level >= max(noise, .018) and crossings > .015
				streak = streak + 1 if candidate else max(0, streak - 1)
				if streak >= required_streak:
					return True
		except Exception as exc:
			print(f"[INTERRUPTION_MONITOR] unavailable: {exc}")
		return False

	def _adaptive_threshold(self, noise_levels: list[float], level: float) -> float:
		background = float(np.median(noise_levels)) if noise_levels else self.noise_floor
		self._last_noise_floor = background
		base = max(self.noise_floor, background * (2.5 / self.sensitivity))
		if self.start_threshold:
			base = max(base, self.start_threshold)
		if self.end_threshold:
			base = max(base, self.end_threshold)
		return float(base)

	def _transcribe(self, recording: np.ndarray) -> str:
		"""Transcribe with retries: plain, then volume-normalised.

		Quiet or soft-spoken audio often fails the first Google pass with
		UnknownValueError; boosting the level and retrying recovers many of
		those utterances instead of asking the user to repeat.
		"""
		attempts = [self._boosted(recording), recording]
		last_error: Exception | None = None
		for index, samples in enumerate(attempts):
			try:
				stt_started = perf_counter()
				audio = sr.AudioData(
					self._as_pcm_bytes(samples), self.sample_rate, 2
				)
				text = self.recognizer.recognize_google(audio).strip()
				print(f"[STT_END] completed: {perf_counter() - stt_started:.2f}s (pass {index + 1})")
				if text:
					return text
			except sr.UnknownValueError as exc:
				last_error = exc
				print(f"[STT] pass {index + 1} unclear, retrying with raw audio...")
			except sr.RequestError as exc:
				raise ListenerError("Speech recognition is unavailable right now.") from exc
			except Exception as exc:
				last_error = exc
		raise ListenerError("I could not understand that. Please try again.") from last_error

	@staticmethod
	def _boosted(recording: np.ndarray) -> np.ndarray:
		"""Normalise audio to a strong level and remove any DC offset."""
		samples = recording.reshape(-1).astype(np.float64)
		samples = samples - float(np.mean(samples))
		peak = float(np.max(np.abs(samples))) or 1.0
		target = 0.65
		if peak < target:
			samples = samples * (target / peak)
		return np.clip(samples, -1.0, 1.0).astype(np.float32).reshape(-1, 1)

	@staticmethod
	def _as_pcm_bytes(recording: np.ndarray) -> bytes:
		samples = np.clip(recording.reshape(-1), -1, 1)
		return (samples * 32767).astype(np.int16).tobytes()