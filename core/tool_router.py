"""Lightweight relevance router inspired by isair/jarvis.

Selects a small subset of OpenJarvis tools before the agentic loop. This first
implementation is deterministic and dependency-free; it can later be upgraded
to a fast-model/embedding selector without changing the caller API.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ToolSelection:
    names: tuple[str, ...]
    scores: dict[str, float]
    reason: str


class SmartToolRouter:
    _RULES = {
        "calculator": ("calculate", "compute", "equation", "math", "percentage", "percent", "multiply", "divide", "plus", "minus", "factorial", "average"),
        "think": ("reason", "why", "explain", "analyze", "analyse", "compare", "plan", "logic", "solve"),
        "file_read": ("read", "file", "document", "pdf", "notes", "folder", "directory", "text file"),
        "web_search": ("search", "research", "latest", "current", "online", "web", "news", "look up", "find information"),
        "retrieval": ("remember", "previous", "earlier", "we discussed", "last time", "my project", "what do you know about me"),
        "llm": ("draft", "write", "rewrite", "brainstorm", "summarize", "summarise", "translate", "generate"),
        "code_interpreter": ("python", "code", "program", "data", "csv", "dataset", "plot", "statistics", "regression", "simulate"),
        "memory_manage": ("remember that", "forget that", "save this to memory", "delete from memory", "update my memory"),
        "user_profile_manage": ("my name", "my preference", "my preferences", "my profile", "about me"),
    }

    _ALIASES = {"chat gpt": "chatgpt"}

    def select(self, query: str, available: list[str], max_tools: int = 5) -> ToolSelection:
        text = re.sub(r"\s+", " ", (query or "").lower()).strip()
        scores: dict[str, float] = {name: 0.0 for name in available}
        for name in available:
            for phrase in self._RULES.get(name, ()):
                if phrase in text:
                    scores[name] += 1.0 + min(len(phrase) / 40.0, 0.5)
        # Always retain the general reasoning tool for ambiguous knowledge tasks.
        if not any(v > 0 for v in scores.values()) and "think" in scores:
            scores["think"] = 0.25
        ranked = sorted(scores, key=lambda n: scores[n], reverse=True)
        selected = [n for n in ranked if scores[n] > 0][:max_tools]
        if not selected and available:
            selected = ["think"] if "think" in available else available[:1]
        # Tool chaining: research commonly needs reasoning; file retrieval commonly needs reasoning.
        if selected and "think" in available and "think" not in selected and any(n in selected for n in ("web_search", "file_read", "retrieval", "code_interpreter")) and len(selected) < max_tools:
            selected.append("think")
        reason = "keyword relevance" if any(v > 0 for v in scores.values()) else "safe fallback"
        return ToolSelection(tuple(selected), scores, reason)


_router = SmartToolRouter()


def select_tools(query: str, available: list[str], max_tools: int = 5) -> ToolSelection:
    return _router.select(query, available, max_tools=max_tools)
