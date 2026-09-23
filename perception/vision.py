"""Screen layout, visual structure, and UI element analysis for JARVIS.

Analyzes button labels, form fields, and screen context for visual question answering
and safe screen control targeting.
"""

from __future__ import annotations

from typing import Any
from perception.ocr import extract_ui_elements
from perception.screen import ScreenPerceiver


def analyze_ui_elements() -> list[dict[str, Any]]:
    """Return recognized text labels and bounding boxes on screen."""
    perceiver = ScreenPerceiver()
    img = perceiver.grab_image()
    if img is None:
        return []
    return extract_ui_elements(img)


def find_button_or_label(target_label: str) -> dict[str, Any] | None:
    """Locate a UI element on screen by matching text label."""
    target_lower = target_label.lower().strip()
    elements = analyze_ui_elements()

    # Exact match
    for elem in elements:
        if elem["text"].lower() == target_lower:
            return elem

    # Partial match
    for elem in elements:
        if target_lower in elem["text"].lower():
            return elem

    return None

