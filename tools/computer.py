"""Application and system control for JARVIS — open, close, list applications."""

from __future__ import annotations

import subprocess
import os
from typing import Any

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False


# Allowlisted applications that can be opened
APPLICATIONS = {
    "notepad": "notepad.exe",
    "calculator": "calc.exe",
    "paint": "mspaint.exe",
    "browser": None,  # Special handling
    "chrome": "chrome.exe",
    "firefox": "firefox.exe",
    "edge": "msedge.exe",
    "spotify": "spotify.exe",
    "vscode": "code.exe",
    "code": "code.exe",
    "terminal": "cmd.exe",
    "command prompt": "cmd.exe",
    "cmd": "cmd.exe",
    "powershell": "powershell.exe",
    "word": "winword.exe",
    "excel": "excel.exe",
    "powerpoint": "powerpnt.exe",
    "explorer": "explorer.exe",
    "file explorer": "explorer.exe",
    "settings": "ms-settings:",
    "task manager": "taskmgr.exe",
    "control panel": "control.exe",
    "discord": "discord.exe",
    "slack": "slack.exe",
    "zoom": "zoom.exe",
    "steam": "steam.exe",
}


def launch(application: str) -> str:
    """Launch an application by name.

    Tries the allowlisted applications first, then falls back to
    os.startfile for arbitrary executable/protocol names.
    """
    name = application.strip().lower()
    command = APPLICATIONS.get(name)

    if command is None:
        # Allow os.startfile to handle it (e.g. "explorer", "ms-settings:", or a raw .exe name)
        command = name

    if command.startswith("ms-"):
        os.startfile(command)
        return f"Opened {name}."

    # For known allowlisted commands, use subprocess.Popen
    if name in APPLICATIONS:
        command = APPLICATIONS[name]
        if command is None:
            import webbrowser
            webbrowser.open("about:blank")
            return "Opened default browser."
        try:
            subprocess.Popen([command])
            return f"Opened {name}."
        except FileNotFoundError:
            raise RuntimeError(f"'{name}' doesn't appear to be installed.")
        except Exception as exc:
            raise RuntimeError(f"Couldn't open {name}: {exc}")

    # Fallback: try os.startfile for anything else
    try:
        os.startfile(command)
        return f"Opened {name}."
    except FileNotFoundError:
        raise RuntimeError(f"'{name}' doesn't appear to be installed.")
    except Exception as exc:
        raise RuntimeError(f"Couldn't open {name}: {exc}")


def close(application: str) -> str:
    """Close an application by name."""
    if not HAS_PSUTIL:
        raise RuntimeError("Process management requires 'psutil'. Install it with: pip install psutil")

    name = application.strip().lower()
    target = APPLICATIONS.get(name, name)
    if target.endswith(".exe"):
        target_name = target[:-4]
    else:
        target_name = name

    closed = []
    for proc in psutil.process_iter(['name', 'pid']):
        try:
            proc_name = proc.info['name']
            if proc_name and target_name in proc_name.lower():
                proc.terminate()
                closed.append(proc_name)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    if not closed:
        raise RuntimeError(f"No running process matching '{name}' was found.")
    unique = list(dict.fromkeys(closed))
    return f"Closed {', '.join(unique)}."


def list_running() -> str:
    """List currently running applications."""
    if not HAS_PSUTIL:
        raise RuntimeError("Process management requires 'psutil'. Install it with: pip install psutil")

    apps: dict[str, int] = {}
    for proc in psutil.process_iter(['name']):
        try:
            name = proc.info['name']
            if name and name.endswith('.exe'):
                short = name[:-4].capitalize()
                apps[short] = apps.get(short, 0) + 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    if not apps:
        return "No applications detected."

    sorted_apps = sorted(apps.items(), key=lambda x: x[1], reverse=True)
    lines = ["Running applications:"]
    for name, count in sorted_apps[:20]:
        lines.append(f"  {name}" + (f" (x{count})" if count > 1 else ""))
    return "\n".join(lines)


def get_system_info() -> str:
    """Get basic system information."""
    if not HAS_PSUTIL:
        raise RuntimeError("System info requires 'psutil'. Install it with: pip install psutil")

    import platform
    cpu_percent = psutil.cpu_percent(interval=0.5)
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage(str(os.path.expanduser("~"))[:3])

    lines = [
        f"OS: {platform.system()} {platform.release()}",
        f"CPU usage: {cpu_percent}%",
        f"Memory: {memory.percent}% used ({memory.used // (1024**3)}GB / {memory.total // (1024**3)}GB)",
        f"Disk: {disk.percent}% used ({disk.used // (1024**3)}GB / {disk.total // (1024**3)}GB)",
    ]
    return "\n".join(lines)
