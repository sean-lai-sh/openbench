"""Module implementations and the registry configs pick from.

``REGISTRY[slot][impl]`` is a class implementing ``interfaces.INTERFACES[slot]``
whose constructor takes the config's ``params`` as keyword arguments. Harness
files (``harness_*.py``) register more implementations and tool factories at
import; ``load_harness_modules()`` imports them.

``TOOLS[(family, name)]`` builds a ``Tool`` for the M2 catalog. ``family``
keeps two harnesses' same-named tools apart (``pi:read`` vs ``opencode:read``).
"""
from __future__ import annotations

import importlib
import json
import os
import re
import time
from pathlib import Path
from typing import Callable

from thesis.base_agent import tools as T
from thesis.base_agent.interfaces import (
    INTERFACES, CachePolicy, ContextManager, Delegation, Editor, ExecResult, Executor,
    LoopController, ModelError, Permissions, Planner, PromptAssembler, RetryPolicy, RunContext,
    SamplingPolicy, SideCalls, Tool, ToolError, ToolRegistry,
)

REGISTRY: dict[str, dict[str, type]] = {slot: {} for slot in INTERFACES}
TOOLS: dict[tuple[str, str], Callable[[dict], Tool]] = {}
SOURCES: dict[str, str] = {}  # "M7:pi_edit" / "tool:pi:read" -> source
ORIGINAL = "original: thesis/base_agent"

HARNESS_MODULES = ()  # filled in as harness files are added


def _check_source(source: str, what: str) -> None:
    if not (source == ORIGINAL or re.match(r"^[\w.-]+/[\w.-]+@[0-9a-f]{7,40}:\S", source or "")):
        raise ValueError(f"{what}: source must be {ORIGINAL!r} or 'org/repo@<commit>:<path>'")


def register(slot: str, name: str, source: str):
    """``source`` is where the behaviour comes from: ``ORIGINAL`` (written
    here, no upstream) or ``org/repo@<pinned commit>:<path>`` of an
    open-source harness."""
    def deco(cls):
        if not issubclass(cls, INTERFACES[slot]):
            raise TypeError(f"{cls.__name__} does not implement {slot}")
        if name in REGISTRY[slot]:
            raise ValueError(f"{slot}:{name} registered twice")
        _check_source(source, f"{slot}:{name}")
        REGISTRY[slot][name] = cls
        SOURCES[f"{slot}:{name}"] = source
        return cls
    return deco


def tool(family: str, name: str, source: str):
    def deco(fn):
        if (family, name) in TOOLS:
            raise ValueError(f"tool {family}:{name} registered twice")
        _check_source(source, f"tool {family}:{name}")
        TOOLS[(family, name)] = fn
        SOURCES[f"tool:{family}:{name}"] = source
        return fn
    return deco


def load_harness_modules() -> None:
    for mod in HARNESS_MODULES:
        importlib.import_module(mod)


def build(slot: str, impl: str, params: dict | None = None):
    try:
        cls = REGISTRY[slot][impl]
    except KeyError:
        raise ValueError(f"unknown implementation {slot}:{impl}") from None
    return cls(**(params or {}))


def find_context_files(workdir: str, names=("AGENTS.md", "CLAUDE.md"), stop_at_git: bool = True) -> list[dict]:
    """Walk from ``workdir`` up to the repo root (or filesystem root) and
    return instruction files, outermost first."""
    out = []
    d = Path(workdir).resolve()
    while True:
        for n in names:
            f = d / n
            if f.is_file():
                out.append({"path": str(f), "content": f.read_text(encoding="utf-8", errors="replace")})
                break
        if (stop_at_git and (d / ".git").exists()) or d.parent == d:
            break
        d = d.parent
    return list(reversed(out))


