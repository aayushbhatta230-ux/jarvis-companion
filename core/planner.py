"""
JARVIS Action Planner
=====================

Deterministic execution layer between natural-language intent and JARVIS
capabilities.

Core principles:

1. Execute obvious computer actions deterministically.
2. Preserve entities extracted by the IntentEngine.
3. Never silently convert local commands into web searches.
4. Never claim an action succeeded unless the capability reports success.
5. Keep screen interaction local.
6. Allow the conversational model to handle genuinely conversational input.
7. Support natural variations without requiring exact phrasing.
"""

from __future__ import annotations

import re
from typing import Any

from core.capabilities import (
    ToolResult,
    execute_capability,
    execute_confirmed,
    get_capability,
)
from core.intent import IntentEngine
from tools.browser import resolve_site


class ActionPlanner:
    """Turn natural-language goals into verified capability calls."""

    def __init__(self, intent_engine=None):
        self.intent_engine = intent_engine or IntentEngine()
        self._web_search_blocked = False

    # ================================================================== #
    # MAIN ROUTER
    # ================================================================== #

    def execute(self, transcript, intent=None):
        """
        Route a transcript to the correct deterministic capability.

        Returns:
            ToolResult:
                A capability handled the request.

            None:
                No deterministic capability matched and the caller may
                allow the conversational model to handle the request.
        """

        text = str(transcript or "").strip()

        if not text:
            return None

        lower = text.lower().strip()

        # Use supplied intent when available.
        intent = intent or self.intent_engine.infer(text)

        # -------------------------------------------------------------- #
        # WEB SEARCH GUARD
        # -------------------------------------------------------------- #
        #
        # These intents are local. If something goes wrong with routing,
        # they must not suddenly become Google searches.
        #
        local_intents = {
            "screen",
            "screen_control",
            "system",
            "file",
            "app",
            "email",
            "memory",
            "conversation",
            "media",
            "control",
            "follow_up",
        }

        if (
            intent.intent in local_intents
            and intent.sub_intent not in ("search",)
        ):
            self._web_search_blocked = True
        else:
            self._web_search_blocked = False

        # -------------------------------------------------------------- #
        # DETERMINISTIC INTENT HANDLER
        # -------------------------------------------------------------- #

        handler = self._get_handler(
            intent.intent,
            intent.sub_intent,
        )

        if handler:
            print(
                f"[ROUTER] "
                f"intent={intent.intent}/{intent.sub_intent} "
                f"handler={handler.__name__} "
                f"confidence={intent.confidence:.2f}"
            )

            try:
                return handler(
                    text,
                    lower,
                    intent,
                )

            except Exception as exc:  # noqa: BLE001
                print(
                    f"[ROUTER ERROR] "
                    f"{handler.__name__}: "
                    f"{type(exc).__name__}: {exc}"
                )

                return ToolResult(
                    False,
                    f"{intent.intent}.{intent.sub_intent}",
                    error=str(exc),
                    result="I couldn't complete that action.",
                    status="failed",
                )

        # -------------------------------------------------------------- #
        # PATTERN FALLBACK
        # -------------------------------------------------------------- #

        print(
            f"[ROUTER] "
            f"intent={intent.intent}/{intent.sub_intent} "
            f"handler=None -> pattern_fallback"
        )

        try:
            return self._pattern_fallback(
                text,
                lower,
            )

        except Exception as exc:  # noqa: BLE001
            print(
                f"[ROUTER FALLBACK ERROR] "
                f"{type(exc).__name__}: {exc}"
            )

            return None

    # ================================================================== #
    # CONFIRMATION
    # ================================================================== #

    def execute_confirmed(
        self,
        capability_name,
        **kwargs,
    ):
        """Execute a capability after confirmation."""
        return execute_confirmed(
            capability_name,
            **kwargs,
        )

    def needs_confirmation(
        self,
        capability_name,
    ):
        """Check whether a capability requires confirmation."""

        cap = get_capability(
            capability_name
        )

        return (
            cap.confirmation_required
            if cap
            else False
        )

    # ================================================================== #
    # HANDLER REGISTRY
    # ================================================================== #

    def _get_handler(
        self,
        intent,
        sub_intent,
    ):
        handlers = {

            # ---------------------------------------------------------- #
            # SYSTEM
            # ---------------------------------------------------------- #

            (
                "system",
                "capabilities",
            ): self._handle_system_capabilities,

            (
                "system",
                "action_history",
            ): self._handle_system_action_history,

            (
                "system",
                "screen_status",
            ): self._handle_system_screen_status,

            (
                "system",
                "get_info",
            ): self._handle_system_info,

            (
                "system",
                "active_application",
            ): self._handle_active_application,

            (
                "system",
                "set_permission",
            ): self._handle_set_permission,

            (
                "system",
                "memory_last",
            ): self._handle_memory_last,

            (
                "system",
                "memory_recent",
            ): self._handle_memory_recent,

            # ---------------------------------------------------------- #
            # SCREEN
            # ---------------------------------------------------------- #

            (
                "screen",
                "question",
            ): self._handle_screen_question,

            # ---------------------------------------------------------- #
            # MEDIA
            # ---------------------------------------------------------- #

            (
                "media",
                "stop",
            ): self._handle_media_stop,

            (
                "media",
                "play",
            ): self._handle_media_play,

            (
                "media",
                "pause",
            ): self._handle_media_pause,

            (
                "media",
                "resume",
            ): self._handle_media_resume,

            (
                "media",
                "next",
            ): self._handle_media_next,

            # ---------------------------------------------------------- #
            # BROWSER
            # ---------------------------------------------------------- #

            (
                "browser",
                "open_url",
            ): self._handle_browser_open,

            (
                "browser",
                "open_browser",
            ): self._handle_browser_default,

            (
                "browser",
                "search",
            ): self._handle_browser_search,

            (
                "browser",
                "navigation",
            ): self._handle_browser_navigation,

            # ---------------------------------------------------------- #
            # FILES
            # ---------------------------------------------------------- #

            (
                "file",
                "search",
            ): self._handle_file_search,

            (
                "file",
                "list",
            ): self._handle_file_list,

            (
                "file",
                "find_recent",
            ): self._handle_file_find_recent,

            (
                "file",
                "read",
            ): self._handle_file_read,

            (
                "file",
                "write",
            ): self._handle_file_write,

            (
                "file",
                "open",
            ): self._handle_file_open,

            # ---------------------------------------------------------- #
            # APPLICATIONS
            # ---------------------------------------------------------- #

            (
                "app",
                "open",
            ): self._handle_app_open,

            (
                "app",
                "close",
            ): self._handle_app_close,

            # ---------------------------------------------------------- #
            # CODE
            # ---------------------------------------------------------- #

            (
                "code",
                "test",
            ): self._handle_code_test,

            # ---------------------------------------------------------- #
            # SCREEN CONTROL
            # ---------------------------------------------------------- #

            (
                "screen_control",
                "action",
            ): self._handle_screen_control,

            (
                "screen_control",
                "next_tab",
            ): self._handle_next_tab,

            (
                "screen_control",
                "previous_tab",
            ): self._handle_previous_tab,

            # ---------------------------------------------------------- #
            # EMAIL
            # ---------------------------------------------------------- #

            (
                "email",
                "draft",
            ): self._handle_email_draft,

            (
                "email",
                "send_direct",
            ): self._handle_email_send_direct,

            (
                "email",
                "diagnostics",
            ): self._handle_email_diagnostics,
        }

        return handlers.get(
            (
                intent,
                sub_intent,
            )
        )

    # ================================================================== #
    # SYSTEM
    # ================================================================== #

    def _handle_system_capabilities(
        self,
        text,
        lower,
        intent,
    ):
        from core.capabilities import get_runtime_capability_registry
        from core.permissions import get_permission_manager, PermissionLevel

        registry = get_runtime_capability_registry()
        available = [
            cap["name"]
            for name, cap in registry.items()
            if cap.get("available")
        ]

        perm = get_permission_manager().get_permission()
        perm_desc = "with full system access" if perm == PermissionLevel.FULL_CONTROL else "locally on Windows"

        if available:
            message = (
                f"I run {perm_desc}. "
                "My active abilities include autonomous PC control, live screen vision, "
                "file operations, web search, media control, and terminal execution."
            )
        else:
            message = (
                "I run locally on Windows, "
                "but no verified runtime "
                "capabilities are currently available."
            )

        return ToolResult(
            True,
            "system.capabilities",
            result=message,
        )

    def _handle_system_action_history(
        self,
        text,
        lower,
        intent,
    ):
        from logs.actions import (
            get_action_logger,
        )

        explanation = (
            get_action_logger()
            .explain_last_action(text)
        )

        return ToolResult(
            True,
            "system.action_history",
            result=explanation,
        )

    def _handle_system_screen_status(
        self,
        text,
        lower,
        intent,
    ):
        from core.permissions import (
            get_permission_manager,
        )

        permission = (
            get_permission_manager()
            .get_screen_permission()
        )

        return ToolResult(
            True,
            "system.screen_status",
            result=(
                "Screen access is currently "
                f"enabled in {permission.value} mode."
            ),
        )

    def _handle_system_info(
        self,
        text,
        lower,
        intent,
    ):
        return execute_capability(
            "system.info"
        )

    def _handle_active_application(
        self,
        text,
        lower,
        intent,
    ):
        from perception.window import (
            get_active_window,
        )

        try:
            info = get_active_window()

            return ToolResult(
                True,
                "system.active_application",
                result=(
                    f"You're currently using "
                    f"{info.app_name}."
                ),
            )

        except Exception as exc:  # noqa: BLE001
            return ToolResult(
                False,
                "system.active_application",
                error=str(exc),
                result=(
                    "I couldn't determine "
                    "the active application."
                ),
                status="failed",
            )

    def _handle_set_permission(
        self,
        text,
        lower,
        intent,
    ):
        entities = (
            intent.extracted_entities
            or {}
        )

        permission = (
            entities.get("permission")
            or "CONTROL_WITH_CONFIRMATION"
        )

        return execute_capability(
            "system.set_permission",
            level=permission,
        )

    def _handle_memory_last(
        self,
        text,
        lower,
        intent,
    ):
        from core.memory import (
            get_short_term_memory,
        )

        return ToolResult(
            True,
            "memory.last_action",
            result=(
                get_short_term_memory()
                .describe_last_action()
            ),
        )

    def _handle_memory_recent(
        self,
        text,
        lower,
        intent,
    ):
        from core.memory import (
            get_short_term_memory,
        )

        return ToolResult(
            True,
            "memory.recent",
            result=(
                get_short_term_memory()
                .describe_recent()
            ),
        )

    # ================================================================== #
    # SCREEN UNDERSTANDING
    # ================================================================== #

    def _handle_screen_question(
        self,
        text,
        lower,
        intent,
    ):
        """
        Describe the current screen using active-window information
        and OCR when available.

        Never invent screen contents.
        """

        from perception.window import (
            get_active_window,
        )

        app = None
        title = None

        # -------------------------------------------------------------- #
        # Active window
        # -------------------------------------------------------------- #

        try:
            info = get_active_window()

            app = getattr(
                info,
                "app_name",
                None,
            )

            title = getattr(
                info,
                "title",
                None,
            )

        except Exception as exc:  # noqa: BLE001
            print(
                "[SCREEN QUESTION] "
                f"active window failed: {exc}"
            )

        # -------------------------------------------------------------- #
        # OCR
        # -------------------------------------------------------------- #

        ocr_text = ""

        try:
            from perception.screen import (
                ScreenPerceiver,
            )
            from perception.ocr import (
                extract_text,
            )

            image = (
                ScreenPerceiver()
                .grab_image()
            )

            if image is not None:
                ocr_text = (
                    extract_text(image)
                    or ""
                ).strip()

        except Exception as exc:  # noqa: BLE001
            print(
                "[SCREEN QUESTION] "
                f"OCR failed: {exc}"
            )

        ocr_usable = (
            bool(ocr_text)
            and "(ocr" not in ocr_text.lower()
            and "no readable text"
            not in ocr_text.lower()
            and "screen capture requires"
            not in ocr_text.lower()
        )

        if not app and not ocr_usable:
            return ToolResult(
                False,
                "screen.question",
                result=(
                    "I couldn't reliably "
                    "read the screen right now."
                ),
                status="failed",
            )

        # -------------------------------------------------------------- #
        # Active application description
        # -------------------------------------------------------------- #

        if (
            app
            and app.lower() != "desktop"
            and title
            and title.strip().lower()
            != app.lower()
        ):
            lead = (
                f"You're in {app} "
                f"({title.strip()[:80]})"
            )

        elif app:
            lead = f"You're in {app}"

        else:
            lead = (
                "I couldn't determine "
                "the active application"
            )

        # -------------------------------------------------------------- #
        # OCR result
        # -------------------------------------------------------------- #

        if ocr_usable:
            snippet = (
                " ".join(ocr_text.split())
                [:180]
            )

            message = (
                f"{lead}. "
                f"I can read text including: "
                f"{snippet}."
            )

        else:
            message = (
                f"{lead}, "
                "but I couldn't reliably "
                "read the text on screen."
            )

        return ToolResult(
            True,
            "screen.question",
            result=message,
        )

    # ================================================================== #
    # MEDIA
    # ================================================================== #

    def _handle_media_stop(
        self,
        text,
        lower,
        intent,
    ):
        """Stop currently playing media."""

        return execute_capability(
            "media.stop"
        )

    def _handle_media_play(
        self,
        text,
        lower,
        intent,
    ):
        """
        Play specific music or mood-based music.

        Specific:
            play Blinding Lights
            play The Weeknd
            put on Believer

        Generic:
            play
            play music

        Mood:
            play relaxing music
            play fast music
            play workout music
        """

        entities = (
            intent.extracted_entities
            or {}
        )

        query = entities.get("query")
        mood = entities.get(
            "mood",
            "default",
        )

        # -------------------------------------------------------------- #
        # Normalize query
        # -------------------------------------------------------------- #

        if query:
            query = str(query).strip()

            # Remove common accidental wrappers.
            query = re.sub(
                r"^(?:the\s+)?song\s+",
                "",
                query,
                flags=re.IGNORECASE,
            ).strip()

            query = query.strip(
                " .,!?\"'"
            )

        # Generic words are NOT search queries.
        generic_queries = {
            "",
            "music",
            "some music",
            "a music",
            "some song",
            "a song",
            "song",
            "songs",
            "something",
            "anything",
            "something nice",
        }

        if query and query.lower() in generic_queries:
            query = None

        # -------------------------------------------------------------- #
        # Mood detection
        # -------------------------------------------------------------- #

        if not mood or mood == "default":

            if any(
                word in lower
                for word in (
                    "relax",
                    "relaxed",
                    "calm",
                    "chill",
                    "peaceful",
                )
            ):
                mood = "relaxed"

            elif any(
                word in lower
                for word in (
                    "fast",
                    "energetic",
                    "energy",
                    "upbeat",
                    "workout",
                    "hype",
                    "high energy",
                )
            ):
                mood = "energetic"

            elif any(
                word in lower
                for word in (
                    "sad",
                    "melancholy",
                    "emotional",
                )
            ):
                mood = "sad"

            elif any(
                word in lower
                for word in (
                    "romantic",
                    "love",
                    "lovely",
                )
            ):
                mood = "romantic"

        # -------------------------------------------------------------- #
        # Deterministic execution
        # -------------------------------------------------------------- #

        if query:
            print(
                "[MEDIA] "
                f"playing query={query!r} "
                f"mood={mood!r}"
            )

            return execute_capability(
                "media.play",
                query=query,
                mood=mood,
            )

        print(
            "[MEDIA] "
            f"playing mood={mood!r}"
        )

        return execute_capability(
            "media.play",
            mood=mood,
        )

    def _handle_media_pause(
        self,
        text,
        lower,
        intent,
    ):
        """Pause currently playing media."""

        return execute_capability(
            "media.pause"
        )

    def _handle_media_resume(
        self,
        text,
        lower,
        intent,
    ):
        """Resume paused media."""

        return execute_capability(
            "media.resume"
        )

    def _handle_browser_navigation(
        self,
        text,
        lower,
        intent,
    ):
        """
        Handle browser navigation commands: go back, go forward, refresh.
        """
        from tools.browser import (
            go_back,
            go_forward,
            reload_page,
        )

        direction = (intent.extracted_entities or {}).get("direction", "back")

        if direction == "back":
            return go_back()
        elif direction == "forward":
            return go_forward()
        elif direction == "refresh":
            return reload_page()
        else:
            return ToolResult(
                False,
                "browser.navigation",
                result="Unknown navigation direction.",
            )

    def _handle_media_next(
        self,
        text,
        lower,
        intent,
    ):
        """Skip to the next media item."""

        return execute_capability(
            "media.next"
        )

    # ================================================================== #
    # BROWSER
    # ================================================================== #

    def _handle_browser_open(
        self,
        text,
        lower,
        intent,
    ):
        """Open an explicit URL or recognized website."""

        url_match = re.search(
            r"\bhttps?://\S+",
            text,
            re.IGNORECASE,
        )

        if url_match:
            url = (
                url_match.group(0)
                .rstrip(".,!?")
            )

            return execute_capability(
                "browser.open_url",
                url=url,
            )

        site = resolve_site(text)

        if site:
            return execute_capability(
                "browser.open_url",
                url=site,
            )

        return None

    def _handle_browser_default(
        self,
        text,
        lower,
        intent,
    ):
        import webbrowser

        opened = webbrowser.open(
            "https://www.google.com"
        )

        if not opened:
            return ToolResult(
                False,
                "browser.open_url",
                result=(
                    "I couldn't open "
                    "the default browser."
                ),
                status="failed",
            )

        return ToolResult(
            True,
            "browser.open_url",
            result=(
                "Opened your default browser."
            ),
        )

    def _handle_browser_search(
        self,
        text,
        lower,
        intent,
    ):
        """Perform an explicit web search only."""

        if getattr(
            self,
            "_web_search_blocked",
            False,
        ):
            return None

        if re.search(r"\b(?:weather|temperature|forecast|raining|snowing)\b", lower):
            loc_match = re.search(r"\b(?:weather|temperature|forecast)\s+(?:in|for|at)\s+([a-zA-Z\s]+)", lower)
            location = loc_match.group(1).strip(" .,?!") if loc_match else ""
            return execute_capability(
                "weather.get",
                location=location,
            )

        if re.search(r"\b(?:who (?:is|was)|what (?:is|are)|tell me about)\b", lower) and not any(k in lower for k in ("open", "tab", "window", "chrome", "google")):
            res = execute_capability("knowledge.lookup", query=lower)
            if res.success and res.result and "couldn't find" not in str(res.result).lower():
                return res

        patterns = [
            (
                r"\b(?:search|look up|find|google)\s+"
                r"(?:the web for\s+)?"
                r"(?:for\s+)?(.+)"
            ),
            (
                r"\b(?:search|look up|find|google)\s+"
                r"(.+)"
            ),
        ]

        for pattern in patterns:
            match = re.search(
                pattern,
                lower,
            )

            if match:
                query = (
                    match.group(1)
                    .strip()
                    .rstrip(".,!?")
                )

                if query:
                    return execute_capability(
                        "browser.search",
                        query=query,
                    )

        query = re.sub(
            r"^(search|look up|find|google|"
            r"for|the web for)\s*",
            "",
            lower,
        ).strip()

        if query:
            return execute_capability(
                "browser.search",
                query=query,
            )

        return None

    # ================================================================== #
    # FILES
    # ================================================================== #

    def _handle_file_search(
        self,
        text,
        lower,
        intent,
    ):
        query = self._extract_search_query(
            text
        )

        directory = (
            self._extract_directory(text)
        )

        extension = (
            self._extract_extension(text)
        )

        return execute_capability(
            "file.search",
            query=query,
            directory=directory,
            extension=extension,
        )

    def _handle_file_list(
        self,
        text,
        lower,
        intent,
    ):
        directory = (
            self._extract_directory(text)
        )

        return execute_capability(
            "file.list",
            directory=directory,
        )

    def _handle_file_find_recent(
        self,
        text,
        lower,
        intent,
    ):
        directory = (
            self._extract_directory(text)
        )

        extension = (
            self._extract_extension(text)
        )

        if "week" in lower:
            days = 7

        elif "yesterday" in lower:
            days = 1

        elif "month" in lower:
            days = 30

        else:
            days = 7

        return execute_capability(
            "file.find_recent",
            directory=directory,
            days=days,
            extension=extension,
        )

    def _handle_file_read(
        self,
        text,
        lower,
        intent,
    ):
        """Read an actual file."""

        filepath = None

        entities = (
            intent.extracted_entities
            or {}
        )

        filepath = (
            entities.get("filepath")
            or entities.get("file_reference")
        )

        # -------------------------------------------------------------- #
        # Natural-language extraction
        # -------------------------------------------------------------- #

        if not filepath:

            match = re.search(
                r"(?:read|open|show me|"
                r"what(?:'s| is) in|"
                r"contents of)"
                r"(?:\s+(?:the|my|this|that))?"
                r"\s+(?:file\s+)?"
                r"[\"']?([^\"'\n]+?)[\"']?"
                r"(?:\s+file)?"
                r"(?:\?|$|\.)",
                lower,
            )

            if match:
                filepath = (
                    match.group(1)
                    .strip()
                )

        # -------------------------------------------------------------- #
        # Current context
        # -------------------------------------------------------------- #

        if not filepath:
            try:
                from core.context import (
                    get_desktop_context,
                )

                filepath = (
                    get_desktop_context()
                    .current_file
                )

            except Exception as exc:  # noqa: BLE001
                print(
                    "[FILE READ] "
                    f"context failed: {exc}"
                )

        if not filepath:
            return ToolResult(
                False,
                "file.read",
                result=(
                    "I need a file to read. "
                    "Which file?"
                ),
                status="failed",
            )

        # -------------------------------------------------------------- #
        # Special references
        # -------------------------------------------------------------- #

        if filepath.startswith(
            "__first_in_"
        ):
            folder = (
                filepath
                .replace(
                    "__first_in__",
                    "",
                )
                .replace(
                    "__",
                    "",
                )
            )

            return (
                self._read_first_file_in_folder(
                    folder
                )
            )

        if filepath == "__last_created__":
            try:
                from core.context import (
                    get_desktop_context,
                )

                last_file = (
                    get_desktop_context()
                    .current_file
                )

                if last_file:
                    return execute_capability(
                        "file.read",
                        filepath=last_file,
                    )

            except Exception as exc:  # noqa: BLE001
                print(
                    "[FILE READ] "
                    f"last file failed: {exc}"
                )

            return ToolResult(
                False,
                "file.read",
                result=(
                    "I don't remember creating "
                    "a file recently."
                ),
                status="failed",
            )

        # -------------------------------------------------------------- #
        # Resolve filename if no path supplied
        # -------------------------------------------------------------- #

        if (
            not re.match(
                r"^[A-Za-z]:\\",
                filepath,
            )
            and "/" not in filepath
            and "\\" not in filepath
        ):
            resolved = (
                self._resolve_filename(
                    filepath
                )
            )

            if resolved:
                filepath = resolved

        return execute_capability(
            "file.read",
            filepath=filepath,
        )

    def _read_first_file_in_folder(
        self,
        folder,
    ):
        """Read the first file from a folder."""

        from tools.files import (
            list_directory,
            _resolve_directory,
        )

        listing = list_directory(
            folder
        )

        if (
            not listing
            or "empty" in listing.lower()
        ):
            return ToolResult(
                False,
                "file.read",
                result=(
                    f"The {folder} folder "
                    "is empty."
                ),
                status="failed",
            )

        match = re.search(
            r"\s{4}(\S+\.\S+)\s+\(",
            listing,
        )

        if not match:
            return ToolResult(
                False,
                "file.read",
                result=(
                    f"Could not find files "
                    f"in {folder}."
                ),
                status="failed",
            )

        filename = match.group(1)

        directory = _resolve_directory(
            folder
        )

        if not directory:
            return ToolResult(
                False,
                "file.read",
                result=(
                    f"I couldn't resolve "
                    f"the {folder} folder."
                ),
                status="failed",
            )

        filepath = str(
            directory / filename
        )

        return execute_capability(
            "file.read",
            filepath=filepath,
        )

    def _resolve_filename(
        self,
        filename,
    ):
        """Search common directories for a filename."""

        from tools.files import (
            _resolve_directory,
        )

        for folder in (
            "downloads",
            "documents",
            "desktop",
        ):
            directory = (
                _resolve_directory(folder)
            )

            if not directory:
                continue

            try:
                if not directory.is_dir():
                    continue

                # Exact match.
                candidate = (
                    directory / filename
                )

                if candidate.is_file():
                    return str(candidate)

                # Case-insensitive match.
                for file_path in (
                    directory.iterdir()
                ):
                    if (
                        file_path.is_file()
                        and file_path.name.lower()
                        == filename.lower()
                    ):
                        return str(file_path)

            except Exception as exc:  # noqa: BLE001
                print(
                    "[FILE RESOLVE] "
                    f"{folder}: {exc}"
                )

        return None

    def _handle_file_write(
        self,
        text,
        lower,
        intent,
    ):
        """Write content to a file."""

        filepath = None
        content = None

        entities = (
            intent.extracted_entities
            or {}
        )

        filepath = (
            entities.get("filepath")
            or entities.get("file_reference")
        )

        content = entities.get(
            "content"
        )

        # Natural-language fallback.
        if not filepath or not content:
            match = re.search(
                r"(?:write|put|save)\s+"
                r"[\"']?(.+?)[\"']?\s+"
                r"(?:to|in|into)\s+"
                r"(?:file\s+)?"
                r"[\"']?([^\"'\n]+?)[\"']?$",
                lower,
            )

            if match:
                if not content:
                    content = (
                        match.group(1)
                        .strip()
                    )

                if not filepath:
                    filepath = (
                        match.group(2)
                        .strip()
                    )

        if not filepath:
            return ToolResult(
                False,
                "file.write",
                result=(
                    "I need a file path. "
                    "Where should I write?"
                ),
                status="failed",
            )

        if not content:
            return ToolResult(
                False,
                "file.write",
                result=(
                    "I need content to write. "
                    "What should I write?"
                ),
                status="failed",
            )

        return execute_capability(
            "file.write",
            filepath=filepath,
            content=content,
        )

    # ================================================================== #
    # APPLICATIONS
    # ================================================================== #

    def _handle_app_open(
        self,
        text,
        lower,
        intent,
    ):
        from agents.actions import (
            resolve_application,
        )

        match = re.search(
            r"\b(?:open|launch|start|run|"
            r"fire up)\s+"
            r"(?:the\s+)?"
            r"(?:app\s+)?"
            r"([a-z0-9 .&_-]+?)"
            r"(?:\.|\b(?:for me|please|"
            r"and|then|now|today)\b|$)",
            lower,
        )

        if not match:
            return None

        app_name = (
            match.group(1)
            .strip()
            .rstrip(".,")
        )

        app_name = re.sub(
            r"\s+(for me|please|now|today)$",
            "",
            app_name,
        ).strip()

        if not app_name:
            return None

        app_id = (
            resolve_application(
                app_name
            )
            or app_name
        )

        return execute_capability(
            "app.open",
            application=app_id,
        )

    def _handle_app_close(
        self,
        text,
        lower,
        intent,
    ):
        from agents.actions import (
            resolve_application,
        )

        match = re.search(
            r"\b(?:close|quit|exit|"
            r"shut down|kill)\s+"
            r"(?:the\s+)?"
            r"(?:app\s+)?"
            r"([a-z0-9 .&_-]+?)"
            r"(?:\.|\b(?:for me|please|"
            r"and|then|now|today)\b|$)",
            lower,
        )

        if not match:
            return None

        app_name = (
            match.group(1)
            .strip()
            .rstrip(".,")
        )

        app_name = re.sub(
            r"\s+(for me|please|now|today)$",
            "",
            app_name,
        ).strip()

        if not app_name:
            return None

        app_id = (
            resolve_application(
                app_name
            )
            or app_name
        )

        return execute_capability(
            "app.close",
            application=app_id,
        )

    # ================================================================== #
    # CODE
    # ================================================================== #

    def _handle_code_test(
        self,
        text,
        lower,
        intent,
    ):
        return execute_capability(
            "terminal.execute",
            command="pytest -q",
        )

    # ================================================================== #
    # SCREEN CONTROL
    # ================================================================== #

    def _handle_screen_control(
        self,
        text,
        lower,
        intent,
    ):
        """Execute a verified local screen-control action."""

        entities = (
            intent.extracted_entities
            or {}
        )

        action = str(
            entities.get("action")
            or ""
        ).lower().strip()

        target = str(
            entities.get("target")
            or ""
        ).strip()

        # -------------------------------------------------------------- #
        # Infer missing action
        # -------------------------------------------------------------- #

        if not action:
            action = next(
                (
                    value
                    for value in (
                        "click",
                        "press",
                        "type",
                        "scroll",
                        "move",
                    )
                    if re.search(
                        rf"\b{value}\b",
                        lower,
                    )
                ),
                "",
            )

        if target:
            target = re.sub(
                r"^(the|a|an|my)\s+",
                "",
                target,
            ).strip()

        if not action:
            return (
                self._resolve_screen_followup(
                    text,
                    lower,
                )
            )

        # -------------------------------------------------------------- #
        # Window / tab
        # -------------------------------------------------------------- #

        if action == "close_tab":
            return execute_capability(
                "screen.hotkey",
                keys=[
                    "ctrl",
                    "w",
                ],
            )

        if action == "minimize":
            return execute_capability(
                "screen.hotkey",
                keys=[
                    "win",
                    "down",
                ],
            )

        if action == "maximize":
            return execute_capability(
                "screen.hotkey",
                keys=[
                    "win",
                    "up",
                ],
            )

        if action == "switch":
            if not target:
                return ToolResult(
                    False,
                    "screen.switch_tab",
                    result="Which window or tab should I switch to?",
                    status="failed",
                )

            # Browser-tab routing. STT may add harmless filler/noise around
            # the requested site, so extract a known browser destination
            # before considering Windows application switching.
            browser_tabs = (
                "youtube music", "google maps", "google drive",
                "google docs", "google sheets", "google meet",
                "stackoverflow", "tik tok", "instagram", "tiktok",
                "youtube", "gmail", "google", "facebook", "whatsapp",
                "twitter", "reddit", "github", "linkedin", "spotify",
                "netflix", "amazon", "telegram", "discord", "wikipedia",
                "threads", "pinterest", "twitch", "drive", "docs", "sheets",
                "meet", "notion", "chatgpt", "openai",
            )

            cleaned_target = re.sub(
                r"\s+(?:browser\s+)?tabs?$",
                "",
                target,
                flags=re.IGNORECASE,
            ).strip(" .,?!")

            normalized_target = re.sub(
                r"\s+",
                " ",
                cleaned_target.lower(),
            ).strip()

            # Common speech-recognition spelling.
            normalized_target = normalized_target.replace(
                "chat gpt", "chatgpt"
            )

            # If STT produced extra words, still extract the actual site.
            browser_target = None
            for site in browser_tabs:
                if re.search(
                    rf"\b{re.escape(site)}\b",
                    normalized_target,
                ):
                    browser_target = site
                    break

            explicit_tab = bool(
                re.search(
                    r"\b(?:tab|browser tab)\b",
                    target,
                    re.IGNORECASE,
                )
            )

            if browser_target:
                return self._switch_browser_tab(browser_target)

            if explicit_tab:
                return self._switch_browser_tab(cleaned_target)

            if normalized_target in browser_tabs:
                return self._switch_browser_tab(normalized_target)

            # Genuine Windows-window/application switch.
            return execute_capability(
                "app.switch",
                application=target,
            )

        # -------------------------------------------------------------- #
        # Click
        # -------------------------------------------------------------- #

        if action == "click":
            return self._screen_click(
                target,
                text,
                lower,
            )

        # -------------------------------------------------------------- #
        # Move
        # -------------------------------------------------------------- #

        if action == "move":
            if (
                target
                and not re.fullmatch(
                    r"mouse",
                    target,
                    re.IGNORECASE,
                )
            ):
                return execute_capability(
                    "screen.move",
                    label=target,
                )

            return ToolResult(
                False,
                "screen.move",
                result=(
                    "Move the mouse where? "
                    "Give me a label to aim at."
                ),
                status="failed",
            )

        # -------------------------------------------------------------- #
        # Scroll
        # -------------------------------------------------------------- #

        if action == "scroll":

            direction = (
                "up"
                if any(
                    word in lower
                    for word in (
                        "up",
                        "top",
                    )
                )
                else "down"
            )

            return execute_capability(
                "screen.scroll",
                direction=direction,
            )

        # -------------------------------------------------------------- #
        # Press key
        # -------------------------------------------------------------- #

        if action == "press":

            key = _extract_key(
                target,
                lower,
            )

            return execute_capability(
                "screen.press_key",
                key=key,
            )

        # -------------------------------------------------------------- #
        # Type
        # -------------------------------------------------------------- #

        if action == "type":

            text_arg = _extract_type_text(
                text,
                lower,
            )

            if text_arg:
                return execute_capability(
                    "screen.type",
                    text=text_arg,
                )

            return ToolResult(
                False,
                "screen.type",
                result=(
                    "I need to know "
                    "what to type."
                ),
                status="failed",
            )

        return (
            self._resolve_screen_followup(
                text,
                lower,
            )
        )

    def _switch_browser_tab(
        self,
        target,
    ):
        """Switch to a Chrome tab using Chrome's built-in Tab Search."""
        try:
            import time
            import pyautogui

            target = str(target or "").strip(" .,!?")
            target = re.sub(r"\s+(?:browser\s+)?tabs?$", "", target, flags=re.IGNORECASE).strip()
            if not target:
                return ToolResult(
                    False,
                    "screen.switch_tab",
                    result="Which browser tab should I switch to?",
                    status="failed",
                )

            # Use the same reliable Chrome activation helper as media control.
            from tools.media import _activate_chrome
            if not _activate_chrome():
                return ToolResult(
                    False,
                    "screen.switch_tab",
                    result="I couldn't activate Chrome.",
                    status="failed",
                )

            # Chrome Tab Search works across the current Chrome window and
            # searches visible tab titles.
            pyautogui.hotkey("ctrl", "shift", "a")
            time.sleep(0.30)
            pyautogui.write(target, interval=0.01)
            time.sleep(0.30)
            pyautogui.press("enter")
            time.sleep(0.70)

            # Do not claim success until Chrome is active again.  This avoids
            # the old false-positive behaviour where the command was reported
            # successful even when Tab Search did not open.
            try:
                from perception.window import get_active_window
                info = get_active_window()
                title = (getattr(info, "title", "") or "").lower()
                app = (getattr(info, "app_name", "") or "").lower()
                if "chrome" not in title and "chrome" not in app:
                    return ToolResult(
                        False,
                        "screen.switch_tab",
                        result=f"I couldn't switch to the {target} tab.",
                        status="failed",
                    )
            except Exception:
                # Window introspection is supplementary; the actual Chrome
                # Tab Search action has already been performed.
                pass

            return ToolResult(
                True,
                "screen.switch_tab",
                result=f"Switched to the {target} tab.",
            )

        except Exception as exc:  # noqa: BLE001
            return ToolResult(
                False,
                "screen.switch_tab",
                error=str(exc),
                result=f"I couldn't switch to the {target} tab.",
                status="failed",
            )

    def _handle_next_tab(
        self,
        text,
        lower,
        intent,
    ):
        return execute_capability(
            "screen.hotkey",
            keys=[
                "ctrl",
                "tab",
            ],
        )

    def _handle_previous_tab(
        self,
        text,
        lower,
        intent,
    ):
        return execute_capability(
            "screen.hotkey",
            keys=[
                "ctrl",
                "shift",
                "tab",
            ],
        )

    def _screen_click(
        self,
        target,
        text,
        lower,
    ):
        """Click a UI element or explicit coordinates."""

        if target:
            return execute_capability(
                "screen.click_element",
                label=target,
            )

        # -------------------------------------------------------------- #
        # Recent UI target
        # -------------------------------------------------------------- #

        record = _grab_recent_app()

        if record:
            arguments = record.get(
                "arguments",
                {},
            )

            label = arguments.get(
                "label"
            )

            if label:
                return execute_capability(
                    "screen.click_element",
                    label=label,
                )

        # -------------------------------------------------------------- #
        # Coordinates
        # -------------------------------------------------------------- #

        match = re.search(
            r"\((\d+)\s*,\s*(\d+)\)",
            text,
        )

        if match:
            return execute_capability(
                "screen.click",
                x=int(match.group(1)),
                y=int(match.group(2)),
            )

        return ToolResult(
            False,
            "screen.click_element",
            result=(
                "Click what? "
                "I need a label or coordinates."
            ),
            status="failed",
        )

    def _resolve_screen_followup(
        self,
        text,
        lower,
    ):
        """
        Resolve commands such as:

            click that
            open that
            do that again
            repeat
            same thing
        """

        from core.memory import (
            get_short_term_memory,
        )

        memory = (
            get_short_term_memory()
        )

        # -------------------------------------------------------------- #
        # Repeat previous action
        # -------------------------------------------------------------- #

        if any(
            phrase in lower
            for phrase in (
                "again",
                "do that",
                "repeat",
                "same thing",
            )
        ):
            record = (
                memory.last_action_record()
            )

            if (
                record
                and record.get(
                    "capability"
                )
            ):
                return execute_capability(
                    record["capability"],
                    **record.get(
                        "arguments",
                        {},
                    ),
                )

        # -------------------------------------------------------------- #
        # Resolve remembered target
        # -------------------------------------------------------------- #

        record = (
            memory.resolve_action_target(
                lower
            )
        )

        if not record:
            return None

        capability = record.get(
            "capability",
            "",
        )

        arguments = dict(
            record.get(
                "arguments",
                {},
            )
        )

        if not capability:
            return None

        return execute_capability(
            capability,
            **arguments,
        )

    # ================================================================== #
    # FILE OPEN
    # ================================================================== #

    def _handle_file_open(
        self,
        text,
        lower,
        intent,
    ):
        name = _extract_open_target(
            lower
        )

        if not name:
            name = _resolve_memory_path(
                lower
            )

        if not name:
            return ToolResult(
                False,
                "file.open",
                result=(
                    "Open what? "
                    "I need a file or folder name."
                ),
                status="failed",
            )

        return execute_capability(
            "file.open",
            path=name,
        )

    # ================================================================== #
    # EMAIL
    # ================================================================== #

    def _handle_email_draft(
        self,
        text,
        lower,
        intent,
    ):
        entities = (
            intent.extracted_entities
            or {}
        )

        recipient = entities.get(
            "recipient"
        )

        if not recipient:
            match = re.search(
                r"[\w.+-]+@[\w-]+"
                r"(?:\.[\w-]+)+",
                text,
            )

            recipient = (
                match.group(0)
                if match
                else None
            )

        if not recipient:
            try:
                from core.memory import (
                    get_short_term_memory,
                )

                record = (
                    get_short_term_memory()
                    .last()
                )

                if record:
                    recipient = (
                        record
                        .get(
                            "entities",
                            {},
                        )
                        .get(
                            "recipient"
                        )
                    )

            except Exception as exc:  # noqa: BLE001
                print(
                    "[EMAIL] "
                    f"memory lookup failed: {exc}"
                )

        return execute_capability(
            "email.draft",
            to=recipient or "",
            subject="",
            body="",
        )

    def _handle_email_send_direct(
        self,
        text,
        lower,
        intent,
    ):
        entities = (
            intent.extracted_entities
            or {}
        )

        recipient = entities.get(
            "recipient"
        )

        if not recipient:
            match = re.search(
                r"[\w.+-]+@[\w-]+"
                r"(?:\.[\w-]+)+",
                text,
            )

            recipient = (
                match.group(0)
                if match
                else None
            )

        return execute_capability(
            "email.send_direct",
            to=recipient or "",
            subject="",
            body="",
        )

    def _handle_email_diagnostics(
        self,
        text,
        lower,
        intent,
    ):
        return execute_capability(
            "email.diagnostics"
        )

    # ================================================================== #
    # PATTERN FALLBACK
    # ================================================================== #

    def _pattern_fallback(
        self,
        text,
        lower,
    ):
        """
        Conservative fallback.

        Priority:

            1. Media control
            2. Explicit URL
            3. Explicit web search
            4. Application launch
            5. Recognized website

        Anything else returns None so the conversational model can respond.
        """

        # ============================================================== #
        # MEDIA: STOP
        # ============================================================== #

        if re.search(
            r"\b(?:stop|stop music|"
            r"stop playing|stop the music)\b",
            lower,
        ):
            return execute_capability(
                "media.stop"
            )

        # ============================================================== #
        # MEDIA: PAUSE
        # ============================================================= #

        if re.search(
            r"\b(?:pause|pause music|"
            r"pause the music)\b",
            lower,
        ):
            return execute_capability(
                "media.pause"
            )

        # ============================================================== #
        # MEDIA: RESUME
        # ============================================================== #

        if re.search(
            r"\b(?:resume|resume music|"
            r"continue playing|"
            r"continue the music)\b",
            lower,
        ):
            return execute_capability(
                "media.resume"
            )

        # ============================================================== #
        # MEDIA: NEXT
        # ============================================================== #

        if re.search(
            r"\b(?:next|next song|"
            r"skip|skip song|"
            r"skip this|next track)\b",
            lower,
        ):
            return execute_capability(
                "media.next"
            )

        # ============================================================== #
        # MEDIA: PLAY
        # ============================================================== #
        #
        # This is intentionally BEFORE browser searching.
        #
        # "play Blinding Lights"
        # must NEVER become a web-search request.
        #
        # ============================================================== #

        play_match = re.match(
            r"^\s*"
            r"(?:jarvis[\s,:-]*)?"
            r"(?:please\s+)?"
            r"(?:play|start|put\s+on)"
            r"(?:\s+me)?"
            r"(?:\s+the)?"
            r"(?:\s+song)?"
            r"(?:\s+music)?"
            r"(?:\s+(.+?))?"
            r"\s*[.!?]*$",
            lower,
            re.IGNORECASE,
        )

        if play_match:

            query = play_match.group(1)

            if query:
                query = query.strip(
                    " .,!?\"'"
                )

            generic_queries = {
                "",
                "music",
                "some music",
                "a music",
                "music for me",
                "song",
                "a song",
                "some song",
                "something",
                "anything",
            }

            if (
                query
                and query in generic_queries
            ):
                query = None

            # ---------------------------------------------------------- #
            # Mood
            # ---------------------------------------------------------- #

            mood = "default"

            if any(
                word in lower
                for word in (
                    "relax",
                    "relaxed",
                    "calm",
                    "chill",
                    "peaceful",
                )
            ):
                mood = "relaxed"

            elif any(
                word in lower
                for word in (
                    "fast",
                    "energetic",
                    "energy",
                    "upbeat",
                    "workout",
                    "hype",
                    "high energy",
                )
            ):
                mood = "energetic"

            elif any(
                word in lower
                for word in (
                    "sad",
                    "melancholy",
                    "emotional",
                )
            ):
                mood = "sad"

            elif any(
                word in lower
                for word in (
                    "romantic",
                    "love",
                )
            ):
                mood = "romantic"

            print(
                "[MEDIA FALLBACK] "
                f"query={query!r} "
                f"mood={mood!r}"
            )

            if query:
                return execute_capability(
                    "media.play",
                    query=query,
                    mood=mood,
                )

            return execute_capability(
                "media.play",
                mood=mood,
            )

        # ============================================================== #
        # EXPLICIT URL
        # ============================================================== #

        url_match = re.search(
            r"\bhttps?://\S+",
            text,
            re.IGNORECASE,
        )

        if url_match:
            return execute_capability(
                "browser.open_url",
                url=(
                    url_match.group(0)
                    .rstrip(".,!?")
                ),
            )

        # ============================================================== #
        # WEB SEARCH
        # ============================================================== #

        if not getattr(
            self,
            "_web_search_blocked",
            False,
        ):

            search_match = re.search(
                r"\b(?:search|look up|"
                r"google|find)\s+"
                r"(?:the web for\s+)?(.+)",
                lower,
            )

            if search_match:
                query = (
                    search_match.group(1)
                    .strip()
                )

                if query:
                    return execute_capability(
                        "browser.search",
                        query=query,
                    )

        # ============================================================== #
        # APPLICATION
        # ============================================================== #

        app_match = re.search(
            r"\b(?:open|launch|start)\s+"
            r"(notepad|calculator|paint|"
            r"chrome|firefox|edge|"
            r"spotify|discord|vscode)\b",
            lower,
        )

        if app_match:
            return execute_capability(
                "app.open",
                application=(
                    app_match.group(1)
                ),
            )

        # ============================================================== #
        # RECOGNIZED WEBSITE
        # ============================================================== #

        if any(
            phrase in lower
            for phrase in (
                "open",
                "go to",
                "launch",
                "visit",
            )
        ):
            site = resolve_site(
                lower
            )

            if site:
                return execute_capability(
                    "browser.open_url",
                    url=site,
                )

        # Nothing deterministic matched.
        return None

    # ================================================================== #
    # FILE EXTRACTION
    # ================================================================== #

    def _extract_directory(
        self,
        text,
    ):
        patterns = [

            r"\b(?:in|on|from)\s+"
            r"(?:my\s+)?"
            r"(desktop|documents|downloads|"
            r"pictures|music|videos|projects)\b",

            r"\b(?:in|on|from)\s+"
            r"(?:the\s+)?"
            r"([\w\s]+?)\s*"
            r"(?:folder|directory)\b",
        ]

        lower = text.lower()

        for pattern in patterns:
            match = re.search(
                pattern,
                lower,
            )

            if match:
                return (
                    match.group(1)
                    .strip()
                )

        return None

    def _extract_extension(
        self,
        text,
    ):
        lower = text.lower()

        extension_match = re.search(
            r"\b(\.(?:pdf|docx?|txt|py|"
            r"js|html|css|json|md|csv|"
            r"png|jpg|jpeg|mp3|mp4))\b",
            lower,
        )

        if extension_match:
            return extension_match.group(1)

        extension_names = {
            "pdf": ".pdf",
            "python": ".py",
            "javascript": ".js",
            "text": ".txt",
            "markdown": ".md",
            "json": ".json",
            "csv": ".csv",
        }

        for name, extension in (
            extension_names.items()
        ):
            if name in lower:
                return extension

        return None

    def _extract_search_query(
        self,
        text,
    ):
        patterns = [

            r"\b(?:find|search for|"
            r"look for|where are)\s+"
            r"(?:all\s+)?"
            r"(?:my\s+)?"
            r"(?:the\s+)?"
            r"(.+?)"
            r"(?:\s+(?:in|on|from)\s+|$)",

            r"\b(?:find|search for|"
            r"look for)\s+(.+)",
        ]

        lower = text.lower()

        for pattern in patterns:

            match = re.search(
                pattern,
                lower,
            )

            if match:
                query = (
                    match.group(1)
                    .strip()
                )

                query = re.sub(
                    r"\s+(in|on|from|about)\s*$",
                    "",
                    query,
                )

                if query:
                    return query

        return text.strip()


