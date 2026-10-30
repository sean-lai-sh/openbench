"""OpenCode (sst/opencode @ c10134729d, MIT) re-expressed as base-agent modules.

Text is vendored byte for byte under assets/opencode/ (see assets/SOURCE.md).
Parameter schemas are transcribed from the Effect Schema definitions in
packages/opencode/src/tool/*.ts at that pin. Effect's JSON Schema output
(key order, ``additionalProperties``, integer bounds) is approximated; the
AC3 build check measures the difference at the proxy.

Two schemas live outside the tool files and are reconstructed, not
transcribed: ``Todo.Info`` (session/todo.ts -> core SessionTodo) and
``Question.Prompt`` (question/index.ts -> core QuestionV1).
"""
from __future__ import annotations

import json
import re
import urllib.request
from pathlib import Path

from thesis.base_agent import tools as T
from thesis.base_agent.interfaces import Delegation, Editor, Planner, PromptAssembler, Tool, ToolError
from thesis.base_agent.modules import TitleCall, find_context_files, register, tool

PIN = "c10134729dd2ce00beb18604ec91f10319f59a78"
SRC = f"sst/opencode@{PIN}:packages/opencode/src/"  # module sources (modules.register)
ASSETS = Path(__file__).resolve().parent / "assets" / "opencode"
MAX_LINES, MAX_BYTES = 2000, 50 * 1024  # tool/truncate.ts:14-15
DEFAULT_TIMEOUT_MS = 2 * 60 * 1000  # tool/shell.ts:347


def asset(name: str) -> str:
    return (ASSETS / name).read_text(encoding="utf-8")


@register("M1", "opencode", SRC + "session/system.ts")
class OpenCodePrompt(PromptAssembler):
    """session/system.ts: the per-family provider prompt (anthropic.txt for a
    model id containing "claude") as block 1; environment, skills and
    AGENTS.md/CLAUDE.md instructions joined as block 2."""

    def __init__(self, provider_id: str = "anthropic", context_files: bool = True, memory_files: bool = False,
                 skills_text: str = "No skills are currently available."):
        self.provider_id, self.context_files, self.memory_files = provider_id, context_files, memory_files
        self.skills_text = skills_text

    def system_blocks(self, ctx, tools):
        env = ctx.env
        parts = ["\n".join([
            f"You are powered by the model named {ctx.model}. The exact model ID is {self.provider_id}/{ctx.model}",
            "Here is some useful information about the environment you are running in:",
            "<env>",
            f"  Working directory: {ctx.workdir}",
            f"  Workspace root folder: {ctx.workdir}",
            f"  Is directory a git repo: {'yes' if env.get('is_git') else 'no'}",
            f"  Platform: {env.get('platform', 'linux')}",
            f"  Today's date: {env.get('date', '')}",
            "</env>",
        ])]
        if any(t.name == "skill" for t in tools):
            parts.append("\n".join([
                "Skills provide specialized instructions and workflows for specific tasks.",
                "Use the skill tool to load a skill when a task matches its description.",
                self.skills_text]))
        if self.context_files:
            for f in find_context_files(ctx.workdir):
                parts.append(f"Instructions from: {f['path']}\n{f['content']}")
        return [asset("anthropic.txt"), "\n".join(parts)]


def _s(desc: str, **kw) -> dict:
    return {"type": "string", "description": desc, **kw}