# --- M1 PromptAssembler ---------------------------------------------------
@register("M1", "base", ORIGINAL)
class BasePrompt(PromptAssembler):
    """Minimal neutral prompt: preamble, optional project files, cwd."""

    def __init__(self, preamble: str = "You are a coding agent. Use the tools to complete the task in the working directory. Finish by replying without a tool call.",
                 context_files: bool = False, memory_files: bool = False):
        self.preamble = preamble
        self.context_files = context_files
        self.memory_files = memory_files  # row 14; fixed off, no implementation reads memory

    def system_blocks(self, ctx, tools):
        parts = [self.preamble]
        if self.context_files:
            for f in find_context_files(ctx.workdir):
                parts.append(f"Instructions from {f['path']}:\n{f['content']}")
        parts.append(f"Working directory: {ctx.workdir}")
        return ["\n\n".join(parts)]


# --- M2 ToolRegistry ------------------------------------------------------
@register("M2", "catalog", ORIGINAL)
class CatalogTools(ToolRegistry):
    """Tools in the configured order. A name is looked up first among tools
    contributed by M7/M9/M10, then in ``TOOLS[(family, name)]``."""

    def __init__(self, family: str = "base", tools: list[str] = ("bash", "read", "write"),
                 drop_tools: list[str] = (), mcp: bool = False, tool_params: dict | None = None):
        self.family = family
        self.order = list(tools)
        self.drop = set(drop_tools)
        self.mcp = mcp  # row 20; fixed off, no MCP client exists
        self.tool_params = tool_params or {}

    def tools(self, ctx, contributed):
        out = []
        for name in self.order:
            if name in self.drop:
                continue
            if name in contributed:
                out.append(contributed[name])
                continue
            factory = TOOLS.get((self.family, name))
            if factory is None:
                raise ValueError(f"M2: no tool {self.family}:{name} and no module contributed it")
            out.append(factory(dict(self.tool_params.get(name, {}))))
        missing = set(contributed) - set(self.order)
        if missing:
            raise ValueError(f"M2: contributed tools not placed in the tool order: {sorted(missing)}")
        return out


