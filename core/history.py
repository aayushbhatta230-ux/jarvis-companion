"""Lightweight persistent conversation log.

A plain JSON array appended to ``memory/history.json``. This is intentionally
simpler than the (currently empty) SQLite database: it matches the existing
``preferences.json`` pattern and has no extra dependencies. The log is capped
so it stays small.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


class HistoryStore:
    def __init__(self, path: str | Path | None = None, limit: int = 200) -> None:
        self.path = Path(path) if path else Path(__file__).resolve().parent.parent / "memory" / "history.json"
        self.limit = limit
        self.items: list[dict[str, Any]] = self._load()

    def _load(self) -> list[dict[str, Any]]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            data = []
        if not isinstance(data, list):
            return []
        valid = [e for e in data if isinstance(e, dict) and e.get("role") in ("user", "assistant") and isinstance(e.get("text"), str)]
        return valid[-self.limit:]

    def append(self, role: str, text: str) -> None:
        self.items.append(
            {"role": role, "text": text, "ts": time.strftime("%Y-%m-%d %H:%M:%S")}
        )
        if len(self.items) > self.limit:
            self.items = self.items[-self.limit:]
        self.save()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def snapshot(self) -> list[dict[str, Any]]:
        return list(self.items)