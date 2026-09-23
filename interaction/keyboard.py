"""Keyboard interaction control for JARVIS desktop automation.

Supports typing text, pressing individual keys, and triggering keyboard shortcuts.
Enforces safety and permission checks.
"""

from __future__ import annotations

import time

HAS_PYAUTOGUI = True
try:
    import pyautogui
except ImportError:
    HAS_PYAUTOGUI = False

from core.permissions import get_permission_manager, PermissionState


def type_text(text: str, interval: float = 0.02) -> str:
    perm = get_permission_manager().get_screen_permission()
    if not get_permission_manager().can_control_screen():
        return f"Cannot type text: Screen control permission is {perm.value}."

    if not HAS_PYAUTOGUI:
        return "Keyboard control requires 'pyautogui'."

    pyautogui.write(text, interval=interval)
    return f"Typed text: '{text}'"


def press_key(key: str) -> str:
    perm = get_permission_manager().get_screen_permission()
    if not get_permission_manager().can_control_screen():
        return f"Cannot press key: Screen control permission is {perm.value}."

    if not HAS_PYAUTOGUI:
        return "Keyboard control requires 'pyautogui'."

    pyautogui.press(key)
    return f"Pressed key '{key}'."


def press_hotkey(*keys: str) -> str:
    perm = get_permission_manager().get_screen_permission()
    if not get_permission_manager().can_control_screen():
        return f"Cannot execute hotkey: Screen control permission is {perm.value}."

    if not HAS_PYAUTOGUI:
        return "Keyboard control requires 'pyautogui'."

    pyautogui.hotkey(*keys)
    return f"Executed hotkey: {'+'.join(keys)}"