def _schema(props: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": props, "required": required}


@tool("base", "bash", ORIGINAL)
def _base_bash(p):
    def run(args, ctx):
        if not isinstance(args.get("command"), str):
            raise ToolError("command is required")
        return ctx.executor.format(ctx.executor.run(args["command"], ctx.workdir, args.get("timeout")))
    return Tool("bash", "Run a bash command in the working directory. Returns combined stdout and stderr.",
                _schema({"command": {"type": "string"},
                         "timeout": {"type": "number", "description": "Timeout in seconds"}}, ["command"]), run)


@tool("base", "read", ORIGINAL)
def _base_read(p):
    def run(args, ctx):
        return T.read_file(ctx.workdir, args.get("path"), args.get("offset"), args.get("limit"),
                           p.get("max_lines", 2000), p.get("max_bytes", 50 * 1024), p.get("numbered", False))
    return Tool("read", "Read a file. Use offset/limit for large files.",
                _schema({"path": {"type": "string"}, "offset": {"type": "integer"},
                         "limit": {"type": "integer"}}, ["path"]), run)


@tool("base", "write", ORIGINAL)
def _base_write(p):
    return Tool("write", "Create or overwrite a file.",
                _schema({"path": {"type": "string"}, "content": {"type": "string"}}, ["path", "content"]),
                lambda a, ctx: T.write_file(ctx.workdir, a.get("path"), a.get("content")))


@tool("base", "glob", ORIGINAL)
def _base_glob(p):
    return Tool("glob", "Find files by glob pattern.",
                _schema({"pattern": {"type": "string"}, "path": {"type": "string"}}, ["pattern"]),
                lambda a, ctx: T.glob_files(ctx.workdir, a.get("pattern"), a.get("path")))


@tool("base", "grep", ORIGINAL)
def _base_grep(p):
    return Tool("grep", "Search file contents with a regex.",
                _schema({"pattern": {"type": "string"}, "path": {"type": "string"},
                         "include": {"type": "string"}}, ["pattern"]),
                lambda a, ctx: T.grep_files(ctx.workdir, a.get("pattern"), a.get("path"), a.get("include")))


# --- M3 CachePolicy -------------------------------------------------------
@register("M3", "none", ORIGINAL)
class NoCache(CachePolicy):
    def apply(self, request):
        return None


@register("M3", "anthropic", ORIGINAL)
class AnthropicBreakpoints(CachePolicy):
    """``cache_control: ephemeral`` on the last system block, the last tool,
    and the last ``messages`` messages (at most 4 breakpoints in total)."""

    def __init__(self, system: bool = True, tools: bool = False, messages: int = 2):
        self.system, self.tools, self.messages = system, tools, messages

    @staticmethod
    def _mark(block: dict) -> None:
        block["cache_control"] = {"type": "ephemeral"}

    def apply(self, request):
        if self.system and isinstance(request.get("system"), list) and request["system"]:
            self._mark(request["system"][-1])
        if self.tools and request.get("tools"):
            self._mark(request["tools"][-1])
        for msg in (request.get("messages") or [])[-self.messages:] if self.messages else []:
            content = msg.get("content")
            if isinstance(content, str):
                msg["content"] = content = [{"type": "text", "text": content}]
            if content:
                self._mark(content[-1])


# --- M4 SamplingPolicy (fixed) ---------------------------------------------
@register("M4", "fixed", ORIGINAL)
class FixedSampling(SamplingPolicy):
    def __init__(self, max_tokens: int = 32000, temperature: float | None = None,
                 thinking_budget: int | None = None):
        self.max_tokens, self.temperature, self.thinking_budget = max_tokens, temperature, thinking_budget

    def apply(self, request):
        request["max_tokens"] = self.max_tokens
        if self.temperature is not None:
            request["temperature"] = self.temperature
        if self.thinking_budget:
            request["thinking"] = {"type": "enabled", "budget_tokens": self.thinking_budget}


# --- M5 SideCalls ---------------------------------------------------------
@register("M5", "none", ORIGINAL)
class NoSideCalls(SideCalls):
    def on_start(self, ctx):
        return None


@register("M5", "title", ORIGINAL)
class TitleCall(SideCalls):
    """One title request before the main loop, as OpenCode makes. Its tokens
    are tagged ``side:title`` at the proxy."""

    def __init__(self, system: str = "Generate a short title (at most 50 characters) for this conversation. Reply with the title only.",
                 max_tokens: int = 64, model: str | None = None):
        self.system, self.max_tokens, self.model = system, max_tokens, model

    def on_start(self, ctx):
        req = {"model": self.model or ctx.model, "max_tokens": self.max_tokens,
               "system": [{"type": "text", "text": self.system}],
               "messages": [{"role": "user", "content": ctx.instruction}]}
        try:
            ctx.client.complete(req, role="side:title")
            ctx.event("side_call", detail="title")
        except ModelError as exc:  # a failed title never fails the run
            ctx.event("side_call_error", detail="title", error=str(exc))


# --- M6 ContextManager ----------------------------------------------------
@register("M6", "none", ORIGINAL)
class KeepAll(ContextManager):
    def prepare(self, messages, last_usage, ctx):
        return messages


@register("M6", "summarize", ORIGINAL)
class SummarizeOnThreshold(ContextManager):
    """When the last main request's input tokens reach ``threshold`` of
    ``context_window`` (or ``context_window - reserve_tokens``), replace the
    history with one user turn: the original instruction plus a summary
    from a ``side:summary`` call."""

    def __init__(self, context_window: int = 200000, threshold: float | None = None,
                 reserve_tokens: int | None = None, max_tokens: int = 4096,
                 prompt: str = "Summarize the conversation so far so another agent can continue the task: what was asked, what was done, which files changed, and what remains."):
        if threshold is None and reserve_tokens is None:
            raise ValueError("M6 summarize needs threshold or reserve_tokens")
        self.window, self.threshold, self.reserve = context_window, threshold, reserve_tokens
        self.max_tokens, self.prompt = max_tokens, prompt

    def limit(self) -> int:
        if self.reserve is not None:
            return self.window - self.reserve
        return int(self.window * self.threshold)

    def prepare(self, messages, last_usage, ctx):
        if not last_usage:
            return messages
        used = sum(int(last_usage.get(k) or 0) for k in
                   ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
        if used < self.limit():
            return messages
        req = {"model": ctx.model, "max_tokens": self.max_tokens,
               "messages": messages + [{"role": "user", "content": self.prompt}]}
        resp = ctx.client.complete(req, role="side:summary")
        summary = "".join(b.get("text", "") for b in resp.get("content") or [] if b.get("type") == "text")
        ctx.event("compaction", used=used, limit=self.limit())
        return [{"role": "user", "content": f"{ctx.instruction}\n\nSummary of earlier work:\n{summary}\n\nContinue."}]


# --- M7 Editor ------------------------------------------------------------
@register("M7", "none", ORIGINAL)
class NoEditor(Editor):
    """No edit tool: edits go through the shell (Codex on Claude)."""

    def tools(self, ctx):
        return []


@register("M7", "replace", ORIGINAL)
class BaseReplace(Editor):
    def tools(self, ctx):
        return [Tool("edit", "Replace one exact, unique occurrence of old_text with new_text in a file.",
                     _schema({"path": {"type": "string"}, "old_text": {"type": "string"},
                              "new_text": {"type": "string"}}, ["path", "old_text", "new_text"]),
                     lambda a, c: T.replace_exact(c.workdir, a.get("path"), a.get("old_text"), a.get("new_text")),
                     slot="M7")]


# --- M8 Executor ----------------------------------------------------------
@register("M8", "shell", ORIGINAL)
class ShellExecutor(Executor):
    """``default_timeout_s`` None means no timeout unless the model sets one.
    The observation keeps the ``keep`` end of the output within
    ``max_lines`` / ``max_bytes``."""

    def __init__(self, default_timeout_s: float | None = None, max_timeout_s: float | None = None,
                 timeout_unit: str = "s", max_lines: int | None = 2000, max_bytes: int | None = 50 * 1024,
                 keep: str = "tail"):
        if keep not in ("head", "tail") or timeout_unit not in ("s", "ms"):
            raise ValueError("M8: keep must be head|tail, timeout_unit s|ms")
        self.default_timeout_s, self.max_timeout_s = default_timeout_s, max_timeout_s
        self.timeout_unit, self.max_lines, self.max_bytes, self.keep = timeout_unit, max_lines, max_bytes, keep

    def run(self, command, cwd, timeout_s=None):
        if timeout_s is not None and self.timeout_unit == "ms":
            timeout_s = float(timeout_s) / 1000.0
        t = timeout_s if timeout_s is not None else self.default_timeout_s
        if t is not None and self.max_timeout_s is not None:
            t = min(float(t), self.max_timeout_s)
        res = T.run_shell(command, cwd, t)
        text, cut = T.truncate(res.output, self.max_lines, self.max_bytes, self.keep)
        res.output, res.truncated = text, cut
        res.timeout_used = t  # type: ignore[attr-defined]
        return res

    def format(self, result: ExecResult) -> str:
        out = result.output.rstrip("\n") or "(no output)"
        if result.truncated:
            out = (f"[output truncated to the {'last' if self.keep == 'tail' else 'first'} "
                   f"{self.max_lines} lines / {self.max_bytes} bytes]\n" + out)
        if result.timed_out:
            out += f"\n\nCommand timed out after {getattr(result, 'timeout_used', None)} seconds"
        elif result.exit_code:
            out += f"\n\nCommand exited with code {result.exit_code}"
        return out


# --- M9 Planner / M10 Delegation ------------------------------------------
@register("M9", "none", ORIGINAL)
class NoPlanner(Planner):
    def tools(self, ctx):
        return []


@register("M10", "none", ORIGINAL)
class NoDelegation(Delegation):
    def tools(self, ctx):
        return []


# --- M11 LoopController ---------------------------------------------------
@register("M11", "basic", ORIGINAL)
class BasicLoop(LoopController):
    """``max_steps`` is the fixed global cap (row 23). ``hooks`` are the
    swappable row-25 behaviours:

    * ``doom_loop``: ``doom_threshold`` identical consecutive tool calls are
      logged; with ``doom_action = "warn"`` a warning is appended to the
      tool-result turn. (OpenCode asks permission here; headless with its
      auto-approve flag the ask is approved, so its parity value is ``log``.)
    """

    def __init__(self, max_steps: int = 1000, hooks: list[str] = (), doom_threshold: int = 3,
                 doom_action: str = "log"):
        unknown = set(hooks) - {"doom_loop"}
        if unknown:
            raise ValueError(f"M11: unknown hooks {sorted(unknown)}")
        if doom_action not in ("log", "warn"):
            raise ValueError("M11: doom_action must be log|warn")
        self.max_steps, self.hooks = max_steps, list(hooks)
        self.doom_threshold, self.doom_action = doom_threshold, doom_action
        self._recent: list[str] = []

    def after_tools(self, calls, results, ctx):
        if "doom_loop" not in self.hooks:
            return None
        for c in calls:
            self._recent.append(json.dumps([c.get("name"), c.get("input")], sort_keys=True))
        tail = self._recent[-self.doom_threshold:]
        if len(tail) == self.doom_threshold and len(set(tail)) == 1:
            ctx.event("doom_loop", call=tail[-1])
            if self.doom_action == "warn":
                return f"You have made the same tool call {self.doom_threshold} times in a row. Try a different approach."
        return None


# --- M12 RetryPolicy (fixed) ------------------------------------------------
@register("M12", "backoff", ORIGINAL)
class BackoffRetry(RetryPolicy):
    def __init__(self, max_attempts: int = 4, initial_s: float = 2.0, factor: float = 2.0,
                 max_s: float = 30.0, sleep: Callable[[float], None] | None = None):
        self.max_attempts, self.initial_s, self.factor, self.max_s = max_attempts, initial_s, factor, max_s
        self.sleep = sleep or time.sleep

    def call(self, fn, ctx):
        delay = self.initial_s
        for attempt in range(1, self.max_attempts + 1):
            try:
                return fn()
            except ModelError as exc:
                if not exc.retryable or attempt == self.max_attempts:
                    raise
                ctx.event("retry", attempt=attempt, status=exc.status, error=str(exc)[:200])
                self.sleep(min(delay, self.max_s))
                delay *= self.factor
        raise AssertionError("unreachable")


# --- M13 Permissions (fixed) ------------------------------------------------
@register("M13", "allow_all", ORIGINAL)
class AllowAll(Permissions):
    """Headless allow-all (rows 26-29). Never asks, never auto-rejects. The
    container is the sandbox. ``deny_tools`` exists only so a parity arm can
    reproduce a harness that blocks a tool; refusals are logged."""

    def __init__(self, deny_tools: list[str] = (), path_guards: bool = False,
                 destructive_guard: bool = False):
        if path_guards or destructive_guard:
            raise ValueError("M13: path and destructive-command guards are fixed off (container sandbox)")
        self.deny = set(deny_tools)

    def check(self, tool, args, ctx):
        if tool in self.deny:
            ctx.event("permission_denied", tool=tool)
            return f"Permission denied for tool {tool}"
        return None


def environment(workdir: str) -> dict:
    return {"platform": os.uname().sysname.lower() if hasattr(os, "uname") else os.name,
            "is_git": (Path(workdir) / ".git").exists(),
            "date": time.strftime("%a %b %d %Y")}
