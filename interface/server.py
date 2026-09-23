"""Zero-dependency web bridge for the JARVIS interface.

Serves the static UI and exposes a small JSON API plus a Server-Sent-Events
stream so the interface reflects the assistant's state and conversation in
real time. Everything is read-only for browsers except a small, validated set
of commands (type a message, adjust settings, request an interrupt) — no
arbitrary execution is reachable from the frontend.

Uses only the Python standard library. ``requirements.txt`` is unchanged.
"""

from __future__ import annotations

import json
import socket
import sys
from pathlib import Path
from queue import Empty
from typing import Any
from urllib.parse import urlparse

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from core.conversation import ConversationManager
from core.history import HistoryStore
from core.settings import Settings

# BASE_DIR is the directory that contains this module (interface/), and also
# where index.html / style.css / app.js live.
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR

MIME = {
	".html": "text/html; charset=utf-8",
	".css": "text/css; charset=utf-8",
	".js": "application/javascript; charset=utf-8",
	".svg": "image/svg+xml",
	".json": "application/json; charset=utf-8",
	".woff2": "font/woff2",
	".png": "image/png",
	".ico": "image/x-icon",
}

def _json_body(handler: BaseHTTPRequestHandler) -> dict[str, Any] | None:
	"""Parse a small JSON POST body defensively; returns None on malformed."""
	length = handler.headers.get("Content-Length")
	if not length:
		return {}
	try:
		size = int(length)
		if size < 0 or size > 1_000_000:
			return None
		raw = handler.rfile.read(size).decode("utf-8")
	except Exception:  # noqa: BLE001
		return None
	if not raw.strip():
		return {}
	try:
		parsed = json.loads(raw)
	except json.JSONDecodeError:
		return None
	return parsed if isinstance(parsed, dict) else {}


