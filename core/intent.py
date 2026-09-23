"""Intent inference for natural companion conversations.

Understands natural phrasing, direct actions, media commands,
screen control, browser requests, file operations, and follow-ups.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import re


@dataclass
class IntentResult:
    intent: str
    sub_intent: str
    confidence: float
    needs_confirmation: bool
    rationale: str
    suggestions: list[str] = field(default_factory=list)
    extracted_entities: dict[str, Any] = field(default_factory=dict)


class IntentEngine:
    """Infer likely goals from natural language."""

    COMMON_KNOWN_DIRS = (
        "downloads",
        "documents",
        "desktop",
        "pictures",
        "music",
        "videos",
    )

    # ------------------------------------------------------------------
    # Main intent inference
    # ------------------------------------------------------------------

    def infer(self, text, context=None, preferences=None):
        lower = text.lower().strip()
        context_text = " ".join(context or []).lower()
        entities = self._extract_entities(lower, context_text)

        # --------------------------------------------------------------
        # Cancellation
        # --------------------------------------------------------------

        cancel_phrases = (
            "never mind",
            "cancel that",
            "forget it",
            "don't do that",
            "do not do that",
            "nevermind",
            "stop that",
            "abort",
            "no thanks",
            "no thank you",
        )

        if self._matches(lower, cancel_phrases):
            return IntentResult(
                "control",
                "cancel",
                0.95,
                False,
                "User cancelled.",
            )

        # --------------------------------------------------------------
        # Self-awareness
        # --------------------------------------------------------------

        if self._matches(
            lower,
            (
                "what can you do",
                "what are your abilities",
                "your capabilities",
                "what features do you have",
                "what can jarvis do",
            ),
        ):
            return IntentResult(
                "system",
                "capabilities",
                0.95,
                False,
                "User asked about assistant capabilities.",
            )

        if self._matches(
            lower,
            (
                "why did you",
                "what did you just do",
                "why did you search",
                "did you send it",
                "why did you do that",
            ),
        ):
            return IntentResult(
                "system",
                "action_history",
                0.95,
                False,
                "User asked about previous actions.",
            )

        if self._matches(
            lower,
            (
                "what did i ask",
                "what did i just ask",
                "do you remember what i asked",
                "do you remember what i just asked",
                "what were we talking about",
            ),
        ):
            return IntentResult(
                "system",
                "memory_recent",
                0.95,
                False,
                "User asked about recent conversation context.",
            )

        # --------------------------------------------------------------
        # SCREEN / COMPUTER CONTROL PRIORITY
        # Must be checked BEFORE browser inference so phrases like
        # "click the search bar", "read this page", "scroll down"
        # route to screen_control instead of browser.
        # --------------------------------------------------------------

        asks_active_app = self._asks_active_application(lower)
        control = self._detect_control_action(lower)

        if control:
            action, target = control

            return IntentResult(
                "screen_control",
                "action",
                0.95,
                False,
                "User wants to control the screen or a window.",
                extracted_entities={
                    "action": action,
                    "target": target,
                },
            )

        asks_screen_content = self._asks_screen_content(lower)

        if asks_screen_content and not asks_active_app:
            return IntentResult(
                "screen",
                "question",
                0.95,
                False,
                "User asked what is on the screen.",
            )

        if asks_active_app:
            return IntentResult(
                "system",
                "active_application",
                0.95,
                False,
                "User asked which application/window is active.",
            )

        # --------------------------------------------------------------
        # Specific website open requests (high priority — before other
        # browser actions so that "take me to GitHub" opens the site
        # rather than trying to switch an existing tab).
        # --------------------------------------------------------------

        browser_result = self._infer_browser(
            lower,
            context_text,
            entities,
        )
        # Return browser navigation/intent results directly (not just open_url)
        if browser_result and browser_result.intent == "browser":
            return browser_result

        # --------------------------------------------------------------
        # Screen access status
        # --------------------------------------------------------------

        if self._matches(
            lower,
            (
                "do you have screen access",
                "can you access my screen",
                "is screen access",
                "screen access status",
                "do you have access to my screen",
            ),
        ):
            return IntentResult(
                "system",
                "screen_status",
                0.95,
                False,
                "User asked about screen access.",
            )

        # --------------------------------------------------------------
        # Computer-control permission
        # --------------------------------------------------------------

        if any(
            phrase in lower
            for phrase in (
                "full access",
                "full control",
                "access to everything",
                "full permission",
                "unrestricted access",
                "grant full access",
                "give full access",
                "give it full access",
                "all permissions",
            )
        ):
            return IntentResult(
                "system",
                "set_permission",
                0.95,
                False,
                "User wants to grant full access to everything.",
                extracted_entities={
                    "permission": "FULL_CONTROL"
                },
            )

        if (
            any(
                word in lower
                for word in (
                    "enable",
                    "turn on",
                    "allow",
                    "activate",
                    "grant",
                )
            )
            and any(
                word in lower
                for word in (
                    "computer control",
                    "screen control",
                    "control of the computer",
                    "control",
                )
            )
        ):
            return IntentResult(
                "system",
                "set_permission",
                0.92,
                False,
                "User wants to enable computer control.",
                extracted_entities={
                    "permission": "CONTROL_WITH_CONFIRMATION"
                },
            )

        if (
            any(
                word in lower
                for word in (
                    "disable",
                    "turn off",
                    "deactivate",
                    "disallow",
                    "revoke",
                )
            )
            and any(
                word in lower
                for word in (
                    "computer control",
                    "screen control",
                    "control",
                    "permission",
                )
            )
        ):
            return IntentResult(
                "system",
                "set_permission",
                0.92,
                False,
                "User wants to disable computer control.",
                extracted_entities={
                    "permission": "OBSERVE_ONLY"
                },
            )

        # --------------------------------------------------------------
        # Explicit web search
        # --------------------------------------------------------------

        if (
            not asks_screen_content
            and not asks_active_app
            and not control
            and self._is_explicit_web_search(lower)
        ):
            query = re.sub(
                r"^(search|look up|google|find)"
                r"( the web)?( for| about| up)?\s*",
                "",
                lower,
            ).strip()

            return IntentResult(
                "browser",
                "search",
                0.90,
                False,
                "Explicit web search requested.",
                extracted_entities={
                    "query": query
                },
            )

        # --------------------------------------------------------------
        # File deletion priority
        # --------------------------------------------------------------

        if self._matches(
            lower,
            (
                "delete",
                "get rid of",
                "remove",
                "trash",
            ),
        ):
            return IntentResult(
                "file",
                "delete",
                0.80,
                True,
                "Delete a file (needs confirmation).",
                extracted_entities=entities,
            )

        # --------------------------------------------------------------
        # MEDIA
        # --------------------------------------------------------------

        media_result = self._infer_media(lower, context_text)

        if media_result:
            return media_result

        # --------------------------------------------------------------
        # Specific website requests
        # --------------------------------------------------------------

        browser_result = self._infer_browser(
            lower,
            context_text,
            entities,
        )

        if browser_result and browser_result.sub_intent == "open_url":
            return browser_result

        # --------------------------------------------------------------
        # Applications
        # --------------------------------------------------------------

        app_result = self._infer_app_control(
            lower,
            context_text,
            entities,
        )

        if app_result:
            return app_result

        # --------------------------------------------------------------
        # Files
        # --------------------------------------------------------------

        file_result = self._infer_file_operations(
            lower,
            context_text,
            entities,
        )

        if file_result:
            return file_result

        # --------------------------------------------------------------
        # Browser
        # --------------------------------------------------------------

        browser_result = self._infer_browser(
            lower,
            context_text,
            entities,
        )

        if browser_result:
            return browser_result

        # --------------------------------------------------------------
        # Email
        # --------------------------------------------------------------

        email_result = self._infer_email(
            lower,
            context_text,
            entities,
        )

        if email_result:
            return email_result

        # --------------------------------------------------------------
        # Documents
        # --------------------------------------------------------------

        document_result = self._infer_document_ops(
            lower,
            context_text,
            entities,
        )

        if document_result:
            return document_result

        # --------------------------------------------------------------
        # Terminal / code
        # --------------------------------------------------------------

        terminal_result = self._infer_terminal(
            lower,
            context_text,
            entities,
        )

        if terminal_result:
            return terminal_result

        # --------------------------------------------------------------
        # System information
        # --------------------------------------------------------------

        if self._matches(
            lower,
            (
                "system info",
                "computer status",
                "cpu usage",
                "memory usage",
                "system information",
                "specifications",
                "specs",
                "how's my computer",
                "how is my computer",
                "my computer doing",
                "computer's status",
            ),
        ):
            return IntentResult(
                "system",
                "get_info",
                0.90,
                False,
                "User wants system information.",
            )

        if re.search(
            r"what.s my (cpu|ram|memory|disk|computer)",
            lower,
        ):
            return IntentResult(
                "system",
                "get_info",
                0.85,
                False,
                "User wants system information.",
            )

        # --------------------------------------------------------------
        # Entertainment
        # --------------------------------------------------------------

        if self._matches(
            lower,
            (
                "watch",
                "show me something",
                "something to watch",
            ),
        ):
            return IntentResult(
                "entertainment",
                "watch_video",
                0.85,
                False,
                "User wants something to watch.",
            )

        # --------------------------------------------------------------
        # Study
        # --------------------------------------------------------------

        if self._matches(
            lower,
            (
                "need to study",
                "study",
                "revise",
                "learn",
                "help me study",
            ),
        ):
            return IntentResult(
                "study",
                "study_support",
                0.82,
                False,
                "User wants study support.",
            )

        # --------------------------------------------------------------
        # Bored / discovery
        # --------------------------------------------------------------

        if self._matches(
            lower,
            (
                "don't know what",
                "do something",
                "something interesting",
                "surprise me",
                "bored",
                "i'm bored",
            ),
        ):
            return IntentResult(
                "discovery",
                "suggestion",
                0.60,
                False,
                "User wants a suggestion.",
            )

        # --------------------------------------------------------------
        # Wellbeing
        # --------------------------------------------------------------

        if self._matches(
            lower,
            (
                "tired",
                "low energy",
                "need a break",
                "exhausted",
            ),
        ):
            return IntentResult(
                "wellbeing",
                "low_effort_activity",
                0.75,
                False,
                "User may prefer a low-effort activity.",
            )

        # --------------------------------------------------------------
        # Follow-up
        # --------------------------------------------------------------

        if self._matches(
            lower,
            (
                "open it",
                "open that",
                "show it",
                "show me that",
                "do it",
                "go ahead",
            ),
        ):
            return IntentResult(
                "follow_up",
                "execute_previous",
                0.70,
                False,
                "User refers to a previous action.",
                extracted_entities={
                    "is_follow_up": True
                },
            )

        # --------------------------------------------------------------
        # Confirmation
        # --------------------------------------------------------------

        if self._matches(
            lower,
            (
                "yes",
                "yeah",
                "yep",
                "sure",
                "okay",
                "ok",
                "do it",
                "send it",
                "confirm",
            ),
        ):
            return IntentResult(
                "control",
                "confirm",
                0.85,
                False,
                "User confirmed.",
            )

        if self._matches(
            lower,
            (
                "no",
                "nope",
                "don't",
                "cancel",
                "never mind",
                "stop",
            ),
        ):
            return IntentResult(
                "control",
                "cancel",
                0.85,
                False,
                "User declined.",
            )

        # --------------------------------------------------------------
        # Recent conversation / memory
        # --------------------------------------------------------------

        if self._matches(
            lower,
            (
                "what are you talking about",
                "what are we talking about",
                "what were we talking about",
                "what was i saying",
                "what did i say",
                "do you remember what i said",
                "what were we discussing",
                "what is the context",
                "what am i talking about",
                "what was i talking about",
                "where did you find",
                "where did you locate",
                "where did you",
                "how did you find",
            ),
        ):
            return IntentResult(
                "system",
                "memory_recent",
                0.95,
                False,
                "User asked about recent conversation context.",
            )

        # --------------------------------------------------------------
        # "Where is [name]?" → file search (before general question)
        # --------------------------------------------------------------

        where_is_match = re.match(
            r"^(?:jarvis[, ]+)?(?:please )?where (?:is|'s)\s+(.+)",
            lower,
        )
        if where_is_match:
            remainder = where_is_match.group(1).strip(" .,?!")
            # Don't catch memory/context questions like "where is it".
            if not self._matches(
                remainder,
                ("them", "that", "it", "we", "this", "the"),
            ):
                return IntentResult(
                    "file",
                    "search",
                    0.85,
                    False,
                    "User asked where to find a file.",
                    extracted_entities={"query": remainder},
                )

        # --------------------------------------------------------------
        # Questions
        # --------------------------------------------------------------

        if self._is_question(lower):
            return IntentResult(
                "conversation",
                "general_question",
                0.90,
                False,
                "User asked for information.",
            )

        # --------------------------------------------------------------
        # General conversation
        # --------------------------------------------------------------

        return IntentResult(
            "conversation",
            "general_request",
            0.40,
            False,
            "No specific action inferred.",
        )

    # ==================================================================
    # MEDIA
    # ==================================================================

    def _infer_media(self, lower, context_text):
        """Infer music/media commands and extract song queries."""

        # --------------------------------------------------------------
        # STOP
        # --------------------------------------------------------------

        stop_phrases = (
            "stop the music",
            "stop music",
            "turn the music off",
            "turn music off",
            "stop playing",
            "no more music",
            "that's enough music",
            "stop that noise",
            "i don't want to listen",
            "i do not want to listen",
            "don't want music",
            "i don't want music",
            "i do not want music",
        )

        if self._matches(lower, stop_phrases):
            return IntentResult(
                "media",
                "stop",
                0.90,
                False,
                "Stop media playback.",
            )

        # Context-based stop
        if self._matches(
            lower,
            (
                "turn that off",
                "turn it off",
            ),
        ) and any(
            word in context_text
            for word in (
                "music",
                "playing",
                "track",
            )
        ):
            return IntentResult(
                "media",
                "stop",
                0.85,
                False,
                "Stop media playback using context.",
            )

        # --------------------------------------------------------------
        # PAUSE
        # --------------------------------------------------------------

        if self._matches(
            lower,
            (
                "pause",
                "pause the music",
                "pause music",
                "hold the music",
                "pause that",
            ),
        ) and not self._is_question(lower):
            return IntentResult(
                "media",
                "pause",
                0.90,
                False,
                "Pause media playback.",
            )

        # --------------------------------------------------------------
        # RESUME
        # --------------------------------------------------------------

        if self._matches(
            lower,
            (
                "resume",
                "continue",
                "resume the music",
                "play it again",
                "unpause",
            ),
        ) and not self._is_question(lower):
            return IntentResult(
                "media",
                "resume",
                0.88,
                False,
                "Resume media playback.",
            )

        # --------------------------------------------------------------
        # NEXT
        # --------------------------------------------------------------

        if self._matches(
            lower,
            (
                "skip this",
                "next song",
                "next track",
                "skip the song",
                "skip",
                "next",
            ),
        ):
            return IntentResult(
                "media",
                "next",
                0.90,
                False,
                "Skip to the next track.",
            )

        # --------------------------------------------------------------
        # PLAY
        # --------------------------------------------------------------

        if self._is_play_request(lower):

            query = self._extract_music_query(lower)

            mood = self._extract_music_mood(lower)

            entities = {
                "mood": mood,
            }

            if query:
                entities["query"] = query

            rationale = (
                f"Play music request"
                + (f" for '{query}'." if query else ".")
            )

            return IntentResult(
                "media",
                "play",
                0.95 if query else 0.90,
                False,
                rationale,
                extracted_entities=entities,
            )

        return None

    def _is_play_request(self, text):
        """Detect both generic music and specific song requests."""

        if self._is_question(text):
            return False

        # "watch" belongs to entertainment/video handling.
        if re.search(r"\bwatch\b", text):
            return False

        # --------------------------------------------------------------
        # Direct generic music commands
        # --------------------------------------------------------------

        if re.search(
            r"\b(play|start|put on)\b\s+"
            r"(?:me\s+|the\s+|some\s+)?"
            r"(?:music|song|songs|something|a song|a music)\b",
            text,
        ):
            return True

        # --------------------------------------------------------------
        # Specific music/song commands
        #
        # Examples:
        #   play Blinding Lights
        #   play me Blinding Lights
        #   start Blinding Lights
        #   put on Blinding Lights
        # --------------------------------------------------------------

        if re.search(
            r"\b(play|start|put on)\b\s+"
            r"(?:me\s+|the\s+)?"
            r"[a-z0-9][a-z0-9 '&.\-]{1,100}$",
            text,
        ):
            return True

        # --------------------------------------------------------------
        # Natural music requests
        # --------------------------------------------------------------

        if re.search(
            r"\b(i feel like|i want|i need|listen to|let me hear)\b.*"
            r"\b(music|something|song|songs|listening)\b",
            text,
        ):
            return True

        return False

    def _extract_music_query(self, text):
        """Extract a specific song/artist query from a play command."""

        patterns = (
            r"^\s*(?:jarvis[\s,:-]+)?"
            r"(?:please\s+)?"
            r"(?:play|start|put on)\s+"
            r"(?:me\s+)?"
            r"(?:the\s+)?"
            r"(.+?)\s*$",
        )

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)

            if not match:
                continue

            query = match.group(1).strip(" .,!?")

            # Generic commands should not become queries.
            generic = {
                "music",
                "song",
                "songs",
                "something",
                "a song",
                "a music",
            }

            if query.lower() in generic:
                return None

            # Queries that *start* with a generic word (e.g. "something
            # chill while I work") are mood-based requests, not specific
            # songs — strip the generic prefix and treat as no query.
            first_word = query.split()[0].lower() if query.split() else ""
            if first_word in generic:
                return None

            # Mood-only requests are handled by mood.
            mood_words = {
                "relaxing",
                "relaxed",
                "calm",
                "chill",
                "energetic",
                "upbeat",
                "workout",
                "sad",
                "romantic",
            }

            if query.lower() in mood_words:
                return None

            return query

        return None

    def _extract_music_mood(self, text):
        """Detect a requested music mood."""

        if any(
            word in text
            for word in (
                "relax",
                "relaxed",
                "calm",
                "chill",
            )
        ):
            return "relaxed"

        if any(
            word in text
            for word in (
                "energetic",
                "upbeat",
                "workout",
            )
        ):
            return "energetic"

        if "sad" in text:
            return "sad"

        if "romantic" in text:
            return "romantic"

        return "default"

    # ==================================================================
    # BROWSER
    # ==================================================================

    def _infer_browser(self, lower, context_text, entities):
        """Infer browser navigation/search requests."""

        # Contextual questions should not become searches.
        if self._matches(
            lower,
            (
                "where did you",
                "where did i",
                "how did you",
                "did you find",
                "did you locate",
            ),
        ):
            return None

        # ------------------------------------------------------------------
        # BROWSER NAVIGATION (go back/forward, refresh/reload)
        # ------------------------------------------------------------------
        # These are explicit navigation commands that should be handled
        # deterministically by the browser controller rather than being sent
        # to the conversational model.
        # ------------------------------------------------------------------

        navigation_back_patterns = (
            "go back",
            "come back",
            "come back to the previous page",
            "navigate back",
            "go back to the previous page",
            "previous page",
            "back",
            "go back a page",
        )

        navigation_forward_patterns = (
            "go forward",
            "navigate forward",
            "next page",
            "forward",
            "go forward a page",
        )

        refresh_patterns = (
            "refresh",
            "reload",
            "reload this page",
            "refresh this page",
            "reload the page",
            "refresh the page",
            "refreshed",
            "reloaded",
        )

        # Detect back navigation
        if any(self._matches(lower, (p,)) for p in navigation_back_patterns):
            return IntentResult(
                "browser",
                "navigation",
                0.95,
                False,
                "Browser back navigation requested.",
                extracted_entities={"direction": "back"},
            )

        # Detect forward navigation
        if any(self._matches(lower, (p,)) for p in navigation_forward_patterns):
            return IntentResult(
                "browser",
                "navigation",
                0.95,
                False,
                "Browser forward navigation requested.",
                extracted_entities={"direction": "forward"},
            )

        # Detect refresh/reload
        if any(self._matches(lower, (p,)) for p in refresh_patterns):
            return IntentResult(
                "browser",
                "navigation",
                0.95,
                False,
                "Browser page refresh/reload requested.",
                extracted_entities={"direction": "refresh"},
            )

        # Site keywords for browser open/search detection
        site_keywords = (
            "github",
            "gitlab",
            "bitbucket",
            "youtube",
            "youtube music",
            "spotify",
            "google",
            "google maps",
            "google drive",
            "google docs",
            "google sheets",
            "google slides",
            "google meet",
            "gmail",
            "google classroom",
            "chatgpt",
            "chat gpt",
            "openai",
            "claude",
            "gemini",
            "copilot",
            "perplexity",
            "deepseek",
            "hugging face",
            "huggingface",
            "stackoverflow",
            "stack overflow",
            "reddit",
            "wikipedia",
            "quora",
            "instagram",
            "facebook",
            "whatsapp",
            "linkedin",
            "tiktok",
            "tik tok",
            "twitter",
            "x",
            "threads",
            "telegram",
            "discord",
            "snapchat",
            "pinterest",
            "netflix",
            "prime video",
            "amazon",
            "twitch",
            "steam",
            "notion",
            "canva",
            "dropbox",
            "onedrive",
            "slack",
            "zoom",
            "trello",
            "npm",
            "pypi",
            "replit",
            "codepen",
            "leetcode",
            "geeksforgeeks",
            "w3schools",
            "coursera",
            "udemy",
            "khan academy",
            "duolingo",
            "ebay",
        )

        browser_open_verbs = (
            "open",
            "go to",
            "visit",
            "take me",
            "get me",
            "bring me",
            "launch",
            "load",
            "pull up",
            "browse",
            "check",
            "show me",
        )

        has_site = any(
            re.search(
                rf"\b{re.escape(site)}(?:\.com)?\b",
                lower,
            )
            for site in site_keywords
            )

        # "get X up" pattern (e.g., "Can you get GitHub up?")
        get_up_match = re.search(
            r"\bget\s+(?:the\s+|my\s+)?(\w+)\s+up\b",
            lower,
        )
        if get_up_match:
            target_word = get_up_match.group(1).lower()
            if target_word in site_keywords:
                return IntentResult(
                    "browser",
                    "open_url",
                    0.95,
                    False,
                    "Open specific website.",
                    extracted_entities=entities,
                )

        has_open_request = any(
            verb in lower
            for verb in browser_open_verbs
        )

        if has_site and has_open_request:
            return IntentResult(
                "browser",
                "open_url",
                0.95,
                False,
                "Open specific website.",
                extracted_entities=entities,
            )

        if self._matches(
            lower,
            (
                "open my browser",
                "open the browser",
                "launch browser",
                "open browser",
                "start browser",
                "open chrome",
                "open firefox",
                "open edge",
            ),
        ):
            return IntentResult(
                "browser",
                "open_browser",
                0.90,
                False,
                "Open default browser.",
            )

        # Current/latest information
        external_patterns = (
            r"\b(latest|current|new|recent)\b.*"
            r"\b(news|version|update|information|release|price|score|result)\b",

            r"\bwhat\s+is\s+the\s+"
            r"(latest|current|new|recent)\b",

            r"\bhow\s+much\s+is\b",

            r"\bwhat\s+is\s+the\s+price\b",

            r"\bweather\b",

            r"\bnews\s+about\b",

            r"\bfind\s+the\s+latest\b",

            r"\blook\s+up\s+(the\s+)?"
            r"(latest|current|price|weather)\b",
        )

        for pattern in external_patterns:
            if re.search(pattern, lower):
                return IntentResult(
                    "browser",
                    "search",
                    0.90,
                    False,
                    "External information requested.",
                    extracted_entities=entities,
                )

        # Search commands
        file_search_terms = (
            "file",
            "document",
            "doc",
            "folder",
            "assignment",
            "homework",
            "pdf",
            "downloads",
            "desktop",
            "notes",
            "note",
            "paper",
            "sheet",
            "spreadsheet",
            "presentation",
            "slides",
        )
        has_file_entity = bool(
            entities.get("file_reference")
            or entities.get("extension")
        )
        if not any(term in lower for term in file_search_terms) and not has_file_entity:
            search_patterns = (
                r"\b(search|look up|find|google)\b.*"
                r"\b(for|about|on the web)\b",

                r"\b(search|look up|find|google)\s+(.+)",
            )

            for pattern in search_patterns:
                if re.search(pattern, lower):
                    return IntentResult(
                        "browser",
                        "search",
                        0.90,
                        False,
                        "Search the web.",
                        extracted_entities=entities,
                    )

        # Direct URL
        if re.search(r"https?://\S+", lower):
            return IntentResult(
                "browser",
                "open_url",
                0.95,
                False,
                "Open URL.",
                extracted_entities=entities,
            )

        return None

    # ==================================================================
    # FILES
    # ==================================================================

    def _infer_file_operations(self, lower, context_text, entities):

        if self._matches(
            lower,
            (
                "where did you",
                "where did i",
                "what did you just",
                "how did you",
                "why did you",
                "did you find",
                "did you locate",
                "did you open",
                "did you click",
            ),
        ):
            return None

        # Content generation
        content_gen_match = re.search(
            r"\b(write|create|make|draft)\s+"
            r"(?:a|an|the|my)?\s*"
            r"(essay|report|letter|document|notes?|plan|"
            r"time\s*table|schedule|study\s*(?:plan|table|schedule)|"
            r"summary|outline|list|story|poem|article)\s+"
            r"(?:on|about|for|regarding)\s+(.+?)"
            r"(?:\s+(?:and\s+)?"
            r"(?:save|store|keep)\s*(?:it)?"
            r"(?:\s+(?:in|to|into)\s+"
            r"(?:notepad|file|a\s+file))?)?$",
            lower,
        )

        if content_gen_match:
            doc_type = content_gen_match.group(1)
            topic = content_gen_match.group(2).strip()

            entities["content_topic"] = topic
            entities["document_type"] = doc_type
            entities["needs_generation"] = True

            return IntentResult(
                "file",
                "write",
                0.88,
                False,
                f"Generate {doc_type} about {topic} and save to file.",
                extracted_entities=entities,
            )

        # Directory listing
        if self._matches(
            lower,
            (
                "what's in",
                "what is in",
                "what files are in",
                "what's inside",
                "what is inside",
                "show me what's in",
                "show me what is in",
                "contents of",
                "what do i have in",
                "list the contents of",
            ),
        ):
            return IntentResult(
                "file",
                "list",
                0.85,
                False,
                "List directory contents.",
                extracted_entities=entities,
            )

        # File searching
        file_search_phrases = (
            "find the file",
            "find a file",
            "find my file",
            "search for the file",
            "search for a file",
            "look for the file",
            "locate the file",
            "where is the file",
            "where's the file",
            "find the document",
            "find a document",
            "where is the document",
            "search my files",
            "search files",
            "find in my files",
            "find all files",
            "list all files",
        )

        file_reference_words = (
            "file",
            "document",
            "folder",
            "directory",
            "pdf",
            "download",
            "downloads",
            "assignment",
            "homework",
            "notes",
            "project",
            "report",
            "paper",
        )

        if self._matches(lower, file_search_phrases) or (
            any(
                word in lower
                for word in file_reference_words
            )
            and self._matches(
                lower,
                (
                    "find",
                    "search",
                    "look for",
                    "locate",
                    "where is",
                    "where's",
                ),
            )
        ):
            return IntentResult(
                "file",
                "search",
                0.85,
                False,
                "Search for files.",
                extracted_entities=entities,
            )

        # Known folder listing
        if (
            self._matches(
                lower,
                (
                    "show me",
                    "show my",
                    "show the",
                    "list",
                    "what's in",
                    "what is in",
                ),
            )
            and any(
                folder in lower
                for folder in self.COMMON_KNOWN_DIRS
            )
        ):
            return IntentResult(
                "file",
                "list",
                0.85,
                False,
                "List directory contents.",
                extracted_entities=entities,
            )

        # Open file
        if self._matches(
            lower,
            (
                "open",
                "pull up",
                "bring up",
                "get me",
                "show me",
                "grab",
            ),
        ) and self._has_file_reference(
            lower,
            context_text,
        ):
            return IntentResult(
                "file",
                "open",
                0.85,
                False,
                "Find and open a file.",
                extracted_entities=entities,
            )

        # Recent file
        if self._matches(
            lower,
            (
                "the file",
                "that file",
                "the one",
                "the document",
                "that document",
                "what i was working on",
                "from yesterday",
                "from last",
                "recent",
            ),
        ):
            return IntentResult(
                "file",
                "find_recent",
                0.80,
                False,
                "Find a recently used file.",
                extracted_entities=entities,
            )

        # Read file
        if self._matches(
            lower,
            (
                "read",
                "show me the contents of",
                "what's in",
                "what is in",
                "read me",
                "tell me what's in",
                "what does this file say",
                "what's inside",
            ),
        ):
            file_ref = self._extract_file_reference(
                lower,
                context_text,
            )

            entities["file_reference"] = file_ref

            return IntentResult(
                "file",
                "read",
                0.85,
                False,
                "Read file contents.",
                extracted_entities=entities,
            )

        # Create file
        if self._matches(
            lower,
            (
                "create a file",
                "make a file",
                "new file",
                "create a new file",
                "write a file",
                "create a new document",
                "make a document",
                "create a notepad file",
                "make a notepad file",
                "create a text file",
                "make a text file",
            ),
        ):
            fname = self._extract_filename_from_create(
                lower
            )

            if fname:
                entities["filename"] = fname

            return IntentResult(
                "file",
                "create",
                0.85,
                False,
                "Create a new file.",
                extracted_entities=entities,
            )

        # Folder
        if self._matches(
            lower,
            (
                "create a folder",
                "make a folder",
                "new folder",
                "create the folder",
                "make a new folder",
                "add a folder",
            ),
        ):
            return IntentResult(
                "file",
                "create_folder",
                0.85,
                False,
                "Create a folder.",
                extracted_entities=entities,
            )

        # Delete
        if self._matches(
            lower,
            (
                "delete",
                "get rid of",
                "remove",
                "trash",
                "discard",
            ),
        ):
            return IntentResult(
                "file",
                "delete",
                0.80,
                True,
                "Delete a file (needs confirmation).",
                extracted_entities=entities,
            )

        # Move
        if self._matches(
            lower,
            (
                "move",
                "relocate",
                "shift",
            ),
        ):
            return IntentResult(
                "file",
                "move",
                0.80,
                False,
                "Move a file.",
                extracted_entities=entities,
            )

        # Copy
        if self._matches(
            lower,
            (
                "copy",
                "duplicate",
                "make a copy of",
            ),
        ):
            return IntentResult(
                "file",
                "copy",
                0.80,
                False,
                "Copy a file.",
                extracted_entities=entities,
            )

        # Rename
        if self._matches(
            lower,
            (
                "rename",
                "change the name of",
                "call it",
            ),
        ):
            return IntentResult(
                "file",
                "rename",
                0.80,
                False,
                "Rename a file.",
                extracted_entities=entities,
            )

        # Generic file search
        if self._matches(
            lower,
            (
                "find all",
                "search for",
                "look for",
                "search",
                "list all",
                "show me all",
                "where are",
            ),
        ):
            return IntentResult(
                "file",
                "search",
                0.80,
                False,
                "Search for files.",
                extracted_entities=entities,
            )

        # List directory
        if self._matches(
            lower,
            (
                "what's on my",
                "whats on my",
                "list",
                "show me",
                "contents of",
                "what do i have in",
                "what's in",
            ),
        ):
            return IntentResult(
                "file",
                "list",
                0.80,
                False,
                "List directory contents.",
                extracted_entities=entities,
            )

        return None

    # ==================================================================
    # APPLICATIONS
    # ==================================================================

    def _infer_app_control(self, lower, context_text, entities):

        if self._matches(
            lower,
            (
                "open",
                "launch",
                "start",
                "run",
                "fire up",
                "bring up",
            ),
        ) and self._has_app_reference(lower):
            return IntentResult(
                "app",
                "open",
                0.85,
                False,
                "Open an application.",
                extracted_entities=entities,
            )

        if self._matches(
            lower,
            (
                "close",
                "quit",
                "exit",
                "shut down",
                "kill",
                "stop",
            ),
        ) and self._has_app_reference(lower):
            return IntentResult(
                "app",
                "close",
                0.85,
                False,
                "Close an application.",
                extracted_entities=entities,
            )

        if self._matches(
            lower,
            (
                "the application",
                "the app",
                "that app",
                "that application",
                "the program",
                "the one i just opened",
            ),
        ):
            if self._matches(
                lower,
                (
                    "close",
                    "quit",
                    "exit",
                    "shut down",
                ),
            ):
                return IntentResult(
                    "app",
                    "close",
                    0.80,
                    False,
                    "Close the referenced app.",
                    extracted_entities=entities,
                )

        return None

    # ==================================================================
    # EMAIL
    # ==================================================================

    def _infer_email(self, lower, context_text, entities):

        # Screen/tab/window commands should not become email commands.
        if any(
            word in lower
            for word in (
                "screen",
                "tab",
                "window",
                "click",
                "close",
                "minimize",
                "maximize",
                "scroll",
            )
        ):
            return None

        if self._matches(
            lower,
            (
                "email",
                "send an email",
                "write an email",
                "compose",
                "draft",
                "send a message",
                "write to",
                "message",
            ),
        ):
            return IntentResult(
                "email",
                "draft",
                0.85,
                False,
                "Draft an email.",
                extracted_entities=entities,
            )

        if (
            "email" in lower
            and any(
                verb in lower
                for verb in (
                    "tell",
                    "say",
                    "inform",
                    "let",
                )
            )
        ):
            return IntentResult(
                "email",
                "draft",
                0.85,
                False,
                "Draft an email with a message.",
                extracted_entities=entities,
            )

        if self._matches(
            lower,
            (
                "make sure",
                "let him know",
                "let her know",
                "tell them",
            ),
        ):
            return IntentResult(
                "email",
                "draft",
                0.75,
                False,
                "Communicate information.",
                extracted_entities=entities,
            )

        if self._matches(
            lower,
            (
                "reply to",
                "respond to",
                "answer",
            ),
        ):
            return IntentResult(
                "email",
                "reply",
                0.80,
                False,
                "Reply to an email.",
                extracted_entities=entities,
            )

        if self._matches(
            lower,
            (
                "check my email",
                "read my email",
                "any new emails",
                "email inbox",
                "do i have new emails",
            ),
        ):
            return IntentResult(
                "email",
                "check",
                0.85,
                False,
                "Check for new emails.",
                extracted_entities=entities,
            )

        return None

    # ==================================================================
    # DOCUMENTS
    # ==================================================================

    def _infer_document_ops(
        self,
        lower,
        context_text,
        entities,
    ):

        if self._matches(
            lower,
            (
                "summarize",
                "summary",
                "give me a summary",
                "sum up",
                "in short",
                "tldr",
                "brief overview",
                "summarize it",
                "summarize this",
                "and summarize",
            ),
        ):
            return IntentResult(
                "document",
                "summarize",
                0.85,
                False,
                "Summarize the document.",
                extracted_entities=entities,
            )

        if self._matches(
            lower,
            (
                "clean up",
                "fix the formatting",
                "format this",
                "make it look better",
                "tidy up",
                "fix formatting",
                "reformat",
            ),
        ):
            return IntentResult(
                "document",
                "clean_format",
                0.80,
                False,
                "Clean up document formatting.",
                extracted_entities=entities,
            )

        if self._matches(
            lower,
            (
                "turn these",
                "turn this",
                "convert this",
                "make this into",
                "transform",
            ),
        ):
            return IntentResult(
                "document",
                "restructure",
                0.75,
                False,
                "Restructure the document.",
                extracted_entities=entities,
            )

        if self._matches(
            lower,
            (
                "save the summary",
                "save a copy",
                "save it as",
                "create a new document",
                "save the result",
                "put that in a new",
            ),
        ):
            return IntentResult(
                "document",
                "create_from_result",
                0.80,
                False,
                "Save content to a new document.",
                extracted_entities=entities,
            )

        if self._matches(
            lower,
            (
                "fix the grammar",
                "grammar check",
                "rewrite",
                "make it professional",
                "polish this",
                "improve this",
                "edit this paragraph",
            ),
        ):
            return IntentResult(
                "document",
                "improve",
                0.80,
                False,
                "Improve the document.",
                extracted_entities=entities,
            )

        return None

    # ==================================================================
    # TERMINAL / CODE
    # ==================================================================

    def _infer_terminal(
        self,
        lower,
        context_text,
        entities,
    ):

        if self._matches(
            lower,
            (
                "open command prompt",
                "launch command prompt",
                "start command prompt",
            ),
        ):
            return None

        if self._matches(
            lower,
            (
                "run the command",
                "execute",
                "run this",
                "type this command",
                "in the terminal",
                "in terminal",
                "command prompt",
            ),
        ):
            return IntentResult(
                "terminal",
                "execute",
                0.80,
                False,
                "Run a terminal command.",
                extracted_entities=entities,
            )

        if self._matches(
            lower,
            (
                "what's wrong",
                "what is wrong",
                "why is it",
                "figure out why",
                "fix the bug",
                "fix the error",
                "debug",
                "find the problem",
                "throwing an error",
                "not working",
                "broken",
            ),
        ):
            return IntentResult(
                "code",
                "diagnose",
                0.80,
                False,
                "Diagnose a code problem.",
                extracted_entities=entities,
            )

        if self._matches(
            lower,
            (
                "run the tests",
                "run tests",
                "test this",
                "check if it works",
                "does it pass",
                "verify",
            ),
        ):
            return IntentResult(
                "code",
                "test",
                0.80,
                False,
                "Run tests on the project.",
                extracted_entities=entities,
            )

        return None

    # ==================================================================
    # ENTITY EXTRACTION
    # ==================================================================

    def _extract_entities(self, text, context_text):

        entities = {}

        # File references
        file_patterns = (
            r"\b(\w+(?:_\w+)*\.(?:pdf|docx?|txt|py|js|html|css|json|md|csv))\b",
            r"\b(my\s+\w+\s+(?:notes?|assignment|paper|essay|project|document))\b",
            r"\b(\w+\s+(?:notes?|assignment|paper|essay|project|document))\b",
        )

        for pattern in file_patterns:
            match = re.search(
                pattern,
                text,
                re.IGNORECASE,
            )

            if match:
                entities["file_reference"] = match.group(1)
                break

        # Subject
        subjects = (
            "physics",
            "chemistry",
            "math",
            "biology",
            "english",
            "history",
            "science",
            "computer",
            "programming",
            "python",
        )

        for subject in subjects:
            if subject in text:
                entities["subject"] = subject
                break

        # Person references
        person_patterns = (
            r"\b(my\s+(?:teacher|professor|instructor))\b",
            r"\b(to\s+(?:john|eva|sarah|mike|jane|mom|dad))\b",
            r"\b((?:mr|ms|dr|prof)\.?\s+\w+)\b",
        )

        for pattern in person_patterns:
            match = re.search(
                pattern,
                text,
                re.IGNORECASE,
            )

            if match:
                entities["person"] = match.group(1)
                break

        # Action verb
        action_verbs = (
            "open",
            "close",
            "read",
            "write",
            "create",
            "delete",
            "move",
            "copy",
            "rename",
            "search",
            "find",
            "summarize",
            "fix",
            "send",
            "play",
            "start",
        )

        for verb in action_verbs:
            if re.search(
                rf"\b{re.escape(verb)}\b",
                text,
            ):
                entities["action_verb"] = verb
                break

        # Time references
        time_refs = (
            "yesterday",
            "today",
            "last night",
            "last week",
            "last month",
            "recently",
            "just now",
            "earlier",
            "this morning",
        )

        for ref in time_refs:
            if ref in text:
                entities["time_reference"] = ref
                break

        return entities

    # ==================================================================
    # SCREEN HELPERS
    # ==================================================================

    def _matches(self, text, phrases):
        return any(
            re.search(
                rf"\b{re.escape(phrase)}\b",
                text,
            )
            for phrase in phrases
        )

    def _asks_active_application(self, lower: str) -> bool:

        if any(
            phrase in lower
            for phrase in (
                "what application",
                "which application",
                "what app",
                "which app",
                "what program",
                "which program",
                "what window",
                "which window",
                "active window",
                "current window",
                "current application",
                "current app",
                "application am i using",
                "app am i using",
                "program am i using",
                "window am i using",
                "window is open",
                "window is active",
                "application is open",
                "application is active",
                "app is open",
                "app is active",
                "what's open",
                "whats open",
            )
        ):
            return True

        if re.search(
            r"\b(is|are)\s+.+?\s+(active|open|running|the active)\b",
            lower,
        ):
            return True

        return False

    def _asks_screen_content(self, lower: str) -> bool:
        if self._detect_control_action(lower):
            return False

        explicit = (
            "what do you see",
            "what am i looking at",
            "what is displayed",
            "what's displayed",
            "whats displayed",
            "read the screen",
            "describe my screen",
            "describe the screen",
            "check my screen",
            "look at my screen",
            "look at the screen",
            "see my screen",
            "see the screen",
            "what is currently open",
            "what's currently open",
            "whats currently open",
            "what's on my screen",
            "whats on my screen",
            "what is on my screen",
            "what is on the screen",
            "what's on the screen",
            "whats on the screen",
            "what is on screen",
            "what's on screen",
            "whats on screen",
            "what's this",
            "what is this",
            "do you see",
            "can you see",
            "do you see the",
            "can you see the",
            "read this page",
            "read this screen",
            "read the page",
            "what does this page say",
            "what does the page say",
            "what does this say",
            "what does that say",
            "can you read this",
            "can you read that",
            "search this page",
            "search the page",
            "search this screen",
            "find on this page",
            "find on the page",
            "find on this screen",
        )

        if any(
            phrase in lower
            for phrase in explicit
        ):
            return True

        has_screen = any(
            word in lower
            for word in (
                "screen",
                "monitor",
                "display",
                "page",
                "tab",
            )
        )

        if not has_screen:
            return False

        if any(
            word in lower
            for word in (
                "document",
                "file",
                "folder",
                "formatting",
                "code",
                "pdf",
                "screenshot of the folder",
            )
        ):
            return False

        return any(
            word in lower
            for word in (
                "what",
                "see",
                "look",
                "read",
                "describe",
                "show",
                "tell me",
                "displayed",
                "check",
            )
        )

    def _detect_control_action(self, lower: str):

        # --------------------------------------------------------------
        # Browser tab / window management
        # --------------------------------------------------------------

        # Close the current tab.
        if (
            re.search(
                r"\b(close|shut|kill)\b.{0,30}"
                r"\b(tab|page|browser tab|this page|current page)\b",
                lower,
            )
            or re.fullmatch(
                r"(jarvis[, ]+)?(please )?"
                r"(close|shut) (this|the|current) (tab|page)\.?",
                lower.strip(),
            )
        ):
            return ("close_tab", "")

        # Move to the next tab.
        if re.search(
            r"^(?:jarvis[, ]+)?(?:please )?"
            r"(?:next|switch to the next|go to the next|move to the next|"
            r"take me to the next|show me the next)\s+(?:browser )?tab\b",
            lower,
        ) or re.search(
            r"\b(?:next tab|next browser tab)\b",
            lower,
        ):
            return ("next_tab", "")

        # Move to the previous tab.
        if re.search(
            r"^(?:jarvis[, ]+)?(?:please )?"
            r"(?:previous|prev|back to the previous|go to the previous|"
            r"move to the previous|take me to the previous|"
            r"show me the previous)\s+(?:browser )?tab\b",
            lower,
        ) or re.search(
            r"\b(?:previous tab|prev tab|previous browser tab)\b",
            lower,
        ):
            return ("previous_tab", "")

        # Move one tab left/right.
        if re.search(
            r"\b(?:tab )?(?:to the )?(left|right)\b",
            lower,
        ) and re.search(r"\b(?:tab|move|switch|go)\b", lower):
            if "left" in lower:
                return ("previous_tab", "")
            return ("next_tab", "")

        # Minimize / maximize the current application window.
        if re.search(
            r"\b(minimize|hide)\b.{0,20}\b(window|app|application|chrome|browser)\b",
            lower,
        ) or re.fullmatch(r"(jarvis[, ]+)?(?:please )?minimize(?: it| this)?\.?", lower.strip()):
            return ("minimize", "")

        if (
            "maximize" in lower
            or "full screen" in lower
            or "fullscreen" in lower
            or re.search(r"\bmake\b.{0,12}\b(full screen|fullscreen)\b", lower)
        ):
            return ("maximize", "")

        # --------------------------------------------------------------
        # Switch/focus an existing application OR browser tab.
        #
        # Accept natural forms such as:
        #   switch to Instagram
        #   switch to the Instagram tab
        #   go to TikTok
        #   focus on YouTube
        #   bring up my WhatsApp tab
        #   take me to the GitHub tab
        #   put me on Instagram
        #   jump to Chrome
        # --------------------------------------------------------------
        switch = re.search(
            r"\b(?:switch(?:\s+over)?(?:\s+to)?|switch onto|focus on|"
            r"bring (?:up|forward)|go to|take me to|"
            r"put me on|jump to|move to|change to|"
            r"show me|pull up)\s+"
            r"(?:the |my |this )?"
            r"(.+?)"
            r"(?:\s+(?:browser )?tab|\s+page)?\s*$",
            lower,
        )

        if switch:
            target = switch.group(1).strip(" .,?!")
            target = re.sub(
                r"\s+(?:browser )?tab\s*$",
                "",
                target,
                flags=re.IGNORECASE,
            ).strip(" .,?!")

            if target and self._has_app_reference(target):
                from tools.browser import resolve_site
                is_site = bool(resolve_site(target))
                has_tab_mention = bool(re.search(r"\b(?:tab|page|window)\b", lower))
                if is_site and not has_tab_mention and any(v in lower for v in ("take me to", "go to", "visit", "navigate to", "open")):
                    pass
                else:
                    return ("switch", target)

        # Generic tab switching phrasing without a named destination.
        if re.search(
            r"^(?:jarvis[, ]+)?(?:please )?"
            r"(?:switch|change|move|go)\s+(?:over )?(?:to )?"
            r"(?:the )?(?:browser )?tab\b",
            lower,
        ):
            return ("next_tab", "")

        # --------------------------------------------------------------
        # Physical input
        # --------------------------------------------------------------
        # Avoid turning file-writing commands into screen controls.
        file_write_match = re.search(
            r"\b(write|create|make|draft)\s+"
            r"(a|an|the|my)?\s*"
            r"(essay|report|letter|document|notes?|plan|"
            r"time\s*table|schedule|study\s*(plan|table|schedule)|"
            r"summary|outline|list|story|poem|article)\s+"
            r"(on|about|for|regarding)\s+(.+?)"
            r"(?:\s+(?:and\s+)?"
            r"(?:save|store|keep)\s*(?:it)?"
            r"(?:\s+(?:in|to|into)\s+"
            r"(?:notepad|file|a\s+file))?)?$",
            lower,
        )

        if file_write_match:
            return None

        for verb in (
            "double click",
            "right click",
            "click",
            "press",
            "type",
            "write",
            "scroll",
            "move",
        ):
            match = re.search(
                rf"\b{re.escape(verb)}\b(.*)",
                lower,
            )

            if not match:
                continue

            target = match.group(1).strip(" .,?!")
            target = re.sub(
                r"^(the|a|an|my|on|at|to|in)\s+",
                "",
                target,
            )
            target = re.sub(
                r"\s+(on|from|in|into)\s+(the\s+|my\s+)?(screen|display|monitor)\b.*$",
                "",
                target,
                flags=re.IGNORECASE,
            ).strip(" .,?!")

            if verb in ("type", "write"):
                target = re.sub(
                    r"\s+(in|into)\s+"
                    r"(notepad|it|the\s+notepad)$",
                    "",
                    target,
                )

            if verb == "move" and re.fullmatch(
                r"(the )?mouse",
                target or "",
            ):
                target = ""

            return (verb.replace(" ", "_"), target)

        return None

    # ==================================================================
    # WEB SEARCH
    # ==================================================================

    def _is_explicit_web_search(
        self,
        lower: str,
    ) -> bool:

        if self._matches(
            lower,
            (
                "where did you",
                "where did i",
                "how did you",
                "did you find",
                "did you locate",
            ),
        ):
            return False

        if re.search(
            r"\b(search|look up|google|find)\b"
            r"[^.]*\b(web|internet|online)\b",
            lower,
        ):
            return True

        if re.search(
            r"\b(google|bing|duckduckgo)\b",
            lower,
        ):
            if re.search(
                r"\b(is|are)\s+.+?\s+"
                r"(active|open|running)\b",
                lower,
            ):
                return False

            return True

        if (
            re.search(
                r"\b(search|look up|find)\b\s+"
                r"(?:for\s+|about\s+)?\S+",
                lower,
            )
            and re.search(
                r"\b(news|weather|price|score|"
                r"documentation|latest|current|today)\b",
                lower,
            )
        ):
            return True

        return False

    # ==================================================================
    # GENERAL HELPERS
    # ==================================================================

    def _is_question(self, text):
        return (
            "?" in text
            or bool(
                re.match(
                    r"^(why|what|how|when|where|"
                    r"can you tell me|could you explain|"
                    r"is|are|does|do)\b",
                    text,
                )
            )
        )

    def _has_file_reference(
        self,
        text,
        context,
    ):
        file_indicators = (
            ".pdf",
            ".doc",
            ".txt",
            ".py",
            ".js",
            ".html",
            ".md",
            ".csv",
            ".json",
            "notes",
            "assignment",
            "paper",
            "essay",
            "document",
            "file",
            "presentation",
            "the one",
            "that file",
            "homework",
            "project",
            "report",
            "folder",
            "directory",
            "downloads",
            "desktop",
            "documents",
            "pictures",
            "videos",
            "music folder",
        )

        return any(
            indicator in text
            or indicator in context
            for indicator in file_indicators
        )

    def _extract_file_reference(
        self,
        lower,
        context_text,
    ):
        """Extract a file reference from a read command."""

        match = re.search(
            r"\b(?:read|open|show me|what's in|"
            r"what is in)\s+"
            r"(?:the\s+)?(?:file\s+)?"
            r"['\"]?([^\s'\"]+\.\w{2,5})['\"]?",
            lower,
        )

        if match:
            return match.group(1)

        match = re.search(
            r"([A-Za-z]:\\(?:[^\\/:*?\"<>|\r\n]+\\)*"
            r"[^\\/:*?\"<>|\r\n]*)",
            lower,
        )

        if match:
            return match.group(1)

        match = re.search(
            r"(?:first|1st)\s+file\s+"
            r"(?:in|of)\s+(?:my\s+)?"
            r"(downloads|documents|desktop)",
            lower,
        )

        if match:
            return f"__first_in_{match.group(1)}__"

        if (
            "the file i just created" in lower
            or "the file i just made" in lower
        ):
            return "__last_created__"

        match = re.search(
            r"\b(?:read|open)\s+"
            r"(?:the\s+)?(?:file\s+)?"
            r"['\"]?([a-z0-9_\-]+)['\"]?",
            lower,
        )

        if match:
            return match.group(1)

        return ""

    def _extract_filename_from_create(
        self,
        lower,
    ):
        match = re.search(
            r"(?:create|make)\s+"
            r"(?:a\s+)?"
            r"(?:notepad\s+|text\s+)?"
            r"file\s+"
            r"(?:named|called)\s+"
            r"['\"]?([a-z0-9_\-\.]+)['\"]?",
            lower,
        )

        if match:
            return match.group(1)

        match = re.search(
            r"(?:create|make)\s+"
            r"(?:a\s+)?"
            r"([a-z0-9_\-\.]+\.\w{2,5})",
            lower,
        )

        if match:
            return match.group(1)

        return ""

    def _has_app_reference(
        self,
        text,
    ):
        app_indicators = (
            # Desktop applications
            "notepad",
            "calculator",
            "paint",
            "browser",
            "chrome",
            "firefox",
            "edge",
            "spotify",
            "vscode",
            "visual studio code",
            "code",
            "terminal",
            "word",
            "excel",
            "powerpoint",
            "discord",
            "steam",
            "zoom",
            "slack",
            "whatsapp",
            "telegram",
            "app",
            "application",
            "program",
            "explorer",
            "settings",
            "command prompt",
            "cmd",
            "powershell",

            # Common browser destinations that can also be existing tabs.
            "github",
            "gitlab",
            "bitbucket",
            "youtube",
            "youtube music",
            "spotify",
            "google",
            "google maps",
            "google drive",
            "google docs",
            "google sheets",
            "google slides",
            "google meet",
            "gmail",
            "google classroom",
            "chatgpt",
            "chat gpt",
            "openai",
            "claude",
            "gemini",
            "copilot",
            "perplexity",
            "deepseek",
            "hugging face",
            "huggingface",
            "stackoverflow",
            "stack overflow",
            "reddit",
            "wikipedia",
            "quora",
            "instagram",
            "facebook",
            "whatsapp",
            "linkedin",
            "tiktok",
            "tik tok",
            "twitter",
            "x",
            "threads",
            "telegram",
            "discord",
            "snapchat",
            "pinterest",
            "netflix",
            "prime video",
            "amazon",
            "twitch",
            "steam",
            "notion",
            "canva",
            "dropbox",
            "onedrive",
            "slack",
            "zoom",
            "trello",
            "npm",
            "pypi",
            "replit",
            "codepen",
            "leetcode",
            "geeksforgeeks",
            "w3schools",
            "coursera",
            "udemy",
            "khan academy",
            "duolingo",
            "ebay",
        )

        return any(
            indicator in text
            for indicator in app_indicators
        )



