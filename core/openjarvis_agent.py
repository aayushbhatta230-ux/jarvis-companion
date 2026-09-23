"""
OpenJarvis agent bridge for JARVIS.

JARVIS remains the outer assistant:
- voice
- personality
- conversation history
- deterministic Windows actions
- UI/screen control

OpenJarvis provides:
- multi-step reasoning
- tool calling
- tool chaining
- complex task execution
"""

from __future__ import annotations

import logging
from typing import Any

from core.tool_router import select_tools
from core.knowledge_graph import KnowledgeGraph

logger = logging.getLogger(__name__)


class _JARVISMemoryBackend:
    """Python fallback memory backend for OpenJarvis retrieval.

    OpenJarvis's current SQLite backend requires its native Rust extension.
    JARVIS already has a local SQLite knowledge graph, so use that when the
    optional native backend is unavailable. This keeps retrieval functional
    without weakening Windows security or requiring a Rust build.
    """

    backend_id = "jarvis_knowledge_graph"

    def __init__(self) -> None:
        self.graph = KnowledgeGraph()

    def store(self, content: str, *, source: str = "", metadata: dict | None = None) -> str:
        label = content.strip()[:200]
        node_id = self.graph.upsert(
            "memory",
            label or "memory",
            content,
            1.0,
        )
        return str(node_id)

    def retrieve(self, query: str, *, top_k: int = 5, **kwargs: Any):
        from openjarvis.tools.storage._stubs import RetrievalResult

        results = []
        for row in self.graph.search(query, limit=top_k):
            results.append(
                RetrievalResult(
                    content=row.get("value") or row.get("label") or "",
                    score=float(row.get("confidence", 0.0)),
                    source="JARVIS knowledge graph",
                    metadata={"trust": "trusted", "kind": row.get("kind", "memory")},
                )
            )
        return results

    def delete(self, doc_id: str) -> bool:
        # The graph deliberately does not expose destructive deletion through
        # this compatibility layer. Explicit memory deletion remains owned by
        # JARVIS/OpenJarvis memory-management tools.
        return False

    def clear(self) -> None:
        return None


