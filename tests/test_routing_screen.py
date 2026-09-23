"""Comprehensive routing tests for screen perception, control, and web search."""

from __future__ import annotations

import pytest

from core.intent import IntentEngine
from core.planner import ActionPlanner


@pytest.fixture
def engine():
    return IntentEngine()


@pytest.fixture
def planner():
    return ActionPlanner()


# ================================================================
# Screen question routing
# ================================================================
class TestScreenQuestionRouting:
    def test_what_is_on_screen(self, engine):
        r = engine.infer("What is on my screen?")
        assert r.intent == "screen"
        assert r.sub_intent == "question"

    def test_what_can_you_see(self, engine):
        r = engine.infer("what can you see on my screen?")
        assert r.intent == "screen"
        assert r.sub_intent == "question"

    def test_do_you_see_search_bar(self, engine):
        r = engine.infer("do you see the search bar?")
        assert r.intent == "screen"
        assert r.sub_intent == "question"

    def test_can_you_see(self, engine):
        r = engine.infer("can you see the search bar?")
        assert r.intent == "screen"
        assert r.sub_intent == "question"

    def test_read_this_page(self, engine):
        r = engine.infer("read this page")
        assert r.intent == "screen"
        assert r.sub_intent == "question"

    def test_read_this_screen(self, engine):
        r = engine.infer("read this screen")
        assert r.intent == "screen"
        assert r.sub_intent == "question"

    def test_whats_on_screen(self, engine):
        r = engine.infer("what's on my screen right now?")
        assert r.intent == "screen"
        assert r.sub_intent == "question"

    def test_what_application_am_i_using(self, engine):
        r = engine.infer("what application am I using?")
        assert r.intent == "system"
        assert r.sub_intent == "active_application"


# ================================================================
# Screen control routing
# ================================================================
class TestScreenControlRouting:
    def test_click_search_bar(self, engine):
        r = engine.infer("click the search bar")
        assert r.intent == "screen_control"
        assert r.sub_intent == "action"

    def test_close_this_tab(self, engine):
        r = engine.infer("close this tab")
        assert r.intent == "screen_control"
        assert r.sub_intent == "action"

    def test_close_email_tab(self, engine):
        r = engine.infer("close the email tab")
        assert r.intent == "screen_control"
        assert r.sub_intent == "action"

    def test_click_email(self, engine):
        r = engine.infer("click the email")
        assert r.intent == "screen_control"
        assert r.sub_intent == "action"

    def test_scroll_down(self, engine):
        r = engine.infer("scroll down")
        assert r.intent == "screen_control"
        assert r.sub_intent == "action"

    def test_press_enter(self, engine):
        r = engine.infer("press enter")
        assert r.intent == "screen_control"
        assert r.sub_intent == "action"

    def test_type_hello(self, engine):
        r = engine.infer("type hello")
        assert r.intent == "screen_control"
        assert r.sub_intent == "action"


# ================================================================
# Email routing
# ================================================================
class TestEmailRouting:
    def test_send_email(self, engine):
        r = engine.infer("send an email")
        assert r.intent == "email"

    def test_draft_email(self, engine):
        r = engine.infer("draft an email")
        assert r.intent == "email"
        assert r.sub_intent == "draft"

    def test_email_diagnostics(self, engine):
        r = engine.infer("check my email configuration")
        assert r.intent == "email"


# ================================================================
# Memory / conversation routing
# ================================================================
class TestMemoryRouting:
    def test_what_did_you_just_do(self, engine):
        r = engine.infer("what did you just do?")


# ================================================================
# Web search routing (ONLY for explicit external info requests)
# ================================================================
class TestWebSearchRouting:
    def test_search_web_for_python(self, engine):
        r = engine.infer("search the web for Python")
        assert r.intent == "browser"
        assert r.sub_intent == "search"

    def test_what_is_latest_python_version(self, engine):
        r = engine.infer("what is the latest Python version?")
        assert r.intent == "browser"
        assert r.sub_intent == "search"

    def test_google_python(self, engine):
        r = engine.infer("google Python asyncio")
        assert r.intent == "browser"
        assert r.sub_intent == "search"


