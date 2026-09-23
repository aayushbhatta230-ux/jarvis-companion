'''Vision analysis module for JARVIS.

Provides OCR on the current screen using pytesseract and returns structured
information including text strings and bounding boxes.
'''

from __future__ import annotations

import os
from dataclasses import dataclass
from shutil import which
from typing import List, Tuple

from tools.screen import _grab_image  # internal helper to capture Pillow Image

try:
    import pytesseract  # noqa: F401
    HAS_TESSERACT = True
except ImportError:  # pragma: no cover
    HAS_TESSERACT = False

# Common install locations for the Tesseract engine binary on Windows.
_TESSERACT_BIN_CANDIDATES = (
    "C:/Program Files/Tesseract-OCR/tesseract.exe",
    "C:/Program Files (x86)/Tesseract-OCR/tesseract.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe"),
)

# Whether the Windows built-in OCR engine is reachable (best-effort fallback).
HAS_WINDOWS_OCR = False
try:
    import winsdk.windows.media.ocr as _wocr  # type: ignore  # noqa: F401
    HAS_WINDOWS_OCR = True
except Exception:  # pragma: no cover - optional fallback only  # noqa: BLE001
    HAS_WINDOWS_OCR = False


@dataclass(frozen=True)
class VisionBox:
    """Bounding box for a piece of recognized text.

    The coordinates are given as (left, top, width, height) in screen pixel
    space, matching the format returned by ``pytesseract.image_to_data``.
    """

    text: str
    bbox: Tuple[int, int, int, int]


@dataclass(frozen=True)
class VisionResult:
    """Result of a full screen analysis.

    * ``full_text`` – concatenated OCR text of the whole screen.
    * ``boxes`` – list of :class:`VisionBox` objects for each recognised word.
    """

    full_text: str
    boxes: List[VisionBox]


def tesseract_available() -> bool:
    """True when the Tesseract *engine* can actually be invoked (not just pkg)."""
    if not HAS_TESSERACT:
        return False
    if which("tesseract"):
        return True
    return any(os.path.exists(c) for c in _TESSERACT_BIN_CANDIDATES)


def _configure_tesseract() -> bool:
    """Point pytesseract at a discovered engine; return True if it is usable."""
    if not HAS_TESSERACT:
        return False
    for candidate in _TESSERACT_BIN_CANDIDATES:
        if os.path.exists(candidate):
            try:
                import pytesseract as _pt
                _pt.pytesseract.tesseract_cmd = candidate
                _pt.get_tesseract_version()  # raises if the engine is unusable
                return True
            except Exception:  # noqa: BLE001
                continue
    return False


def analyze_screen(img: Image.Image | None = None) -> VisionResult:
    """Capture the screen and run OCR, returning text and per-word boxes.

    Prefers Tesseract. If its engine binary is missing it falls back to the
    Windows built-in OCR engine. If neither is usable it raises a clear
    ``RuntimeError`` so callers never see fabricated text.
    """
    if tesseract_available():
        _configure_tesseract()
        try:
            return _analyze_tesseract(img)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"OCR (Tesseract) failed: {exc}") from exc
    if _configure_tesseract():
        try:
            return _analyze_tesseract(img)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"OCR (Tesseract) failed: {exc}") from exc
    if HAS_WINDOWS_OCR:
        try:
            return _analyze_windows_ocr(img)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"OCR (Windows) failed: {exc}") from exc
    raise RuntimeError(
        "OCR is not available. Tesseract is not installed and the Windows OCR "
        "engine is unreachable. Install Tesseract "
        "(https://github.com/UB-Mannheim/tesseract/wiki) and restart JARVIS."
    )


def _analyze_tesseract(img: Image.Image | None = None) -> VisionResult:
    if img is None:
        img = _grab_image()
    data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
    words = data["text"]
    left = data["left"]
    top = data["top"]
    width = data["width"]
    height = data["height"]
    boxes: List[VisionBox] = []
    parts: List[str] = []
    for txt, l, t, w, h in zip(words, left, top, width, height):
        piece = str(txt).strip()
        if piece:
            parts.append(piece)
            boxes.append(VisionBox(text=piece, bbox=(int(l), int(t), int(w), int(h))))
    return VisionResult(full_text=" ".join(parts), boxes=boxes)


def _analyze_windows_ocr(img: Image.Image | None = None) -> VisionResult:
    """OCR through the Windows 10+ built-in engine (best-effort fallback)."""
    import asyncio
    from io import BytesIO

    import winsdk.windows.graphics.imaging as wimg
    import winsdk.windows.media.ocr as wocr
    import winsdk.windows.storage.streams as wstreams
    from winsdk.windows.media.ocr import OcrEngine

    async def _inner() -> VisionResult:
        langs = await wocr.OcrEngine.available_recognizer_languages
        language = langs[0] if langs and len(langs) else None
        if language is None:
            raise RuntimeError("Windows OCR has no available language packs.")
        engine = OcrEngine.try_create_from_language(language)
        if engine is None:
            raise RuntimeError("Windows OCR engine could not be created.")
        if img is None:
            img_to_use = _grab_image()
        else:
            img_to_use = img
        raw = BytesIO()
        img_to_use.save(raw, format="PNG")
        raw.seek(0)
        mem = wstreams.InMemoryRandomAccessStream()
        writer = wstreams.DataWriter(mem.get_output_stream())
        writer.write_bytes(raw.getvalue())
        await writer.store_async()
        writer.detach_stream()
        mem.seek(0)
        decoder = await wimg.BitmapDecoder.create_async(mem)
        bitmap = await decoder.get_software_bitmap_async()
        result = await engine.recognize_async(bitmap)
        parts: List[str] = []
        boxes: List[VisionBox] = []
        for idx in range(result.lines.size):
            line = result.lines.get_at(idx)
            for word_idx in range(line.words.size):
                word = line.words.get_at(word_idx)
                text = word.text.strip()
                if not text:
                    continue
                parts.append(text)
                rect = word.bounding_rect
                boxes.append(VisionBox(text=text, bbox=(int(rect.x), int(rect.y), int(rect.width), int(rect.height))))
        return VisionResult(full_text=" ".join(parts), boxes=boxes)

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_inner())
    finally:
        loop.close()
