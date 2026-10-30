"""Module-slot interfaces M1-M13 and the types they share.

Every slot is an abstract class. A config picks one implementation per slot
by name (see ``modules.REGISTRY``); the loop in ``agent.py`` only talks to
these interfaces. Messages and requests use the Anthropic Messages shape,
which is what the counting proxy serves on ``POST /v1/messages``.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any, Callable


class ToolError(Exception):
    """A tool failed; the text goes back to the model with ``is_error``."""


class ModelError(Exception):
    def __init__(self, message: str, status: int | None = None, retryable: bool = False):
        super().__init__(message)
        self.status = status
        self.retryable = retryable


class ModelClient(abc.ABC):
    """Sends one Messages request. ``role`` is the proxy call role
    (``main``, ``side:title``, ``side:summary``, ``side:subagent``)."""

    @abc.abstractmethod
    def complete(self, request: dict, role: str = "main") -> dict: ...


@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict
    handler: Callable[[dict, "RunContext"], str]
    slot: str = "M2"  # module that contributed it

    def spec(self) -> dict:
        return {"name": self.name, "description": self.description, "input_schema": self.input_schema}


@dataclass
class ExecResult:
    output: str
    exit_code: int | None
    timed_out: bool
    truncated: bool = False


@dataclass
class RunContext:
    """Per-run state shared by modules. Modules may read it; only the loop
    and the module that owns a field write to it."""

    workdir: str
    instruction: str
    model: str
    client: ModelClient
    executor: "Executor"
    env: dict = field(default_factory=dict)  # platform, date, is_git, ...
    todos: list = field(default_factory=list)
    events: list = field(default_factory=list)
    depth: int = 0  # 0 = main agent, 1 = subagent
    spawn: Callable[[str, str], str] | None = None  # (description, prompt) -> final text

    def event(self, kind: str, **data: Any) -> None:
        self.events.append({"event": kind, **data})


# --- M1 -----------------------------------------------------------------
class PromptAssembler(abc.ABC):
    """Rows 1, 2, 14. Returns system prompt blocks in request order."""

    @abc.abstractmethod
    def system_blocks(self, ctx: RunContext, tools: list[Tool]) -> list[str]: ...

    def first_user_message(self, ctx: RunContext) -> str:
        return ctx.instruction


# --- M2 -----------------------------------------------------------------
class ToolRegistry(abc.ABC):
    """Rows 3, 4, 5, 11, 12, 19, 20. Owns the request's tool list and order.
    M7, M9 and M10 contribute their tools through it."""

    @abc.abstractmethod
    def tools(self, ctx: RunContext, contributed: dict[str, Tool]) -> list[Tool]: ...

    def render(self, tools: list[Tool]) -> list[dict]:
        return [t.spec() for t in tools]


# --- M3 -----------------------------------------------------------------
class CachePolicy(abc.ABC):
    """Row 8. Marks cache breakpoints on the outgoing request in place."""

    @abc.abstractmethod
    def apply(self, request: dict) -> None: ...


# --- M4 -----------------------------------------------------------------
class SamplingPolicy(abc.ABC):
    """Row 9 (fixed). Sets max_tokens / temperature / thinking."""

    @abc.abstractmethod
    def apply(self, request: dict) -> None: ...


# --- M5 -----------------------------------------------------------------
class SideCalls(abc.ABC):
    """Row 10. Model calls outside the main loop (title, ...)."""

    @abc.abstractmethod
    def on_start(self, ctx: RunContext) -> None: ...


# --- M6 -----------------------------------------------------------------
class ContextManager(abc.ABC):
    """Row 13. May rewrite history before each main-loop request."""

    @abc.abstractmethod
    def prepare(self, messages: list[dict], last_usage: dict | None, ctx: RunContext) -> list[dict]: ...


# --- M7 -----------------------------------------------------------------
class Editor(abc.ABC):
    """Row 15. Contributes zero or more edit tools."""

    @abc.abstractmethod
    def tools(self, ctx: RunContext) -> list[Tool]: ...


# --- M8 -----------------------------------------------------------------
class Executor(abc.ABC):
    """Rows 16, 17. Runs shell commands and formats their observation."""

    default_timeout_s: float | None

    @abc.abstractmethod
    def run(self, command: str, cwd: str, timeout_s: float | None = None) -> ExecResult: ...

    @abc.abstractmethod
    def format(self, result: ExecResult) -> str: ...


# --- M9 -----------------------------------------------------------------
class Planner(abc.ABC):
    """Row 21. Contributes a todo/plan tool, or nothing."""

    @abc.abstractmethod
    def tools(self, ctx: RunContext) -> list[Tool]: ...


# --- M10 ----------------------------------------------------------------
class Delegation(abc.ABC):
    """Row 22. Contributes a subagent tool, or nothing."""

    @abc.abstractmethod
    def tools(self, ctx: RunContext) -> list[Tool]: ...


# --- M11 ----------------------------------------------------------------
class LoopController(abc.ABC):
    """Rows 23 (fixed step cap) and 25 (error recovery hooks)."""

    max_steps: int

    def after_tools(self, calls: list[dict], results: list[dict], ctx: RunContext) -> str | None:
        """Return text to append to the tool-result turn, or None."""
        return None

    def should_stop(self, response: dict, ctx: RunContext) -> bool:
        return not any(b.get("type") == "tool_use" for b in response.get("content") or [])


# --- M12 ----------------------------------------------------------------
class RetryPolicy(abc.ABC):
    """Row 24 (fixed). Wraps every model call."""

    @abc.abstractmethod
    def call(self, fn: Callable[[], dict], ctx: RunContext) -> dict: ...


# --- M13 ----------------------------------------------------------------
class Permissions(abc.ABC):
    """Rows 26-29 (fixed). Returns None to allow, or a refusal message."""

    @abc.abstractmethod
    def check(self, tool: str, args: dict, ctx: RunContext) -> str | None: ...


INTERFACES = {
    "M1": PromptAssembler, "M2": ToolRegistry, "M3": CachePolicy, "M4": SamplingPolicy,
    "M5": SideCalls, "M6": ContextManager, "M7": Editor, "M8": Executor, "M9": Planner,
    "M10": Delegation, "M11": LoopController, "M12": RetryPolicy, "M13": Permissions,
}
