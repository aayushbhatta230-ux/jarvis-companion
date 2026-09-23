"""Action logging and event audit system for JARVIS.

Records all intent classifications, tool executions, parameters, outcomes,
and reasoning notes to support self-awareness questions like:
- "Why did you do that?"
- "Why did you search the web?"
- "What did you just do?"
"""

from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

LOG_FILE = Path(__file__).resolve().parent.parent / "memory" / "action_log.json"


@dataclass
class ActionEvent:
    id: str
    timestamp: str
    user_input: str
    intent: str
    sub_intent: str
    capability: str
    arguments: dict[str, Any] = field(default_factory=dict)
    status: str = "success"  # success, failure, pending, cancelled
    result: str | None = None
    error: str | None = None
    rationale: str = ""
    source: str = "user"  # user, system, proactive

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ActionEvent:
        return cls(**data)


class ActionLogger:
    """In-memory and persisted audit log of all JARVIS actions."""

    _instance: ActionLogger | None = None

    def __new__(cls) -> ActionLogger:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._lock = threading.Lock()
            cls._instance._events = []
            cls._instance._load()
        return cls._instance

    def _load(self) -> None:
        if LOG_FILE.exists():
            try:
                data = json.loads(LOG_FILE.read_text(encoding="utf-8"))
                self._events = [ActionEvent.from_dict(item) for item in data[-100:]]
            except Exception:
                self._events = []

    def _save(self) -> None:
        try:
            with self._lock:
                LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
                data = [event.to_dict() for event in self._events[-100:]]
            LOG_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as exc:
            print(f"[ACTION LOG] Save error: {exc}")

    def log(
        self,
        user_input: str,
        intent: str,
        sub_intent: str,
        capability: str,
        arguments: dict[str, Any] | None = None,
        status: str = "success",
        result: str | None = None,
        error: str | None = None,
        rationale: str = "",
        source: str = "user",
    ) -> ActionEvent:
        event_id = f"evt_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
        event = ActionEvent(
            id=event_id,
            timestamp=datetime.now().isoformat(),
            user_input=user_input,
            intent=intent,
            sub_intent=sub_intent,
            capability=capability,
            arguments=arguments or {},
            status=status,
            result=result,
            error=error,
            rationale=rationale,
            source=source,
        )
        with self._lock:
            self._events.append(event)
        self._save()
        return event

    def get_last_event(self) -> ActionEvent | None:
        with self._lock:
            return self._events[-1] if self._events else None

    def get_recent(self, limit: int = 10) -> list[ActionEvent]:
        with self._lock:
            return self._events[-limit:]

    def explain_last_action(self, query: str = "") -> str:
        with self._lock:
            if not self._events:
                return "I haven't taken any recorded actions yet."
            events_copy = list(self._events)
        
        last = events_copy[-1]
        query_lower = query.lower()

        if "web" in query_lower or "search" in query_lower:
            web_events = [e for e in events_copy if e.capability in ("browser.search", "web_search") or e.intent == "browser"]
            if web_events:
                target = web_events[-1]
                return (
                    f"I searched the web for '{target.arguments.get('query', target.user_input)}' "
                    f"because the request was classified as requiring web information ({target.rationale or 'information lookup'})."
                )

        return (
            f"My last action was executing '{last.capability}' for your request '{last.user_input}'. "
            f"Status: {last.status}. {f'Result: {last.result[:150]}' if last.result else ''}"
        )


def get_action_logger() -> ActionLogger:
    return ActionLogger()