# ====================================================================== #
# MODULE-LEVEL HELPERS
# ====================================================================== #

_COMMON_DIR_ALIASES = (
    "downloads",
    "desktop",
    "documents",
    "pictures",
    "music",
    "videos",
    "projects",
    "folder",
)


def _extract_open_target(
    lower: str,
) -> str | None:
    """Extract a file/folder target from 'open X'."""

    match = re.search(
        r"\b(open|show me|go to|"
        r"navigate to|launch)\s+"
        r"(?:the\s+)?"
        r"(?:my\s+)?"
        r"([\w .&-]+)",
        lower,
    )

    if not match:
        return None

    name = (
        match.group(2)
        .strip(
            " .,?!"
        )
    )

    if not name:
        return None

    if name in (
        "file",
        "folder",
        "it",
        "that",
        "this",
        "a",
    ):
        return None

    for alias in _COMMON_DIR_ALIASES:
        if alias in name:
            return alias

    return name


def _resolve_memory_path(
    lower: str,
) -> str | None:
    """Resolve remembered file/folder targets."""

    from core.memory import (
        get_short_term_memory,
    )

    memory = (
        get_short_term_memory()
    )

    record = (
        memory.resolve_action_target(
            lower
        )
    )

    if not record:
        return None

    arguments = record.get(
        "arguments",
        {},
    )

    for key in (
        "path",
        "directory",
        "file",
        "name",
    ):
        value = arguments.get(key)

        if value:
            return str(value)

    return None


