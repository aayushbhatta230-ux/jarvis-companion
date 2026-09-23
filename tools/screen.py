'''Screen capture and vision capabilities for JARVIS.

Provides screen capture functionality that can be used to understand
what's on the screen, extract text via OCR, and feed visual context
to the AI for reasoning about desktop state.
'''

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import base64
import io
import os

try:
    import mss
    import mss.tools
    HAS_MSS = True
except ImportError:
    HAS_MSS = False

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

try:
    import pytesseract
    HAS_TESSERACT = True
except ImportError:
    HAS_TESSERACT = False

SCREENSHOT_DIR = Path(__file__).resolve().parent.parent / "memory" / "screenshots"

def _ensure_tesseract_configured() -> bool:
    """Point pytesseract at a discovered Tesseract engine if needed."""
    try:
        import pytesseract as _pt
        if getattr(_pt.pytesseract, "tesseract_cmd", None):
            try:
                _pt.get_tesseract_version()
                return True
            except Exception:
                pass
        from vision.analyze import _configure_tesseract
        return _configure_tesseract()
    except ImportError:
        return False


def _grab_image() -> Image.Image:
    """Capture the primary monitor and return a Pillow Image.

    Uses mss.grab for a raw RGB buffer and constructs an Image.
    """
    if not HAS_MSS:
        raise RuntimeError("Screen capture requires 'mss'. Install with: pip install mss")
    if not HAS_PIL:
        raise RuntimeError("Screen capture requires 'Pillow'. Install with: pip install Pillow")
    with mss.mss() as sct:
        monitor = sct.monitors[1]
        sct_img = sct.grab(monitor)
        img = Image.frombytes("RGB", sct_img.size, sct_img.rgb)
        return img

def capture_screen(output_path: str | None = None, width: int = 1920, height: int = 1080) -> str:
    """Capture the current screen and save it to disk.

    Returns the path to the saved screenshot. This can be used for:
    - The AI to analyze what's on screen
    - OCR text extraction
    - Visual context for file operations

    Args:
        output_path: Optional path for the screenshot. If not provided,
                     a timestamped file is created.
        width: Target width for the screenshot (downscales if needed).
        height: Target height for the screenshot.
    """
    if not HAS_MSS:
        raise RuntimeError("Screen capture requires 'mss'. Install with: pip install mss")
    if not HAS_PIL:
        raise RuntimeError("Screen capture requires 'Pillow'. Install with: pip install Pillow")

    if output_path is None:
        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = str(SCREENSHOT_DIR / f"screenshot_{timestamp}.png")

    output_path = os.path.expanduser(output_path)

    img = _grab_image()
    if img.width > width or img.height > height:
        img.thumbnail((width, height), Image.Resampling.LANCZOS)

    img.save(output_path, "PNG")
    return f"Screenshot saved to {output_path}"

def get_screen_base64(width: int = 1920, height: int = 1080) -> str:
    """Capture the screen and return it as a base64‑encoded PNG string.

    Useful for sending image data directly to an AI model without writing to disk.
    """
    img = _grab_image()
    if img.width > width or img.height > height:
        img.thumbnail((width, height), Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")

def extract_text_from_screen() -> str:
    """Capture the screen and extract text using OCR.

    Returns the extracted text. Useful for reading what's on screen.
    """
    if not HAS_TESSERACT:
        raise RuntimeError("OCR requires 'pytesseract'. Install with: pip install pytesseract")
    _ensure_tesseract_configured()
    img = _grab_image()
    text = pytesseract.image_to_string(img)
    return text.strip() if text.strip() else "(No text detected on screen)"

def describe_screen() -> str:
    """Capture and describe what's on the screen.

    Returns a textual description of the screen contents.
    """
    try:
        text = extract_text_from_screen()
        if text and len(text) > 10:
            return f"Screen contains: {text[:200]}..." if len(text) > 200 else f"Screen contains: {text}"
        return "Screen captured but no text content detected."
    except RuntimeError:
        return "Screen capture not available. Install: pip install mss Pillow pytesseract"
