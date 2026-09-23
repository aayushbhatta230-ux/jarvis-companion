"""Live knowledge & research tool for JARVIS.

Queries Wikipedia REST API and DuckDuckGo for fast, factual summaries
without opening browser windows or requiring paid API subscriptions.
"""

from __future__ import annotations

import re
import requests

try:
    from ddgs import DDGS
    HAS_DDGS = True
except ImportError:
    HAS_DDGS = False


def lookup_knowledge(query: str) -> str:
    """Fetch a concise, authoritative answer for a person, concept, or topic.

    Parameters
    ----------
    query: str
        The question or search topic (e.g. 'Albert Einstein', 'James Webb Telescope').
    """
    clean = (query or "").strip().rstrip("?.!")
    if not clean:
        return "What would you like me to look up?"

    clean = re.sub(
        r"^(?:who is|who was|what is|what are|tell me about|look up|search for)\s+",
        "",
        clean,
        flags=re.IGNORECASE,
    ).strip()

    # 1. Try Wikipedia REST API for clean encyclopedic summaries
    try:
        slug = requests.utils.quote(clean.replace(" ", "_"))
        headers = {"User-Agent": "JarvisAICompanion/1.0 (Windows NT; contact: local)"}
        resp = requests.get(
            f"https://en.wikipedia.org/api/rest_v1/page/summary/{slug}",
            headers=headers,
            timeout=3.5,
        )
        if resp.status_code == 200:
            extract = resp.json().get("extract")
            if extract:
                # Return the first 1-2 sentences for concise voice delivery
                sentences = re.split(r"(?<=[.!?])\s+", extract.strip())
                return " ".join(sentences[:2])
    except Exception:
        pass

    # 2. Fallback to DuckDuckGo instant summary
    if HAS_DDGS:
        try:
            with DDGS() as ddgs:
                results = list(ddgs.text(clean, max_results=1))
                if results and results[0].get("body"):
                    body = results[0]["body"].strip()
                    sentences = re.split(r"(?<=[.!?])\s+", body)
                    return " ".join(sentences[:2])
        except Exception:
            pass

    return f"I couldn't find a quick summary for '{clean}'."
