'''System utilities for JARVIS.

Provides active window title detection on Windows.
'''

from __future__ import annotations

try:
    import pywinctl as pwc  # modern cross‑platform library
    HAS_PYWINCTL = True
except ImportError:  # pragma: no cover
    HAS_PYWINCTL = False
    try:
        import win32gui  # fallback to pywin32
        HAS_WIN32 = True
    except ImportError:
        HAS_WIN32 = False


def get_active_window_title() -> str:
    """Return the title of the currently active window.

    Raises
    ------
    RuntimeError
        If neither ``pywinctl`` nor ``win32gui`` is available.
    """
    if HAS_PYWINCTL:
        title = pwc.getActiveWindowTitle()
        return title if title else "(No active window)"
    if HAS_WIN32:
        hwnd = win32gui.GetForegroundWindow()
        title = win32gui.GetWindowText(hwnd)
        return title if title else "(No active window)"
    raise RuntimeError(
        "Active window detection requires 'pywinctl' or 'pywin32'. Install with: pip install pywinctl pywin32"
    )

