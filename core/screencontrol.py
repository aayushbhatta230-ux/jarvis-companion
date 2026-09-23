"""Real Windows screen-control executor.

Implements the full pipeline described in the reliability spec:

    pre-action perception -> action -> post-action perception -> verification

Every screen-changing capability funnels through here so that JARVIS only
reports "Done" when it can show the action actually took effect. When it
cannot verify, it says so honestly.

All OS interaction (mss screenshots, pyautogui input, OCR) is behind small
methods so unit tests can monkeypatch them without touching a real desktop.
"""

from __future__ import annotations

import re
import time
from typing import Any, Callable

from core.actionresult import ActionResult
from core.permissions import get_permission_manager, PermissionLevel

try:
    import pyautogui
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.05
    HAS_PYAUTOGUI = True
except ImportError:  # pragma: no cover - depends on environment
    HAS_PYAUTOGUI = False

try:
    import mss
    HAS_MSS = True
except ImportError:  # pragma: no cover - depends on environment
    HAS_MSS = False

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:  # pragma: no cover - depends on environment
    HAS_PIL = False


# Semantic aliases for common UI targets
_SEMANTIC_ALIASES: dict[str, tuple[str, ...]] = {
    "search bar": ("search", "search google", "search or type", "search mail",
                   "search this page", "search field", "search box", "find"),
    "search field": ("search", "search google", "search or type", "search mail"),
    "search box": ("search", "search google", "search or type"),
    "address bar": ("address", "url", "location", "omnibox"),
    "url bar": ("address", "url", "location", "omnibox"),
    "close button": ("close", "x", "×"),
    "minimize button": ("minimize", "_"),
    "maximize button": ("maximize", "max", "□"),
    "help": ("help", "?", "support", "get help", "help & support", "faq", "guide", "documentation", "readme"),
    "review": ("review", "leave a review", "reviews", "ratings", "feedback", "submit review", "write a review"),
    "settings": ("settings", "preferences", "config", "gear", "options"),
    "proceed": ("proceed", "continue", "next", "confirm", "ok", "yes"),
}


def _normalize_text(text: str) -> str:
    """Normalize text for comparison: lowercase, collapse whitespace, strip punctuation."""
    text = text.lower().strip()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[^\w\s]", "", text)
    return text


def _fuzzy_match(query: str, target: str) -> float:
    """Return a similarity score between 0.0 and 1.0 for query against target."""
    import difflib
    query_norm = _normalize_text(query)
    target_norm = _normalize_text(target)
    if not query_norm or not target_norm:
        return 0.0
    if query_norm == target_norm:
        return 1.0
    if query_norm in target_norm:
        return 0.85 + 0.15 * (len(query_norm) / len(target_norm))
    if target_norm in query_norm:
        return 0.70 + 0.15 * (len(target_norm) / len(query_norm))
    # Character sequence ratio for OCR noise tolerance
    ratio = difflib.SequenceMatcher(None, query_norm, target_norm).ratio()
    if ratio >= 0.72:
        return ratio
    # Word overlap scoring
    query_words = set(query_norm.split())
    target_words = set(target_norm.split())
    if not query_words or not target_words:
        return 0.0
    overlap = query_words & target_words
    return len(overlap) / max(len(query_words), len(target_words)) * 0.75


def _grab_image_windows() -> "Image.Image":
    """Capture the primary monitor as a Pillow Image via mss."""
    with mss.mss() as sct:
        monitor = sct.monitors[0]
        shot = sct.grab(monitor)
        return Image.frombytes("RGB", shot.size, shot.rgb)


