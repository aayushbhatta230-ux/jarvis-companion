"""Reliability tests 1/3 — startup, capability registry, vision OCR, target detection."""

from __future__ import annotations

import pytest

import core.capabilities as capabilities
from core.capabilities import CAPABILITIES, get_capability
from core.screencontrol import ScreenControlExecutor


@pytest.fixture
def executor():
    return ScreenControlExecutor()


def _fake_ocr(elements):
    return lambda: elements


# --- Startup / imports / capability registry ------------------------- #
def test_startup_imports_cleanly():
    import main  # noqa: F401
    import core.brain  # noqa: F401
    import core.conversation  # noqa: F401
    import vision  # noqa: F401


def test_vision_analyze_is_imported_not_lazy():
    cap = get_capability("vision.analyze")
    assert cap is not None and callable(cap.handler)
    from vision.analyze import analyze_screen
    assert cap.handler is analyze_screen


def test_active_window_capability_uses_real_import():
    cap = get_capability("system.active_window")
    assert cap is not None and callable(cap.handler)
    from tools.system import get_active_window_title
    assert cap.handler is get_active_window_title


def test_no_duplicate_capability_names():
    assert len(CAPABILITIES) == len({c.name for c in CAPABILITIES.values()})


def test_capability_registry_reports_availability():
    reg = capabilities.get_runtime_capability_registry()
    assert reg["screen.capture"]["available"] is True
    assert reg["screen.click_element"]["available"] is True
    assert reg["email.diagnostics"]["available"] is True


# --- Vision OCR + bounding boxes ------------------------------------- #
def test_analyze_screen_returns_boxes(monkeypatch):
    from vision import analyze as va
    fake_data = {
        "text": ["Hello", "world", "", "Search"],
        "left": [10, 60, 0, 200],
        "top": [20, 20, 0, 300],
        "width": [40, 50, 0, 60],
        "height": [12, 12, 0, 14],
    }
    monkeypatch.setattr(va.pytesseract, "image_to_data", lambda img, output_type=None: fake_data)
    monkeypatch.setattr(va, "_grab_image", lambda: object())
    monkeypatch.setattr(va, "tesseract_available", lambda: True)
    result = va.analyze_screen()
    assert isinstance(result, va.VisionResult)
    assert result.full_text == "Hello world Search"
    assert [b.text for b in result.boxes] == ["Hello", "world", "Search"]
    assert result.boxes[0].bbox == (10, 20, 40, 12)
    assert result.boxes[2].bbox == (200, 300, 60, 14)


def test_analyze_screen_raises_clearly_without_ocr_engine(monkeypatch):
    from vision import analyze as va
    monkeypatch.setattr(va, "tesseract_available", lambda: False)
    monkeypatch.setattr(va, "_configure_tesseract", lambda: False)
    monkeypatch.setattr(va, "HAS_WINDOWS_OCR", False)
    with pytest.raises(RuntimeError) as exc:
        va.analyze_screen()
    assert "not installed" in str(exc.value)


# --- Screen target detection ----------------------------------------- #
def test_find_target_exact_match(executor):
    executor._set_ocr_provider(_fake_ocr([
        {"text": "Search", "left": 5, "top": 5, "width": 50, "height": 10},
    ]))
    target = executor.find_target("search")
    assert target is not None and target["text"] == "Search"


def test_find_target_partial_match(executor):
    executor._set_ocr_provider(_fake_ocr([
        {"text": "Google Chrome", "left": 0, "top": 0, "width": 100, "height": 20},
    ]))
    assert executor.find_target("chrome") is not None


def test_find_target_none_when_absent(executor):
    executor._set_ocr_provider(_fake_ocr([
        {"text": "File", "left": 0, "top": 0, "width": 30, "height": 10},
    ]))
    assert executor.find_target("Search") is None


def test_find_target_refuses_ambiguous_guess(executor):
    executor._set_ocr_provider(_fake_ocr([
        {"text": "Search", "left": 0, "top": 0, "width": 40, "height": 10},
        {"text": "Search", "left": 400, "top": 0, "width": 40, "height": 10},
    ]))
    assert executor.find_target("search") is None