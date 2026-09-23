"""Reliability tests 3/3 — memory, local-first routing, email, browser fallback."""

from __future__ import annotations

import json
import smtplib
from pathlib import Path
from types import SimpleNamespace

import core.capabilities as capabilities
from core.intent import IntentEngine
from core.memory import ShortTermMemory, get_short_term_memory
from core.planner import ActionPlanner


def _stub_result(name, **kw):
    return SimpleNamespace(success=True, tool=name, result="ok", error=None,
                           status="completed", arguments=kw, verification=None)


# --- Short-term memory ------------------------------------------------ #
def test_short_term_memory_is_bounded():
    mem = ShortTermMemory(capacity=3)
    for i in range(10):
        mem.record(transcript=f"t{i}", capability=f"cap{i}")
    assert len(mem.records) == 3
    assert mem.records[0]["transcript"] == "t7"


def test_memory_describes_last_action():
    mem = ShortTermMemory(capacity=5)
    assert "haven't performed" in mem.describe_last_action()
    mem.record(transcript="open downloads", capability="file.open", status="success",
               arguments={"path": "downloads"}, result="Opened Downloads.")
    text = mem.describe_last_action()
    assert "file.open" in text and "Opened Downloads." in text


def test_memory_resolves_anaphoric_reference():
    mem = ShortTermMemory(capacity=5)
    mem.record(transcript="open downloads", capability="file.open",
               arguments={"path": "downloads"}, status="success")
    record = mem.resolve_action_target("open that folder")
    assert record is not None and record["capability"] == "file.open"


def test_memory_singleton_available():
    assert get_short_term_memory() is get_short_term_memory()


def test_memory_has_no_record_when_idle():
    assert ShortTermMemory().last_action_record() is None


# --- Local-first routing ---------------------------------------------- #
def test_active_application_intent_is_local_not_browser():
    result = IntentEngine().infer("what application am I using?")
    assert result.intent == "system"
    assert result.sub_intent == "active_application"


def test_screen_question_intent_is_local():
    result = IntentEngine().infer("what is on my screen?")
    assert result.intent == "screen"
    assert result.sub_intent == "question"


def test_click_routes_to_verified_screen_control(monkeypatch):
    planner = ActionPlanner()
    seen = []
    monkeypatch.setattr("core.planner.execute_capability",
                        lambda name, **kw: seen.append((name, kw)) or _stub_result(name, **kw))
    result = planner.execute("click the search bar")
    assert result.success is True
    assert seen == [("screen.click_element", {"label": "search bar"})]


def test_press_enter_routes_to_screen_press(monkeypatch):
    planner = ActionPlanner()
    seen = []
    monkeypatch.setattr("core.planner.execute_capability",
                        lambda name, **kw: seen.append((name, kw)) or _stub_result(name, **kw))
    planner.execute("press enter")
    assert seen == [("screen.press_key", {"key": "enter"})]


def test_scroll_routes_locally(monkeypatch):
    planner = ActionPlanner()
    seen = []
    monkeypatch.setattr("core.planner.execute_capability",
                        lambda name, **kw: seen.append((name, kw)) or _stub_result(name, **kw))
    planner.execute("scroll down")
    assert seen == [("screen.scroll", {"direction": "down"})]


def test_open_downloads_routes_to_file_open(monkeypatch):
    planner = ActionPlanner()
    seen = []
    monkeypatch.setattr("core.planner.execute_capability",
                        lambda name, **kw: seen.append((name, kw)) or _stub_result(name, **kw))
    planner.execute("open my Downloads folder")
    assert seen and seen[0][0] == "file.open"
    assert seen[0][1]["path"] == "downloads"


def test_active_application_answer_uses_real_window(monkeypatch):
    planner = ActionPlanner()
    monkeypatch.setattr("perception.window.get_active_window",
                        lambda: SimpleNamespace(app_name="Google Chrome", title="x", hwnd=1))
    result = planner._handle_active_application("what application am i using", "x", None)
    assert result.success is True
    assert "Google Chrome" in result.result


def test_active_application_failure_is_honest(monkeypatch):
    planner = ActionPlanner()

    def boom():
        raise RuntimeError("no window")
    monkeypatch.setattr("perception.window.get_active_window", boom)
    result = planner._handle_active_application("what application am i using", "x", None)
    assert result.success is False
    assert "couldn't determine" in result.result


def test_general_knowledge_still_routes_to_browser(monkeypatch):
    planner = ActionPlanner()
    seen = []
    monkeypatch.setattr("core.planner.execute_capability",
                        lambda name, **kw: seen.append((name, kw)) or _stub_result(name, **kw))
    planner.execute("search the web for python asyncio")
    assert seen and seen[0][0] == "browser.search"


def test_browser_search_still_opens_when_asked(monkeypatch):
    import tools.browser as browser
    opened = {}
    monkeypatch.setattr(browser.webbrowser, "open", lambda url, new=0: opened.setdefault("u", url) or True)
    assert "python" in browser.search_web("python")
    assert "google.com/search" in opened["u"]