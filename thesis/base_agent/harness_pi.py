"""Pi (badlogic/pi-mono @ d0aa218, MIT) re-expressed as base-agent modules.

Sources (review criterion 1):
* system prompt: strings copied from packages/coding-agent/src/core/
  system-prompt.ts and core/tools/*.ts (snippets, guidelines) at the pin;
* tool specs (name, description, schema, strict / eager_input_streaming /
  defer_loading): assets/pi/tools.json, taken verbatim from the real Pi
  capture in captures/pi/ (see assets/SOURCE.md). Pi's pi-ai layer rewrites
  its TypeBox schemas for strict mode (every property required, optional
  ones nullable) and adds a deferred placeholder tool, so the wire form is
  read from the capture rather than transcribed.

Only Pi's default tool set (read, bash, edit, write; settings-manager.ts:85)
is reproduced. The docs paths in the prompt depend on where Pi is installed;
``RunContext.env["pi_install_root"]`` overrides ``install_root`` the way the
workdir overrides cwd.
"""
from __future__ import annotations

from pathlib import Path

from thesis.base_agent import tools as T
from thesis.base_agent.interfaces import Editor, PromptAssembler, ToolError
from thesis.base_agent.modules import captured_tools, find_context_files, register, tool, tool_from_spec

PIN = "d0aa218cb16c333c008f6aa3dcd670ac8b68383c"
SRC = f"badlogic/pi-mono@{PIN}:packages/coding-agent/src/core/"  # module sources (modules.register)
MAX_LINES, MAX_BYTES = 2000, 50 * 1024  # core/tools/truncate.ts:11-12

PREAMBLE = ("You are an expert coding assistant operating inside pi, a coding agent harness. "
            "You help users by reading files, executing commands, editing code, and writing new files.")

# core/tools/*.ts: promptSnippet and promptGuidelines per tool.
SNIPPETS = {
    "read": "Read file contents",
    "bash": "Execute bash commands (ls, grep, find, etc.)",
    "edit": "Make precise file edits with exact text replacement, including multiple disjoint edits in one call",
    "write": "Create or overwrite files",
}
GUIDELINES = {
    "read": ["Use read to examine files instead of cat or sed."],
    "bash": ["You can inspect PI_* environment variables for current model and session details."],
    "edit": [
        "Use edit for precise changes (edits[].oldText must match exactly)",
        "When changing multiple separate locations in one file, use one edit call with multiple entries in edits[] instead of multiple edit calls",
        "Each edits[].oldText is matched against the original file, not after earlier edits are applied. Do not emit overlapping or nested edits. Merge nearby changes into one edit.",
        "Keep edits[].oldText as small as possible while still being unique in the file. Do not pad with large unchanged regions.",
    ],
    "write": ["Use write only for new files or complete rewrites."],
}


def _docs(root: str) -> str:
    return f"""Pi documentation (read only when the user asks about pi itself, its SDK, extensions, themes, skills, or TUI):
- Main documentation: {root}/README.md
- Additional docs: {root}/docs
- Examples: {root}/examples (extensions, custom tools, SDK)
- When reading pi docs or examples, resolve docs/... under Additional docs and examples/... under Examples, not the current working directory
- When asked about: extensions (docs/extensions.md, examples/extensions/), themes (docs/themes.md), skills (docs/skills.md), prompt templates (docs/prompt-templates.md), TUI components (docs/tui.md), keybindings (docs/keybindings.md), SDK integrations (docs/sdk.md), custom providers (docs/custom-provider.md), adding models (docs/models.md), pi packages (docs/packages.md), environment variables (docs/environment-variables.md), MCP servers (docs/mcp.md), codemode scripts and non-LLM models such as classifiers and image models (docs/codemode.md)
- When working on pi topics, read the docs and examples, and follow .md cross-references before implementing
- Always read pi .md files completely and follow links to related docs (e.g., tui.md for TUI API details)"""