class JarvisHandler(BaseHTTPRequestHandler):
	"""Handles static files, the SSE stream, and the small command API."""
	protocol_version = "HTTP/1.1"
	manager: ConversationManager
	settings: Settings
	history: HistoryStore

	def log_message(self, fmt: str, *args: Any) -> None:
		print(f"[HTTP] {self.address_string()} {fmt % args}")

	def _send_json(self, status: int, payload: dict[str, Any]) -> None:
		body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
		self.send_response(status)
		self.send_header("Content-Type", "application/json; charset=utf-8")
		self.send_header("Content-Length", str(len(body)))
		self.send_header("Cache-Control", "no-store")
		self.end_headers()
		self.wfile.write(body)

	# ------------------------------------------------------------------ #
	# GET
	# ------------------------------------------------------------------ #

	def do_GET(self) -> None:
		parsed = urlparse(self.path)
		path = parsed.path

		if path == "/events":
			self._sse_handler()
			return
		if path == "/api/state":
			self._send_json(200, {"state": self.manager.state, "turn": self.manager.turn_id})
			return
		if path == "/api/health":
			self._send_json(200, {"ok": True, "state": self.manager.state})
			return
		if path == "/api/settings":
			self._send_json(200, {"settings": self.settings.snapshot()})
			return
		if path == "/api/history":
			self._send_json(200, {"history": self.history.snapshot()[-80:]})
			return
		if path.startswith(("/api/", "/events")):
			self._send_json(404, {"error": "unknown endpoint"})
			return
		self._serve_static(path)

	def _serve_static(self, path: str) -> None:
		"""Serve a file from STATIC_DIR; '/' maps to index.html."""
		relative = "index.html" if path in ("/", "") else path.lstrip("/")
		candidate = (STATIC_DIR / relative).resolve()
		try:
			candidate.relative_to(STATIC_DIR.resolve())
		except ValueError:
			self._send_json(404, {"error": "not found"})
			return
		if not candidate.is_file():
			self._send_json(404, {"error": "not found"})
			return
		content = candidate.read_bytes()
		ext = candidate.suffix.lower()
		content_type = MIME.get(ext, "application/octet-stream")
		self.send_response(200)
		self.send_header("Content-Type", content_type)
		self.send_header("Content-Length", str(len(content)))
		self.send_header("Cache-Control", "no-cache")
		self.end_headers()
		self.wfile.write(content)

	def _sse_handler(self) -> None:
		"""Stream events to one browser client using chunked transfer encoding.

		A keep-alive comment is sent on inactivity so proxies and the browser
		keep the stream open; the client reconnects automatically if the
		connection is ever dropped (history is replayed on reconnect).
		"""
		queue = self.manager.events.subscribe()
		self.send_response(200)
		self.send_header("Content-Type", "text/event-stream")
		self.send_header("Cache-Control", "no-store")
		self.send_header("X-Accel-Buffering", "no")
		self.send_header("Transfer-Encoding", "chunked")
		self.end_headers()

		def emit(fragment: str) -> None:
			data = fragment.encode("utf-8")
			self.wfile.write(b"%x\r\n" % len(data))
			self.wfile.write(data)
			self.wfile.write(b"\r\n")
			self.wfile.flush()

		try:
			# Tell the browser how fast to reconnect so a dropped stream is
			# back online within a second or two instead of the default 3s+.
			emit("retry: 1500\n\n")
			emit(f"data: {json.dumps({'type': 'hello', 'state': self.manager.state}, ensure_ascii=False)}\n\n")
			while True:
				try:
					event = queue.get(timeout=10)
				except Empty:
					emit(": ping\n\n")
					continue
				emit(f"data: {event}\n\n")
		except Exception:  # noqa: BLE001 - client disconnect
			pass
		finally:
			self.manager.events.unsubscribe(queue)
			try:
				self.wfile.write(b"0\r\n\r\n")
				self.wfile.flush()
			except Exception:  # noqa: BLE001
				pass

	# ------------------------------------------------------------------ #
	# POST (validated command API)
	# ------------------------------------------------------------------ #

	def do_POST(self) -> None:
		parsed = urlparse(self.path)
		path = parsed.path
		if path == "/api/command":
			body = _json_body(self)
			if body is None:
				self._send_json(400, {"error": "invalid JSON"})
				return
			text = (body.get("text") or "").strip()
			if not text or len(text) > 4000:
				self._send_json(400, {"error": "empty or oversized command"})
				return
			self.manager.submit_text(text)
			self._send_json(200, {"ok": True})
			return

		if path == "/api/stop":
			# Interrupt current speech (and pause-generation) immediately.
			try:
				self.manager.speaker.stop_speaking()
			except Exception as exc:  # noqa: BLE001
				self._send_json(500, {"error": str(exc)})
				return
			self._send_json(200, {"ok": True})
			return

		if path == "/api/listen":
			body = _json_body(self)
			if body is None or "enable" not in body:
				self._send_json(400, {"error": "expected enable boolean"})
				return
			enable = bool(body.get("enable"))
			if hasattr(self.manager, "set_auto_listen"):
				self.manager.set_auto_listen(enable)
				self.settings.set("auto_listen", enable)
			else:
				self._send_json(400, {"error": "listening control unavailable"})
				return
			self._send_json(200, {"ok": True, "auto_listen": enable})
			return

		if path == "/api/confirm":
			body = _json_body(self)
			if body is None or "action" not in body:
				self._send_json(400, {"error": "expected action ('confirm' or 'decline')"})
				return
			action = str(body["action"]).lower()
			response_text = "yes" if action in ("confirm", "yes") else "no"
			self.manager.submit_text(response_text)
			self._send_json(200, {"ok": True, "action": action})
			return

		if path == "/api/permissions":
			body = _json_body(self)
			if body is None or "state" not in body:
				self._send_json(400, {"error": "expected state"})
				return
			from core.permissions import get_permission_manager
			msg = get_permission_manager().set_screen_permission(str(body["state"]))
			self._send_json(200, {"ok": True, "message": msg, "permission": get_permission_manager().get_screen_permission().value})
			return

		if path == "/api/settings":
			body = _json_body(self)
			if body is None or "key" not in body or "value" not in body:
				self._send_json(400, {"error": "expected key and value"})
				return
			key = str(body["key"]).strip()
			if key not in ("mic_sensitivity", "response_verbosity", "visual_intensity", "theme", "auto_listen", "voice", "barge_in"):
				self._send_json(400, {"error": "unknown setting"})
				return
			self.settings.set(key, body["value"])
			self._apply_setting(key)
			self._send_json(200, {"ok": True, "settings": self.settings.snapshot()})
			return


		self._send_json(404, {"error": "unknown endpoint"})

	def _apply_setting(self, key: str) -> None:
		"""Push a changed setting into the live subsystem it controls."""
		if key == "mic_sensitivity" and self.manager.listener is not None:
			self.manager.listener.sensitivity = max(0.4, min(2.5, float(self.settings.get("mic_sensitivity"))))
		elif key == "auto_listen":
			self.manager.set_auto_listen(bool(self.settings.get("auto_listen")))
		elif key == "voice":
			# Voice selection applies on next JARVIS start (SAPI is already
			# running); report success without pretending it changed live.
			pass

	def finish(self) -> None:
		try:
			super().finish()
		except Exception:  # noqa: BLE001 - ignore write-side disconnects
			pass


class QuietHTTPServer(ThreadingHTTPServer):
	"""ThreadingHTTPServer that stays silent about client-side disconnects.

	Aborted connections (browser tab refresh, fetch cancellation) otherwise
	print a full ConnectionAbortedError traceback on every request.
	"""

	def handle_error(self, request, client_address) -> None:
		exc = sys.exc_info()[1]
		if isinstance(exc, (ConnectionError, TimeoutError, socket.timeout)):
			return  # normal client disconnects, not server faults
		super().handle_error(request, client_address)


def make_handler_class(manager: ConversationManager, settings: Settings, history: HistoryStore) -> type[BaseHTTPRequestHandler]:
	"""Return a request-handler class bound to the given runtime objects."""
	bound_settings = settings
	bound_history = history
	bound_manager = manager

	class BoundHandler(JarvisHandler):
		manager = bound_manager
		settings = bound_settings
		history = bound_history

	return BoundHandler


def create_server(manager: ConversationManager, settings: Settings, history: HistoryStore,
			  host: str = "127.0.0.1", port: int = 8765) -> ThreadingHTTPServer:
	"""Build the threaded HTTP server serving the interface + event stream."""
	handler = make_handler_class(manager, settings, history)
	server = QuietHTTPServer((host, port), handler)
	server.daemon_threads = True
	return server