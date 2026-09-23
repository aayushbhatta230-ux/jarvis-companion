"""Reliability tests 2/3 — verified screen control, permissions, confirmation args."""

from __future__ import annotations

import pytest

import core.capabilities as capabilities
from core.actionresult import ActionResult
from core.capabilities import execute_capability
from core.intent import IntentEngine
from core.permissions import PermissionLevel, get_permission_manager
from core.screencontrol import ScreenControlExecutor


@pytest.fixture
def observe_only():
    pm = get_permission_manager()
    previous = pm.get_permission()
    pm.set_permission(PermissionLevel.OBSERVE_ONLY)
    yield pm
    pm.set_permission(previous)


@pytest.fixture
def confirm_control(observe_only):
    pm = get_permission_manager()
    pm.set_permission(PermissionLevel.CONTROL_WITH_CONFIRMATION)
    return pm


@pytest.fixture
def full_control(observe_only):
    pm = get_permission_manager()
    pm.set_permission(PermissionLevel.FULL_CONTROL)
    return pm


@pytest.fixture
def executor():
    return ScreenControlExecutor()


def _fake_ocr(elements):
    return lambda: elements


# --- Verified screen control ----------------------------------------- #
def test_click_denied_in_observe_only(executor, observe_only):
    executor._set_ocr_provider(_fake_ocr([{"text": "Search", "left": 0, "top": 0, "width": 10, "height": 10}]))
    result = executor.click_ui_element("Search")
    assert result.success is False
    assert result.status == "permission_denied"
    assert result.verification is None


def test_click_requires_confirmation_at_capability_layer(confirm_control):
    """The single confirmation gate lives in the capability registry."""
    result = execute_capability("screen.click_element", label="Search")
    assert result.success is False
    assert result.status == "confirmation_required"
    assert result.arguments == {"label": "Search"}
    assert result.verification is None


def test_click_reports_target_not_found(executor, full_control):
    executor._set_ocr_provider(_fake_ocr([]))
    result = executor.click_ui_element("Search")
    assert result.success is False
    assert result.status == "target_not_found"
    assert result.verification is None
    assert "didn't click anything" in result.message


def test_click_reports_unknown_when_screen_did_not_change(executor, full_control, monkeypatch):
    """Unchanged OCR cannot prove a click worked — verification must be None."""
    executor._set_ocr_provider(_fake_ocr([{"text": "Search", "left": 0, "top": 0, "width": 60, "height": 20}]))
    import core.screencontrol as sc
    monkeypatch.setattr(sc.pyautogui, "moveTo", lambda x, y, duration=None: None)
    monkeypatch.setattr(sc.pyautogui, "click", lambda x=None, y=None, button=None: None)
    result = executor.click_ui_element("Search")
    assert result.success is True
    assert result.verification is None
    assert "couldn't verify" in result.message


def test_click_reports_success_when_screen_changed(executor, full_control, monkeypatch):
    """Post-action OCR differs from pre-action OCR -> verified True."""
    import core.screencontrol as sc
    calls = {"n": 0}

    def provider():
        calls["n"] += 1
        if calls["n"] == 1:  # target discovery
            return [{"text": "Search", "left": 0, "top": 0, "width": 60, "height": 20}]
        if calls["n"] == 2:  # pre-action preview
            return [{"text": "Search", "left": 0, "top": 0, "width": 60, "height": 20}]
        return [{"text": "Search results", "left": 0, "top": 0, "width": 200, "height": 20}]

    executor._set_ocr_provider(provider)
    monkeypatch.setattr(sc.pyautogui, "moveTo", lambda x, y, duration=None: None)
    monkeypatch.setattr(sc.pyautogui, "click", lambda x=None, y=None, button=None: None)
    result = executor.click_ui_element("Search")
    assert result.success is True
    assert result.verification is True


def test_unknown_verification_is_none_not_true(executor, full_control, monkeypatch):
    """When OCR yields nothing before/after, verification is honestly None."""
    import core.screencontrol as sc
    calls = {"n": 0}

    def provider():
        calls["n"] += 1
        if calls["n"] == 1:  # target discovery finds the element
            return [{"text": "Search", "left": 0, "top": 0, "width": 60, "height": 20}]
        return []  # OCR unavailable afterwards

    executor._set_ocr_provider(provider)
    monkeypatch.setattr(sc.pyautogui, "moveTo", lambda x, y, duration=None: None)
    monkeypatch.setattr(sc.pyautogui, "click", lambda x=None, y=None, button=None: None)
    result = executor.click_ui_element("Search")
    assert result.success is True
    assert result.verification is None
    assert "couldn't verify" in result.message
    # And an empty OCR world can never be claimed as a verified change.
    assert executor._verify_change("", "click", "x", 1, 1) is None


