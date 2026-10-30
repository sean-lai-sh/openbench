"""OpenCode build ba54cee5 (sst/opencode, MIT) re-expressed as base-agent modules.

Researcher ruling 2026-10-30: the config targets ba54cee5, the build the
#196 OpenCode cells ran, not the sheet's c10134729d.

Sources (review criterion 1):
* system prompt: assets/opencode/anthropic.txt (session/prompt/anthropic.txt,
  byte-identical at ba54cee5 and c10134729d) plus the environment block of
  session/system.ts at ba54cee5;
* title side call: assets/opencode/title.txt (agent/prompt/title.txt);
* tool specs: assets/opencode/tools.json, taken verbatim from the real
  ba54cee5 capture in captures/opencode/ (zod -> JSON Schema output, tool
  descriptions from tool/*.txt, the task tool's agent list).

Deliberate deviation: for the anthropic provider, ba54cee5 starts the system
prompt with a Claude Code identity line (its own system block and again at the
top of the main block). Review criterion 1 bars Claude Code text, so the base
config does not send it. The AC3 build check reports the byte gap (~1.4% of
system bytes).
"""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path

from thesis.base_agent import tools as T
from thesis.base_agent.interfaces import Delegation, Editor, Planner, PromptAssembler, ToolError
from thesis.base_agent.modules import TitleCall, captured_tools, register, tool, tool_from_spec

PIN = "ba54cee55e18b47fb70badc84ae2cbac7c83d258"
SRC = f"sst/opencode@{PIN}:packages/opencode/src/"  # module sources (modules.register)
ASSETS = Path(__file__).resolve().parent / "assets" / "opencode"
SPECS = captured_tools(ASSETS / "tools.json")
MAX_LINES, MAX_BYTES = 2000, 50 * 1024  # tool/truncation.ts:10-11
DEFAULT_TIMEOUT_MS = 2 * 60 * 1000  # tool/bash.ts:22
SMALL_MODEL_DEFAULT = "anthropic/claude-haiku-4-5-20251001"  # data/opencode-harness-smoke/cell.py (#189)


def asset(name: str) -> str:
    return (ASSETS / name).read_text(encoding="utf-8")


@register("M1", "opencode", SRC + "session/system.ts")
class OpenCodePrompt(PromptAssembler):
    """session/system.ts at ba54cee5: anthropic.txt (provider prompt for a
    model id containing "claude") followed by the environment block, in one
    system block. session/llm.ts joins everything after the header with
    "\\n"; the header itself is the identity line this config leaves out."""

    def __init__(self, provider_id: str = "anthropic", context_files: bool = False, memory_files: bool = False):
        self.provider_id, self.context_files, self.memory_files = provider_id, context_files, memory_files

    def system_blocks(self, ctx, tools):
        env = ctx.env
        environment = "\n".join([
            f"You are powered by the model named {ctx.model}. The exact model ID is {self.provider_id}/{ctx.model}",
            "Here is some useful information about the environment you are running in:",
            "<env>",
            f"  Working directory: {ctx.workdir}",
            f"  Is directory a git repo: {'yes' if env.get('is_git') else 'no'}",
            f"  Platform: {env.get('platform', 'linux')}",
            f"  Today's date: {env.get('date', '')}",
            "</env>",
            "<directories>",
            "  ",
            "</directories>",
        ])
        return [asset("anthropic.txt") + "\n" + environment]


@tool("opencode", "bash", SRC + "tool/bash.ts")
def _bash(p):
    def run(a, ctx):
        if not isinstance(a.get("command"), str):
            raise ToolError("command is required")
        wd = str(T.resolve(ctx.workdir, a["workdir"])) if a.get("workdir") else ctx.workdir
        return ctx.executor.format(ctx.executor.run(a["command"], wd, a.get("timeout")))
    return tool_from_spec(SPECS["bash"], run)


@tool("opencode", "read", SRC + "tool/read.ts")
def _read(p):
    return tool_from_spec(SPECS["read"], lambda a, ctx: T.read_file(
        ctx.workdir, a.get("filePath"), a.get("offset"), a.get("limit"), MAX_LINES, MAX_BYTES, numbered=True))


@tool("opencode", "glob", SRC + "tool/glob.ts")
def _glob(p):
    return tool_from_spec(SPECS["glob"], lambda a, ctx: T.glob_files(ctx.workdir, a.get("pattern"), a.get("path")))


