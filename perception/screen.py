"""Screen perception pipeline and perception strategy for JARVIS.

Captures desktop screen state efficiently without excessive CPU/GPU usage,
providing OCR and visual context to the reasoning engine when needed.
"""

from __future__ import annotations

import io
import os
from datetime import datetime
from pathlib import Path
from PIL import Image

try:
    import mss
    HAS_MSS = True
except ImportError:
    HAS_MSS = False

from core.context import get_desktop_context
from core.permissions import get_permission_manager, PermissionState
from perception.ocr import extract_text
from perception.window import get_active_window

SCREENSHOT_DIR = Path(__file__).resolve().parent.parent / "memory" / "screenshots"


class PerceptionStrategy:
    IDLE = "idle"
    USER_SPEAKS = "user_speaks"
    SCREEN_QUESTION = "screen_question"
    ACTIVE_TASK = "active_task"


class ScreenPerceiver:
    """Manages efficient screen capture and context updating."""

    def __init__(self) -> None:
        self.last_capture_time: float = 0.0
        self.last_window_title: str = ""

    def grab_image(self) -> Image.Image | None:
        if not HAS_MSS:
            return None
        try:
            sct_cls = getattr(mss, "MSS", getattr(mss, "mss", None))
            with sct_cls() as sct:
                monitor = sct.monitors[1]
                sct_img = sct.grab(monitor)
                return Image.frombytes("RGB", sct_img.size, sct_img.rgb)
        except Exception as exc:
            print(f"[SCREEN] Capture error: {exc}")
            return None


    def perceive(self, strategy: str = PerceptionStrategy.USER_SPEAKS) -> str:
        perm = get_permission_manager().get_screen_permission()
        if perm == PermissionState.OFF:
            return "Screen access is turned OFF."

        context = get_desktop_context()
        window_info = context.update_window()

        img = self.grab_image()
        if img is None:
            return "Screen capture module (mss/Pillow) is not available."

        # Perform OCR
        ocr_text = extract_text(img)
        context.visible_content = ocr_text

        obs = f"Active Window: '{window_info.title}' ({window_info.app_name}). Screen text preview: {ocr_text[:120]}..."
        context.add_observation(obs)

        return obs


_perceiver = ScreenPerceiver()


def perceive_screen(strategy: str = PerceptionStrategy.USER_SPEAKS) -> str:
    return _perceiver.perceive(strategy)
