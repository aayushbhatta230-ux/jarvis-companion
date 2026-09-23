"""Safe terminal execution for JARVIS — run commands with output capture."""

from __future__ import annotations

import subprocess
import os
from pathlib import Path

# Commands that are always blocked
BLOCKED_COMMANDS = {
    "format", "del", "rm", "rmdir", "rd", "shutdown", "reboot",
    "taskkill", "reg", "regedit", "netsh", "diskpart", "bcdedit",
}

# Commands that are always allowed (read-only)
ALLOWED_COMMANDS = {
    "dir", "ls", "cat", "type", "echo", "cd", "pwd", "chdir",
    "mkdir", "md", "copy", "xcopy", "move", "ren", "rename",
    "find", "findstr", "grep", "more", "head", "tail",
    "git status", "git log", "git diff", "git branch", "git show",
    "pip list", "pip show", "python --version", "python -m",
    "node --version", "npm list", "npm run", "npm test",
    "pytest", "py", "python", "cls", "clear", "whoami", "hostname",
    "ipconfig", "ping", "tracert", "nslookup", "netstat",
    "systeminfo", "tasklist", "sc query", "wmic",
}


def execute(command: str, timeout: int = 30, working_dir: str | None = None) -> str:
    """Execute a command and return its output. Blocked commands are rejected."""
    if not command or not command.strip():
        return "No command provided."

    cmd_lower = command.strip().lower()

    # Check for blocked commands
    for blocked in BLOCKED_COMMANDS:
        if cmd_lower.startswith(blocked + " ") or cmd_lower == blocked:
            return f"I can't run '{command}' — that command is blocked for safety."

    # Check for shell operators that could chain dangerous commands
    # Check multi-char operators first, then single-char
    if '&&' in command or '||' in command:
        return "I can't run commands with chained operators — please run a single simple command."
    dangerous_chars = ['|', ';', '>', '<', '`', '$(', '&']
    for char in dangerous_chars:
        if char in command:
            return f"I can't run commands with '{char}' — please run a single simple command."

    # Determine working directory
    cwd = None
    if working_dir:
        cwd = str(Path(working_dir).expanduser().resolve())

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
            env={**os.environ},
        )
        output = result.stdout.strip()
        errors = result.stderr.strip()

        if result.returncode != 0 and errors:
            return f"Command failed (exit code {result.returncode}):\n{errors}"

        if not output and not errors:
            return "Command completed successfully (no output)."

        return output or errors
    except subprocess.TimeoutExpired:
        return f"Command timed out after {timeout} seconds."
    except FileNotFoundError:
        return f"Command not found: {command.split()[0]}"
    except Exception as exc:
        return f"Couldn't run command: {exc}"


def run_python(code: str, timeout: int = 15) -> str:
    """Execute Python code and return the output."""
    if not code or not code.strip():
        return "No code provided."

    # Block dangerous imports/modules
    dangerous = ['os.system', 'subprocess', 'eval(', 'exec(', '__import__',
                  'shutil.rmtree', 'open(', 'file(', 'input(']
    for pattern in dangerous:
        if pattern in code:
            return f"I can't run code containing '{pattern}' for safety."

    try:
        result = subprocess.run(
            ["python", "-c", code],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = result.stdout.strip()
        errors = result.stderr.strip()

        if result.returncode != 0:
            return f"Error: {errors}"
        return output or "Code ran successfully (no output)."
    except subprocess.TimeoutExpired:
        return f"Code execution timed out after {timeout} seconds."
    except Exception as exc:
        return f"Couldn't run code: {exc}"
