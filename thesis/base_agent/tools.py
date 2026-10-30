"""File and shell primitives behind the tool modules.

Tool *specs* (name, description, JSON schema) belong to the module that
exposes them; these functions are the shared behaviour underneath, so two
configs that expose the same operation under different schemas run the same
code. Errors raise ``ToolError``; the loop sends the text back with
``is_error``.
"""
from __future__ import annotations

import fnmatch
import os
import re
import shutil
import signal
import subprocess
from pathlib import Path

from thesis.base_agent.interfaces import ExecResult, ToolError


def resolve(workdir: str, path: str) -> Path:
    if not isinstance(path, str) or not path:
        raise ToolError("path is required")
    p = Path(path)
    return p if p.is_absolute() else Path(workdir) / p


def truncate(text: str, max_lines: int | None, max_bytes: int | None, keep: str = "head") -> tuple[str, bool]:
    """Cut ``text`` to at most ``max_lines`` lines and ``max_bytes`` UTF-8
    bytes, keeping the head or the tail. Cuts on line boundaries."""
    lines = text.split("\n")
    truncated = False
    if max_lines is not None and len(lines) > max_lines:
        lines = lines[:max_lines] if keep == "head" else lines[-max_lines:]
        truncated = True
    if max_bytes is not None:
        kept: list[str] = []
        size = 0
        seq = lines if keep == "head" else list(reversed(lines))
        for line in seq:
            n = len(line.encode("utf-8")) + 1
            if size + n > max_bytes:
                truncated = True
                break
            kept.append(line)
            size += n
        lines = kept if keep == "head" else list(reversed(kept))
    return "\n".join(lines), truncated


def read_file(workdir: str, path: str, offset: int | None = None, limit: int | None = None,
              max_lines: int = 2000, max_bytes: int = 50 * 1024, numbered: bool = False) -> str:
    p = resolve(workdir, path)
    if p.is_dir():
        entries = sorted(e.name + ("/" if e.is_dir() else "") for e in p.iterdir())
        return "\n".join(entries)
    if not p.exists():
        raise ToolError(f"File not found: {p}")
    text = p.read_text(encoding="utf-8", errors="replace")
    lines = text.split("\n")
    start = max(int(offset or 1), 1)
    if start > len(lines) and lines != [""]:
        raise ToolError(f"Offset {start} is beyond end of file ({len(lines)} lines total)")
    count = min(int(limit), max_lines) if limit else max_lines
    window = lines[start - 1:start - 1 + count]
    if numbered:
        window = [f"{start + i}: {line}" for i, line in enumerate(window)]
    body, cut = truncate("\n".join(window), None, max_bytes, "head")
    end = start + len(body.split("\n")) - 1
    if cut or end < len(lines):
        body += f"\n\n[Showing lines {start}-{end} of {len(lines)}. Use offset={end + 1} to continue.]"
    return body


def write_file(workdir: str, path: str, content: str) -> str:
    p = resolve(workdir, path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content if isinstance(content, str) else "", encoding="utf-8")
    return f"Wrote {len(content.encode('utf-8'))} bytes to {p}"


def replace_exact(workdir: str, path: str, old: str, new: str, replace_all: bool = False) -> str:
    p = resolve(workdir, path)
    if old == new:
        raise ToolError("No changes to apply: old and new text are identical.")
    if old == "":
        if p.exists() and p.read_text(encoding="utf-8", errors="replace"):
            raise ToolError("old text is empty but the file already has content")
        return write_file(workdir, path, new)
    if not p.exists():
        raise ToolError(f"File not found: {p}")
    text = p.read_text(encoding="utf-8", errors="replace")
    n = text.count(old)
    if n == 0:
        raise ToolError("Could not find the text to replace in the file.")
    if n > 1 and not replace_all:
        raise ToolError(f"Found {n} matches for the text to replace; add context to make it unique or set replace all.")
    p.write_text(text.replace(old, new) if replace_all else text.replace(old, new, 1), encoding="utf-8")
    return f"Edited {p}"


