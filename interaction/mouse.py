"""Mouse interaction control for JARVIS desktop automation.

Supports mouse moves, single clicks, double clicks, right clicks, scrolling,
and label-based UI element target clicking. Enforces strict safety permissions.
"""

from __future__ import annotations

import time
from typing import Any

HAS_PYAUTOGUI = True
try:
    import pyautogui
    pyautogui.FAILSAFE = True
except ImportError:
    HAS_PYAUTOGUI = False

from core.permissions import get_permission_manager, PermissionState
from perception.vision import find_button_or_label


def click(x: int, y: int, button: str = "left") -> str:
    perm = get_permission_manager().get_screen_permission()
    if not get_permission_manager().can_control_screen():
        return f"Cannot click: Screen control is disabled (Current permission: {perm.value})."

    if not HAS_PYAUTOGUI:
        return "Mouse control requires 'pyautogui'. Install with: pip install pyautogui"

    try:
        pyautogui.click(x=x, y=y, button=button)
        return f"Clicked {button} button at ({x}, {y})."
    except Exception as exc:
        return f"Mouse click error: {exc}"


def click_ui_element(label: str) -> str:
    perm = get_permission_manager().get_screen_permission()
    if not get_permission_manager().can_control_screen():
        return f"Cannot click element '{label}': Screen control permission is {perm.value}."

    elem = find_button_or_label(label)
    if elem is None:
        return f"Could not find UI element or button labeled '{label}' on screen."

    x = elem["left"] + elem["width"] // 2
    y = elem["top"] + elem["height"] // 2
    return click(x, y)


def scroll(clicks: int) -> str:
    perm = get_permission_manager().get_screen_permission()
    if not get_permission_manager().can_control_screen():
        return f"Cannot scroll: Screen control permission is {perm.value}."

    if not HAS_PYAUTOGUI:
        return "Mouse control requires 'pyautogui'."

    pyautogui.scroll(clicks)
    return f"Scrolled {'up' if clicks > 0 else 'down'} {abs(clicks)} clicks."