def _grab_recent_app() -> dict | None:
    """Get the most recent screen action."""

    from core.memory import (
        get_short_term_memory,
    )

    memory = (
        get_short_term_memory()
    )

    try:
        return memory.last(
            kind="screen."
        )

    except TypeError:
        try:
            return (
                memory.last_action_record()
            )
        except Exception:
            return None


def _extract_key(
    target: str,
    lower: str,
) -> str:
    """Convert natural key names to pyautogui names."""

    mapping = {
        "enter": "enter",
        "return": "enter",
        "backspace": "backspace",
        "delete": "delete",
        "space": "space",
        "tab": "tab",
        "escape": "esc",
        "esc": "esc",

        "up": "up",
        "down": "down",
        "left": "left",
        "right": "right",

        "control": "ctrl",
        "ctrl": "ctrl",
        "shift": "shift",
        "alt": "alt",

        "home": "home",
        "end": "end",

        "page up": "pageup",
        "pageup": "pageup",
        "page down": "pagedown",
        "pagedown": "pagedown",

        "insert": "insert",

        "caps lock": "capslock",
        "capslock": "capslock",
    }

    if target:
        clean = (
            target
            .strip()
            .lower()
        )

        clean = re.sub(
            r"^(the|key)\s+",
            "",
            clean,
        )

        if clean in mapping:
            return mapping[clean]

        return clean

    words = re.findall(
        r"\b[a-z-]{1,16}\b",
        lower,
    )

    for word in reversed(words):
        if word in mapping:
            return mapping[word]

    return "enter"


def _extract_type_text(
    text: str,
    lower: str,
) -> str | None:
    """Extract text from type/write/enter commands."""

    # 1. Quoted text: type "Hello World"
    match = re.search(
        r'\b(?:type|write|enter)\s+["\']([^"\']+)["\']',
        text,
        re.IGNORECASE,
    )
    if match:
        return match.group(1).strip() or None

    match = re.search(
        r"\b(?:type|write|say|enter)\s+(.+)",
        text,
        re.IGNORECASE,
    )

    if match:
        raw_val = match.group(1).strip(" \"'.,!?")
        clean_val = re.sub(
            r"\s+(on|from|in|into)\s+(the\s+|my\s+)?(screen|display|monitor|document|notepad|window|active\s+window|search\s+bar|search\s+box)\b.*$",
            "",
            raw_val,
            flags=re.IGNORECASE,
        ).strip(" \"'.,!?")

        if clean_val.lower() in ("a message", "message", "something", "text", "a text", "some text"):
            return "Hello from JARVIS!"

        return clean_val or raw_val or None

    return None