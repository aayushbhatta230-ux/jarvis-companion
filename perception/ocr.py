"""OCR text extraction pipeline for JARVIS.

Extracts text from screenshots, handling clean text filtering
and window bounding boxes, delegating to the unified vision/analyze engine.
"""

from __future__ import annotations

from typing import Any
from PIL import Image

from vision.analyze import analyze_screen

def extract_text(image: Image.Image) -> str:
    """Extract clean text from a Pillow Image."""
    try:
        result = analyze_screen(image)
        text = result.full_text.strip()
        return text if text else "(No readable text detected on screen)"
    except Exception as exc:
        return f"(OCR processing error: {exc})"

def extract_ui_elements(image: Image.Image) -> list[dict[str, Any]]:
    """Extract text data with bounding boxes for basic UI element awareness."""
    try:
        result = analyze_screen(image)
        elements = []
        for box in result.boxes:
            elements.append({
                "text": box.text,
                "left": box.bbox[0],
                "top": box.bbox[1],
                "width": box.bbox[2],
                "height": box.bbox[3],
                "confidence": 100,
            })
        return elements
    except Exception:
        return []