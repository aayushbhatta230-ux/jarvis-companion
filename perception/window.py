"""Active window and desktop application focus perception for Windows.

Detects the active foreground window, window title, process executable name,
and active document context.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Any

HAS_WIN32 = False
try:
    import win32gui
    import win32process
    import win32api
    HAS_WIN32 = True
except ImportError:
    HAS_WIN32 = False

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes


@dataclass
class WindowInfo:
    title: str
    app_name: str
    hwnd: int
    is_active: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "app_name": self.app_name,
            "hwnd": self.hwnd,
            "is_active": self.is_active,
        }


def get_active_window() -> WindowInfo:
    """Get information about the currently active foreground window on Windows."""
    if sys.platform != "win32":
        return WindowInfo("Non-Windows OS Window", "System", 0)

    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return WindowInfo("No Active Window", "Desktop", 0)

        length = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value or "Untitled Window"

        app_name = _get_app_name_from_title(title, hwnd)
        return WindowInfo(title=title, app_name=app_name, hwnd=hwnd, is_active=True)
    except Exception as exc:
        print(f"[PERCEPTION] Window perception error: {exc}")
        return WindowInfo("Desktop Window", "Explorer", 0)


def _get_app_name_from_title(title: str, hwnd: int) -> str:
    """Infer the application name from window title or process."""
    title_lower = title.lower()
    if "visual studio code" in title_lower or "vscode" in title_lower or ".py" in title_lower or ".js" in title_lower:
        return "VS Code"
    if "chrome" in title_lower:
        return "Google Chrome"
    if "edge" in title_lower:
        return "Microsoft Edge"
    if "firefox" in title_lower:
        return "Firefox"
    if "terminal" in title_lower or "cmd" in title_lower or "powershell" in title_lower:
        return "Terminal"
    if "notepad" in title_lower:
        return "Notepad"
    if "word" in title_lower or ".docx" in title_lower:
        return "Microsoft Word"
    if "excel" in title_lower or ".xlsx" in title_lower:
        return "Microsoft Excel"

    if HAS_WIN32:
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            handle = win32api.OpenProcess(0x0400 | 0x0010, False, pid)
            if handle:
                import os
                import win32process
                exe = win32process.GetModuleFileNameEx(handle, 0)
                win32api.CloseHandle(handle)
                return os.path.basename(exe)
        except Exception:
            pass

    # Extract after last dash if available (e.g. "document.docx - Word")
    if " - " in title:
        return title.split(" - ")[-1].strip()

    return "Desktop Application"

