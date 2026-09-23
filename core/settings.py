"""Persistent user settings stored in ``config/settings.json``.

Only real, effective knobs are exposed here. Changing a value feeds the
corresponding subsystem the next time it reads or initialises its
resources, so there are no fake settings that do nothing.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

# Defaults can be overridden by environment variables (lower precedence than
# the JSON file, which itself is user-modifiable at runtime).
DEFAULTS: dict[str, Any] = {
    "voice": os.getenv("JARVIS_VOICE", "").strip(),
    "mic_sensitivity": 1.0,
    "response_verbosity": "concise",
    "visual_intensity": 0.7,
    "theme": "dark",
    "auto_listen": True,
    # Opt-in: on loudspeakers the mic hears JARVIS's own voice, so barge-in
    # is off by default for reliability. UI/voice "stop" always works.
    "barge_in": False,
    "permission_level": "FULL_CONTROL",
}

VALID_VERBOSITY = ("concise", "normal", "detailed")
SENSITIVITY_RANGE = (0.4, 2.5)


class Settings:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else Path(__file__).resolve().parent.parent / "config" / "settings.json"
        self.data: dict[str, Any] = self._load()
        if not self.path.exists():
            # Write the defaults once so the file is discoverable and editable.
            try:
                self.save()
            except OSError as exc:
                print(f"Settings: could not create {self.path.name}: {exc}")

    def _load(self) -> dict[str, Any]:
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            loaded = {}
        merged = dict(DEFAULTS)
        if isinstance(loaded, dict):
            for key, value in loaded.items():
                if key in DEFAULTS:
                    merged[key] = self._coerce(key, value)
        return merged

    def get(self, key: str) -> Any:
        return self.data.get(key, DEFAULTS.get(key))

    def set(self, key: str, value: Any) -> Any:
        coerced = self._coerce(key, value)
        self.data[key] = coerced
        self.save()
        return coerced

    def _coerce(self, key: str, value: Any) -> Any:
        if key == "voice":
            return str(value).strip()[:120]
        if key == "mic_sensitivity":
            try:
                return round(float(min(max(float(value), *SENSITIVITY_RANGE), 2.5)), 2)
            except (TypeError, ValueError):
                return DEFAULTS["mic_sensitivity"]
        if key == "response_verbosity":
            return value if value in VALID_VERBOSITY else DEFAULTS["response_verbosity"]
        if key == "visual_intensity":
            try:
                return round(float(min(max(float(value), 0.0), 1.0)), 2)
            except (TypeError, ValueError):
                return DEFAULTS["visual_intensity"]
        if key == "theme":
            return value if isinstance(value, str) else DEFAULTS["theme"]
        if key == "auto_listen":
            return bool(value)
        if key == "barge_in":
            return bool(value)
        if key == "permission_level":
            val = str(value).upper().strip()
            if val in ("OFF", "OBSERVE_ONLY", "CONTROL_WITH_CONFIRMATION", "FULL_CONTROL"):
                return val
            return DEFAULTS["permission_level"]
        return value

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2) + "\n", encoding="utf-8")

    def snapshot(self) -> dict[str, Any]:
        return json.loads(json.dumps(self.data))