def _rules(names: list[str]) -> str:
    rules: list[str] = []

    def add(rule: str) -> None:
        if rule.strip() and rule.strip() not in rules:
            rules.append(rule.strip())

    if "bash" in names and not ({"grep", "find", "ls"} & set(names)):
        add("Use bash for file operations like ls, rg, find")
    for n in names:
        for r in GUIDELINES.get(n, []):
            add(r)
    add("Be concise in your responses")
    add("Show file paths clearly when working with files")
    return "\n".join(f"- {r}" for r in rules)


@register("M1", "pi", SRC + "system-prompt.ts")
class PiPrompt(PromptAssembler):
    """system-prompt.ts buildSystemPromptSections: preamble, then tagged
    tools / rules / docs / project_context / cwd sections."""

    def __init__(self, install_root: str = "/usr/local/lib/node_modules/@earendil-works/pi-coding-agent",
                 context_files: bool = True, memory_files: bool = False, joiner: str = "\n\n"):
        self.root, self.context_files, self.memory_files, self.joiner = install_root, context_files, memory_files, joiner

    def system_blocks(self, ctx, tools):
        names = [t.name for t in tools]
        visible = [n for n in names if n in SNIPPETS]
        tool_lines = "\n".join(f"- {n}: {SNIPPETS[n]}" for n in visible) or "(none)"
        sections = {
            "tools": f"{tool_lines}\n\nIn addition to the tools above, you may have access to other custom tools depending on the project.",
            "rules": _rules(names),
            "docs": _docs(ctx.env.get("pi_install_root", self.root)),
        }
        if self.context_files:
            files = find_context_files(ctx.workdir)
            if files:
                sections["project_context"] = "\n\n".join(
                    ["Project-specific instructions and guidelines:"]
                    + [f'<project_instructions path="{f["path"]}">\n{f["content"]}\n</project_instructions>' for f in files])
        sections["cwd"] = ctx.workdir.replace("\\", "/")
        parts = [PREAMBLE] + [f"<{k}>\n{v}\n</{k}>" for k, v in sections.items()]
        return [self.joiner.join(parts)]


ASSETS = Path(__file__).resolve().parent / "assets" / "pi"
SPECS = captured_tools(ASSETS / "tools.json")


def _nullable(v):
    return None if v is None else v


@tool("pi", "read", SRC + "tools/read.ts")
def _read(p):
    def run(a, ctx):
        return T.read_file(ctx.workdir, a.get("path"), _nullable(a.get("offset")), _nullable(a.get("limit")),
                           MAX_LINES, MAX_BYTES)
    return tool_from_spec(SPECS["read"], run)


@tool("pi", "bash", SRC + "tools/bash.ts")
def _bash(p):
    def run(a, ctx):
        if not isinstance(a.get("command"), str):
            raise ToolError("command is required")
        return ctx.executor.format(ctx.executor.run(a["command"], ctx.workdir, _nullable(a.get("timeout"))))
    return tool_from_spec(SPECS["bash"], run)


@tool("pi", "write", SRC + "tools/write.ts")
def _write(p):
    return tool_from_spec(SPECS["write"], lambda a, ctx: T.write_file(ctx.workdir, a.get("path"), a.get("content")))


@tool("pi", "__pi_deferred_placeholder__", SRC + "tools/index.ts")
def _placeholder(p):
    def run(a, ctx):
        raise ToolError("This tool is a reserved placeholder and is never available.")
    return tool_from_spec(SPECS["__pi_deferred_placeholder__"], run)


@register("M7", "pi_edit", SRC + "tools/edit.ts")
class PiEdit(Editor):
    """core/tools/edit.ts: one file, edits[] of exact oldText/newText pairs,
    each unique and non-overlapping in the original file."""

    def tools(self, ctx):
        return [tool_from_spec(SPECS["edit"], lambda a, c: T.replace_many(c.workdir, a.get("path"), a.get("edits")),
                               slot="M7")]
