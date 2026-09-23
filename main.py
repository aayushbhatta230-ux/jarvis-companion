"""Run JARVIS v0.1 continuously: local web interface + voice brain-loop.

The web interface comes up first so the browser is never left "offline"
while the voice stack (TTS, microphone, model) initialises. Every subsystem
is optional: a failure in speech output or microphone capture degrades to a
text-only assistant with a notice in the UI instead of crashing the process.
Close the window or press Ctrl+C to stop.
"""

from __future__ import annotations

from threading import Thread

from core.brain import Brain
from core.conversation import ConversationManager
from core.events import EventHub
from core.history import HistoryStore
from core.settings import Settings
from interface.server import create_server
from voice.listener import Listener
from voice.speaker import Speaker, SpeakerError

HOST = "127.0.0.1"
PORTS = (8765, 8766, 8767, 8768, 8769, 8770)


def _bind_server(manager: ConversationManager, settings: Settings, history: HistoryStore):
	"""Bind the web server on the first free port."""
	last_error: Exception | None = None
	for port in PORTS:
		try:
			server = create_server(manager, settings, history, host=HOST, port=port)
			print(f"[WEB] interface at http://{HOST}:{port}/")
			return server
		except OSError as exc:
			last_error = exc
			print(f"[WEB] port {port} unavailable: {exc}")
	raise RuntimeError(f"Could not bind a web port ({PORTS[0]}-{PORTS[-1]}).") from last_error


def main() -> None:
	print("JARVIS v0.1 ready. Press Ctrl+C to stop.")
	settings = Settings()
	history = HistoryStore()
	events = EventHub()
	speaker = None
	listener = None
	manager = None
	server = None
	try:
		# 1. Web first: the UI shows "online" the moment this returns.
		brain = Brain()
		manager = ConversationManager(brain, speaker=None, events=events,
			settings=settings, history=history)
		server = _bind_server(manager, settings, history)

		# 2. Warm the model in the background so the first turn is fast.
		Thread(target=brain.warm_up, name="jarvis-warmup", daemon=True).start()

		# 3. Voice output (optional — text-only fallback on failure).
		try:
			speaker = Speaker()
		except SpeakerError as exc:
			print(f"Voice output unavailable: {exc}")
			events.emit({"type": "notice", "text": f"Speech output unavailable: {exc}"})
		manager.speaker = speaker or _SilentSpeaker()

		# 4. Microphone (optional — typing still works on failure).
		try:
			listener = Listener(sensitivity=settings.get("mic_sensitivity"))
			manager.listener = listener
		except Exception as exc:  # noqa: BLE001 - keep the UI alive
			print(f"Voice input unavailable: {exc}")
			events.emit({"type": "notice", "text": "Microphone unavailable — you can still type to JARVIS."})

		# 5. Start the brain loop + voice listening.
		manager.start()

		# Run web server in background thread just in case
		Thread(target=server.serve_forever, daemon=True).start()
		
		# Start Native Qt UI
		from interface.desktop import start_desktop_ui
		try:
			start_desktop_ui(manager)
		except KeyboardInterrupt:
			print("\nShutting down...")
	finally:
		if server is not None:
			# Prevent WinError 10038 by shutting down the server loop cleanly
			import threading
			threading.Thread(target=server.shutdown, daemon=True).start()
			import time; time.sleep(0.1)
			server.server_close()
		if manager is not None:
			manager.stop()
		if speaker is not None:
			try:
				speaker.stop()
			except SpeakerError as exc:
				print(f"Voice output cleanup: {exc}")


import threading

class _SilentSpeaker:
	"""No-op speaker used when text-to-speech cannot be initialised."""

	voice_name = "unavailable"
	speaking = threading.Event()

	def begin_utterance(self) -> None: ...
	def enqueue_chunk(self, text: str) -> None: ...
	def speak(self, text: str, wait: bool = True) -> None: ...
	def wait_until_idle(self, timeout: float = 120.0) -> None: ...
	def stop_speaking(self) -> None: ...
	def stop(self) -> None: ...


if __name__ == "__main__":
	main()