# ================================================================
# Commands that must NOT trigger web search
# ================================================================
class TestNoRandomWebSearch:
    def test_what_is_on_screen_not_web(self, engine):
        r = engine.infer("what is on my screen?")
        assert r.intent != "browser"

    def test_do_you_see_not_web(self, engine):
        r = engine.infer("do you see the search bar?")
        assert r.intent != "browser"

    def test_click_search_bar_not_web(self, engine):
        r = engine.infer("click the search bar")
        assert r.intent != "browser"

    def test_close_tab_not_web(self, engine):
        r = engine.infer("close this tab")
        assert r.intent != "browser"

    def test_what_are_you_talking_about_not_web(self, engine):
        r = engine.infer("what are you talking about?")
        assert r.intent != "browser"

    def test_what_did_you_just_do_not_web(self, engine):
        r = engine.infer("what did you just do?")
        assert r.intent != "browser"



# ================================================================
# Planner web search guard
# ================================================================
class TestPlannerWebSearchGuard:
    def test_planner_blocks_browser_for_screen_intent(self, planner):
        result = planner.execute("what is on my screen?")
        if result is not None:
            assert result.tool != "browser.search"

    def test_planner_blocks_browser_for_system_intent(self, planner):
        result = planner.execute("what application am I using?")
        if result is not None:
            assert result.tool != "browser.search"

    def test_planner_allows_browser_for_explicit_search(self, planner):
        result = planner.execute("search the web for Python")
        if result is not None:
            assert result.tool == "browser.search"


# ================================================================
# Screen control vs email disambiguation
# ================================================================
class TestScreenVsEmail:
    def test_click_email_is_screen(self, engine):
        r = engine.infer("click the email")
        assert r.intent == "screen_control"

    def test_close_email_tab_is_screen(self, engine):
        r = engine.infer("close my Gmail tab")
        assert r.intent == "screen_control"

    def test_send_email_is_email(self, engine):
        r = engine.infer("send an email to john@example.com")
        assert r.intent == "email"


# ================================================================
# Screen control vs file system disambiguation
# ================================================================
class TestScreenVsFile:
    def test_read_this_page_is_screen(self, engine):
        r = engine.infer("read this page")
        assert r.intent == "screen"

    def test_search_this_page_is_screen(self, engine):
        r = engine.infer("search this page for Python")
        assert r.intent == "screen"


# ================================================================
# Screen control vs web disambiguation
# ================================================================
class TestScreenVsWeb:
    def test_click_search_bar_is_screen(self, engine):
        r = engine.infer("click the search bar")
        assert r.intent == "screen_control"

    def test_search_this_page_is_screen_not_web(self, engine):
        r = engine.infer("search this page for Python")
        assert r.intent == "screen"

    def test_whats_on_screen_is_screen_not_web(self, engine):
        r = engine.infer("what's on my screen?")
        assert r.intent == "screen"
    def test_read_this_page_not_web(self, engine):
        r = engine.infer("read this page")
        assert r.intent != "browser"

    def test_search_this_page_not_web(self, engine):
        r = engine.infer("search this page for Python")
        assert r.intent != "browser"

    def test_what_application_not_web(self, engine):
        r = engine.infer("what application am I using?")
        assert r.intent != "browser"
        assert r.intent == "system"
        assert r.sub_intent == "active_application"


# ================================================================
# File Explorer application routing
# ================================================================
class TestFileExplorerRouting:
    def test_open_file_explorer(self, engine):
        r = engine.infer("open file explorer")
        assert r.intent == "app"
        assert r.sub_intent == "open"

    def test_launch_file_explorer(self, engine):
        r = engine.infer("launch file explorer")
        assert r.intent == "app"
        assert r.sub_intent == "open"

    def test_open_explorer(self, engine):
        r = engine.infer("open explorer")
        assert r.intent == "app"
        assert r.sub_intent == "open"

    def test_open_windows_file_explorer(self, engine):
        r = engine.infer("open windows file explorer")
        assert r.intent == "app"
        assert r.sub_intent == "open"

    def test_show_downloads_is_list(self, engine):
        r = engine.infer("show me what is in downloads")
        assert r.intent == "file"
        assert r.sub_intent == "list"

    def test_open_downloads_is_open(self, engine):
        r = engine.infer("open downloads")
        assert r.intent == "file"
        assert r.sub_intent == "open"

    def test_what_are_you_talking_about(self, engine):
        r = engine.infer("what are you talking about?")
        assert r.intent == "system"
        assert r.sub_intent == "memory_recent"

    def test_what_were_we_discussing(self, engine):
        r = engine.infer("what were we discussing?")
        assert r.intent == "system"
        assert r.sub_intent == "memory_recent"