def replace_many(workdir: str, path: str, edits: list[dict]) -> str:
    """Pi semantics: every edit is matched against the original file, must be
    unique, and must not overlap another edit."""
    p = resolve(workdir, path)
    if not p.exists():
        raise ToolError(f"File not found: {p}")
    if not isinstance(edits, list) or not edits:
        raise ToolError("edits must be a non-empty array")
    text = p.read_text(encoding="utf-8", errors="replace")
    spans = []
    for i, e in enumerate(edits):
        old, new = (e or {}).get("oldText"), (e or {}).get("newText")
        if not isinstance(old, str) or not isinstance(new, str) or not old:
            raise ToolError(f"edits[{i}] needs non-empty oldText and newText")
        n = text.count(old)
        if n != 1:
            raise ToolError(f"edits[{i}].oldText matched {n} times; it must match exactly once")
        start = text.index(old)
        spans.append((start, start + len(old), new, i))
    spans.sort()
    for a, b in zip(spans, spans[1:]):
        if b[0] < a[1]:
            raise ToolError(f"edits[{a[3]}] and edits[{b[3]}] overlap; merge them into one edit")
    out, pos = [], 0
    for start, end, new, _ in spans:
        out += [text[pos:start], new]
        pos = end
    out.append(text[pos:])
    p.write_text("".join(out), encoding="utf-8")
    return f"Successfully replaced {len(spans)} block(s) in {p}."


def glob_files(workdir: str, pattern: str, path: str | None = None, limit: int = 100) -> str:
    root = resolve(workdir, path) if path else Path(workdir)
    if not root.is_dir():
        raise ToolError(f"glob path must be a directory: {root}")
    hits = [p for p in root.rglob("*") if p.is_file() and (
        fnmatch.fnmatch(str(p.relative_to(root)), pattern) or fnmatch.fnmatch(p.name, pattern))]
    hits.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    if not hits:
        return "No files found"
    out = [str(p) for p in hits[:limit]]
    if len(hits) > limit:
        out.append(f"\n(Results are truncated: showing first {limit} results.)")
    return "\n".join(out)


def grep_files(workdir: str, pattern: str, path: str | None = None, include: str | None = None,
               limit: int = 100) -> str:
    root = resolve(workdir, path) if path else Path(workdir)
    rg = shutil.which("rg")
    if rg:
        cmd = [rg, "-n", "--no-heading", "-e", pattern]
        if include:
            cmd += ["--glob", include]
        proc = subprocess.run(cmd + [str(root)], capture_output=True, text=True, timeout=60)
        if proc.returncode not in (0, 1):
            raise ToolError(proc.stderr.strip() or "grep failed")
        lines = proc.stdout.splitlines()
    else:
        try:
            rx = re.compile(pattern)
        except re.error as exc:
            raise ToolError(f"invalid regex: {exc}") from exc
        lines = []
        files = [root] if root.is_file() else sorted(p for p in root.rglob("*") if p.is_file())
        for f in files:
            if include and not fnmatch.fnmatch(f.name, include):
                continue
            try:
                for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                    if rx.search(line):
                        lines.append(f"{f}:{i}:{line}")
            except (UnicodeDecodeError, OSError):
                continue
    if not lines:
        return "No files found"
    out = lines[:limit]
    if len(lines) > limit:
        out.append(f"\n(Results are truncated: showing first {limit} matches.)")
    return "\n".join(out)


def run_shell(command: str, cwd: str, timeout_s: float | None) -> ExecResult:
    """``bash -c`` in its own process group; the whole group is killed on
    timeout. stdout and stderr are combined in arrival order."""
    proc = subprocess.Popen(["bash", "-c", command], cwd=cwd, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                            start_new_session=True)
    try:
        out, _ = proc.communicate(timeout=timeout_s)
        return ExecResult(out.decode("utf-8", "replace"), proc.returncode, False)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        out, _ = proc.communicate()
        return ExecResult(out.decode("utf-8", "replace"), None, True)
