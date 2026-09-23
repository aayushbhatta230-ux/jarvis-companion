"""JARVIS vision package.

Re-exports the screen-OCR entry point so both ``from vision import
analyze_screen`` and ``from vision.analyze import analyze_screen`` work.
"""

from __future__ import annotations

from vision.analyze import (
    HAS_TESSERACT,
    HAS_WINDOWS_OCR,
    VisionBox,
    VisionResult,
    analyze_screen,
    tesseract_available,
)

__all__ = [
    "analyze_screen",
    "VisionBox",
    "VisionResult",
    "HAS_TESSERACT",
    "HAS_WINDOWS_OCR",
    "tesseract_available",
]