# ================================================================
# Generic agent routing guarantees (find vs open vs list vs memory)
# ================================================================
class TestGenericAgentRouting:
    def test_find_my_physics_paper_is_search(self, engine):
        r = engine.infer("find my physics paper")
        assert r.intent == "file"
        assert r.sub_intent == "search"

    def test_find_the_file_jarvis_is_search(self, engine):
        r = engine.infer("find the file jarvis")
        assert r.intent == "file"
        assert r.sub_intent == "search"

    def test_where_is_jarvis_is_search(self, engine):
        r = engine.infer("where is jarvis")
        assert r.intent == "file"
        assert r.sub_intent == "search"

    def test_show_me_my_downloads_is_list(self, engine):
        r = engine.infer("show me my downloads")
        assert r.intent == "file"
        assert r.sub_intent == "list"

    def test_what_files_are_in_downloads_is_list(self, engine):
        r = engine.infer("what files are in downloads")
        assert r.intent == "file"
        assert r.sub_intent == "list"

    def test_contextual_where_did_you_find_not_file(self, engine):
        # "where did you find them" is a memory/context question, NOT file/open
        r = engine.infer("where did you find them")
        assert r.intent == "system"
        assert r.sub_intent == "memory_recent"

    def test_contextual_where_did_you_locate_not_file(self, engine):
        r = engine.infer("where did you locate the file jarvis")
        assert r.intent in ("system", None)


# ================================================================
# Agent-level routing guarantees (active app, downloads history, notepad)
# ================================================================
class TestAgentLocalRouting:
    """Agent-level (not intent-engine-level) routing for local computer actions."""

    @pytest.fixture
    def agent(self):
        from agents.agent import ComputerAgent
        return ComputerAgent()

    def test_what_am_i_using_is_active_app(self, agent):
        action = agent._parse_intent("what am I using")
        assert action["type"] == "observe"
        assert action.get("intent_type") == "system"

    def test_download_history_last_week_is_recent(self, agent):
        action = agent._parse_intent("what did I download last week")
        assert action["type"] == "observe"
        assert action.get("recent_folder") == "downloads"

    def test_write_in_notepad_is_document(self, agent):
        action = agent._parse_intent("write 'hello jarvis' in notepad")
        assert action["type"] == "type"
        assert action.get("intent_type") == "document"

    def test_create_study_plan_in_notepad_is_document(self, agent):
        action = agent._parse_intent("create a physics study plan in notepad")
        assert action["type"] == "type"
        assert action.get("intent_type") == "document"

    def test_screen_question_is_observe(self, agent):
        action = agent._parse_intent("what's on my screen")
        assert action["type"] == "observe"

    def test_open_file_explorer_is_app(self, agent):
        action = agent._parse_intent("open file explorer")
        assert action["type"] == "open"
        assert action.get("intent_type") == "app"


# ================================================================
# Vocal screen control with screen references & acoustic robustness
# ================================================================
class TestVocalScreenControlAndAcousticRobustness:
    def test_vocal_click_on_help_on_my_screen(self, engine, planner):
        text = "service like can you click on help on my screen"
        r = engine.infer(text)
        assert r.intent == "screen_control"
        assert r.sub_intent == "action"
        assert r.extracted_entities.get("action") == "click"
        assert r.extracted_entities.get("target") == "help"

        plan = planner.execute(text, r)
        assert plan.tool == "screen.click_element"
        assert plan.arguments.get("label") == "help"

    def test_vocal_type_message_on_my_screen(self, engine, planner):
        text = "roses I mean I need you to like type a message on my screen"
        r = engine.infer(text)
        assert r.intent == "screen_control"
        assert r.sub_intent == "action"
        assert r.extracted_entities.get("action") == "type"

        plan = planner.execute(text, r)
        assert plan.tool == "screen.type"
        assert plan.arguments.get("text") == "Hello from JARVIS!"

    def test_passive_screen_question_not_control(self, engine):
        r = engine.infer("what do you see on my screen?")
        assert r.intent == "screen"
        assert r.sub_intent == "question"

    def test_weather_query_routes_to_weather_capability(self, engine, planner):
        r = engine.infer("what is the weather in Tokyo")
        plan = planner.execute("what is the weather in Tokyo", r)
        assert plan.tool == "weather.get"
        assert plan.success is True
        assert "Tokyo" in str(plan.result)