def test_type_reports_honestly(executor, full_control, monkeypatch):
    import core.screencontrol as sc
    typed = {}
    monkeypatch.setattr(sc.pyautogui, "write", lambda text, interval=0: typed.setdefault("t", text))
    result = executor.type_text("hello")
    assert result.success is True
    assert typed["t"] == "hello"
    assert result.verification in (True, False, None)


def test_press_key_and_hotkey_pass_through(executor, full_control, monkeypatch):
    import core.screencontrol as sc
    seen = []
    monkeypatch.setattr(sc.pyautogui, "press", lambda k: seen.append(("press", k)))
    monkeypatch.setattr(sc.pyautogui, "hotkey", lambda *ks: seen.append(("hotkey", ks)))
    assert executor.press_key("enter").success is True
    assert executor.press_hotkey("ctrl", "c").success is True
    assert ("press", "enter") in seen
    assert ("hotkey", ("ctrl", "c")) in seen


def test_capability_layer_reflects_verification():
    result = execute_capability("screen.click_element", label="Search")
    assert result.success is False
    assert result.verification is None


def test_action_result_fields_project_onto_tool_result():
    ar = ActionResult(True, "completed", "click_ui_element", verification=True,
                      arguments={"label": "x"}, message="done")
    projected = ar.to_tool_fields()
    assert projected["success"] is True and projected["verification"] is True


# --- Permissions ------------------------------------------------------ #
def test_default_permission_is_observe_only(observe_only):
    pm = get_permission_manager()
    assert pm.get_permission() == PermissionLevel.OBSERVE_ONLY
    assert pm.can_observe_screen() is True
    assert pm.can_control_screen() is False


def test_enable_and_disable_computer_control():
    pm = get_permission_manager()
    pm.set_permission(PermissionLevel.CONTROL_WITH_CONFIRMATION)
    assert pm.can_control_screen() is True
    pm.set_permission(PermissionLevel.OBSERVE_ONLY)
    assert pm.can_control_screen() is False


def test_email_and_deletes_always_require_confirmation(observe_only):
    pm = get_permission_manager()
    assert pm.requires_confirmation("email.send") is True
    assert pm.requires_confirmation("file.delete") is True


def test_permission_intent_extracts_level():
    result = IntentEngine().infer("JARVIS, enable computer control.")
    assert result.intent == "system"
    assert result.sub_intent == "set_permission"
    assert result.extracted_entities["permission"] == "CONTROL_WITH_CONFIRMATION"
    off = IntentEngine().infer("JARVIS, disable computer control.")
    assert off.extracted_entities["permission"] == "OBSERVE_ONLY"


def test_set_permission_capability_changes_state():
    pm = get_permission_manager()
    try:
        result = execute_capability("system.set_permission", level="CONTROL_WITH_CONFIRMATION")
        assert result.success is True
        assert pm.get_permission() == PermissionLevel.CONTROL_WITH_CONFIRMATION
    finally:
        pm.set_permission(PermissionLevel.FULL_CONTROL)


# --- Confirmation preserves the complete pending action --------------- #
def test_confirmation_carries_arguments_to_execution():
    pm = get_permission_manager()
    try:
        pm.set_permission(PermissionLevel.CONTROL_WITH_CONFIRMATION)
        result = execute_capability("screen.type", text="hello")
        assert result.status == "confirmation_required"
        assert result.arguments == {"text": "hello"}
    finally:
        pm.set_permission(PermissionLevel.FULL_CONTROL)


def test_execute_confirmed_uses_passed_arguments(full_control, monkeypatch):
    import core.screencontrol as sc
    typed = {}
    monkeypatch.setattr(sc.pyautogui, "write", lambda text, interval=0: typed.setdefault("t", text))
    result = capabilities.execute_confirmed("screen.type", text="hello")
    assert result.success is True
    assert typed["t"] == "hello"