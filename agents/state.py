"""Computer state representation for JARVIS agent."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

from perception.window import get_active_window, WindowInfo


@dataclass
class UIElement:
    """A detected UI element on screen."""
    text: str
    bbox: tuple[int, int, int, int]
    confidence: float = 0.0
    role: str = "unknown"
    clickable: bool = True

    @property
    def center(self) -> tuple[int, int]:
        return (self.bbox[0] + self.bbox[2] // 2, self.bbox[1] + self.bbox[3] // 2)

    @property
    def left(self) -> int:
        return self.bbox[0]

    @property
    def top(self) -> int:
        return self.bbox[1]

    @property
    def width(self) -> int:
        return self.bbox[2]

    @property
    def height(self) -> int:
        return self.bbox[3]


@dataclass
class ComputerState:
    """Authoritative computer state for the agent."""
    active_application: str = "Desktop"
    active_window_title: str = "Desktop"
    active_process: str = ""
    screenshot: Any = None
    ocr_text: str = ""
    ocr_elements: list[UIElement] = field(default_factory=list)
    screen_dimensions: tuple[int, int] = (0, 0)
    browser_name: str = ""
    browser_tabs: list[str] = field(default_factory=list)
    active_tab_index: int = -1
    focused_element: str = ""
    cursor_position: tuple[int, int] = (0, 0)
    last_action: str = ""
    last_action_type: str = ""
    last_target: str = ""
    last_target_element: UIElement | None = None
    last_coordinates: tuple[int, int] | None = None
    last_result: Any = None
    last_verification: bool | None = None
    last_file: str = ""
    last_folder: str = ""
    pending_action: dict[str, Any] | None = None
    last_refresh: float = 0.0
    last_ocr_time: float = 0.0
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)

    def refresh_window(self) -> WindowInfo:
        info = get_active_window()
        with self._lock:
            self.active_application = info.app_name
            self.active_window_title = info.title
            self.last_refresh = time.time()
        return info

    def refresh_screen(self, ocr_text: str, ocr_boxes: list[dict[str, Any]],
                       dimensions: tuple[int, int] | None = None) -> None:
        with self._lock:
            self.ocr_text = ocr_text
            self.ocr_elements = []
            for box in ocr_boxes:
                element = UIElement(
                    text=str(box.get("text", "")),
                    bbox=(int(box.get("left", 0)), int(box.get("top", 0)),
                          int(box.get("width", 0)), int(box.get("height", 0))),
                    confidence=float(box.get("confidence", 0)) / 100.0,
                    role=self._infer_role(str(box.get("text", ""))),
                )
                self.ocr_elements.append(element)
            if dimensions:
                self.screen_dimensions = dimensions
            self.last_ocr_time = time.time()

    def _infer_role(self, text: str) -> str:
        text_lower = text.lower().strip()
        if not text_lower:
            return "empty"
        if any(w in text_lower for w in ("ok", "cancel", "submit", "save", "close", "open")):
            return "button"
        if any(w in text_lower for w in ("click", "here", "more", "learn")):
            return "link"
        if any(w in text_lower for w in ("search", "enter", "type", "email", "password")):
            return "field"
        if any(w in text_lower for w in ("tab", "home", "history", "subscriptions", "library")):
            return "tab"
        return "text"

    def find_elements(self, query: str, fuzzy: bool = True) -> list[tuple[float, UIElement]]:
        from core.screencontrol import _fuzzy_match, _normalize_text
        results = []
        query_norm = _normalize_text(query)
        with self._lock:
            elements_copy = list(self.ocr_elements)
        for element in elements_copy:
            text_norm = _normalize_text(element.text)
            if not text_norm:
                continue
            score = _fuzzy_match(query_norm, text_norm)
            if score >= 0.5:
                results.append((score, element))
        results.sort(key=lambda x: x[0], reverse=True)
        return results

    def clear_pending(self) -> None:
        with self._lock:
            self.pending_action = None

    def set_pending(self, action_type: str, arguments: dict[str, Any]) -> None:
        with self._lock:
            self.pending_action = {"type": action_type, "arguments": arguments, "timestamp": time.time()}

    def is_stale(self, max_age: float = 30.0) -> bool:
        with self._lock:
            return (time.time() - self.last_ocr_time) > max_age


_computer_state = ComputerState()


def get_computer_state() -> ComputerState:
    _computer_state.refresh_window()
    return _computer_state