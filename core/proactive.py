"""Proactive intelligence and opportunity observer for JARVIS.

Notices helpful opportunities (terminal errors, open document follow-ups,
routine automation suggestions) naturally without constant narrations.
"""

from __future__ import annotations

import re
from typing import Any
from core.context import DesktopContext, get_desktop_context


class ProactiveEngine:
    """Evaluate desktop context for helpful proactive suggestions."""

    def __init__(self) -> None:
        self.last_suggested_topic: str | None = None

    def evaluate(self, context: DesktopContext | None = None) -> str | None:
        context = context or get_desktop_context()

        visible = context.visible_content.lower()
        title = context.active_window_title.lower()

        # 1. Detect terminal crash / module import error
        if ("importerror" in visible or "traceback" in visible or "syntaxerror" in visible or "exception" in visible) and ("terminal" in context.current_application.lower() or "code" in context.current_application.lower()):
            topic = "terminal_error"
            if self.last_suggested_topic != topic:
                self.last_suggested_topic = topic
                return "I noticed an error in your terminal or editor. Would you like me to inspect it?"

        # 2. Open document / CV check
        if "cv" in title or "resume" in title or "profile" in visible:
            topic = "cv_review"
            if self.last_suggested_topic != topic:
                self.last_suggested_topic = topic
                return "I can summarize this CV, check for missing sections, or compare it with a job description."

        return None


_proactive_engine = ProactiveEngine()


def check_proactive_suggestion() -> str | None:
    return _proactive_engine.evaluate()

