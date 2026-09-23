from __future__ import annotations

from enum import Enum
from typing import Any

class PermissionLevel(str, Enum):
    OFF = "OFF"
    OBSERVE_ONLY = "OBSERVE_ONLY"
    CONTROL_WITH_CONFIRMATION = "CONTROL_WITH_CONFIRMATION"
    FULL_CONTROL = "FULL_CONTROL"

# For backward compatibility, keep the old name
PermissionState = PermissionLevel

MANDATORY_CONFIRMATION_CAPABILITIES = {
    "email.send",
    "email.send_direct",
    "email.confirm_send",
    "file.delete",
    "file.write",
    "file.move",
    "terminal.execute",
    "screen.click_dangerous",
    "screen.type_sensitive",
}

class PermissionManager:
    """Singleton managing permission levels for JARVIS.
    Provides both legacy screen permission methods and the new unified permission level.
    """

    _instance: "PermissionManager" | None = None

    def __new__(cls) -> "PermissionManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            try:
                from core.settings import Settings
                configured = Settings().get("permission_level") or "FULL_CONTROL"
                default_perm = PermissionLevel(str(configured).upper())
            except Exception:
                default_perm = PermissionLevel.FULL_CONTROL
            cls._instance._general_permission = default_perm
            cls._instance._screen_permission = default_perm
        return cls._instance

    # Unified permission handling
    def set_permission(self, level: PermissionLevel | str) -> str:
        if isinstance(level, str):
            level = PermissionLevel(level.upper())
        self._general_permission = level
        self._screen_permission = level
        try:
            from core.settings import Settings
            Settings().set("permission_level", level.value)
        except Exception:
            pass
        if level == PermissionLevel.FULL_CONTROL:
            return "Full access granted. All computer control, vision, and system actions are unlocked."
        return f"Permission level set to {level.value}."

    def get_permission(self) -> PermissionLevel:
        return self._general_permission

    # Legacy screen‑specific API used in existing code
    def set_screen_permission(self, level: PermissionLevel | str) -> str:
        return self.set_permission(level)

    def get_screen_permission(self) -> PermissionLevel:
        return self._screen_permission

    # Confirmation decision logic
    def requires_confirmation(self, capability_name: str, arguments: dict[str, Any] | None = None) -> bool:
        arguments = arguments or {}
        # Under FULL_CONTROL, allow autonomous screen control, file manipulation, and terminal execution,
        # keeping outbound communications (email.send) confirmation-gated for safety.
        if self._general_permission == PermissionLevel.FULL_CONTROL:
            if capability_name in ("email.send", "email.send_direct", "email.confirm_send"):
                return True
            return False

        # 1. Mandatory confirmation capabilities (emails, destructive actions)
        if capability_name in MANDATORY_CONFIRMATION_CAPABILITIES:
            return True
        # 2. Screen control actions need confirmation unless FULL_CONTROL
        if capability_name.startswith("screen."):
            if self._general_permission in (PermissionLevel.OFF, PermissionLevel.OBSERVE_ONLY, PermissionLevel.CONTROL_WITH_CONFIRMATION):
                return True
        # 3. Dangerous keywords in arguments
        if any(word in str(arguments).lower() for word in ("delete", "rmdir", "drop")):
            return True
        return False

    def can_observe_screen(self) -> bool:
        return self._general_permission != PermissionLevel.OFF

    def can_control_screen(self) -> bool:
        return self._general_permission in (PermissionLevel.CONTROL_WITH_CONFIRMATION, PermissionLevel.FULL_CONTROL)

def get_permission_manager() -> PermissionManager:
    return PermissionManager()
