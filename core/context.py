"""Structured Desktop and Conversation Context Object for JARVIS reasoning.

Tracks current application, active window, visible screen contents,
active open document/file, recent observations, and recent actions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from perception.window import get_active_window, WindowInfo
from core.permissions import get_permission_manager, PermissionLevel


@dataclass
class DesktopContext:
    current_application: str = "Desktop"
    active_window_title: str = "Desktop"
    visible_content: str = ""
    current_file: str | None = None
    current_task: str = "Working on computer"
    recent_screen_observations: list[str] = field(default_factory=list)
    recent_actions: list[str] = field(default_factory=list)
    permission_state: PermissionLevel = PermissionLevel.OBSERVE_ONLY
    # Screen persistence fields
    recent_ocr_text: str = ""
    recent_ocr_boxes: list[dict[str, Any]] = field(default_factory=list)
    detected_targets: list[dict[str, Any]] = field(default_factory=list)
    last_screen_capture_time: float = 0.0
    last_action: str = ""
    last_target: str = ""
    last_coordinates: tuple[int, int] | None = None
    last_verification: bool | None = None
    screen_dimensions: tuple[int, int] = (0, 0)

    def update_window(self) -> WindowInfo:
        info = get_active_window()
        self.current_application = info.app_name
        self.active_window_title = info.title
        self.permission_state = get_permission_manager().get_screen_permission()
        return info

    def update_screen(self, ocr_text: str, ocr_boxes: list[dict[str, Any]],
                      dimensions: tuple[int, int] | None = None) -> None:
        """Store the latest screen perception results."""
        from time import time
        self.recent_ocr_text = ocr_text
        self.recent_ocr_boxes = ocr_boxes
        self.last_screen_capture_time = time()
        if dimensions:
            self.screen_dimensions = dimensions
        # Update visible content with a summary
        if ocr_text:
            self.visible_content = ocr_text[:500]

    def record_screen_action(self, action: str, target: str = "",
                             coordinates: tuple[int, int] | None = None,
                             verification: bool | None = None) -> None:
        """Record a screen action with its target and verification result."""
        self.last_action = action
        self.last_target = target
        self.last_coordinates = coordinates
        self.last_verification = verification
        summary = f"{action}: {target}"
        if verification is True:
            summary += " (verified)"
        elif verification is False:
            summary += " (failed)"
        else:
            summary += " (unverified)"
        self.add_action(summary)

    def add_observation(self, obs: str) -> None:
        if obs and obs not in self.recent_screen_observations:
            self.recent_screen_observations.append(obs)
            if len(self.recent_screen_observations) > 5:
                self.recent_screen_observations = self.recent_screen_observations[-5:]

    def add_action(self, action_summary: str) -> None:
        if action_summary:
            self.recent_actions.append(action_summary)
            if len(self.recent_actions) > 5:
                self.recent_actions = self.recent_actions[-5:]

    def to_prompt_context(self) -> str:
        self.update_window()
        file_info = f"Current active file: {self.current_file}\n" if self.current_file else ""
        visible_info = f"Visible screen text: {self.visible_content[:300]}...\n" if self.visible_content else ""
        obs_info = f"Recent screen observations: {'; '.join(self.recent_screen_observations[-3:])}\n" if self.recent_screen_observations else ""
        act_info = f"Recent actions: {'; '.join(self.recent_actions[-3:])}\n" if self.recent_actions else ""
        target_info = f"Last target: {self.last_target} at {self.last_coordinates}\n" if self.last_target else ""

        return (
            f"=== CURRENT DESKTOP STATE ===\n"
            f"Current application: {self.current_application}\n"
            f"Active window: {self.active_window_title}\n"
            f"Screen Access Permission: {self.permission_state}\n"
            f"Current task: {self.current_task}\n"
            f"Screen dimensions: {self.screen_dimensions}\n"
            f"{target_info}"
            f"{file_info}"
            f"{visible_info}"
            f"{obs_info}"
            f"{act_info}"
            f"============================="
        )


_global_context = DesktopContext()


def get_desktop_context() -> DesktopContext:
    _global_context.update_window()
    return _global_context

