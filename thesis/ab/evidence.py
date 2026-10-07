"""Mark whether a saved cell exercised a pull request's evidence pattern.

The A/B runner keeps a transcript plus the copied OpenCode storage and logs
for each cell. This module greps those files with the pattern from
``thesis/ab/fixtures/trigger-evidence.csv`` and writes ``exercised`` on the cell:

- ``exercised`` when a transcript or copied storage/log matches
- ``not exercised`` when those files exist and none match
- ``undeterminable`` when no evidence file is present

It also writes ``evidence-summary.json`` with a count per PR and side.

PR 984 is stricter than its pattern row. ``classify_edit_only`` marks a cell
exercised only when the evidence has at least one edit call and zero
``"tool": "bash"`` or ``"tool": "write"`` parts. The cell records
``edit_calls`` and ``bash_write_calls`` (the largest count in any one file).

PR 19058 is also stricter. The parent logs ``touching file`` and then an
``lsp.client`` didOpen or publishDiagnostics line for the outside path. The
merge logs only ``touching file``. ``classify_lsp_outside`` counts a cell as
exercised only when the touch is present and the client line is absent. The
cell records ``outside_touch_lines`` and ``outside_lsp_client_lines``.

PR 2367's trigger is whether a list tool output contains ``generated/``.
PR 1248's trigger is whether the child session received the plan-mode
reminder, not merely that the parent message recorded ``"mode": "plan"``.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from thesis.ab.durable import publish_text
from thesis.ab.run_ab import read_cell, task_component

EXERCISED = "exercised"
NOT_EXERCISED = "not exercised"
UNDETERMINABLE = "undeterminable"
_STATUSES = (EXERCISED, NOT_EXERCISED, UNDETERMINABLE)
_MAX_BYTES = 32 * 1024 * 1024
# make-ci-green for #984 must actually call edit, and the mode.build.tools
# config must have removed bash and write. The pattern file still matches edit.
EDIT_ONLY_PRS = frozenset({"984"})
LSP_OUTSIDE_PRS = frozenset({"19058"})
LIST_GENERATED_PRS = frozenset({"2367"})
PLAN_REMINDER_PRS = frozenset({"1248"})
_BASH_OR_WRITE = re.compile(r'"tool": ?"(bash|write)"')
_OUTSIDE_TOUCH = re.compile(
    r"/tmp/obench-shared-[^\"\n]{0,240}touching file"
    r"|touching file[^\"\n]{0,240}/tmp/obench-shared-"
)
_OUTSIDE_LSP_CLIENT = re.compile(
    r"lsp\.client\b[^\n]*\bpath=/tmp/obench-shared-\S+"
    r"[^\n]*\b(?:didOpen|publishDiagnostics)\b"
)
# Researcher's pattern table, committed next to this module.
DEFAULT_PATTERNS = Path(__file__).resolve().parent / "fixtures" / "trigger-evidence.csv"


class EvidenceError(ValueError):
    pass


@dataclass(frozen=True)
class EvidencePattern:
    pr: str
    task: str
    pattern: str
    compiled: re.Pattern[str]


def load_patterns(path: Path) -> dict[str, EvidencePattern]:
    path = Path(path)
    if not path.is_file():
        raise EvidenceError(f"evidence pattern file not found: {path}")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise EvidenceError(f"evidence pattern file not readable: {path}: {exc}") from exc
    reader = csv.DictReader(text.splitlines())
    fields = set(reader.fieldnames or [])
    missing = {"pr", "task", "evidence_pattern"} - fields
    if missing:
        raise EvidenceError(f"{path}: missing column(s): {', '.join(sorted(missing))}")
    found: dict[str, EvidencePattern] = {}
    for index, row in enumerate(reader, start=2):
        pr = str(row.get("pr") or "").strip()
        if not pr:
            raise EvidenceError(f"{path}:{index}: missing pr")
        if pr in found:
            raise EvidenceError(f"{path}:{index}: duplicate PR {pr}")
        pattern = str(row.get("evidence_pattern") or "")
        if not pattern:
            raise EvidenceError(f"{path}:{index}: missing evidence_pattern")
        try:
            compiled = re.compile(pattern)
        except re.error as exc:
            raise EvidenceError(f"{path}:{index}: evidence_pattern does not compile: {exc}") from exc
        found[pr] = EvidencePattern(
            pr=pr,
            task=str(row.get("task") or "").strip(),
            pattern=pattern,
            compiled=compiled,
        )
    if not found:
        raise EvidenceError(f"{path}: no evidence rows")
    return found


def _header_matches(path: Path, task: str, trial: int) -> bool:
    try:
        head = path.read_text(encoding="utf-8", errors="replace")[:800]
    except OSError:
        return False
    return f"task={task} trial={trial}" in head


def transcript_files(out_dir: Path, pr: str, side: str, task: str, trial: int, row: dict) -> list[Path]:
    root = out_dir / pr / "transcripts" / side
    found: list[Path] = []
    run_id = row.get("run_id")
    if isinstance(run_id, str) and run_id.strip():
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", run_id)
        candidate = root / f"{safe}.txt"
        if candidate.is_file():
            found.append(candidate)
    if root.is_dir():
        for path in sorted(root.glob("*.txt")):
            if path in found:
                continue
            if _header_matches(path, task, trial):
                found.append(path)
    return found


def evidence_files(out_dir: Path, pr: str, side: str, task: str, trial: int) -> list[Path]:
    root = out_dir / pr / "transcripts" / side / task_component(task) / str(trial)
    if not root.is_dir():
        return []
    return [path for path in sorted(root.rglob("*")) if path.is_file()]


def _read_text(path: Path) -> str | None:
    try:
        size = path.stat().st_size
    except OSError:
        return None
    if size > _MAX_BYTES:
        return None
    try:
        data = path.read_bytes()
    except OSError:
        return None
    # Latin-1 keeps every byte. Without DOTALL, `.` stays on one line, which
    # matches the line-oriented patterns checked with grep -E.
    return data.decode("latin-1")


def file_matches(path: Path, pattern: re.Pattern[str]) -> bool:
    text = _read_text(path)
    if text is None:
        return False
    return pattern.search(text) is not None


def tool_call_counts(paths: list[Path], edit_pattern: re.Pattern[str]) -> tuple[int, int]:
    """Largest edit-match count and largest bash/write count in any one file."""
    edits = 0
    denied = 0
    for path in paths:
        text = _read_text(path)
        if text is None:
            continue
        edits = max(edits, sum(1 for _ in edit_pattern.finditer(text)))
        denied = max(denied, sum(1 for _ in _BASH_OR_WRITE.finditer(text)))
    return edits, denied


def classify_edit_only(paths: list[Path], edit_pattern: re.Pattern[str]) -> tuple[str, int, int]:
    """Exercised only with at least one edit and no bash or write tool part.

    Returns ``(status, edit_calls, bash_write_calls)``. No evidence files is
    undeterminable. Files that exist but fail the gate are not exercised.
    """
    if not paths:
        return UNDETERMINABLE, 0, 0
    edits, denied = tool_call_counts(paths, edit_pattern)
    if edits >= 1 and denied == 0:
        return EXERCISED, edits, denied
    return NOT_EXERCISED, edits, denied


def outside_lsp_counts(paths: list[Path]) -> tuple[int, int]:
    """Largest ``touching file`` count and largest outside lsp.client count.

    Each count is the most matches in any one evidence file, so a copied
    transcript is not added to the storage copy.
    """
    touches = 0
    clients = 0
    for path in paths:
        text = _read_text(path)
        if text is None:
            continue
        touches = max(touches, len(_OUTSIDE_TOUCH.findall(text)))
        clients = max(clients, len(_OUTSIDE_LSP_CLIENT.findall(text)))
    return touches, clients


def classify_lsp_outside(paths: list[Path]) -> tuple[str, int, int]:
    """Exercised only when the outside file is touched and no LSP client opens it.

    The parent logs both ``touching file`` and ``lsp.client … didOpen`` or
    ``publishDiagnostics``. The merge logs the touch and not the client line.
    Returns ``(status, outside_touch_lines, outside_lsp_client_lines)``.
    """
    if not paths:
        return UNDETERMINABLE, 0, 0
    touches, clients = outside_lsp_counts(paths)
    if touches >= 1 and clients == 0:
        return EXERCISED, touches, clients
    return NOT_EXERCISED, touches, clients


def classify_files(paths: list[Path], pattern: re.Pattern[str]) -> str:
    if not paths:
        return UNDETERMINABLE
    for path in paths:
        if file_matches(path, pattern):
            return EXERCISED
    return NOT_EXERCISED


_TOOL = re.compile(r'"tool"\s*:\s*"([^"]+)"')
_READ_PATH = re.compile(r'"(?:filePath|path)"\s*:\s*"([^"]+)"|<path>([^<]+)</path>')
_OFFSET = re.compile(r'"offset"\s*:\s*"?(\d+)"?')
_LIMIT = re.compile(r'"limit"\s*:\s*"?(\d+)"?')
_SESSION = re.compile(r'"(?:sessionID|session_id|task_id)"\s*:\s*"(ses_[^"]+)"')
# 12214 prints the returned id in the tool output as `task_id: ses_…`, not as
# a JSON field. A quote right after the key keeps `"task_id":"ses_…"` on the
# structured path above, which is what 4204 builds use.
_PLAIN_SESSION = re.compile(
    r"(?:task_id|session_id)(?!\")\s*:\s*\"?(ses_[A-Za-z0-9]+)"
)
_CHILD_ID_PARENT = re.compile(
    r'"id"\s*:\s*"(ses_[^"]+)"[^}]{0,800}?"parentID"\s*:\s*"(ses_[^"]+)"'
)
_CHILD_PARENT_ID = re.compile(
    r'"parentID"\s*:\s*"(ses_[^"]+)"[^}]{0,800}?"id"\s*:\s*"(ses_[^"]+)"'
)
_WRITE_TOOLS = frozenset({"bash", "edit", "write", "patch"})
# Bash is a child action, but it is not a file edit. 1248 cares about the
# edit/write/patch subset because plan mode blocks those and not a shell.
_FILE_EDIT_TOOLS = frozenset({"edit", "write", "patch"})
_PLAN_REMINDER = re.compile(
    r"plan mode is active"
    r"|you are in plan mode"
    r"|you are a plan agent"
    r"|the user does not want you to execute yet"
    r"|switched to plan mode",
    re.IGNORECASE,
)
_LIST_OUTPUT = re.compile(r'"output"\s*:\s*"((?:\\.|[^"\\])*)"', re.DOTALL)
_DOTNET_BUILD = re.compile(r"dotnet\s+build")
_REJECTION = re.compile(
    r"auto-rejecting"
    r"|permission requested:[^\n]{0,240}reject"
    r"|\"status\"\s*:\s*\"rejected\"",
    re.IGNORECASE,
)
_SEARCH_TOOLS = frozenset({"grep", "glob", "read"})
_RULE_TOKENS = (("GLOBAL-RULE", "global"), ("PROJECT-RULE", "project"))
_EOF = 10**12


def _tool_windows(text: str) -> list[tuple[str, str]]:
    matches = list(_TOOL.finditer(text))
    found = []
    for index, match in enumerate(matches):
        previous = matches[index - 1].end() if index else 0
        start = max(previous, match.start() - 400)
        end = matches[index + 1].start() if index + 1 < len(matches) else min(len(text), match.end() + 2000)
        found.append((match.group(1), text[start:end]))
    return found


def _norm_path(path: str) -> str:
    text = (path or "").replace("\\", "/").strip()
    while text.startswith("./"):
        text = text[2:]
    return text.lstrip("/")


def _same_path(left: str, right: str) -> bool:
    a = _norm_path(left)
    b = _norm_path(right)
    if not a or not b:
        return False
    return a == b or a.endswith("/" + b) or b.endswith("/" + a)


def _read_span(window: str) -> tuple[str, int, int | None]:
    path = ""
    match = _READ_PATH.search(window)
    if match:
        path = match.group(1) or match.group(2) or ""
    offset_match = _OFFSET.search(window)
    limit_match = _LIMIT.search(window)
    offset = int(offset_match.group(1)) if offset_match else 1
    limit = int(limit_match.group(1)) if limit_match else None
    return path, offset, limit


def _ranges_overlap(left: tuple[int, int | None], right: tuple[int, int | None]) -> bool:
    left_end = _EOF if left[1] is None else left[0] + left[1]
    right_end = _EOF if right[1] is None else right[0] + right[1]
    return left[0] < right_end and right[0] < left_end


def _richest(paths: list[Path], kind: str) -> str:
    best = ""
    best_count = -1
    for path in paths:
        text = _read_text(path)
        if text is None:
            continue
        count = sum(1 for name, _window in _tool_windows(text) if name == kind)
        if count > best_count:
            best = text
            best_count = count
    return best


def read_call_stats(paths: list[Path]) -> tuple[int, bool]:
    """Read-tool calls in the file with the most of them, and whether one rereads.

    A reread is a later read of the same path whose range overlaps an earlier
    one. A missing offset starts at the beginning of the file. A missing limit
    runs through EOF, so it overlaps a later read of that path.
    """
    text = _richest(paths, "read")
    if not text:
        return 0, False
    calls = []
    for name, window in _tool_windows(text):
        if name != "read":
            continue
        path, offset, limit = _read_span(window)
        calls.append((path, offset, limit))
    reread = False
    for index, (path, offset, limit) in enumerate(calls):
        for earlier, earlier_offset, earlier_limit in calls[:index]:
            if _same_path(path, earlier) and _ranges_overlap(
                (earlier_offset, earlier_limit), (offset, limit),
            ):
                reread = True
                break
        if reread:
            break
    return len(calls), reread


def _child_sessions(text: str) -> set[str]:
    children = set()
    for match in _CHILD_ID_PARENT.finditer(text):
        children.add(match.group(1))
    for match in _CHILD_PARENT_ID.finditer(text):
        children.add(match.group(2))
    return children


def _child_tool_count(paths: list[Path], tools: frozenset[str]) -> int:
    """Tool calls of ``tools`` inside a child session.

    Child ids are collected across the evidence files. The file with the most
    such calls wins, so a copied transcript is not added to the storage copy.
    """
    texts: list[tuple[Path, str]] = []
    children: set[str] = set()
    for path in paths:
        text = _read_text(path)
        if text is None:
            continue
        texts.append((path, text))
        children.update(_child_sessions(text))
    if not children:
        return 0
    best = 0
    for path, text in texts:
        count = 0
        for name, window in _tool_windows(text):
            if name not in tools:
                continue
            sessions = _SESSION.findall(window)
            if any(session in children for session in sessions):
                count += 1
                continue
            if any(session in str(path) for session in children):
                count += 1
        best = max(best, count)
    return best


def subagent_write_call_count(paths: list[Path]) -> int:
    """Child-session bash, edit, write, and patch calls.

    This count includes bash. ``child_edit_call_count`` is the file-edit
    subset (edit, write, patch) and leaves bash out.
    """
    return _child_tool_count(paths, _WRITE_TOOLS)


def child_edit_call_count(paths: list[Path]) -> int:
    """Child-session edit, write, and patch calls. Bash is not included."""
    return _child_tool_count(paths, _FILE_EDIT_TOOLS)


def _forward_windows(text: str, kind: str) -> list[str]:
    """Text after each ``tool`` key of ``kind``, up to the next tool key."""
    matches = list(_TOOL.finditer(text))
    found = []
    for index, match in enumerate(matches):
        if match.group(1) != kind:
            continue
        end = matches[index + 1].start() if index + 1 < len(matches) else min(len(text), match.end() + 2000)
        found.append(text[match.end():end])
    return found


def _task_session_ids(window: str) -> list[str]:
    """Session ids on one task call, structured first, then plain text.

    4204 stores the id in metadata or input JSON. 12214 prints it in the tool
    output as ``task_id: ses_… (for resuming…)``. Both have to be recorded or
    the later resume call looks like the first time that id appeared.
    """
    found = _SESSION.findall(window)
    for session in _PLAIN_SESSION.findall(window):
        if session not in found:
            found.append(session)
    return found


def task_call_stats(paths: list[Path]) -> tuple[int, bool, int]:
    """Return ``(task_calls, subagent_resumed, fresh_subagents)``.

    A task call that passes a session id already seen on an earlier task call
    resumes that subagent. Every other task call starts a fresh subagent.
    """
    text = _richest(paths, "task")
    if not text:
        return 0, False, 0
    seen: list[str] = []
    calls = 0
    fresh = 0
    resumed = False
    for window in _forward_windows(text, "task"):
        calls += 1
        ids = _task_session_ids(window)
        if any(session in seen for session in ids):
            resumed = True
        else:
            fresh += 1
        for session in ids:
            if session not in seen:
                seen.append(session)
    return calls, resumed, fresh


def main_agent_searched(paths: list[Path]) -> bool:
    """True when the root session itself grepped, globbed, or read.

    A search whose session id is a child session belongs to the subagent.
    ``main_agent_searched`` is the "searched alone" flag: the main agent did
    the lookup in its own session.
    """
    texts: list[tuple[Path, str]] = []
    children: set[str] = set()
    for path in paths:
        text = _read_text(path)
        if text is None:
            continue
        texts.append((path, text))
        children.update(_child_sessions(text))
    for path, text in texts:
        path_is_child = any(session in str(path) for session in children)
        for name, window in _tool_windows(text):
            if name not in _SEARCH_TOOLS:
                continue
            sessions = _SESSION.findall(window)
            if children and sessions and all(session in children for session in sessions):
                continue
            if children and not sessions and path_is_child:
                continue
            return True
    return False


def classify_rule_prefix(text: str) -> str:
    """Classify the start of a final answer.

    ``both`` when the first non-empty line starts with GLOBAL-RULE and
    PROJECT-RULE in either order. One of those tokens alone is ``global`` or
    ``project``. Anything else is ``neither``.
    """
    line = ""
    for raw in (text or "").splitlines():
        if raw.strip():
            line = raw.strip()
            break
    if not line:
        line = (text or "").strip()
    rest = line
    seen: list[str] = []
    while rest:
        rest = rest.lstrip(" \t:.-")
        matched = False
        for token, label in _RULE_TOKENS:
            if rest.startswith(token):
                seen.append(label)
                rest = rest[len(token):]
                matched = True
                break
        if not matched:
            break
    if "global" in seen and "project" in seen:
        return "both"
    if seen:
        return seen[0]
    return "neither"


def _unescape_output(body: str) -> str:
    return body.replace("\\/", "/").replace("\\n", "\n").replace('\\"', '"')


def list_has_generated(paths: list[Path]) -> bool | None:
    """Whether any list-tool output contains ``generated/``.

    ``None`` when the evidence has no list output, so a missing listing is
    not the same as a listing that omitted the ignored directory.
    """
    saw = False
    found = False
    for path in paths:
        text = _read_text(path)
        if text is None:
            continue
        for window in _forward_windows(text, "list"):
            outputs = _LIST_OUTPUT.findall(window)
            if not outputs:
                continue
            saw = True
            for body in outputs:
                if "generated/" in _unescape_output(body):
                    found = True
        for match in re.finditer(r"\|\s+List\b[^\n]*\n((?:[^\n]*\n){0,80})", text):
            saw = True
            if "generated/" in match.group(1):
                found = True
    if found:
        return True
    if saw:
        return False
    return None


def classify_list_generated(paths: list[Path]) -> tuple[str, bool]:
    """Exercised when a list output contains ``generated/`` (PR 2367's trigger)."""
    if not paths:
        return UNDETERMINABLE, False
    found = list_has_generated(paths)
    if found is None:
        return UNDETERMINABLE, False
    return (EXERCISED if found else NOT_EXERCISED), bool(found)


def child_received_plan_reminder(paths: list[Path]) -> bool:
    """True when a child session's own text contains the plan-mode reminder.

    The parent cell is started with ``--mode plan``, so the reminder on the
    parent message is not the trigger. The child has to receive it.
    """
    texts: list[tuple[Path, str]] = []
    children: set[str] = set()
    for path in paths:
        text = _read_text(path)
        if text is None:
            continue
        texts.append((path, text))
        children.update(_child_sessions(text))
    if not children:
        return False
    for path, text in texts:
        path_is_child = any(session in str(path) for session in children)
        for match in _PLAN_REMINDER.finditer(text):
            if path_is_child:
                return True
            start = text.rfind("{", 0, match.start())
            end = text.find("}", match.end())
            blob = text[start:end + 1] if start >= 0 and end >= 0 else ""
            sessions = _SESSION.findall(blob)
            if any(session in children for session in sessions):
                return True
    return False


def classify_child_plan_reminder(paths: list[Path]) -> tuple[str, bool]:
    """Exercised only when the child session received the plan-mode reminder."""
    if not paths:
        return UNDETERMINABLE, False
    reminded = child_received_plan_reminder(paths)
    return (EXERCISED if reminded else NOT_EXERCISED), reminded


def dotnet_build_call_count(paths: list[Path]) -> int:
    """Bash calls that run ``dotnet build``.

    The largest count in any one file wins, so a copied transcript is not
    added to the storage copy. A file that only has other bash calls does
    not hide a build in a second file.
    """
    best = 0
    for path in paths:
        text = _read_text(path)
        if text is None:
            continue
        count = sum(1 for window in _forward_windows(text, "bash") if _DOTNET_BUILD.search(window))
        best = max(best, count)
    return best


def edit_call_count(paths: list[Path]) -> int:
    """Edit-tool calls in the file that has the most of them."""
    text = _richest(paths, "edit")
    if not text:
        return 0
    return sum(1 for name, _window in _tool_windows(text) if name == "edit")


def rejection_stats(paths: list[Path]) -> tuple[int, bool]:
    """``(permission_rejections, ended_on_rejection)`` from the richest file.

    A rejection is an auto-reject line or a tool state of ``rejected``.
    The cell ended on a rejection when nothing completed and no assistant
    text was recorded after the last one.
    """
    best = ""
    best_count = -1
    for path in paths:
        text = _read_text(path)
        if text is None:
            continue
        count = len(_REJECTION.findall(text))
        if count > best_count:
            best = text
            best_count = count
    if best_count <= 0:
        return 0, False
    last = None
    for match in _REJECTION.finditer(best):
        last = match
    tail = best[last.end():] if last else ""
    later = re.search(
        r'"type"\s*:\s*"text"|"status"\s*:\s*"completed"|plan mode is active',
        tail,
        re.IGNORECASE,
    )
    return best_count, later is None


def rule_prefix_from_dir(root: Path | None) -> str:
    if root is None:
        return "neither"
    from obench.final_answer import final_text
    try:
        return classify_rule_prefix(final_text(root))
    except OSError:
        return "neither"


def _final_answer_text(root: Path | None) -> str:
    if root is None:
        return ""
    from obench.final_answer import final_text
    try:
        return final_text(root)
    except OSError:
        return ""


def attach_cell_metrics(row: dict, evidence_root: Path | str | None, files: list[Path] | None = None) -> dict:
    """Record read, subagent, task, and per-trigger facts on a cell row.

    ``subagent_write_calls`` counts child bash as well as edit, write, and
    patch. ``child_edit_calls`` is edit, write, and patch only.
    ``workspace_changed`` stays the runner's own flag; this function does not
    recompute it. ``tmpdir_leaked_dirs`` is refreshed when the cell wrote
    ``scratch-tmpdir.txt`` and that directory is still on disk.
    """
    if not isinstance(row, dict):
        return row
    paths = list(files or [])
    root = Path(evidence_root) if evidence_root else None
    if not paths and root is not None and root.is_dir():
        paths = [path for path in sorted(root.rglob("*")) if path.is_file()]
    reads, reread = read_call_stats(paths)
    task_calls, resumed, fresh = task_call_stats(paths)
    answer = _final_answer_text(root)
    generated = list_has_generated(paths)
    rejections, ended = rejection_stats(paths)
    row["read_calls"] = reads
    row["reread"] = reread
    row["subagent_write_calls"] = subagent_write_call_count(paths)
    row["child_edit_calls"] = child_edit_call_count(paths)
    row["task_calls"] = task_calls
    row["subagent_resumed"] = resumed
    row["fresh_subagents"] = fresh
    row["main_agent_searched"] = main_agent_searched(paths)
    row["rule_prefix"] = classify_rule_prefix(answer)
    row["final_answer_present"] = bool(answer.strip())
    row["child_plan_reminder"] = child_received_plan_reminder(paths)
    row["list_has_generated"] = bool(generated)
    row["dotnet_build_calls"] = dotnet_build_call_count(paths)
    # PR 984's classifier records edit_calls before this runs. Keep the
    # larger count so a text-UI edit is not replaced by a JSON miss.
    edits = edit_call_count(paths)
    previous = row.get("edit_calls")
    if isinstance(previous, int) and not isinstance(previous, bool):
        edits = max(edits, previous)
    row["edit_calls"] = edits
    row["permission_rejections"] = rejections
    row["ended_on_rejection"] = ended
    marker = root / "scratch-tmpdir.txt" if root is not None else None
    if marker is not None and marker.is_file():
        scratch = ""
        try:
            scratch = marker.read_text(encoding="utf-8").strip()
        except OSError:
            scratch = ""
        if scratch and Path(scratch).is_dir():
            from thesis.ab.run_ab import leaked_temp_dirs
            row["tmpdir_leaked_dirs"] = leaked_temp_dirs(scratch)
    elif "tmpdir_leaked_dirs" not in row:
        row["tmpdir_leaked_dirs"] = 0
    touches, clients = outside_lsp_counts(paths)
    if touches or clients or str(row.get("task") or "") == "trig-lsp-outside":
        row["outside_touch_lines"] = touches
        row["outside_lsp_client_lines"] = clients
    return row


def iter_cells(out_dir: Path):
    root = Path(out_dir)
    if not root.is_dir():
        return
    for pr_dir in sorted(path for path in root.iterdir() if path.is_dir()):
        cells = pr_dir / "cells"
        if not cells.is_dir():
            continue
        for side_dir in sorted(path for path in cells.iterdir() if path.is_dir()):
            for task_dir in sorted(path for path in side_dir.iterdir() if path.is_dir()):
                for trial_path in sorted(task_dir.glob("*.json")):
                    if not trial_path.stem.isdigit():
                        continue
                    row = read_cell(trial_path)
                    if row is None:
                        continue
                    yield pr_dir.name, side_dir.name, task_dir.name, int(trial_path.stem), trial_path, row


def _empty_counts() -> dict[str, int]:
    return {status: 0 for status in _STATUSES}


def annotate(out_dir: Path, patterns: dict[str, EvidencePattern]) -> dict:
    """Write ``exercised`` on each listed PR's cells and return the summary."""
    out_dir = Path(out_dir)
    summary: dict[str, dict] = {}
    for pr, side, task, trial, path, row in iter_cells(out_dir):
        spec = patterns.get(pr)
        if spec is None:
            continue
        task_name = str(row.get("task") or task)
        files = transcript_files(out_dir, pr, side, task_name, trial, row)
        files.extend(evidence_files(out_dir, pr, side, task_name, trial))
        # A transcript path can also sit inside the evidence dir; search once.
        unique: list[Path] = []
        seen: set[Path] = set()
        for item in files:
            resolved = item.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            unique.append(item)
        if pr in EDIT_ONLY_PRS:
            status, edits, denied = classify_edit_only(unique, spec.compiled)
            row["edit_calls"] = edits
            row["bash_write_calls"] = denied
        elif pr in LSP_OUTSIDE_PRS:
            status, touches, clients = classify_lsp_outside(unique)
            row["outside_touch_lines"] = touches
            row["outside_lsp_client_lines"] = clients
        elif pr in LIST_GENERATED_PRS:
            status, _generated = classify_list_generated(unique)
        elif pr in PLAN_REMINDER_PRS:
            status, _reminded = classify_child_plan_reminder(unique)
        else:
            status = classify_files(unique, spec.compiled)
        row["exercised"] = status
        evidence_root = out_dir / pr / "transcripts" / side / task_component(task_name) / str(trial)
        attach_cell_metrics(row, evidence_root, unique)
        publish_text(path, json.dumps(row, sort_keys=True))
        pr_summary = summary.setdefault(pr, {"task": spec.task, "sides": {}})
        side_summary = pr_summary["sides"].setdefault(side, _empty_counts())
        side_summary[status] += 1
    payload = {"prs": summary}
    publish_text(
        out_dir / "evidence-summary.json",
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
    )
    return payload


def render_summary(payload: dict) -> str:
    lines = ["pr side exercised not_exercised undeterminable"]
    prs = payload.get("prs") or {}
    for pr in sorted(prs):
        sides = prs[pr].get("sides") or {}
        if not sides:
            lines.append(f"{pr} - 0 0 0")
            continue
        for side in sorted(sides):
            counts = sides[side]
            lines.append(
                f"{pr} {side} {counts.get(EXERCISED, 0)} "
                f"{counts.get(NOT_EXERCISED, 0)} {counts.get(UNDETERMINABLE, 0)}"
            )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Grep A/B transcripts and copied OpenCode storage for each PR's evidence pattern",
    )
    parser.add_argument("out", type=Path, help="A/B output directory (results/ab)")
    parser.add_argument(
        "patterns",
        nargs="?",
        type=Path,
        default=DEFAULT_PATTERNS,
        help="CSV with pr,task,evidence_pattern (default: thesis/ab/fixtures/trigger-evidence.csv)",
    )
    args = parser.parse_args(argv)
    try:
        patterns = load_patterns(args.patterns)
        payload = annotate(args.out, patterns)
    except EvidenceError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    sys.stdout.write(render_summary(payload))
    print(args.out / "evidence-summary.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
