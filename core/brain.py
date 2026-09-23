"""JARVIS brain backed by OpenJarvis + Ollama."""

from __future__ import annotations

import asyncio
import queue
import threading

from openjarvis import Jarvis

from core.capabilities import describe_capabilities
from core.profile import private_profile_summary


SYSTEM_PROMPT = (
    "You are JARVIS, a capable direct-action personal computer companion running locally on Windows. "
    "You are the reasoning engine for the user's computer assistant. Think independently, use context, "
    "and choose the most useful response or available capability for each request. "
    "You have access only to capabilities explicitly provided by the application. "
    "When an appropriate capability exists and permission allows it, use it rather than merely describing what the user could do. "
    "For unfamiliar but understandable requests, reason from the user's words, recent conversation, desktop context, and available capabilities. "
    "Infer common targets when the intended target is reasonably clear. Ask a concise clarification only when the target genuinely cannot be determined safely. "
    "Do not become stuck because a phrase is not an exact predefined command. "
    "Do not use canned status phrases as answers unless the user actually asks for your status. "
    "CRITICAL: you are controlling and observing a real computer through capabilities supplied by the application. "
    "Never claim an action succeeded unless its verified capability result says so. "
    "Never claim to have seen something unless screen or vision information was actually obtained. "
    "Never invent file contents, download history, open applications, UI elements, or tool results. "
    "If a capability fails, report the actual failure honestly. "
    "Use the capability registry supplied in each request as the source of truth. "
    "Be natural, conversational, concise, and useful. Avoid unnecessary lists, preambles, or theatrical language. "
    "NATURAL VOICE CONVERSATION RULES: "
    "1. Speak naturally, warmly, and concisely like Tony Stark's JARVIS. "
    "2. Keep voice responses strictly to 1 or 2 short sentences (maximum 25 words total). "
    "3. NEVER give long monologues, moral essays, or robotic system narration (e.g. NEVER say '(system.info)', 'According to my system info', 'As your companion, I want to acknowledge that it is okay to feel this way'). "
    "4. When the user asks how they are doing or for a status check, give a crisp, reassuring answer in one sentence. "
    "5. Only provide detailed answers if the user explicitly asks to 'explain in detail'. "
    "For simple questions, answer directly. For complex requests, reason through the task and use the available capabilities when appropriate."
)

DIRECT_ACTION_CONTRACT = (
    "DIRECT-ACTION CONTRACT:\n"
    "- When the user gives an actionable command, EXECUTE it immediately. Do not ask "
    "clarifying questions when the intent is clear from context.\n"
    "- Compound commands (e.g. 'open notepad and write X') are TWO sequential actions: "
    "open the app, then type the content. Execute both without pausing for confirmation.\n"
    "- If the user refers to 'that', 'it', 'the file', etc., resolve it from recent "
    "conversation context and short-term memory. Never ask 'which one?' when the referent "
    "is unambiguous.\n"
    "- You CAN open applications, type into them, read/write files, and observe the screen. "
    "Never claim you cannot do these things — the capability registry is authoritative.\n"
    "- When asked to write or type content, generate the actual content. Do not type the "
    "user's literal request string as the content.\n"
    "- If screen context is empty or unavailable, say you cannot see the screen right now. "
    "Never invent UI elements, buttons, or text that were not actually detected.\n"
    "- Keep confirmation requests only for destructive/irreversible actions (deleting files, "
    "sending emails). Never confirm routine typing, opening, or reading."
)


class BrainError(RuntimeError):
    """Raised when the local AI model cannot answer."""


