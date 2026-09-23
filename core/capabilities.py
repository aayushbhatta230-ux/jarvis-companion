"""Central capability registry and runtime status monitor for JARVIS.

Tracks available tools, permission levels, and actual system availability
(e.g., mss, pytesseract, pyautogui, SMTP credentials) so JARVIS never
hallucinates missing features or claims non-installed capabilities exist.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable

from core.actionresult import ActionResult
from core.permissions import get_permission_manager
from core.screencontrol import get_screen_control
from interaction.applications import switch_to_window
from interaction.keyboard import press_hotkey, press_key, type_text
from interaction.mouse import click, click_ui_element, scroll
from tools.browser import open_url, search_web
from tools.weather import get_weather
from tools.knowledge import lookup_knowledge
from tools.computer import close as close_application, get_system_info, launch as launch_application, list_running
from tools.documents import (
    clean_formatting,
    count_words,
    create_document,
    extract_sections,
    summarize_text,
)
from tools.email import (
    add_contact,
    confirm_send,
    diagnostics as email_diagnostics,
    draft_email,
    get_draft,
    list_contacts,
    list_drafts,
    resolve_contact,
    save_email_config,
    send_email,
    send_email_direct,
    update_draft,
)
from tools.files import (
    copy_file,
    create_file,
    create_folder,
    delete_file,
    edit_file,
    find_recent_files,
    get_file_info,
    list_directory,
    move_file,
    open_item,
    read_file,
    rename_file,
    search_files,
    write_file,
)
from tools.media import next_music, pause_music, play_music, resume_music, stop_music
from tools.screen import capture_screen, describe_screen, extract_text_from_screen, get_screen_base64
from tools.system import get_active_window_title
from tools.terminal import execute as execute_command, run_python
from vision.analyze import analyze_screen


@dataclass(frozen=True)
class Capability:
    name: str
    description: str
    handler: Callable[..., str]
    risk_level: str = "low"  # low, medium, high
    reversible: bool = True
    confirmation_required: bool = False
    requires_dependency: str | None = None

    def is_available(self) -> bool:
        if self.name.startswith("screen"):
            from core.permissions import PermissionLevel
            perm = get_permission_manager().get_screen_permission()
            if perm == PermissionLevel.OFF:
                return False
        if self.requires_dependency == "mss":
            try:
                import mss  # noqa: F401
                import PIL  # noqa: F401
                return True
            except ImportError:
                return False
        if self.requires_dependency == "pytesseract":
            try:
                import pytesseract  # noqa: F401
                return True
            except ImportError:
                return False
        if self.requires_dependency == "pyautogui":
            try:
                import pyautogui  # noqa: F401
                return True
            except ImportError:
                return False
        return True


@dataclass(frozen=True)
class ToolResult:
    success: bool
    tool: str
    result: str | None = None
    error: str | None = None
    status: str = "completed"  # completed, failed, confirmation_required, pending
    arguments: dict | None = None
    verification: bool = False


# --------------------------------------------------------------------- #
# Low-level helper callables referenced by the capability registry.
# --------------------------------------------------------------------- #
def _sc_click_coordinates(x: int, y: int, button: str = "left") -> ActionResult:
    return get_screen_control().click_coordinates(int(x), int(y), button=button)


def _sc_click_element(label: str) -> ActionResult:
    return get_screen_control().click_ui_element(label)


def _sc_move_to(label: str) -> ActionResult:
    return get_screen_control().move_mouse_to(label)


def _sc_scroll(direction: str = "down", clicks: int = 3) -> ActionResult:
    return get_screen_control().scroll(direction=direction, clicks=int(clicks))


def _sc_type(text: str) -> ActionResult:
    return get_screen_control().type_text(text)


def _sc_press_key(key: str) -> ActionResult:
    return get_screen_control().press_key(key)


def _sc_hotkey(keys: list[str]) -> ActionResult:
    return get_screen_control().press_hotkey(*(keys or []))


def _system_diagnostics() -> str:
    """Honest report of dependency availability (never claims what is missing)."""
    from core.screencontrol import HAS_PYAUTOGUI, HAS_MSS, HAS_PIL
    from vision.analyze import HAS_TESSERACT, tesseract_available
    lines = [
        f"Screen capture (mss): {'available' if HAS_MSS else 'missing'}",
        f"Screen capture (Pillow): {'available' if HAS_PIL else 'missing'}",
        f"Keyboard/mouse (pyautogui): {'available' if HAS_PYAUTOGUI else 'missing'}",
        f"OCR package (pytesseract): {'installed' if HAS_TESSERACT else 'missing'}; "
        f"Tesseract engine: {'found' if tesseract_available() else 'NOT FOUND on disk'}",
    ]
    return "\n".join(lines)


def _last_action_summary() -> str:
    try:
        from core.memory import get_short_term_memory
        return get_short_term_memory().describe_last_action()
    except Exception as exc:  # noqa: BLE001
        return f"I couldn't recall my last action: {exc}"


def _recent_memory_summary() -> str:
    try:
        from core.memory import get_short_term_memory
        return get_short_term_memory().describe_recent()
    except Exception as exc:  # noqa: BLE001
        return f"I couldn't recall recent context: {exc}"


def _resolve_result(name: str, res: Any) -> ToolResult:
    """Build a ToolResult from a handler return value, honouring structured results."""
    from tools.email import EmailActionResult
    if isinstance(res, EmailActionResult):
        display = str(res)
        return ToolResult(
            success=res.success,
            tool=name,
            result=display or None,
            error=res.error if not res.success else None,
            status="completed" if res.success else ("failed" if res.status != "UNCONFIGURED" else "unconfigured"),
            arguments=res.to_dict() or None,
            verification=None,
        )
    if isinstance(res, ActionResult):
        display = res.message or res.error
        return ToolResult(
            success=res.success,
            tool=name,
            result=display or None,
            error=res.error if not res.success else None,
            status=res.status,
            arguments=res.arguments or None,
            verification=res.verification,
        )
    # Handle dict returns (e.g. from read_file, write_file)
    if isinstance(res, dict):
        success = res.get("success", True)
        error = res.get("error")
        # For file.read, include the actual content in the result
        if "content" in res:
            result = res["content"]
        elif "verified" in res:
            # For file.write, include verification status
            verified = res.get("verified", False)
            filename = res.get("filename", "file")
            result = f"Saved '{filename}'." + (" (verified)" if verified else "")
        else:
            result = str(res)
        return ToolResult(
            success=success,
            tool=name,
            result=result,
            error=error,
            status="completed" if success else "failed",
            arguments=res,
            verification=res.get("verified"),
        )
    return ToolResult(True, name, result=str(res), status="completed")


CAPABILITIES: dict[str, Capability] = {
    # Browser
    "browser.open_url": Capability("browser.open_url", "Open a URL in browser", open_url, risk_level="low"),
    "browser.search": Capability("browser.search", "Search the web for information", search_web, risk_level="low"),

    # Weather & Knowledge
    "weather.get": Capability("weather.get", "Get live weather forecast for a location", get_weather, risk_level="low"),
    "knowledge.lookup": Capability("knowledge.lookup", "Lookup factual information or encyclopedic summaries", lookup_knowledge, risk_level="low"),

    # Media
    "media.play": Capability("media.play", "Play background music", play_music, risk_level="low"),
    "media.stop": Capability("media.stop", "Stop music playback", stop_music, risk_level="low"),
    "media.pause": Capability("media.pause", "Pause music playback", pause_music, risk_level="low"),
    "media.resume": Capability("media.resume", "Resume music playback", resume_music, risk_level="low"),
    "media.next": Capability("media.next", "Skip to next music track", next_music, risk_level="low"),

    # Files
    "file.search": Capability("file.search", "Search local files by name or query", search_files, risk_level="low"),
    "file.find_recent": Capability("file.find_recent", "Find recently modified files", find_recent_files, risk_level="low"),
    "file.read": Capability("file.read", "Read file contents", read_file, risk_level="low"),
    "file.list": Capability("file.list", "List folder contents", list_directory, risk_level="low"),
    "file.info": Capability("file.info", "Get file metadata", get_file_info, risk_level="low"),
    "file.create": Capability("file.create", "Create a new file", create_file, risk_level="medium"),
    "file.write": Capability("file.write", "Overwrite file content", write_file, risk_level="medium", reversible=False),
    "file.edit": Capability("file.edit", "Edit existing file", edit_file, risk_level="medium"),
    "file.create_folder": Capability("file.create_folder", "Create folder", create_folder, risk_level="low"),
    "file.copy": Capability("file.copy", "Copy file", copy_file, risk_level="low"),
    "file.move": Capability("file.move", "Move file", move_file, risk_level="medium", reversible=False),
    "file.rename": Capability("file.rename", "Rename file", rename_file, risk_level="medium"),
    "file.delete": Capability("file.delete", "Delete file", delete_file, risk_level="high", reversible=False, confirmation_required=True),

    # Applications
    "app.open": Capability("app.open", "Launch desktop application", launch_application, risk_level="low"),
    "app.close": Capability("app.close", "Close running application", close_application, risk_level="medium"),
    "app.list": Capability("app.list", "List running applications", list_running, risk_level="low"),
    "app.switch_window": Capability("app.switch_window", "Switch focus to window", switch_to_window, risk_level="low"),

    # Terminal
    "terminal.execute": Capability("terminal.execute", "Run terminal command", execute_command, risk_level="medium", reversible=False),
    "terminal.run_python": Capability("terminal.run_python", "Run Python script", run_python, risk_level="medium", reversible=False),
    "system.info": Capability("system.info", "Get system hardware/OS specs", get_system_info, risk_level="low"),
    "system.set_permission": Capability("system.set_permission", "Change permission level via voice", lambda level: get_permission_manager().set_permission(level), risk_level="low", confirmation_required=False, reversible=False),
    "system.active_window": Capability("system.active_window", "Get the title of the currently active window", get_active_window_title, risk_level="low"),
    "system.active_application": Capability("system.active_application", "Get the active application name", lambda: get_active_window_title(), risk_level="low"),
    "app.switch": Capability("app.switch", "Switch window focus to an application", switch_to_window, risk_level="low"),
    "system.diagnostics": Capability("system.diagnostics", "Report JARVIS dependency and configuration status", _system_diagnostics, risk_level="low"),

    # Email
    "email.draft": Capability("email.draft", "Draft an email", draft_email, risk_level="low"),
    "email.list_drafts": Capability("email.list_drafts", "List email drafts", list_drafts, risk_level="low"),
    "email.get_draft": Capability("email.get_draft", "Get draft by index", get_draft, risk_level="low"),
    "email.update_draft": Capability("email.update_draft", "Update draft details", update_draft, risk_level="low"),
    "email.confirm_send": Capability("email.confirm_send", "Confirm and send email draft", confirm_send, risk_level="high", reversible=False, confirmation_required=True),
    "email.send": Capability("email.send", "Send email via SMTP", send_email, risk_level="high", reversible=False, confirmation_required=True),
    "email.send_direct": Capability("email.send_direct", "Send direct email", send_email_direct, risk_level="high", reversible=False, confirmation_required=True),
    "email.diagnostics": Capability("email.diagnostics", "Report email configuration status", email_diagnostics, risk_level="low"),
    "email.resolve_contact": Capability("email.resolve_contact", "Resolve contact email", resolve_contact, risk_level="low"),
    "email.add_contact": Capability("email.add_contact", "Add contact", add_contact, risk_level="low"),
    "email.list_contacts": Capability("email.list_contacts", "List contacts", list_contacts, risk_level="low"),
    "email.save_config": Capability("email.save_config", "Save SMTP configuration", save_email_config, risk_level="high", reversible=True, confirmation_required=True),

    # Documents
    "document.summarize": Capability("document.summarize", "Summarize text or document", summarize_text, risk_level="low"),
    "document.create": Capability("document.create", "Create formatted document", create_document, risk_level="medium"),
    "document.clean_formatting": Capability("document.clean_formatting", "Clean document formatting", clean_formatting, risk_level="low"),
    "document.count_words": Capability("document.count_words", "Count words in document", count_words, risk_level="low"),
    "document.extract_sections": Capability("document.extract_sections", "Extract sections from document", extract_sections, risk_level="low"),

    # File/folder open (Explorer / default handler)
    "file.open": Capability("file.open", "Open a file or folder with its default handler", open_item, risk_level="low"),

    # Screen perception
    "screen.capture": Capability("screen.capture", "Capture computer screen shot", capture_screen, risk_level="low", requires_dependency="mss"),
    "screen.describe": Capability("screen.describe", "Describe screen contents", describe_screen, risk_level="low", requires_dependency="mss"),
    "screen.extract_text": Capability("screen.extract_text", "OCR text from screen", extract_text_from_screen, risk_level="low", requires_dependency="pytesseract"),
    "vision.analyze": Capability("vision.analyze", "Full OCR analysis of the screen", analyze_screen, risk_level="high", confirmation_required=False),

    # Screen control (verified pipeline via ScreenControlExecutor)
    "screen.click": Capability("screen.click", "Click mouse at coordinates", _sc_click_coordinates, risk_level="medium", requires_dependency="pyautogui"),
    "screen.click_element": Capability("screen.click_element", "Click UI element by label", _sc_click_element, risk_level="medium", requires_dependency="pyautogui"),
    "screen.move": Capability("screen.move", "Move mouse to UI element by label", _sc_move_to, risk_level="low", requires_dependency="pyautogui"),
    "screen.scroll": Capability("screen.scroll", "Scroll mouse wheel", _sc_scroll, risk_level="low", requires_dependency="pyautogui"),
    "screen.type": Capability("screen.type", "Type text using keyboard", _sc_type, risk_level="medium", requires_dependency="pyautogui"),
    "screen.press_key": Capability("screen.press_key", "Press key on keyboard", _sc_press_key, risk_level="medium", requires_dependency="pyautogui"),
    "screen.hotkey": Capability("screen.hotkey", "Press keyboard shortcut", _sc_hotkey, risk_level="medium", requires_dependency="pyautogui"),

    # Memory
    "memory.last_action": Capability("memory.last_action", "Describe the most recent JARVIS action", _last_action_summary, risk_level="low"),
    "memory.recent": Capability("memory.recent", "Summarise recent conversational memory", _recent_memory_summary, risk_level="low"),
}


def get_runtime_capability_registry() -> dict[str, dict[str, Any]]:
    """Return explicit capability availability states for self-awareness checks."""
    result = {}
    for name, cap in CAPABILITIES.items():
        avail = cap.is_available()
        result[name] = {
            "name": name,
            "description": cap.description,
            "available": avail,
            "risk_level": cap.risk_level,
            "confirmation_required": cap.confirmation_required,
        }
    return result


def describe_capabilities() -> str:
    lines = []
    perm_mgr = get_permission_manager()
    lines.append(f"SCREEN_ACCESS_PERMISSION: {perm_mgr.get_screen_permission().value}")
    for cap in CAPABILITIES.values():
        status = "AVAILABLE" if cap.is_available() else "UNAVAILABLE"
        risk_tag = f" [{cap.risk_level.upper()}]" if cap.risk_level != "low" else ""
        confirm_tag = " [CONFIRM]" if cap.confirmation_required else ""
        lines.append(f"- {cap.name}: {cap.description} ({status}){risk_tag}{confirm_tag}")
    return "\n".join(lines)


def get_capability(name: str) -> Capability | None:
    return CAPABILITIES.get(name)


def execute_capability(name: str, timeout: float = 15.0, **arguments: Any) -> ToolResult:
    capability = get_capability(name)
    if capability is None:
        return ToolResult(False, name, error=f"Capability '{name}' is not registered.", status="failed")

    if not capability.is_available():
        return ToolResult(False, name, error=f"Capability '{name}' is currently unavailable or disabled by permissions.", status="failed")

    perm_mgr = get_permission_manager()
    requires_conf = perm_mgr.requires_confirmation(name, arguments)
    if not requires_conf and capability.confirmation_required:
        from core.permissions import PermissionLevel
        if perm_mgr.get_permission() != PermissionLevel.FULL_CONTROL or name.startswith("email."):
            requires_conf = True

    if requires_conf:
        return ToolResult(False, name, error="CONFIRMATION_REQUIRED",
                          status="confirmation_required",
                          arguments=dict(arguments),
                          verification=None)

    try:
        res = capability.handler(**arguments)
        result = _resolve_result(name, res)
        if result.status == "confirmation_required":
            return ToolResult(False, name, error="CONFIRMATION_REQUIRED",
                              status="confirmation_required",
                              arguments=arguments or result.arguments)
        return result
    except Exception as exc:
        return ToolResult(False, name, error=str(exc), status="failed")


def execute_confirmed(name: str, timeout: float = 15.0, **arguments: Any) -> ToolResult:
    capability = get_capability(name)
    if capability is None:
        return ToolResult(False, name, error=f"Capability '{name}' is not registered.", status="failed")
    try:
        res = capability.handler(**arguments)
        return _resolve_result(name, res)
    except Exception as exc:
        return ToolResult(False, name, error=str(exc), status="failed")
