"""Pi (badlogic/pi-mono @ d0aa218, MIT) re-expressed as base-agent modules.

Prompt and tool strings are copied from packages/coding-agent/src/core/
system-prompt.ts and core/tools/{read,bash,edit,write}.ts at that pin; see
assets/SOURCE.md and assets/pi/LICENSE. Only Pi's default tool set
(read, bash, edit, write; settings-manager.ts:85) is reproduced.

Known gaps, to be measured by the AC3 build check rather than guessed:
* how pi-ai joins prompt sections (assumed "\\n\\n");
* whether pi-ai sends the read tool's outputSchema to Anthropic (not sent here);
* the docs paths, which depend on where Pi is installed in the runner image
  (``install_root``).
"""
from __future__ import annotations

from thesis.base_agent import tools as T
from thesis.base_agent.interfaces import Editor, PromptAssembler, Tool, ToolError
from thesis.base_agent.modules import find_context_files, register, tool

PIN = "d0aa218cb16c333c008f6aa3dcd670ac8b68383c"
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


@register("M1", "pi")
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
            "docs": _docs(self.root),
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


def _obj(props: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": props, "required": required}


@tool("pi", "read")
def _read(p):
    def run(a, ctx):
        return T.read_file(ctx.workdir, a.get("path"), a.get("offset"), a.get("limit"), MAX_LINES, MAX_BYTES)
    return Tool("read",
                f"Read the contents of a file. Supports text files and images (jpg, png, gif, webp, bmp). Images are sent as attachments. For text files, output is truncated to {MAX_LINES} lines or {MAX_BYTES // 1024}KB (whichever is hit first). Use offset/limit for large files. When you need the full file, continue with offset until complete.",
                _obj({"path": {"description": "Path to the file to read (relative or absolute)", "type": "string"},
                      "offset": {"description": "Line number to start reading from (1-indexed)", "type": "number"},
                      "limit": {"description": "Maximum number of lines to read", "type": "number"}}, ["path"]), run)


@tool("pi", "bash")
def _bash(p):
    def run(a, ctx):
        if not isinstance(a.get("command"), str):
            raise ToolError("command is required")
        return ctx.executor.format(ctx.executor.run(a["command"], ctx.workdir, a.get("timeout")))
    return Tool("bash",
                f"Execute a bash command in the current working directory. Returns stdout and stderr. Output is truncated to last {MAX_LINES} lines or {MAX_BYTES // 1024}KB (whichever is hit first). If truncated, full output is saved to a temp file. Optionally provide a timeout in seconds.",
                _obj({"command": {"description": "Shell command to execute", "type": "string"},
                      "timeout": {"description": "Timeout in seconds (optional, no default timeout)", "type": "number"}},
                     ["command"]), run)


@tool("pi", "write")
def _write(p):
    return Tool("write",
                "Write content to a file. Creates the file if it doesn't exist, overwrites if it does. Automatically creates parent directories.",
                _obj({"path": {"description": "Path to the file to write (relative or absolute)", "type": "string"},
                      "content": {"description": "Content to write to the file", "type": "string"}},
                     ["path", "content"]),
                lambda a, ctx: T.write_file(ctx.workdir, a.get("path"), a.get("content")))


@register("M7", "pi_edit")
class PiEdit(Editor):
    """core/tools/edit.ts: one file, edits[] of exact oldText/newText pairs,
    each unique and non-overlapping in the original file."""

    def tools(self, ctx):
        schema = _obj({
            "path": {"description": "Path to the file to edit (relative or absolute)", "type": "string"},
            "edits": {"description": "One or more targeted replacements. Each edit is matched against the original file, not incrementally. Do not include overlapping or nested edits. If two changes touch the same block or nearby lines, merge them into one edit instead.",
                      "type": "array",
                      "items": _obj({"oldText": {"description": "Exact text for one targeted replacement. It must be unique in the original file and must not overlap with any other edits[].oldText in the same call.", "type": "string"},
                                     "newText": {"description": "Replacement text for this targeted edit.", "type": "string"}},
                                    ["oldText", "newText"])},
        }, ["path", "edits"])
        return [Tool("edit",
                     "Edit a single file using exact text replacement. Every edits[].oldText must match a unique, non-overlapping region of the original file. If two changes affect the same block or nearby lines, merge them into one edit instead of emitting overlapping edits. Do not include large unchanged regions just to connect distant changes.",
                     schema, lambda a, c: T.replace_many(c.workdir, a.get("path"), a.get("edits")))]