class Brain:
    """Compatibility layer between the existing JARVIS system and OpenJarvis."""

    KEEP_ALIVE = "60m"

    def __init__(self, model: str = "llama3.2:latest") -> None:
        self.model = model
        self.history: list[dict[str, str]] = []

        try:
            self._jarvis = Jarvis(
                model=self.model,
                engine_key="ollama",
            )
        except Exception as exc:
            raise BrainError(
                f"Could not initialize OpenJarvis with model '{self.model}'."
            ) from exc

    def _build_context(self) -> str:
        """Build the same JARVIS context used by the original Brain."""
        from core.context import get_desktop_context

        desktop_ctx = get_desktop_context().to_prompt_context()

        return (
            f"{desktop_ctx}\n"
            f"Available capabilities:\n{describe_capabilities()}\n"
            f"Private profile: {private_profile_summary()}\n"
            f"{DIRECT_ACTION_CONTRACT}"
        )

    def _build_query(self, prompt: str) -> str:
        """Build the complete prompt sent to OpenJarvis."""

        context = self._build_context()

        history_text = ""

        if self.history:
            history_parts = []

            for message in self.history[-12:]:
                role = message.get("role", "unknown").upper()
                content = message.get("content", "")
                history_parts.append(f"{role}: {content}")

            history_text = (
                "\n\nRECENT JARVIS CONVERSATION:\n"
                + "\n".join(history_parts)
            )

        return (
            f"{SYSTEM_PROMPT}\n\n"
            f"{context}"
            f"{history_text}\n\n"
            f"CURRENT USER REQUEST:\n{prompt}"
        )

    def warm_up(self) -> bool:
        """Load the model before the first real turn."""

        try:
            self._jarvis.ask(
                "Ready?",
                model=self.model,
                max_tokens=1,
                context=False,
            )

            print(
                f"[BRAIN] OpenJarvis model '{self.model}' warmed up and resident"
            )

            return True

        except Exception as exc:
            print(f"[BRAIN] warm-up skipped: {exc}")
            return False

    def respond(self, prompt: str) -> str:
        """Generate a complete response through OpenJarvis."""

        try:
            query = self._build_query(prompt)

            response = self._jarvis.ask(
                query,
                model=self.model,
                max_tokens=180,
                context=False,
            ).strip()

        except Exception as exc:
            raise BrainError(
                f"The OpenJarvis local model is unavailable. "
                f"Start Ollama and make sure '{self.model}' is available."
            ) from exc

        if not response:
            raise BrainError("The local model returned an empty response.")

        self.history.extend(
            [
                {"role": "user", "content": prompt},
                {"role": "assistant", "content": response},
            ]
        )

        return response

    def respond_stream(
        self,
        prompt: str,
        options: dict | None = None,
    ):
        """Yield OpenJarvis streaming output synchronously.

        The existing ConversationManager expects a normal Python generator,
        while OpenJarvis provides an async iterator. A background thread and
        thread-safe queue bridge the two without changing ConversationManager.
        """

        if options is None:
            options = {"num_predict": 180}

        query = self._build_query(prompt)

        token_queue: queue.Queue = queue.Queue()
        parts: list[str] = []

        async def producer() -> None:
            try:
                async for token in self._jarvis.ask_stream(
                    query,
                    model=self.model,
                    max_tokens=options.get("num_predict", 180),
                    context=False,
                ):
                    token_queue.put(("token", token))

            except Exception as exc:
                token_queue.put(("error", exc))

            finally:
                token_queue.put(("done", None))

        def run_producer() -> None:
            asyncio.run(producer())

        thread = threading.Thread(
            target=run_producer,
            daemon=True,
        )

        try:
            thread.start()

            while True:
                event, value = token_queue.get()

                if event == "token":
                    parts.append(value)
                    yield value

                elif event == "error":
                    raise value

                elif event == "done":
                    break

            thread.join(timeout=1)

        except Exception as exc:
            raise BrainError(
                f"The OpenJarvis local model is unavailable. "
                f"Start Ollama and make sure '{self.model}' is available."
            ) from exc

        response = "".join(parts).strip()

        if not response:
            raise BrainError("The local model returned an empty response.")

        self.history.extend(
            [
                {"role": "user", "content": prompt},
                {"role": "assistant", "content": response},
            ]
        )