class OpenJarvisAgent:
    """Thin bridge between JARVIS and OpenJarvis's orchestrator."""

    # OpenJarvis capabilities exposed to JARVIS.
    # Keep destructive/OS-level tools out of this bridge; JARVIS' own
    # deterministic capability layer remains responsible for computer control.
    DEFAULT_TOOLS = [
        "calculator",
        "think",
        "file_read",
        "web_search",
        "retrieval",
        "llm",
        "code_interpreter",
        "memory_manage",
        "user_profile_manage",
    ]

    def __init__(
        self,
        brain: Any,
        *,
        tools: list[str] | None = None,
    ) -> None:
        self.brain = brain
        self.tools = tools or list(self.DEFAULT_TOOLS)

        self._agent = None
        self._initialized = False
        self._tool_instances: dict[str, Any] = {}
        self._agent_cache: dict[tuple[str, ...], Any] = {}

    def _initialize(self) -> bool:
        """Initialize the OpenJarvis orchestrator lazily."""
        if self._initialized:
            return self._agent is not None

        self._initialized = True

        try:
            # Import built-in tools so ToolRegistry is populated.
            import openjarvis.tools  # noqa: F401

            from openjarvis.agents.orchestrator import OrchestratorAgent
            from openjarvis.core.registry import ToolRegistry

            # JARVIS's Brain owns the OpenJarvis runtime.
            runtime = getattr(self.brain, "_jarvis", None)

            if runtime is None:
                logger.error("OpenJarvis bridge: Brain has no Jarvis runtime")
                return False

            # OpenJarvis creates/resolves the actual inference engine lazily.
            ensure_engine = getattr(runtime, "_ensure_engine", None)

            if callable(ensure_engine):
                try:
                    ensure_engine()
                except TypeError:
                    # Some OpenJarvis versions accept optional arguments.
                    pass

            engine = getattr(runtime, "_engine", None)

            if engine is None:
                logger.error("OpenJarvis bridge: no inference engine available")
                return False

            model = getattr(self.brain, "model", None)

            if not model:
                model = getattr(runtime, "_model_override", None)

            if not model:
                resolver = getattr(runtime, "_resolve_model", None)
                if callable(resolver):
                    try:
                        model = resolver()
                    except TypeError:
                        model = None

            if not model:
                model = "llama3.2:latest"

            # Use OpenJarvis' own dependency-aware tool resolver so special
            # tools (memory, LLM, etc.) receive the runtime objects they need.
            from openjarvis.agents.tool_resolver import instantiate_registered_tool

            memory_backend = None
            rust_available = False
            try:
                from openjarvis._rust_bridge import RUST_AVAILABLE
                rust_available = bool(RUST_AVAILABLE)
            except Exception:
                rust_available = False

            if rust_available:
                memory_handle = getattr(runtime, "memory", None)
                if memory_handle is not None:
                    get_backend = getattr(memory_handle, "_get_backend", None)
                    if callable(get_backend):
                        try:
                            memory_backend = get_backend()
                            logger.info("OpenJarvis native memory backend enabled")
                        except Exception as exc:
                            logger.info("OpenJarvis native memory backend unavailable: %s; using fallback.", exc)

            if memory_backend is None:
                try:
                    memory_backend = _JARVISMemoryBackend()
                    logger.info("JARVIS knowledge-graph memory fallback enabled")
                except Exception:
                    logger.exception("Could not initialize JARVIS memory fallback")
                    memory_backend = None

            instances = []

            for tool_name in self.tools:
                try:
                    if not ToolRegistry.contains(tool_name):
                        logger.warning(
                            "OpenJarvis tool not registered: %s",
                            tool_name,
                        )
                        continue

                    registered = ToolRegistry.get(tool_name)
                    tool = instantiate_registered_tool(
                        registered,
                        tool_name,
                        engine=engine,
                        model=model,
                        memory_backend=memory_backend,
                    )
                    instances.append(tool)
                    self._tool_instances[tool_name] = tool

                except Exception:
                    logger.exception(
                        "Failed to initialize OpenJarvis tool: %s",
                        tool_name,
                    )

            self._agent = self._build_agent(tuple(self._tool_instances.keys()))

            logger.info(
                "OpenJarvis orchestrator initialized with tools: %s",
                [type(tool).__name__ for tool in instances],
            )

            return True

        except Exception:
            logger.exception("Failed to initialize OpenJarvis orchestrator")
            self._agent = None
            return False

    def _build_agent(self, tool_names: tuple[str, ...]):
        """Build/cache an OpenJarvis agent with only relevant tools.

        This is the first stage of smart tool selection: shrinking the tool
        catalogue before the model sees the task. The selected tool set is
        cached so repeated queries do not repeatedly construct agents.
        """
        key = tuple(name for name in tool_names if name in self._tool_instances)
        if not key:
            key = tuple(self._tool_instances.keys())
        if key in self._agent_cache:
            return self._agent_cache[key]
        from openjarvis.agents.orchestrator import OrchestratorAgent
        runtime = getattr(self.brain, "_jarvis", None)
        engine = getattr(runtime, "_engine", None)
        model = getattr(self.brain, "model", None) or "llama3.2:latest"
        agent = OrchestratorAgent(
            engine=engine,
            model=model,
            tools=[self._tool_instances[name] for name in key],
            max_turns=8,
            temperature=0.4,
            max_tokens=1024,
            mode="function_calling",
            system_prompt=self._system_prompt(),
            agent_id="jarvis:orchestrator",
        )
        self._agent_cache[key] = agent
        return agent

    @staticmethod
    def _system_prompt() -> str:
        return """
You are the deep-task execution engine inside JARVIS.

JARVIS is the user's primary personal assistant.
You are NOT a separate assistant and must not introduce yourself as one.

Your job is to solve tasks that require:
- multiple reasoning steps
- tool selection and tool chaining
- file inspection
- web research
- calculations
- Python/code execution in OpenJarvis' isolated code tool
- searching JARVIS' persistent OpenJarvis memory
- combining information from multiple sources

Rules:
1. Be concise and useful.
2. Do not describe internal reasoning.
3. Use tools when they materially help.
4. Do not invent tool results.
5. If a task cannot be completed, clearly say what is missing.
6. Return a clean final answer that JARVIS can speak aloud.
7. Never say "As an OpenJarvis agent".
8. Never claim that you performed an action unless a tool actually succeeded.
9. Use memory/profile tools only when the user explicitly asks you to remember,
   update, inspect, or remove stored information. Do not invent memories.
10. Use code_interpreter for calculations, data processing, and code experiments
    when it materially improves accuracy; do not use it to control the user's OS.
11. Do not use tool calls to perform destructive computer actions; those remain
    under JARVIS' deterministic capability and confirmation system.
"""

    def run(self, user_input: str, context: Any = None) -> str:
        """Run one complex task through OpenJarvis with smart tool selection."""
        if not self._initialize():
            return ""

        try:
            selection = select_tools(user_input, list(self._tool_instances.keys()), max_tools=5)
            agent = self._build_agent(selection.names)
            logger.info("OpenJarvis smart tools: %s (%s)", selection.names, selection.reason)
            result = agent.run(
                user_input,
                context=context,
            )

            content = getattr(result, "content", None)

            if content:
                return str(content).strip()

            return ""

        except Exception:
            logger.exception("OpenJarvis task execution failed")
            return ""