@tool("opencode", "grep", SRC + "tool/grep.ts")
def _grep(p):
    return tool_from_spec(SPECS["grep"], lambda a, ctx: T.grep_files(
        ctx.workdir, a.get("pattern"), a.get("path"), a.get("include")))


@tool("opencode", "write", SRC + "tool/write.ts")
def _write(p):
    return tool_from_spec(SPECS["write"], lambda a, ctx: T.write_file(ctx.workdir, a.get("filePath"), a.get("content")))


@tool("opencode", "webfetch", SRC + "tool/webfetch.ts")
def _webfetch(p):
    def run(a, ctx):
        url = a.get("url") or ""
        if not url.startswith(("http://", "https://")):
            raise ToolError("URL must start with http:// or https://")
        timeout = min(float(a.get("timeout") or 30), 120)
        try:
            with urllib.request.urlopen(url, timeout=timeout) as r:
                body = r.read(5 * 1024 * 1024).decode("utf-8", "replace")
        except OSError as exc:
            raise ToolError(f"fetch failed: {exc}") from exc
        return T.truncate(body, MAX_LINES, MAX_BYTES, "head")[0]
    return tool_from_spec(SPECS["webfetch"], run)


@tool("opencode", "skill", SRC + "tool/skill.ts")
def _skill(p):
    def run(a, ctx):
        raise ToolError(f"Skill \"{a.get('name')}\" not found. No skills are available.")
    return tool_from_spec(SPECS["skill"], run)


@tool("opencode", "question", SRC + "tool/question.ts")
def _question(p):
    def run(a, ctx):
        raise ToolError("The user dismissed this question (headless run: no user is available).")
    return tool_from_spec(SPECS["question"], run)


@register("M7", "opencode_edit", SRC + "tool/edit.ts")
class OpenCodeEdit(Editor):
    """tool/edit.ts: one exact oldString -> newString replacement, or every
    occurrence with replaceAll."""

    def tools(self, ctx):
        return [tool_from_spec(SPECS["edit"], lambda a, c: T.replace_exact(
            c.workdir, a.get("filePath"), a.get("oldString"), a.get("newString"), bool(a.get("replaceAll"))),
            slot="M7")]


@register("M9", "opencode_todowrite", SRC + "tool/todo.ts")
class OpenCodeTodo(Planner):
    """tool/todo.ts: the model rewrites the whole todo list each call."""

    def tools(self, ctx):
        def run(a, c):
            todos = a.get("todos")
            if not isinstance(todos, list):
                raise ToolError("todos must be an array")
            c.todos = todos
            c.event("todowrite", open=sum(1 for t in todos if (t or {}).get("status") != "completed"))
            return json.dumps(todos, indent=2)
        return [tool_from_spec(SPECS["todowrite"], run, slot="M9")]


@register("M10", "opencode_task", SRC + "tool/task.ts")
class OpenCodeTask(Delegation):
    """tool/task.ts: run a subagent in a fresh context and return its final
    text. ``subagent_type`` is accepted; every subagent runs with the
    parent's modules minus planner and delegation (OpenCode's ``general``
    agent). ``task_id`` resume is not reproduced."""

    def tools(self, ctx):
        if ctx.depth > 0:
            return []

        def run(a, c):
            if not isinstance(a.get("prompt"), str) or c.spawn is None:
                raise ToolError("prompt is required")
            text = c.spawn(a.get("description") or "", a["prompt"])
            return f"task_id: sub-{len(c.events)}\n\n<task_result>\n{text}\n</task_result>"
        return [tool_from_spec(SPECS["task"], run, slot="M10")]


@register("M5", "opencode_title", SRC + "session/prompt.ts")
class OpenCodeTitle(TitleCall):
    """session/prompt.ts: one title request per session with the title
    agent's prompt (agent/prompt/title.txt) on the small model. #189 pins
    the small model to the main comparison model (Sonnet 5.5) instead of
    OpenCode's Haiku default and writes ``small_model_deviation=true`` on the
    row; this module records the same fields."""

    def __init__(self, max_tokens: int = 1024, model: str | None = None,
                 small_model_default: str = SMALL_MODEL_DEFAULT, provider_id: str = "anthropic"):
        super().__init__(system=asset("title.txt"), max_tokens=max_tokens, model=model)
        self.small_model_default, self.provider_id = small_model_default, provider_id

    def row_fields(self) -> dict:
        ref = f"{self.provider_id}/{self.model}" if self.model else None
        return {"small_model": ref, "small_model_default": self.small_model_default,
                "small_model_deviation": bool(ref) and ref != self.small_model_default}