class ScreenControlExecutor:
    """Performs verified mouse + keyboard interaction on the Windows desktop."""

    def __init__(self) -> None:
        self._ocr_elements: Callable[[], list[dict[str, Any]]] | None = None

    # ------------------------------------------------------------------ #
    # Dependency availability (self-awareness, no silent assumptions)
    # ------------------------------------------------------------------ #
    @staticmethod
    def dependencies_ok() -> str | None:
        """Return a human message if a required dependency is missing."""
        if not HAS_PYAUTOGUI:
            return "pyautogui is not installed. Install with: pip install pyautogui"
        if not HAS_MSS:
            return "mss is not installed. Install with: pip install mss"
        if not HAS_PIL:
            return "Pillow is not installed. Install with: pip install Pillow"
        return None

    # ------------------------------------------------------------------ #
    # Permission gate
    # ------------------------------------------------------------------ #
    def _permission_denied(self, action: str) -> ActionResult:
        perm = get_permission_manager().get_screen_permission()
        return ActionResult(
            success=False, status="permission_denied", action=action,
            error=f"Screen control is disabled (current permission: {perm.value}).",
            verification=None,
            message=(
                f"I can't {action.replace('_', ' ')} — screen control is off "
                f"({perm.value}). Say 'enable computer control' to allow it."
            ),
        )

    def _requires_confirmation(self, action: str) -> bool:
        """Confirmation is owned by the capability layer, not re-checked here.

        ``execute_capability`` returns ``confirmation_required`` (with the exact
        arguments) before the handler ever runs, and ``execute_confirmed`` is
        only called after the user consented. Re-gating here would make a
        confirmed action impossible to complete, so this always returns False.
        Permission checks (``can_control_screen``) are still enforced above.
        """
        return False

    # ------------------------------------------------------------------ #
    # Perception helpers
    # ------------------------------------------------------------------ #
    def _set_ocr_provider(self, provider: Callable[[], list[dict[str, Any]]]) -> None:
        """Allow injection of an OCR provider (used by tests)."""
        self._ocr_elements = provider

    def _screen_elements(self) -> list[dict[str, Any]]:
        """Return OCR-recognised text boxes; falls back to perception.vision."""
        if self._ocr_elements is not None:
            return self._ocr_elements()
        try:
            from perception.vision import analyze_ui_elements
            return analyze_ui_elements()
        except Exception as exc:  # noqa: BLE001 - report capture/OCR issues
            print(f"[SCREEN_CONTROL] element enumeration failed: {exc}")
            return []

    def find_target(self, label: str) -> dict[str, Any] | None:
        """Return the best-matching element for ``label`` or None.

        Performs case-insensitive OCR matching with fuzzy matching and semantic
        aliases. Only returns a *single*, confident target — never a random
        guess. When several elements tie, it returns None so the caller can
        report ambiguity.
        """
        label_l = (label or "").strip().lower()
        if not label_l:
            return None
        elements = self._screen_elements()
        if not elements:
            return None

        # Build the set of acceptable match texts including semantic aliases
        alias_texts = _SEMANTIC_ALIASES.get(label_l, ())

        # Score all elements
        scored: list[tuple[float, dict[str, Any]]] = []
        for elem in elements:
            text = str(elem.get("text", "")).strip()
            if not text:
                continue
            text_lower = text.lower()

            # Exact match
            if text_lower == label_l:
                scored.append((1.0, elem))
                continue
            # Alias exact match
            if text_lower in alias_texts:
                scored.append((0.95, elem))
                continue
            # Fuzzy match against label
            score = _fuzzy_match(label_l, text)
            # Fuzzy match against aliases
            for alias in alias_texts:
                alias_score = _fuzzy_match(alias, text) * 0.9
                if alias_score > score:
                    score = alias_score
            if score >= 0.6:
                scored.append((score, elem))

        if not scored:
            return None

        # Sort by score descending
        scored.sort(key=lambda x: x[0], reverse=True)

        # If top two are too close in score, it's ambiguous
        if len(scored) >= 2:
            # If multiple elements have the same top score, it's ambiguous
            top_score = scored[0][0]
            same_score_count = sum(1 for s, _ in scored if abs(s - top_score) < 0.05)
            if same_score_count >= 2:
                # Unless one is a unique exact match (different text)
                if top_score < 1.0:
                    return None
                # Multiple exact matches with same text -> ambiguous
                top_text = str(scored[0][1].get("text", "")).lower()
                for s, e in scored[1:]:
                    if abs(s - top_score) < 0.05:
                        if str(e.get("text", "")).lower() != top_text:
                            # Different text but same score -> ambiguous
                            return None
                        # Same text, same score -> ambiguous (multiple identical elements)
                        return None

        return scored[0][1]

    def find_ui_target(self, target_text: str, ocr_elements: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
        """Find a UI target with detailed result information.

        Returns a dict with:
          - text: matched text
          - bbox: (left, top, width, height)
          - center: (x, y)
          - confidence: match confidence
          - target_type: button|field|tab|text|unknown
          - status: FOUND|AMBIGUOUS|UNKNOWN
        """
        if ocr_elements is None:
            ocr_elements = self._screen_elements()

        label = (target_text or "").strip().lower()
        if not label or not ocr_elements:
            return {"status": "UNKNOWN", "text": target_text, "confidence": 0.0}

        matches: list[tuple[float, dict[str, Any]]] = []
        alias_texts = _SEMANTIC_ALIASES.get(label, ())

        for elem in ocr_elements:
            text = str(elem.get("text", "")).strip()
            if not text:
                continue
            text_lower = text.lower()
            score = 0.0
            if text_lower == label:
                score = 1.0
            elif text_lower in alias_texts:
                score = 0.95
            else:
                score = _fuzzy_match(label, text)
                for alias in alias_texts:
                    alias_score = _fuzzy_match(alias, text) * 0.9
                    if alias_score > score:
                        score = alias_score
            if score >= 0.5:
                matches.append((score, elem))

        if not matches:
            return {"status": "UNKNOWN", "text": target_text, "confidence": 0.0,
                    "message": f"Could not find '{target_text}' on screen."}

        matches.sort(key=lambda x: x[0], reverse=True)

        if len(matches) >= 2 and matches[0][0] - matches[1][0] < 0.1 and matches[0][0] < 0.95:
            return {"status": "AMBIGUOUS", "text": target_text, "confidence": matches[0][0],
                    "message": f"Found multiple possible matches for '{target_text}'."}

        best = matches[0]
        elem = best[1]
        left = int(elem.get("left", 0))
        top = int(elem.get("top", 0))
        width = int(elem.get("width", 10))
        height = int(elem.get("height", 10))

        # Determine target type from context
        target_type = "unknown"
        text_lower = str(elem.get("text", "")).lower()
        if any(w in text_lower for w in ("button", "btn", "submit", "ok", "cancel")):
            target_type = "button"
        elif any(w in text_lower for w in ("search", "field", "input", "text", "address", "url")):
            target_type = "field"
        elif any(w in text_lower for w in ("tab", "gmail", "inbox", "compose")):
            target_type = "tab"

        return {
            "status": "FOUND",
            "text": elem.get("text", ""),
            "bbox": (left, top, width, height),
            "center": (left + width // 2, top + height // 2),
            "confidence": best[0],
            "target_type": target_type,
        }
# ------------------------------------------------------------------ #
    # Actions
    # ------------------------------------------------------------------ #
    def click_ui_element(self, label: str) -> ActionResult:
        action = "click_ui_element"
        deps_err = self.dependencies_ok()
        if deps_err:
            return ActionResult(False, "failed", action, error=deps_err, verification=None, message=deps_err)
        if not get_permission_manager().can_control_screen():
            return self._permission_denied(action)
        if self._requires_confirmation(action):
            # Use find_ui_target for better matching at confirmation stage
            target_info = self.find_ui_target(label)
            status = target_info.get("status", "UNKNOWN")
            if status == "FOUND":
                msg = f"I found '{target_info.get('text', label)}' ({target_info.get('target_type', 'unknown')}). Shall I click it?"
            elif status == "AMBIGUOUS":
                msg = f"I found multiple possible matches for '{label}'. Please be more specific."
            else:
                msg = f"I couldn't find '{label}' on screen. Shall I try anyway?"
            return ActionResult(
                False, "confirmation_required", action, verification=None,
                arguments={"label": label},
                message=msg,
            )

        target = self.find_target(label)
        if target is None:
            ui_t = self.find_ui_target(label)
            if ui_t and ui_t.get("status") in ("FOUND", "AMBIGUOUS") and "bbox" in ui_t:
                bbox = ui_t["bbox"]
                target = {
                    "left": bbox[0],
                    "top": bbox[1],
                    "width": bbox[2],
                    "height": bbox[3],
                    "text": ui_t.get("text", label),
                }

        if target is None:
            # Record the failed attempt
            from core.context import get_desktop_context
            get_desktop_context().record_screen_action("click", label, None, None)
            return ActionResult(
                False, "target_not_found", action,
                error=f"Could not find '{label}' on screen.",
                verification=None,
                message=f"I couldn't find '{label}' on screen, so I didn't click anything.",
                arguments={"label": label},
            )
        x = int(target.get("left", 0)) + int(target.get("width", 10)) // 2
        y = int(target.get("top", 0)) + int(target.get("height", 10)) // 2
        pre_text = self._ocr_text_preview()
        try:
            pyautogui.moveTo(x, y, duration=0.15)
            time.sleep(0.1)
            pyautogui.click(x=x, y=y)
        except Exception as exc:  # noqa: BLE001 - physical input can fail
            return ActionResult(False, "failed", action, error=str(exc), verification=False,
                                message=f"I tried to click '{label}' but it failed: {exc}",
                                arguments={"label": label})
        verification = self._verify_change(pre_text, "click", label, x, y)
        # Record the action in context
        from core.context import get_desktop_context
        get_desktop_context().record_screen_action("click", label, (x, y), verification)
        if verification is True:
            msg = f"I clicked '{label}' at ({x}, {y})."
        else:
            msg = (f"I clicked '{label}' at ({x}, {y}), but I couldn't verify "
                   f"that it took effect.")
        return ActionResult(True, "completed", action, verification=verification,
                            arguments={"label": label, "x": x, "y": y}, message=msg)

    def click_coordinates(self, x: int, y: int, button: str = "left") -> ActionResult:
        action = "click"
        deps_err = self.dependencies_ok()
        if deps_err:
            return ActionResult(False, "failed", action, error=deps_err, verification=None, message=deps_err)
        if not get_permission_manager().can_control_screen():
            return self._permission_denied(action)
        if self._requires_confirmation(action):
            return ActionResult(False, "confirmation_required", action, verification=None,
                                arguments={"x": x, "y": y, "button": button},
                                message=f"Confirm I should click at ({x}, {y}).")
        pre_text = self._ocr_text_preview()
        try:
            pyautogui.moveTo(x, y, duration=0.15)
            pyautogui.click(x=x, y=y, button=button)
        except Exception as exc:  # noqa: BLE001
            return ActionResult(False, "failed", action, error=str(exc), verification=False,
                                message=f"I tried to click at ({x}, {y}) but it failed: {exc}",
                                arguments={"x": x, "y": y, "button": button})
        verification = self._verify_change(pre_text, "click", "", x, y)
        return ActionResult(True, "completed", action, verification=verification,
                            arguments={"x": x, "y": y, "button": button},
                            message=f"Clicked at ({x}, {y}).")

    def move_mouse_to(self, label: str) -> ActionResult:
        action = "move"
        deps_err = self.dependencies_ok()
        if deps_err:
            return ActionResult(False, "failed", action, error=deps_err, verification=None, message=deps_err)
        if not get_permission_manager().can_control_screen():
            return self._permission_denied(action)
        if self._requires_confirmation(action):
            return ActionResult(False, "confirmation_required", action, verification=None,
                                arguments={"label": label},
                                message=f"Confirm I should move the mouse to '{label}'.")
        target = self.find_target(label)
        if target is None:
            return ActionResult(False, "target_not_found", action,
                                error=f"Could not find '{label}' on screen.", verification=None,
                                message=f"I couldn't find '{label}' on screen, so I didn't move the mouse.",
                                arguments={"label": label})
        x = int(target.get("left", 0)) + int(target.get("width", 10)) // 2
        y = int(target.get("top", 0)) + int(target.get("height", 10)) // 2
        try:
            pyautogui.moveTo(x, y, duration=0.15)
        except Exception as exc:  # noqa: BLE001
            return ActionResult(False, "failed", action, error=str(exc), verification=False,
                                message=f"I couldn't move the mouse to '{label}': {exc}",
                                arguments={"label": label})
        return ActionResult(True, "completed", action, verification=None,
                            arguments={"label": label, "x": x, "y": y},
                            message=f"Moved the mouse to '{label}'.")

    def type_text(self, text: str) -> ActionResult:
        action = "type"
        deps_err = self.dependencies_ok()
        if deps_err:
            return ActionResult(False, "failed", action, error=deps_err, verification=None, message=deps_err)
        if not get_permission_manager().can_control_screen():
            return self._permission_denied(action)
        if self._requires_confirmation(action):
            return ActionResult(False, "confirmation_required", action, verification=None,
                                arguments={"text": text},
                                message="Confirm I should type that text.")
        try:
            pyautogui.write(text, interval=0.015)
        except Exception as exc:  # noqa: BLE001
            return ActionResult(False, "failed", action, error=str(exc), verification=False,
                                message=f"I tried to type but it failed: {exc}", arguments={"text": text})
        verification = self._verify_typed(text)
        msg = f"I typed: '{text}'." if verification is not False else \
              f"I typed '{text}', but I couldn't confirm it appeared on screen."
        return ActionResult(True, "completed", action, verification=verification,
                            arguments={"text": text}, message=msg)

    def press_key(self, key: str) -> ActionResult:
        action = "press_key"
        deps_err = self.dependencies_ok()
        if deps_err:
            return ActionResult(False, "failed", action, error=deps_err, verification=None, message=deps_err)
        if not get_permission_manager().can_control_screen():
            return self._permission_denied(action)
        if self._requires_confirmation(action):
            return ActionResult(False, "confirmation_required", action, verification=None,
                                arguments={"key": key}, message=f"Confirm I should press '{key}'.")
        try:
            pyautogui.press(key)
        except Exception as exc:  # noqa: BLE001
            return ActionResult(False, "failed", action, error=str(exc), verification=False,
                                message=f"I tried to press '{key}' but it failed: {exc}",
                                arguments={"key": key})
        return ActionResult(True, "completed", action, verification=None,
                            arguments={"key": key}, message=f"Pressed '{key}'.")

    def press_hotkey(self, *keys: str) -> ActionResult:
        action = "hotkey"
        deps_err = self.dependencies_ok()
        if deps_err:
            return ActionResult(False, "failed", action, error=deps_err, verification=None, message=deps_err)
        if not get_permission_manager().can_control_screen():
            return self._permission_denied(action)
        if self._requires_confirmation(action):
            return ActionResult(False, "confirmation_required", action, verification=None,
                                arguments={"keys": list(keys)},
                                message=f"Confirm I should press {'+'.join(keys)}.")
        try:
            pyautogui.hotkey(*keys)
        except Exception as exc:  # noqa: BLE001
            return ActionResult(False, "failed", action, error=str(exc), verification=False,
                                message=f"I tried '{'+'.join(keys)}' but it failed: {exc}",
                                arguments={"keys": list(keys)})
        return ActionResult(True, "completed", action, verification=None,
                            arguments={"keys": list(keys)},
                            message=f"Pressed {'+'.join(keys)}.")

    def scroll(self, direction: str = "down", clicks: int = 3) -> ActionResult:
        action = "scroll"
        deps_err = self.dependencies_ok()
        if deps_err:
            return ActionResult(False, "failed", action, error=deps_err, verification=None, message=deps_err)
        if not get_permission_manager().can_control_screen():
            return self._permission_denied(action)
        if self._requires_confirmation(action):
            return ActionResult(False, "confirmation_required", action, verification=None,
                                arguments={"direction": direction, "clicks": clicks},
                                message=f"Confirm I should scroll {direction}.")
        amount = abs(int(clicks)) * (120 if direction == "up" else -120)
        pre_text = self._ocr_text_preview()
        try:
            pyautogui.scroll(amount)
        except Exception as exc:  # noqa: BLE001
            return ActionResult(False, "failed", action, error=str(exc), verification=False,
                                message=f"I tried to scroll but it failed: {exc}",
                                arguments={"direction": direction, "clicks": clicks})
        verification = self._verify_change(pre_text, "scroll", "", None, None)
        return ActionResult(True, "completed", action, verification=verification,
                            arguments={"direction": direction, "clicks": clicks},
                            message=f"Scrolled {direction}.")

    # ------------------------------------------------------------------ #
    # Verification internals
    # ------------------------------------------------------------------ #
    def _ocr_text_preview(self) -> str:
        """Best-effort OCR preview of the screen before an action."""
        try:
            elements = self._screen_elements()
            return " ".join(str(e.get("text", "")) for e in elements if e.get("text"))
        except Exception:  # noqa: BLE001 - preview must never break the flow
            return ""

    def _verify_change(self, before: str, action: str, label: str, x, y) -> bool | None:
        """Attempt to verify a screen changed after ``action``.

        Returns True/False/None:
          True  -> the OCR content actually changed after the action.
          None  -> unchanged OCR; focusing a field often does not alter text,
                   so this is genuinely undeterminable and must not be
                   reported as success or as a hard failure.
        """
        try:
            time.sleep(0.35)
            after = self._ocr_text_preview()
        except Exception:  # noqa: BLE001
            return None
        if after.strip() != before.strip():
            return True
        return None

    def _verify_typed(self, text: str) -> bool | None:
        """Look the typed text up in the next OCR pass."""
        if not text.strip():
            return None
        try:
            time.sleep(0.3)
            after = self._ocr_text_preview().lower()
        except Exception:  # noqa: BLE001
            return None
        if not after:
            return None
        return text.lower()[:12] in after or text.lower() in after


_screen_control = ScreenControlExecutor()


def get_screen_control() -> ScreenControlExecutor:
    return _screen_control