def _obj(props: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": props, "required": required, "additionalProperties": False}


def _nonneg(desc: str) -> dict:
    return {"type": "integer", "minimum": 0, "description": desc}


def shell_description(platform: str = "linux", shell: str = "bash", tmp: str = "/tmp/opencode") -> str:
    """tool/shell/prompt.ts render() for bash: fills shell.txt."""
    chain = ("If the commands depend on each other and must run sequentially, use a single Bash call with '&&' to chain them together (e.g., `git add . && git commit -m \"message\" && git push`). "
             "For instance, if one operation must complete before another starts (like mkdir before cp, Write before Bash for git operations, or git add before git commit), run these operations sequentially instead.")
    command = asset("tool-shell-command.txt").replace("${chain}", chain) \
        .replace("${maxLines}", str(MAX_LINES)).replace("${maxBytes}", str(MAX_BYTES)) \
        .replace("${defaultTimeoutMs}", str(DEFAULT_TIMEOUT_MS))
    values = {
        "intro": "Executes a given bash command in a persistent shell session with optional timeout, ensuring proper handling and security measures.",
        "os": platform, "shell": shell, "tmp": tmp,
        "workdirSection": "All commands run in the current working directory by default. Use the `workdir` parameter if you need to run a command in a different directory. AVOID using `cd <directory> && <command>` patterns - use `workdir` instead.",
        "commandSection": command,
    }
    return re.sub(r"\$\{(\w+)\}", lambda m: values[m.group(1)], asset("tool-shell.txt"))


@tool("opencode", "bash", SRC + "tool/shell.ts")
def _bash(p):
    def run(a, ctx):
        if not isinstance(a.get("command"), str):
            raise ToolError("command is required")
        wd = str(T.resolve(ctx.workdir, a["workdir"])) if a.get("workdir") else ctx.workdir
        return ctx.executor.format(ctx.executor.run(a["command"], wd, a.get("timeout")))
    return Tool("bash", shell_description(p.get("platform", "linux"), "bash", p.get("tmp", "/tmp/opencode")),
                _obj({"command": _s("The command to execute"),
                      "timeout": {"type": "integer", "exclusiveMinimum": 0, "description": "Optional timeout in milliseconds"},
                      "workdir": _s("The working directory to run the command in. Defaults to the current directory. Use this instead of 'cd' commands.")},
                     ["command"]), run)


@tool("opencode", "read", SRC + "tool/read.ts")
def _read(p):
    def run(a, ctx):
        return T.read_file(ctx.workdir, a.get("filePath"), a.get("offset"), a.get("limit"),
                           MAX_LINES, MAX_BYTES, numbered=True)
    return Tool("read", asset("tool-read.txt"),
                _obj({"filePath": _s("The absolute path to the file or directory to read"),
                      "offset": _nonneg("The line number to start reading from (1-indexed)"),
                      "limit": _nonneg("The maximum number of lines to read (defaults to 2000)")}, ["filePath"]), run)


@tool("opencode", "glob", SRC + "tool/glob.ts")
def _glob(p):
    return Tool("glob", asset("tool-glob.txt"),
                _obj({"pattern": _s("The glob pattern to match files against"),
                      "path": _s('The directory to search in. If not specified, the current working directory will be used. IMPORTANT: Omit this field to use the default directory. DO NOT enter "undefined" or "null" - simply omit it for the default behavior. Must be a valid directory path if provided.')},
                     ["pattern"]),
                lambda a, ctx: T.glob_files(ctx.workdir, a.get("pattern"), a.get("path")))


@tool("opencode", "grep", SRC + "tool/grep.ts")
def _grep(p):
    return Tool("grep", asset("tool-grep.txt"),
                _obj({"pattern": _s("The regex pattern to search for in file contents"),
                      "path": _s("The directory to search in. Defaults to the current working directory."),
                      "include": _s('File pattern to include in the search (e.g. "*.js", "*.{ts,tsx}")')},
                     ["pattern"]),
                lambda a, ctx: T.grep_files(ctx.workdir, a.get("pattern"), a.get("path"), a.get("include")))


@tool("opencode", "write", SRC + "tool/write.ts")
def _write(p):
    return Tool("write", asset("tool-write.txt"),
                _obj({"content": _s("The content to write to the file"),
                      "filePath": _s("The absolute path to the file to write (must be absolute, not relative)")},
                     ["content", "filePath"]),
                lambda a, ctx: T.write_file(ctx.workdir, a.get("filePath"), a.get("content")))


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
    return Tool("webfetch", asset("tool-webfetch.txt"),
                _obj({"url": _s("The URL to fetch content from"),
                      "format": {"type": "string", "enum": ["text", "markdown", "html"], "default": "markdown",
                                 "description": "The format to return the content in (text, markdown, or html). Defaults to markdown."},
                      "timeout": {"type": "number", "description": "Optional timeout in seconds (max 120)"}},
                     ["url", "format"]), run)


@tool("opencode", "skill", SRC + "tool/skill.ts")
def _skill(p):
    def run(a, ctx):
        raise ToolError(f"Skill \"{a.get('name')}\" not found. No skills are available.")
    return Tool("skill", asset("tool-skill.txt"),
                _obj({"name": _s("The name of the skill from available_skills")}, ["name"]), run)


@tool("opencode", "question", SRC + "tool/question.ts")
def _question(p):
    def run(a, ctx):
        raise ToolError("The user dismissed this question (headless run: no user is available).")
    option = _obj({"label": _s("Display text (1-5 words, concise)"),
                   "description": _s("Explanation of choice")}, ["label", "description"])
    prompt = _obj({"question": _s("Complete question"),
                   "header": _s("Very short label (max 30 chars)"),
                   "options": {"type": "array", "items": option, "description": "Available choices"},
                   "multiple": {"type": "boolean", "description": "Allow selecting multiple choices"}},
                  ["question", "header", "options"])
    return Tool("question", asset("tool-question.txt"),
                _obj({"questions": {"type": "array", "items": prompt, "description": "Questions to ask"}},
                     ["questions"]), run)


@register("M7", "opencode_edit", SRC + "tool/edit.ts")
class OpenCodeEdit(Editor):
    """tool/edit.ts: one exact oldString -> newString replacement, or every
    occurrence with replaceAll."""

    def tools(self, ctx):
        schema = _obj({"filePath": _s("The absolute path to the file to modify"),
                       "oldString": _s("The text to replace"),
                       "newString": _s("The text to replace it with (must be different from oldString)"),
                       "replaceAll": {"type": "boolean", "description": "Replace all occurrences of oldString (default false)"}},
                      ["filePath", "oldString", "newString"])
        return [Tool("edit", asset("tool-edit.txt"), schema,
                     lambda a, c: T.replace_exact(c.workdir, a.get("filePath"), a.get("oldString"),
                                                  a.get("newString"), bool(a.get("replaceAll"))))]


@register("M9", "opencode_todowrite", SRC + "tool/todo.ts")
class OpenCodeTodo(Planner):
    """tool/todo.ts: the model rewrites the whole todo list each call."""

    def tools(self, ctx):
        item = _obj({"content": _s("Brief description of the task"),
                     "status": _s("Current status of the task: pending, in_progress, completed, cancelled"),
                     "priority": _s("Priority level of the task: high, medium, low")},
                    ["content", "status", "priority"])

        def run(a, c):
            todos = a.get("todos")
            if not isinstance(todos, list):
                raise ToolError("todos must be an array")
            c.todos = todos
            c.event("todowrite", open=sum(1 for t in todos if (t or {}).get("status") != "completed"))
            return json.dumps(todos, indent=2)
        return [Tool("todowrite", asset("tool-todowrite.txt"),
                     _obj({"todos": {"type": "array", "items": item, "description": "The updated todo list"}}, ["todos"]),
                     run)]


@register("M10", "opencode_task", SRC + "tool/task.ts")
class OpenCodeTask(Delegation):
    """tool/task.ts: run a subagent in a fresh context and return its final
    text. ``subagent_type`` and ``background`` are accepted; every subagent
    runs in the foreground with the parent's modules minus planner and
    delegation (OpenCode's ``general`` agent)."""

    AGENTS = {
        "explore": 'Fast agent specialized for exploring codebases. Use this when you need to quickly find files by patterns (eg. "src/components/**/*.tsx"), search code for keywords (eg. "API endpoints"), or answer questions about the codebase (eg. "how do API endpoints work?"). When calling this agent, specify the desired thoroughness level: "quick" for basic searches, "medium" for moderate exploration, or "very thorough" for comprehensive analysis across multiple locations and naming conventions.',
        "general": "General-purpose agent for researching complex questions and executing multi-step tasks. Use this agent to execute multiple units of work in parallel.",
    }

    def tools(self, ctx):
        if ctx.depth > 0:
            return []
        listing = "\n".join(f"- {k}: {v}" for k, v in sorted(self.AGENTS.items()))
        description = "\n".join([asset("tool-task.txt"),
                                 "Available agent types and the tools they have access to:\n" + listing])
        schema = _obj({
            "description": _s("A short (3-5 words) description of the task"),
            "prompt": _s("The task for the agent to perform"),
            "subagent_type": _s("The type of specialized agent to use for this task"),
            "task_id": _s("This should only be set if you mean to resume a previous task (you can pass a prior task_id and the task will continue the same subagent session as before instead of creating a fresh one)"),
            "command": _s("The command that triggered this task"),
            "background": {"type": "boolean", "description": "Run the agent in the background. You will be notified when it completes. DO NOT sleep, poll, or proactively check on its progress"},
        }, ["description", "prompt", "subagent_type"])

        def run(a, c):
            if not isinstance(a.get("prompt"), str) or c.spawn is None:
                raise ToolError("prompt is required")
            text = c.spawn(a.get("description") or "", a["prompt"])
            return f'<task id="sub-{len(c.events)}" state="completed">\n<task_result>\n{text}\n</task_result>\n</task>'
        return [Tool("task", description, schema, run)]


@register("M5", "opencode_title", SRC + "session/prompt.ts")
class OpenCodeTitle(TitleCall):
    """session/prompt.ts:216-252: one title request per session with the
    title agent's prompt (agent/prompt/title.txt). The real runs pin
    small_model to the main model (``small_model_deviation=true``), so
    ``model`` defaults to the main model."""

    def __init__(self, max_tokens: int = 1024, model: str | None = None):
        super().__init__(system=asset("title.txt"), max_tokens=max_tokens, model=model)
