"""Thread-safe pub/sub event hub for JARVIS state and conversation events.

Backend state changes and messages are emitted here and fanned out to every
subscriber. The HTTP/SSE bridge subscribes so the web interface can reflect
the assistant in real time without polling.
"""

from __future__ import annotations

import json
import threading
from collections import deque
from queue import Queue


class EventHub:
    """A small broadcast hub.

    Producer threads call :meth:`emit` with a JSON-serialisable dict; each
    subscriber gets a private :class:`queue.Queue` of JSON-encoded events.
    A bounded recent history is replayed to new subscribers, so a reconnecting
    client immediately catches up with the latest state and messages.
    """

    def __init__(self, history: int = 300) -> None:
        self._lock = threading.Lock()
        self._subscribers: set[Queue[str]] = set()
        self._history: deque[str] = deque(maxlen=history)

    def subscribe(self) -> Queue[str]:
        """Register a new subscriber and replay recent history into it."""
        queue: Queue[str] = Queue()
        with self._lock:
            self._subscribers.add(queue)
            for event in self._history:
                queue.put_nowait(event)
        return queue

    def unsubscribe(self, queue: Queue[str]) -> None:
        with self._lock:
            self._subscribers.discard(queue)

    def emit(self, event: dict) -> None:
        """Broadcast a JSON-serialisable dict to every subscriber."""
        payload = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
        with self._lock:
            self._history.append(payload)
            subscribers = tuple(self._subscribers)
        for queue in subscribers:
            # Skip subscribers that are not keeping up so a slow network
            # client never causes an unbounded memory build-up behind it.
            if queue.qsize() > 512:
                continue
            try:
                queue.put_nowait(payload)
            except Exception:
                pass