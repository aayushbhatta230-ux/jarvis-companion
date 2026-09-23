"""Generic action model for JARVIS agent."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class ActionType:
    """Generic action types for the agent."""
    OBSERVE = "observe"
    CLICK = "click"
    DOUBLE_CLICK = "double_click"
    RIGHT_CLICK = "right_click"
    TYPE = "type"
    KEY = "key"
    HOTKEY = "hotkey"
    SCROLL = "scroll"
    MOVE = "move"
    DRAG = "drag"
    OPEN = "open"
    CLOSE = "close"
    SWITCH = "switch"
    SELECT = "select"
    SEARCH = "search"
    READ = "read"
    FIND = "find"
    NAVIGATE = "navigate"
    SYSTEM = "system"
    EMAIL = "email"
    CONVERSATION = "conversation"
    WEB_RESEARCH = "web_research"


@dataclass
class ActionTarget:
    """Target of an action."""
    description: str = ""
    text: str = ""
    index: int = -1
    coordinates: tuple[int, int] | None = None
    element: Any = None


@dataclass
class Action:
    """Generic action representation."""
    type: str = ActionType.OBSERVE
    target: ActionTarget = field(default_factory=ActionTarget)
    arguments: dict[str, Any] = field(default_factory=dict)
    requires_confirmation: bool = False
    source_phrase: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "target": {
                "description": self.target.description,
                "text": self.target.text,
                "index": self.target.index,
                "coordinates": self.target.coordinates,
            },
            "arguments": self.arguments,
            "requires_confirmation": self.requires_confirmation,
        }


# Natural language patterns mapped to action types (broad categories)
INTENT_PATTERNS = {
    ActionType.CLICK: ["click", "tap", "press", "select", "choose", "pick", "hit", "go to", "activate", "trigger"],
    ActionType.TYPE: ["type", "write", "enter", "input", "fill", "put"],
    ActionType.KEY: ["press", "hit", "send"],
    ActionType.SCROLL: ["scroll", "swipe", "page down", "page up"],
    ActionType.OPEN: ["open", "launch", "start", "run", "bring up"],
    ActionType.CLOSE: ["close", "kill", "exit", "quit", "shut down", "terminate"],
    ActionType.SWITCH: ["switch", "change", "go to", "move to", "activate", "bring to front"],
    ActionType.SEARCH: ["search", "find", "look up", "look for"],
    ActionType.READ: ["read", "show", "display", "view"],
    ActionType.NAVIGATE: ["go back", "go forward", "refresh", "reload", "navigate"],
    ActionType.SYSTEM: ["brightness", "volume", "mute", "lock", "sleep", "minimize", "maximize"],
}

KEY_MAPPINGS = {
    "enter": "enter", "return": "enter", "space": "space",
    "tab": "tab", "escape": "esc", "esc": "esc",
    "backspace": "backspace", "delete": "delete",
    "up": "up", "down": "down", "left": "left", "right": "right",
    "home": "home", "end": "end", "page up": "pageup", "page down": "pagedown",
    "control": "ctrl", "ctrl": "ctrl", "alt": "alt", "shift": "shift",
    "windows": "win", "command": "cmd",
    "f1": "f1", "f2": "f2", "f3": "f3", "f4": "f4", "f5": "f5",
    "f6": "f6", "f7": "f7", "f8": "f8", "f9": "f9", "f10": "f10",
    "f11": "f11", "f12": "f12",
}

APP_ALIASES = {
    "chrome": "chrome", "google chrome": "chrome",
    "edge": "edge", "microsoft edge": "edge",
    "firefox": "firefox", "mozilla firefox": "firefox",
    "safari": "safari", "opera": "opera", "brave": "brave",
    "file explorer": "explorer", "explorer": "explorer",
    "windows explorer": "explorer", "windows file explorer": "explorer",
    "notepad": "notepad", "calculator": "calculator", "calc": "calculator",
    "paint": "paint", "command prompt": "cmd", "cmd": "cmd", "terminal": "cmd",
    "powershell": "powershell", "vscode": "code", "visual studio code": "code",
    "vs code": "code", "code": "code", "word": "winword", "microsoft word": "winword",
    "excel": "excel", "microsoft excel": "excel",
    "powerpoint": "powerpoint", "microsoft powerpoint": "powerpoint",
    "outlook": "outlook", "microsoft outlook": "outlook",
    "discord": "discord", "slack": "slack", "zoom": "zoom",
    "spotify": "spotify", "steam": "steam",
    "task manager": "taskmgr", "control panel": "control", "settings": "ms-settings:",
}


def resolve_known_folder(name: str) -> str | None:
    from pathlib import Path
    name_lower = name.lower().strip()
    if name_lower in ("desktop", "documents", "downloads", "pictures", "music", "videos"):
        # Prefer the OneDrive redirected location (the user's real folders),
        # falling back to the direct folder when the OneDrive one doesn't exist.
        onedrive = Path.home() / "OneDrive" / name_lower.capitalize()
        if onedrive.is_dir():
            return str(onedrive)
        direct = Path.home() / name_lower.capitalize()
        if direct.is_dir():
            return str(direct)
    return None


def resolve_application(name: str) -> str | None:
    return APP_ALIASES.get(name.lower().strip())


def resolve_key(name: str) -> str | None:
    return KEY_MAPPINGS.get(name.lower().strip())