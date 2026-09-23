"""Application management and window focus switching for JARVIS.
"""

from __future__ import annotations

import subprocess
import sys
from tools.computer import close as close_app, launch as launch_app, list_running


def switch_to_window(app_title: str) -> str:
    """Switch window focus to an application by matching title."""
    if sys.platform != "win32":
        return "Window switching is currently supported on Windows."

    try:
        import win32gui
        def enum_windows_callback(hwnd, extra):
            title = win32gui.GetWindowText(hwnd)
            if app_title.lower() in title.lower() and win32gui.IsWindowVisible(hwnd):
                win32gui.SetForegroundWindow(hwnd)
                extra.append(title)
        matches = []
        win32gui.EnumWindows(enum_windows_callback, matches)
        if matches:
            return f"Switched focus to '{matches[0]}'."
        return f"Could not find an active window matching '{app_title}'."
    except Exception as exc:
        return f"Focus switch error: {exc}"

