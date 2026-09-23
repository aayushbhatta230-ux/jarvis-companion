"""JARVIS Computer Agent - Generic local computer agent."""

from __future__ import annotations
import re
from typing import Any
from agents.actions import ActionType, resolve_application, resolve_key, resolve_known_folder
from agents.state import get_computer_state


class ComputerAgent:
    """Generic computer agent that reasons over user intent and computer state."""

    def __init__(self):
        self.state = get_computer_state()

    def handle(self, transcript: str) -> tuple[bool, str]:
        text = transcript.strip()
        if not text:
            return False, ""
        if self.state.pending_action:
            return self._handle_confirmation(text)
        action = self._parse_intent(text)
        if action is None:
            return False, ""
        print(f"[AGENT] intent={action.get('intent_type')} action={action.get('type')} input={text!r}")
        ok, response = self._execute(action, text)
        if ok and response:
            print(f"[AGENT RESULT] action={action.get('type')} -> {response[:120]!r}")
        return ok, response

    def _handle_confirmation(self, text: str) -> tuple[bool, str]:
        lower = text.lower().strip()
        confirm = any(w in lower for w in ("yes", "yeah", "yep", "sure", "okay", "ok", "go ahead", "do it", "send it", "confirm", "proceed"))
        decline = any(w in lower for w in ("no", "nope", "don't", "cancel", "never mind", "stop"))
        if not confirm and not decline:
            self.state.clear_pending()
            return self.handle(text)
        pending = self.state.pending_action
        self.state.clear_pending()
        if decline:
            return True, "Okay, I won't do that."
        return self._run_action(pending.get("type", ""), pending.get("arguments", {}), text)

    def _parse_intent(self, text: str) -> dict[str, Any] | None:
        from core.intent import IntentEngine
        intent = IntentEngine().infer(text)
        action = {"intent_type": intent.intent, "sub_intent": intent.sub_intent,
                  "confidence": intent.confidence, "entities": intent.extracted_entities or {}, "original_text": text}

        # Generic rule: explicit find/search/locate requests => filesystem search
        lower = text.lower()
        if re.match(r"^(find|search for|locate|where is|where's)\b", lower) and not any(
                w in lower for w in ("the web", "online", "internet")):
            action["type"] = ActionType.FIND
            action["intent_type"] = "file"
            return action

        # Generic rule: known folder + list/search verb => filesystem operation,
        # regardless of how the intent engine classified it.
        folder_names = ("downloads", "documents", "desktop", "pictures", "videos", "music", "download")
        if any(f in lower for f in folder_names):
            # "what did I download [last week/month/recently]?" -> real Downloads history
            if "download" in lower and any(w in lower for w in ("what did", "what'd", "recently",
                                                                  "last week", "this week", "last month",
                                                                  "this month", "yesterday", "recent")):
                action["type"] = ActionType.OBSERVE
                action["intent_type"] = "file"
                folder = "downloads" if "download" in lower else ("desktop" if "desktop" in lower else "documents")
                action["recent_folder"] = folder
                return action
            if "recent" in lower or "recently" in lower or "latest" in lower:
                from tools.files import find_recent_files
                folder = "downloads" if "download" in lower else ("desktop" if "desktop" in lower else "documents")
                action["type"] = ActionType.OBSERVE
                action["intent_type"] = "file"
                action["recent_folder"] = folder
                return action
            if any(w in lower for w in ("what's in", "whats in", "what is in", "inside", "list",
                                         "show", "contents", "find", "search", "downloaded")):
                if "find" in lower or "search" in lower:
                    action["type"] = ActionType.FIND
                else:
                    action["type"] = ActionType.OBSERVE
                action["intent_type"] = "file"
                return action

        # Notepad text commands: "write 'hello' in notepad" / "create a study plan in notepad"
        if "notepad" in lower and any(w in lower for w in ("write", "type", "enter", "create", "make",
                                                              "save", "draft", "put", "note down")):
            action["type"] = ActionType.TYPE
            action["intent_type"] = "document"
            action["notepad"] = True
            return action

        # Active-application phrases the intent engine may mark as generic.
        if any(p in lower for p in ("what am i using", "what app am i using", "which app am i using",
                                    "what am i on", "what window is active")):
            action["type"] = ActionType.OBSERVE
            action["intent_type"] = "system"
            action["sub_intent"] = "active_application"
            return action

        if intent.intent == "screen" and intent.sub_intent == "question":
            action["type"] = ActionType.OBSERVE
        elif intent.intent == "screen_control":
            action["type"] = self._infer_screen_action(text)
        elif intent.intent == "app":
            action["type"] = self._infer_app_action(text)
        elif intent.intent == "file":
            action["type"] = self._infer_file_action(text)
        elif intent.intent == "browser":
            action["type"] = self._infer_browser_action(text)
        elif intent.intent == "system" and intent.sub_intent in ("active_application", "capabilities", "screen_status"):
            action["type"] = ActionType.OBSERVE
        elif intent.intent == "system" and intent.sub_intent in ("action_history", "memory_recent"):
            # Contextual / memory questions: fall through to conversational handling
            # which consults short-term context, NOT screen observation or file ops.
            action["type"] = ActionType.CONVERSATION
        elif intent.intent == "system":
            action["type"] = ActionType.SYSTEM
        elif intent.intent == "email":
            action["type"] = ActionType.EMAIL
        else:
            action["type"] = ActionType.CONVERSATION
        return action

    def _infer_screen_action(self, text: str) -> str:
        lower = text.lower()
        stripped = re.sub(r"\b(press|hit|the|key|please|can|you)\b", " ", lower).strip()
        if stripped and resolve_key(stripped):
            return ActionType.KEY
        if "double" in lower: return ActionType.DOUBLE_CLICK
        if "right" in lower: return ActionType.RIGHT_CLICK
        if "scroll" in lower or "swipe" in lower: return ActionType.SCROLL
        if "type" in lower or "write" in lower: return ActionType.TYPE
        if "drag" in lower: return ActionType.DRAG
        if "move" in lower: return ActionType.MOVE
        return ActionType.CLICK

    def _infer_app_action(self, text: str) -> str:
        lower = text.lower()
        if any(w in lower for w in ("close", "kill", "exit", "quit")): return ActionType.CLOSE
        if any(w in lower for w in ("switch", "activate", "bring to front")): return ActionType.SWITCH
        return ActionType.OPEN

    def _infer_file_action(self, text: str) -> str:
        lower = text.lower()
        if any(w in lower for w in ("search", "find", "where")): return ActionType.FIND
        if any(w in lower for w in ("what's in", "whats in", "what is in", "what's inside",
                                     "whats inside", "what is inside", "list", "show me",
                                     "show my", "contents of", "what did i download",
                                     "show downloads", "show documents", "show desktop")):
            return ActionType.OBSERVE
        return ActionType.OPEN

    def _infer_browser_action(self, text: str) -> str:
        lower = text.lower()
        if any(w in lower for w in ("back", "forward", "refresh", "reload")): return ActionType.NAVIGATE
        if "new tab" in lower: return ActionType.OPEN
        if "close tab" in lower or "close this" in lower: return ActionType.CLOSE
        if "switch tab" in lower or "select tab" in lower: return ActionType.SWITCH
        return ActionType.WEB_RESEARCH
    def _execute(self, action: dict[str, Any], text: str) -> tuple[bool, str]:
        t = action.get("type", ActionType.CONVERSATION)
        if t == ActionType.OBSERVE:
            return self._handle_observe(action, text)
        if t in (ActionType.CLICK, ActionType.DOUBLE_CLICK, ActionType.RIGHT_CLICK):
            return self._handle_click(action, text)
        if t == ActionType.TYPE:
            return self._handle_type(action, text)
        if t in (ActionType.KEY, ActionType.HOTKEY):
            return self._handle_key(action, text)
        if t == ActionType.SCROLL:
            return self._handle_scroll(action, text)
        if t == ActionType.OPEN:
            return self._handle_open(action, text)
        if t == ActionType.CLOSE:
            return self._handle_close(action, text)
        if t == ActionType.SWITCH:
            return self._handle_switch(action, text)
        if t == ActionType.FIND:
            return self._handle_find(action, text)
        if t == ActionType.NAVIGATE:
            return self._handle_navigate(action, text)
        if t == ActionType.SYSTEM:
            return self._handle_system(action, text)
        if t == ActionType.EMAIL:
            return True, "Email actions are handled by the main assistant. Please use a natural language request."
        if t == ActionType.WEB_RESEARCH:
            try:
                from tools.browser import search_web
                return True, search_web(action.get("entities", {}).get("query", text))
            except ImportError:
                return True, "Web research actions are handled by the main assistant. Please use a natural language request."
        return False, ""

    def _run_action(self, action_type: str, args: dict[str, Any], text: str) -> tuple[bool, str]:
        return self._execute({"type": action_type, "entities": args, "original_text": text}, text)

    def _handle_observe(self, action: dict[str, Any], text: str) -> tuple[bool, str]:
        # Recent-files query
        if action.get("recent_folder"):
            from tools.files import find_recent_files
            days = self._infer_days(text)
            return True, find_recent_files(action["recent_folder"], days=days, limit=8)

        lower = text.lower()

        # "what did I download last week / month / recently?" -> real Downloads listing
        if any(w in lower for w in ("downloaded", "download last", "download this week",
                                    "download this month", "recent download")):
            from tools.files import find_recent_files
            dl = resolve_known_folder("downloads")
            if dl:
                days = self._infer_days(lower)
                return True, find_recent_files(dl, days=days, limit=12)
            return True, "I couldn't locate your Downloads folder."

        # If the user mentions a known folder, list it instead of screen observation
        for folder_name in ("downloads", "documents", "desktop", "pictures", "videos", "music"):
            if folder_name in lower:
                from tools.files import list_directory
                return True, list_directory(folder_name)

        # Active application / window question -> use the real Windows foreground window
        if action.get("intent_type") == "system" and action.get("sub_intent") == "active_application" \
                or any(p in lower for p in ("what am i using", "what app am i using",
                                             "which app is active", "active application", "active app",
                                             "what is open", "what's open", "whats open",
                                             "what program is running", "what am i on")):
            self.state.refresh_window()
            app = self.state.active_application
            title = self.state.active_window_title
            if app and app.lower() not in ("desktop",):
                if title and title.strip().lower() != app.lower() and len(title.strip()) > 1:
                    return True, f"You're using {app}. The active window is '{title.strip()}'."
                return True, f"You're using {app}."

        # Screen content question ("what's on my screen", "what else do you see", ...)
        self.state.refresh_window()
        app = self.state.active_application
        try:
            from perception.screen import ScreenPerceiver
            img = ScreenPerceiver().grab_image()
        except Exception:
            img = None

        if img is None:
            # Too stale or capture failed -> answer with confirmed window info only.
            return True, (f"You're on {app}." if app else
                          "I can't access the screen right now.")

        # Fresh capture -> refresh OCR state (text + ui elements) from the real screen.
        try:
            from perception.ocr import extract_text, extract_ui_elements
            self.state.refresh_screen(extract_text(img), extract_ui_elements(img), (img.width, img.height))
        except Exception as e:
            print(f"[AGENT] OCR refresh failed: {e}")

        summary = self._summarize_screen(app)
        if summary:
            return True, summary
        text_preview = self.state.ocr_text
        if text_preview and not any(short in text_preview.lower() for short in
                                    ("no readable text", "ocr not available", "no text detected")):
            return True, (f"You're on {app}. " if app else "I can see: ") + \
                         "I can see text: " + " ".join(text_preview.split())[:120] + "..."
        return True, f"You're on {app}, but I couldn't read useful text on the screen."

    def _infer_days(self, lower: str) -> int:
        if "yesterday" in lower:
            return 1
        if "month" in lower:
            return 30
        if "week" in lower or "last week" in lower:
            return 7
        return 7

    def _summarize_screen(self, app: str = "") -> str:
        elements = self.state.ocr_elements
        parts = []
        if app:
            parts.append(f"You're on {app}.")
        if not elements:
            return " ".join(parts).strip()
        # Group OCR elements into meaningful buckets instead of dumping raw text.
        tabs = [e for e in elements if e.role == "tab" and e.text.strip()]
        buttons = [e for e in elements if e.role == "button" and e.text.strip()]
        fields = [e for e in elements if e.role == "field" and e.text.strip()]
        links = [e for e in elements if e.role == "link" and e.text.strip()]
        if tabs:
            parts.append("I see tabs: " + ", ".join(t.text for t in tabs[:5]))
        if fields:
            tab_tokens = {t.text for t in tabs}
            field_labels = [f.text for f in fields[:3] if f.text not in tab_tokens]
            if field_labels:
                parts.append("an input field: " + ", ".join(field_labels))
        if buttons:
            parts.append("buttons: " + ", ".join(b.text for b in buttons[:3]))
        if links and not tabs:
            parts.append("links: " + ", ".join(l.text for l in links[:4]))
        return " ".join(parts).strip()

    def _handle_click(self, action: dict[str, Any], text: str) -> tuple[bool, str]:
        self._refresh_screen_if_needed()
        target = self._extract_target(text)
        if not target:
            return True, "What should I click?"
        matches = self.state.find_elements(target)
        if not matches:
            return True, f"I couldn't find '{target}' on the screen."
        score, element = matches[0]
        if score < 0.6:
            return True, f"I couldn't reliably locate '{target}'."
        if len(matches) >= 2 and matches[0][0] - matches[1][0] < 0.15:
            return True, f"I found multiple possible matches for '{target}'."
        x, y = element.center
        try:
            from core.screencontrol import get_screen_control
            res = get_screen_control().click_coordinates(x, y)
            if not res.success:
                return True, res.message or f"I couldn't click: {res.error}"
            self.state.last_action = "click"
            self.state.last_target = element.text
            self.state.last_coordinates = (x, y)
            return True, f"Clicked {element.text}."
        except Exception as e:
            return True, f"I couldn't click: {e}"

    def _handle_type(self, action: dict[str, Any], text: str) -> tuple[bool, str]:
        # "create/write X in notepad" -> create a file and open it in Notepad
        if action.get("intent_type") == "document" or action.get("notepad"):
            return self._handle_notepad_document(text)
        type_text = self._extract_type_text(text)
        if not type_text:
            return True, "What should I type?"
        try:
            from core.screencontrol import get_screen_control
            res = get_screen_control().type_text(type_text)
            if not res.success:
                return True, res.message or f"I couldn't type: {res.error}"
            self.state.last_action = "type"
            self.state.last_target = type_text
            return True, f"Typed '{type_text}'."
        except Exception as e:
            return True, f"I couldn't type: {e}"

    def _handle_notepad_document(self, text: str) -> tuple[bool, str]:
        """Create a text file from natural wording and open it in Notepad.

        Handles two forms:
          * "write 'hello' in notepad"  -> file content is the quoted text
          * "create a physics study plan in notepad" -> generates a simple
            structured plan file (no fabricated facts, just an outline).
        """
        import re as _re
        lower = text.lower()

        # Explicit quoted / written content.
        quoted = _re.search(r"[\"'](.+?)[\"']", text)
        written = None
        if quoted:
            written = quoted.group(1)
        else:
            m = _re.search(r"\b(?:write|type|enter|put)\s+(.+?)\s+(?:in|into|to)\s+(?:the\s+)?notepad\b", text, _re.IGNORECASE)
            if m:
                written = m.group(1).strip(" \"'.,")
        if not written:
            written = None

        # For "create a <subject> in notepad", derive a subject and filename.
        subject = None
        m = _re.search(r"\b(?:create|make|start|draft|prepare)\s+(?:a|an|the)?\s*(.+?)\s+in\s+(?:the\s+)?notepad\b", lower)
        if m:
            subject = m.group(1).strip(" ,.!?")

        # If we genuinely have text to write verbatim, use it; otherwise build
        # a very simple outline for the requested subject (never fabricated facts).
        if written:
            content = written
            filename_token = written.lower().replace(" ", "_")[:30]
        elif subject:
            content = self._build_outline(subject)
            filename_token = _re.sub(r"[^a-z0-9_\- ]", "", subject).strip().replace(" ", "_")
        else:
            return True, "What should I write in Notepad?"

        if not filename_token:
            filename_token = "note"
        filename_token = _re.sub(r"_+", "_", filename_token).strip("_")

        desktop = resolve_known_folder("desktop") or resolve_known_folder("documents")
        if not desktop:
            return True, "I couldn't find a folder to save the note to."
        import os
        filepath = os.path.join(desktop, f"{filename_token}.txt")
        try:
            with open(filepath, "w", encoding="utf-8") as fh:
                fh.write(content)
        except Exception as e:
            return True, f"I couldn't write the file: {e}"

        # Open the file in Notepad.
        try:
            from tools.files import open_item
            open_item(filepath)
        except Exception as e:
            return True, f"I created {filepath}, but I couldn't open it in Notepad: {e}"
        self.state.last_action = "create_document"
        self.state.last_file = filepath
        self.state.last_target = filename_token
        return True, f"Created '{filename_token}.txt' in Notepad."

    def _build_outline(self, subject: str) -> str:
        """Return a minimal, honest outline skeleton for a requested subject.

        Produces a heading and a few generic prompts the student can fill in —
        it never states facts it doesn't know about a topic.
        """
        s = subject.strip()
        if s.lower().strip(" -_!?.").endswith("study plan"):
            heading = s.capitalize()
            topic_line = f"Topic: {s}"
        else:
            heading = f"{s.capitalize()} — study plan"
            topic_line = f"Topic: {s}"
        return (
            f"{heading}\n"
            "========================\n\n"
            f"{topic_line}\n\n"
            "1. Key concepts (fill in what you already know)\n"
            "2. Formulas / definitions to memorise\n"
            "3. Practice problems\n"
            "4. Review notes\n"
            "5. Test prep checklist\n\n"
            "_Created by JARVIS. Edit this outline with your own content._"
        )

    def _handle_key(self, action: dict[str, Any], text: str) -> tuple[bool, str]:
        key = self._extract_key(text)
        if not key:
            return True, "Which key should I press?"
        try:
            from core.screencontrol import get_screen_control
            res = get_screen_control().press_key(key)
            if not res.success:
                return True, res.message or f"I couldn't press {key}: {res.error}"
            self.state.last_action = "key"
            self.state.last_target = key
            return True, f"Pressed {key}."
        except Exception as e:
            return True, f"I couldn't press {key}: {e}"

    def _handle_scroll(self, action: dict[str, Any], text: str) -> tuple[bool, str]:
        direction = "down" if "down" in text.lower() else "up"
        amount = 10 if "page" in text.lower() else 3
        try:
            from core.screencontrol import get_screen_control
            res = get_screen_control().scroll(direction=direction, clicks=amount)
            if not res.success:
                return True, res.message or f"I couldn't scroll: {res.error}"
            self.state.last_action = "scroll"
            self.state.last_target = direction
            return True, f"Scrolled {direction}."
        except Exception as e:
            return True, f"I couldn't scroll: {e}"

    def _handle_open(self, action: dict[str, Any], text: str) -> tuple[bool, str]:
        intent_type = action.get("intent_type", "")
        if intent_type == "app":
            return self._open_application(text)
        elif intent_type == "file":
            return self._open_file(text)
        elif intent_type == "browser":
            return self._open_browser(text)
        return False, ""

    def _open_application(self, text: str) -> tuple[bool, str]:
        app_name = self._extract_app_name(text)
        if not app_name:
            return True, "Which application should I open?"
        app_id = resolve_application(app_name)
        if not app_id:
            return True, f"I don't recognize '{app_name}'."
        self.state.refresh_window()
        if app_id.lower() in self.state.active_application.lower():
            return True, f"{app_name} is already open."
        try:
            from tools.computer import launch
            launch(app_id)
            self.state.last_action = "open_app"
            self.state.last_target = app_name
            # Verify the application actually launched before claiming success.
            if self._verify_app_running(app_id):
                return True, f"Opened {app_name}."
            return True, f"I opened {app_name}, but I couldn't confirm its window."
        except Exception as e:
            return True, f"I couldn't open {app_name}: {e}"

    def _verify_app_running(self, app_id: str, wait: float = 1.5) -> bool:
        """Check that a launched application's process actually appeared."""
        import time
        from tools.computer import APPLICATIONS
        exe = None
        if app_id.lower() in APPLICATIONS and APPLICATIONS[app_id.lower()]:
            exe = APPLICATIONS[app_id.lower()]
        if not exe:
            exe = app_id if app_id.lower().endswith(".exe") else app_id + ".exe"
        probe = exe.lower() if isinstance(exe, str) else str(exe).lower()
        probe = probe[:-4] if probe.endswith(".exe") else probe
        time.sleep(wait)
        try:
            import subprocess
            out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {probe}.exe"],
                                 capture_output=True, text=True, timeout=5).stdout
            return (probe + ".exe").lower() in out.lower()
        except Exception:
            try:
                import psutil
                for p in psutil.process_iter(["name"]):
                    try:
                        if (p.info["name"] or "").lower() == (probe + ".exe").lower():
                            return True
                    except Exception:
                        continue
            except Exception:
                pass
            return True  # best-effort: cannot verify, do not block on failure

    def _open_file(self, text: str) -> tuple[bool, str]:
        target = self._extract_target(text)
        if not target:
            return True, "What should I open?"
        folder_path = resolve_known_folder(target)
        if folder_path:
            try:
                import os
                os.startfile(folder_path)
                self.state.last_action = "open_folder"
                self.state.last_target = target
                self.state.last_folder = folder_path
                return True, f"Opened {target}."
            except Exception as e:
                return True, f"I couldn't open {target}: {e}"
        return True, f"I couldn't find '{target}'."

    def _open_browser(self, text: str) -> tuple[bool, str]:
        url = self._extract_url(text)
        if url:
            try:
                import webbrowser
                webbrowser.open(url)
                return True, f"Opened {url}."
            except Exception as e:
                return True, f"I couldn't open the URL: {e}"
        try:
            import pyautogui
            pyautogui.hotkey("ctrl", "t")
            return True, "Opened new tab."
        except Exception as e:
            return True, f"I couldn't open new tab: {e}"

    def _handle_close(self, action: dict[str, Any], text: str) -> tuple[bool, str]:
        intent_type = action.get("intent_type", "")
        if intent_type == "app":
            return self._close_application(text)
        elif intent_type == "browser":
            return self._close_browser_tab(text)
        return False, ""

    def _close_application(self, text: str) -> tuple[bool, str]:
        app_name = self._extract_app_name(text)
        if not app_name:
            try:
                import pyautogui
                pyautogui.hotkey("alt", "f4")
                return True, "Closed active window."
            except Exception as e:
                return True, f"I couldn't close: {e}"
        try:
            from tools.computer import close
            close(app_name)
            self.state.last_action = "close_app"
            self.state.last_target = app_name
            return True, f"Closed {app_name}."
        except Exception as e:
            return True, f"I couldn't close {app_name}: {e}"

    def _close_browser_tab(self, text: str) -> tuple[bool, str]:
        try:
            import pyautogui
            pyautogui.hotkey("ctrl", "w")
            self.state.last_action = "close_tab"
            return True, "Closed tab."
        except Exception as e:
            return True, f"I couldn't close tab: {e}"

    def _handle_switch(self, action: dict[str, Any], text: str) -> tuple[bool, str]:
        intent_type = action.get("intent_type", "")
        if intent_type == "app":
            return self._switch_to_application(text)
        elif intent_type == "browser":
            return self._switch_browser_tab(text)
        return False, ""

    def _switch_to_application(self, text: str) -> tuple[bool, str]:
        app_name = self._extract_app_name(text)
        if not app_name:
            return True, "Which application?"
        try:
            from interaction.applications import switch_to_window
            switch_to_window(app_name)
            self.state.last_action = "switch_app"
            self.state.last_target = app_name
            return True, f"Switched to {app_name}."
        except Exception as e:
            return True, f"I couldn't switch to {app_name}: {e}"

    def _switch_browser_tab(self, text: str) -> tuple[bool, str]:
        index = self._extract_number(text)
        try:
            import pyautogui
            if 1 <= index <= 9:
                pyautogui.hotkey("ctrl", str(index))
                self.state.last_action = "switch_tab"
                self.state.last_target = f"tab {index}"
                return True, f"Switched to tab {index}."
            if "next" in text.lower():
                pyautogui.hotkey("ctrl", "tab")
                return True, "Switched to next tab."
            if "previous" in text.lower() or "prev" in text.lower():
                pyautogui.hotkey("ctrl", "shift", "tab")
                return True, "Switched to previous tab."
        except Exception as e:
            return True, f"I couldn't switch tab: {e}"
        return True, "Which tab should I switch to?"

    def _handle_find(self, action: dict[str, Any], text: str) -> tuple[bool, str]:
        query = self._extract_target(text)
        if not query:
            return True, "What should I find?"

        from tools.files import search_files
        from pathlib import Path

        # Semantic search: try the full phrase first, then individual significant terms
        terms = [query] if len(query.split()) <= 1 else [query] + [w for w in query.split() if len(w) > 3]
        seen_paths = set()
        all_matches = []

        for folder in ["downloads", "documents", "desktop", str(Path.home() / "JARVIS")]:
            folder_path = Path(resolve_known_folder(folder)) if folder in ("downloads", "documents", "desktop") else Path(folder)
            if not folder_path.is_dir():
                continue
            for term in terms:
                if len(term) < 2:
                    continue
                result = search_files(term, folder_path, limit=10)
                if not result or "couldn't find" in result.lower() or "is empty" in result.lower():
                    continue
                # Parse paths out of the search result text
                for line in result.splitlines():
                    line = line.strip()
                    if not line or line.endswith(("/", ":")) or line.startswith(("Folders", "Files")):
                        continue
                    # Lines look like "1. name (size)" or "name (size)" or full paths
                    candidate = line.split(" (")[0].strip()
                    candidate = re.sub(r"^\d+\.\s+", "", candidate)
                    if not candidate:
                        continue
                    full = Path(folder_path) / candidate if not candidate.startswith(("C:", "/", "~")) else Path(candidate)
                    if not full.exists():
                        # try walking for the name
                        continue
                    key = str(full).lower()
                    if key in seen_paths:
                        continue
                    seen_paths.add(key)
                    all_matches.append(full)

        if not all_matches:
            # Fall back to a deeper walk over the known folders for any term
            for term in terms:
                if len(term) < 2:
                    continue
                for folder in ["downloads", "documents", "desktop"]:
                    folder_path = resolve_known_folder(folder)
                    if folder_path:
                        result = search_files(term, folder_path, limit=5)
                        if result and "couldn't find" not in result.lower() and "is empty" not in result.lower():
                            return True, result
            return True, f"I couldn't find any files matching '{query}'."

        lines = [f"I found {len(all_matches)} match(es) for '{query}':"]
        for m in all_matches[:5]:
            try:
                from tools.files import _format_time
                import os
                mtime = _format_time(m.stat().st_mtime)
            except Exception:
                mtime = "unknown time"
            lines.append(f"  {m.name} — {m.parent} (modified {mtime})")
        return True, "\n".join(lines)

    def _handle_navigate(self, action: dict[str, Any], text: str) -> tuple[bool, str]:
        lower = text.lower()
        try:
            from core.screencontrol import get_screen_control
            if "back" in lower:
                get_screen_control().press_hotkey("alt", "left")
                return True, "Went back."
            if "forward" in lower:
                get_screen_control().press_hotkey("alt", "right")
                return True, "Went forward."
            if "refresh" in lower or "reload" in lower:
                get_screen_control().press_key("f5")
                return True, "Refreshed."
        except Exception as e:
            return True, f"I couldn't navigate: {e}"
        return False, ""

    def _handle_system(self, action: dict[str, Any], text: str) -> tuple[bool, str]:
        lower = text.lower()
        try:
            from core.screencontrol import get_screen_control
            if "volume up" in lower or "increase volume" in lower:
                get_screen_control().press_key("volumeup")
                return True, "Volume increased."
            if "volume down" in lower or "decrease volume" in lower:
                get_screen_control().press_key("volumedown")
                return True, "Volume decreased."
            if "mute" in lower:
                get_screen_control().press_key("volumemute")
                return True, "Muted."
            if "minimize" in lower:
                get_screen_control().press_hotkey("win", "down")
                return True, "Minimized."
            if "maximize" in lower:
                get_screen_control().press_hotkey("win", "up")
                return True, "Maximized."
        except Exception as e:
            return True, f"I couldn't perform that system action: {e}"
        return True, "I can't control that on this system yet."

    def _refresh_screen_if_needed(self) -> None:
        if self.state.is_stale():
            try:
                from perception.screen import ScreenPerceiver
                from perception.ocr import extract_text, extract_ui_elements
                img = ScreenPerceiver().grab_image()
                if img:
                    self.state.refresh_screen(extract_text(img), extract_ui_elements(img), (img.width, img.height))
            except Exception:
                pass

    def _extract_target(self, text: str) -> str:
        lower = text.lower()
        lower = re.sub(r"\b(click|tap|press|select|open|go to|the|a|an|that|this|please|can you|could you|find|search|locate|my|file|files|folder|for|show|me|where|is|are|project|document)\b", " ", lower)
        words = lower.split()
        return " ".join(words[:4]).strip()

    def _extract_type_text(self, text: str) -> str:
        import re
        match = re.search(r'["\'](.+?)["\']', text)
        if match:
            return match.group(1)
        match = re.search(r'(?:type|write|enter)\s+(.+?)(?:\s+and\s+|$)', text, re.IGNORECASE)
        return match.group(1).strip() if match else ""

    def _extract_key(self, text: str) -> str:
        lower = text.lower()
        lower = re.sub(r"\b(press|hit|the|key|please|can you)\b", " ", lower)
        key = lower.strip()
        return resolve_key(key) or key

    def _extract_app_name(self, text: str) -> str:
        lower = text.lower()
        lower = re.sub(r"\b(open|launch|start|run|close|kill|exit|quit|switch to|activate|bring to front|please|can you|could you|the)\b", " ", lower)
        return lower.strip()

    def _extract_url(self, text: str) -> str:
        import re
        match = re.search(r'https?://\S+', text)
        return match.group(0) if match else ""

    def _extract_number(self, text: str) -> int:
        import re
        word_nums = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5}
        lower = text.lower()
        for word, num in word_nums.items():
            if word in lower:
                return num
        match = re.search(r'(\d+)', text)
        return int(match.group(1)) if match else -1


def get_agent() -> ComputerAgent:
    if not hasattr(get_agent, "_instance"):
        get_agent._instance = ComputerAgent()
    return get_agent._instance
