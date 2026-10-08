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


def _is_sqlite_name(name: str) -> bool:
    """Session databases and their WAL/SHM sidecars, including ``opencode-.db``."""
    lowered = name.lower()
    return lowered.endswith(".db") or lowered.endswith(".db-wal") or lowered.endswith(".db-shm")


def _is_sqlite_db(path: Path) -> bool:
    lowered = path.name.lower()
    return lowered.endswith(".db") and not lowered.endswith(".db-wal") and not lowered.endswith(".db-shm")


def _is_binary_payload(data: bytes) -> bool:
    if data.startswith(b"SQLite format 3"):
        return True
    return b"\x00" in data


def _read_text(path: Path) -> str | None:
    """Text for pattern scans. SQLite files and other binaries are skipped.

    A WAL sidecar stores stale page copies of the same tool-call JSON. Reading
    those bytes as text counts one call many times. Callers that need the
    database use ``sqlite3`` instead.
    """
    if _is_sqlite_name(path.name):
        return None
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
    if _is_binary_payload(data):
        return None
    # Latin-1 keeps every byte. Without DOTALL, `.` stays on one line, which
    # matches the line-oriented patterns checked with grep -E.
    return data.decode("latin-1")


def file_matches(path: Path, pattern: re.Pattern[str]) -> bool:
    text = _read_text(path)
    if text is None:
        return False
    return pattern.search(text) is not None


@dataclass(frozen=True)
class ToolCall:
    """One tool call from text evidence or a sqlite part row."""

    tool: str
    part_id: str
    call_id: str
    sessions: tuple[str, ...]
    window: str
    forward: str
    source: str


_PART_ID = re.compile(
    r'"(?:partID|partId)"\s*:\s*"([^"]+)"'
    r'|"id"\s*:\s*"(prt_[^"]+)"'
)
_CALL_ID = re.compile(r'"(?:callID|callId|call_id)"\s*:\s*"([^"]+)"')
_MEMBERS_LINE3 = "# The lending policy allows each member to hold five books at once."


def _id_value(match: re.Match[str] | None) -> str:
    if match is None:
        return ""
    return match.group(1) or match.group(2) or ""


def _enclosing_start(text: str, tool_start: int) -> int:
    """Index of the ``{`` that opens the object containing this tool key."""
    depth = 0
    region = max(0, tool_start - 4000)
    for index in range(tool_start, region - 1, -1):
        char = text[index]
        if char == "}":
            depth += 1
        elif char == "{":
            if depth == 0:
                return index
            depth -= 1
    return region


def _calls_from_text(text: str, source: str) -> list[ToolCall]:
    matches = list(_TOOL.finditer(text))
    found = []
    for index, match in enumerate(matches):
        previous = matches[index - 1].end() if index else 0
        start = max(previous, match.start() - 400)
        end = matches[index + 1].start() if index + 1 < len(matches) else min(len(text), match.end() + 2000)
        window = text[start:end]
        forward = text[match.start():end]
        # Ids belong to this object. A 400-character lookbehind also holds the
        # previous call, and taking the first id there merges distinct calls.
        owned = text[_enclosing_start(text, match.start()):end]
        part = _PART_ID.search(owned)
        call = _CALL_ID.search(owned)
        found.append(ToolCall(
            tool=match.group(1),
            part_id=_id_value(part),
            call_id=call.group(1) if call else "",
            sessions=tuple(_SESSION.findall(window)),
            window=window,
            forward=forward,
            source=source,
        ))
    return found


def _anon_fingerprint(call: ToolCall) -> str:
    body = re.sub(r"\s+", "", call.forward)
    return call.tool + "\0" + body[:800]


def _dedupe_calls(calls: list[ToolCall]) -> list[ToolCall]:
    """Collapse copies that share a part id or call id.

    Anonymous calls (no id) collapse only when the tool body is the same, so
    a copied transcript is not added to the storage copy. Distinct calls stay.
    A later copy replaces the payload (the completed state) and keeps the
    first position.
    """
    by_part: dict[str, int] = {}
    by_call: dict[str, int] = {}
    anon_seen: set[str] = set()
    items: list[ToolCall] = []
    for call in calls:
        if call.part_id and call.part_id in by_part:
            items[by_part[call.part_id]] = call
            if call.call_id:
                by_call[call.call_id] = by_part[call.part_id]
            continue
        if call.call_id and call.call_id in by_call:
            slot = by_call[call.call_id]
            items[slot] = call
            if call.part_id:
                by_part[call.part_id] = slot
            continue
        if call.part_id or call.call_id:
            slot = len(items)
            items.append(call)
            if call.part_id:
                by_part[call.part_id] = slot
            if call.call_id:
                by_call[call.call_id] = slot
            continue
        fingerprint = _anon_fingerprint(call)
        if fingerprint in anon_seen:
            continue
        anon_seen.add(fingerprint)
        items.append(call)
    return items


def _text_call_groups(paths: list[Path]) -> list[list[ToolCall]]:
    groups = []
    for path in paths:
        text = _read_text(path)
        if text is None:
            continue
        calls = _calls_from_text(text, str(path))
        if calls:
            groups.append(calls)
    return groups


def _duplicate_ids(groups: list[list[ToolCall]]) -> bool:
    seen: set[str] = set()
    for group in groups:
        for call in group:
            keys = []
            if call.part_id:
                keys.append("part:" + call.part_id)
            if call.call_id:
                keys.append("call:" + call.call_id)
            if any(key in seen for key in keys):
                return True
            seen.update(keys)
    return False


def _sqlite_present(paths: list[Path]) -> bool:
    return any(_is_sqlite_name(path.name) for path in paths)


# sqlite3.Connection has no instance dict on Python 3.12, so the temp copy
# that owns the open database is tracked beside the connection.
_SQLITE_TEMPDIRS: dict[int, object] = {}


def _open_sqlite(path: Path):
    """Copy the db plus WAL/SHM and return an open connection.

    The copy is so a read does not checkpoint the stored evidence in place.
    ``PRAGMA wal_checkpoint`` applies the WAL through sqlite, not a byte scan.
    """
    import shutil
    import sqlite3
    import tempfile

    temporary = tempfile.TemporaryDirectory()
    try:
        dest = Path(temporary.name) / path.name
        shutil.copy2(path, dest)
        for suffix in ("-wal", "-shm"):
            sidecar = Path(str(path) + suffix)
            if sidecar.is_file():
                shutil.copy2(sidecar, Path(str(dest) + suffix))
        connection = sqlite3.connect(str(dest))
        try:
            connection.execute("PRAGMA wal_checkpoint(PASSIVE)")
        except sqlite3.Error:
            pass
    except (OSError, sqlite3.Error):
        temporary.cleanup()
        raise
    _SQLITE_TEMPDIRS[id(connection)] = temporary
    return connection


def _close_sqlite(connection) -> None:
    temporary = _SQLITE_TEMPDIRS.pop(id(connection), None)
    try:
        connection.close()
    except Exception:
        pass
    if temporary is not None:
        temporary.cleanup()


def _sqlite_part_calls(path: Path) -> list[ToolCall]:
    import sqlite3

    try:
        connection = _open_sqlite(path)
    except (OSError, sqlite3.Error):
        return []
    try:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        if "part" not in tables:
            return []
        columns = [row[1] for row in connection.execute("PRAGMA table_info(part)")]
        index = {name: position for position, name in enumerate(columns)}
        if "data" not in index:
            return []
        calls = []
        for row in connection.execute("SELECT * FROM part"):
            raw = row[index["data"]]
            if not isinstance(raw, str) or not raw:
                continue
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict):
                continue
            tool = payload.get("tool")
            if not isinstance(tool, str) or not tool:
                continue
            kind = str(payload.get("type") or "")
            if kind and kind not in {"tool", "tool-invocation"}:
                continue
            part_id = ""
            if "id" in index and row[index["id"]] is not None:
                part_id = str(row[index["id"]])
            if not part_id:
                part_id = str(payload.get("id") or "")
            message_id = ""
            if "message_id" in index and row[index["message_id"]] is not None:
                message_id = str(row[index["message_id"]])
            session = ""
            if "session_id" in index and row[index["session_id"]] is not None:
                session = str(row[index["session_id"]])
            if not session:
                for key in ("sessionID", "sessionId"):
                    if isinstance(payload.get(key), str):
                        session = payload[key]
                        break
            call_id = ""
            for key in ("callID", "callId", "call_id"):
                if isinstance(payload.get(key), str) and payload[key]:
                    call_id = payload[key]
                    break
            state = payload.get("state") if isinstance(payload.get("state"), dict) else {}
            blob = {
                "id": part_id,
                "messageID": message_id,
                "sessionID": session,
                "tool": tool,
                "callID": call_id,
                "state": state,
            }
            window = json.dumps(blob, ensure_ascii=False)
            calls.append(ToolCall(
                tool=tool,
                part_id=part_id,
                call_id=call_id,
                sessions=tuple([session] if session else ()),
                window=window,
                forward=window,
                source=str(path),
            ))
        return calls
    except sqlite3.Error:
        return []
    finally:
        _close_sqlite(connection)


def _sqlite_calls(paths: list[Path]) -> list[ToolCall]:
    calls = []
    seen: set[str] = set()
    for path in paths:
        if not _is_sqlite_db(path):
            continue
        try:
            key = str(path.resolve())
        except OSError:
            key = str(path)
        if key in seen:
            continue
        seen.add(key)
        calls.extend(_sqlite_part_calls(path))
    return calls


def _absorb_children(obj, children: set[str]) -> None:
    if isinstance(obj, dict):
        ident = obj.get("id")
        parent = obj.get("parentID")
        if parent is None:
            parent = obj.get("parentId")
        if (
            isinstance(ident, str) and ident.startswith("ses_")
            and isinstance(parent, str) and parent.startswith("ses_")
        ):
            children.add(ident)
        for value in obj.values():
            _absorb_children(value, children)
    elif isinstance(obj, list):
        for item in obj:
            _absorb_children(item, children)


def _sqlite_children(paths: list[Path]) -> set[str]:
    import sqlite3

    children: set[str] = set()
    seen: set[str] = set()
    for path in paths:
        if not _is_sqlite_db(path):
            continue
        try:
            key = str(path.resolve())
        except OSError:
            key = str(path)
        if key in seen:
            continue
        seen.add(key)
        try:
            connection = _open_sqlite(path)
        except (OSError, sqlite3.Error):
            continue
        try:
            tables = {
                row[0]
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            for table in tables:
                if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", table):
                    continue
                columns = [row[1] for row in connection.execute(f"PRAGMA table_info({table})")]
                for name in columns:
                    if not isinstance(name, str):
                        continue
                    lowered = name.lower()
                    if lowered not in {"data", "id", "parent_id", "parentid"} and "parent" not in lowered:
                        continue
                    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
                        continue
                    try:
                        rows = connection.execute(f"SELECT {name} FROM {table}").fetchall()
                    except sqlite3.Error:
                        continue
                    for (value,) in rows:
                        if isinstance(value, str) and value.startswith("{"):
                            try:
                                _absorb_children(json.loads(value), children)
                            except json.JSONDecodeError:
                                continue
                        elif isinstance(value, str) and value.startswith("ses_") and "parent" in lowered:
                            children.add(value)
        except sqlite3.Error:
            continue
        finally:
            _close_sqlite(connection)
    return children


def _children_for(paths: list[Path]) -> set[str]:
    children: set[str] = set()
    for path in paths:
        text = _read_text(path)
        if text:
            children |= _child_sessions(text)
    if _sqlite_present(paths):
        children |= _sqlite_children(paths)
    return children


def _authoritative_calls(paths: list[Path]) -> tuple[str, list[list[ToolCall]]]:
    """Return ``(mode, groups)``.

    ``legacy`` keeps the per-file richest-call behavior for evidence that has
    no sqlite sidecar and no repeated part or call id. Recomputing those
    results stays the same. ``deduped`` is one list: text tool calls collapsed
    by part id or call id, or the sqlite ``part`` table when text has none.
    """
    groups = _text_call_groups(paths)
    dedupe = _sqlite_present(paths) or _duplicate_ids(groups)
    if not dedupe:
        return "legacy", groups
    flat = [call for group in groups for call in group]
    if not flat:
        flat = _sqlite_calls(paths)
    return "deduped", [_dedupe_calls(flat)]


def _metric_calls(paths: list[Path], predicate) -> list[ToolCall]:
    """Tool calls for one count, from the shared authoritative list.

    Legacy evidence uses the single file with the most matches so a copied
    transcript is not added to storage. Deduped evidence uses one list.
    """
    mode, groups = _authoritative_calls(paths)
    if mode == "deduped":
        calls = groups[0] if groups else []
        return [call for call in calls if predicate(call)]
    best: list[ToolCall] = []
    for group in groups:
        chosen = [call for call in group if predicate(call)]
        if len(chosen) > len(best):
            best = chosen
    return best


def _regex_tool_counts(paths: list[Path], edit_pattern: re.Pattern[str]) -> tuple[int, int]:
    edits = 0
    denied = 0
    for path in paths:
        text = _read_text(path)
        if text is None:
            continue
        edits = max(edits, sum(1 for _ in edit_pattern.finditer(text)))
        denied = max(denied, sum(1 for _ in _BASH_OR_WRITE.finditer(text)))
    return edits, denied


def tool_call_counts(paths: list[Path], edit_pattern: re.Pattern[str]) -> tuple[int, int]:
    """Edit matches and bash/write calls from the authoritative source.

    Text evidence without repeated ids keeps the largest count in any one
    file. SQLite sidecars and repeated part ids are deduped instead of scanned
    as bytes.
    """
    regex_edits, regex_denied = _regex_tool_counts(paths, edit_pattern)
    mode, _groups = _authoritative_calls(paths)
    if mode != "deduped":
        return regex_edits, regex_denied
    calls = _metric_calls(paths, lambda _call: True)
    edits = sum(
        1 for call in calls
        if call.tool in {"edit", "multiedit"} or edit_pattern.search(call.window)
    )
    denied = sum(1 for call in calls if call.tool in {"bash", "write"})
    if edits == 0:
        edits = regex_edits
    if denied == 0:
        denied = regex_denied
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
_RULE_BULLET = re.compile(r"^(?:[-*+]|\d+[.)])\s+")
_RULE_SEPARATOR_CHARS = frozenset(" \t:.,>-")
# Text-UI edits have no `"tool": "edit"` part. The 984 pattern matches the same shape.
_TEXT_UI_EDIT = re.compile(r"\| .{0,24}\bEdit {2,}")
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


def read_call_stats(paths: list[Path]) -> tuple[int, bool]:
    """Read-tool calls from the authoritative source, and whether one rereads.

    A reread is a later read of the same path whose range overlaps an earlier
    one. A missing offset starts at the beginning of the file. A missing limit
    runs through EOF, so it overlaps a later read of that path. Copies that
    share a part id or call id count once.
    """
    mode, _groups = _authoritative_calls(paths)
    calls = []
    for call in _metric_calls(paths, lambda item: item.tool == "read"):
        # Legacy windows keep the historical lookbehind so a sqlite-free
        # recompute stays byte-identical. Deduped calls use the text after
        # this tool key, so a previous object's path is not this read's path.
        span = call.forward if mode == "deduped" else call.window
        path, offset, limit = _read_span(span)
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


def _is_child_call(call: ToolCall, children: set[str]) -> bool:
    if any(session in children for session in call.sessions):
        return True
    return any(session in call.source for session in children)


def _child_tool_count(paths: list[Path], tools: frozenset[str]) -> int:
    """Tool calls of ``tools`` inside a child session.

    Child ids are collected across the evidence files. The count goes through
    the same deduped path as the other tool metrics.
    """
    children = _children_for(paths)
    if not children:
        return 0
    calls = _metric_calls(
        paths,
        lambda call: call.tool in tools and _is_child_call(call, children),
    )
    return len(calls)


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
    Repeated part ids count once, in first-seen order.
    """
    seen: list[str] = []
    calls = 0
    fresh = 0
    resumed = False
    for call in _metric_calls(paths, lambda item: item.tool == "task"):
        calls += 1
        ids = _task_session_ids(call.forward)
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
    the lookup in its own session. Deduped evidence uses the same call list
    as the counts. Legacy evidence still searches every text file.
    """
    children = _children_for(paths)
    mode, groups = _authoritative_calls(paths)
    if mode == "deduped":
        calls = groups[0] if groups else []
    else:
        calls = [call for group in groups for call in group]
    for call in calls:
        if call.tool not in _SEARCH_TOOLS:
            continue
        if children and call.sessions and all(session in children for session in call.sessions):
            continue
        if children and not call.sessions and any(session in call.source for session in children):
            continue
        return True
    return False


def _normalize_rule_line(raw: str) -> str:
    """Drop whitespace, markdown bullets, and backticks from one answer line."""
    text = raw.replace("`", "").strip()
    while True:
        updated = _RULE_BULLET.sub("", text, count=1).strip()
        if updated == text:
            return text
        text = updated


def _consume_rule_separators(rest: str) -> str:
    """Skip commas, ``>``, ``->``, ``then``, and the older punctuation separators."""
    while rest:
        if rest[0] in _RULE_SEPARATOR_CHARS:
            rest = rest[1:]
            continue
        if rest[:4].lower() == "then" and (
            len(rest) == 4 or not (rest[4].isalnum() or rest[4] == "_")
        ):
            rest = rest[4:]
            continue
        break
    return rest


def _rule_labels_in_line(raw: str) -> tuple[list[str], bool] | None:
    """``(labels, pure)`` for one line.

    ``None`` when the line is empty after stripping. ``pure`` is true when
    the line contains only rule tokens and separators.
    """
    rest = _normalize_rule_line(raw)
    if not rest:
        return None
    labels: list[str] = []
    while rest:
        rest = _consume_rule_separators(rest)
        if not rest:
            break
        matched = False
        for token, label in _RULE_TOKENS:
            if rest.startswith(token):
                labels.append(label)
                rest = rest[len(token):]
                matched = True
                break
        if not matched:
            return labels, False
    return labels, True


def _leading_rule_labels(text: str) -> list[str]:
    """GLOBAL-RULE / PROJECT-RULE labels in the leading block of the answer.

    The block is the consecutive leading non-empty lines that contain only
    those tokens and separators (comma, ``>``, ``->``, ``then``, and the
    older punctuation), after stripping whitespace, markdown bullets, and
    backticks. Both tokens on one line count. A line that starts with rule
    tokens and then turns into prose still contributes those tokens and ends
    the block. A line that does not start with a rule token ends the block
    without contributing. Order is first appearance.
    """
    labels: list[str] = []
    for raw in (text or "").splitlines():
        if not raw.strip():
            continue
        parsed = _rule_labels_in_line(raw)
        if parsed is None:
            continue
        found, pure = parsed
        if not found:
            break
        labels.extend(found)
        if not pure:
            break
    return labels


def classify_rule_prefix(text: str) -> str:
    """Classify the leading rule block of a final answer.

    ``both`` when that block contains GLOBAL-RULE and PROJECT-RULE in either
    order, on one line or on consecutive rule-only lines. One of those tokens
    alone is ``global`` or ``project``. Anything else is ``neither``.
    """
    seen = _leading_rule_labels(text)
    if "global" in seen and "project" in seen:
        return "both"
    if seen:
        return seen[0]
    return "neither"


def classify_rule_order(text: str) -> str:
    """Order of the leading rule tokens.

    ``global_first`` or ``project_first`` when both tokens appear in the
    leading block, in first-seen order. ``one`` when only one of them does.
    ``none`` otherwise. ``rule_prefix`` still reports ``both`` and does not
    keep this order.
    """
    kinds: list[str] = []
    for label in _leading_rule_labels(text):
        if label not in kinds:
            kinds.append(label)
    if "global" in kinds and "project" in kinds:
        return "global_first" if kinds[0] == "global" else "project_first"
    if kinds:
        return "one"
    return "none"


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
    if not saw:
        for call in _metric_calls(paths, lambda item: item.tool == "list"):
            outputs = _LIST_OUTPUT.findall(call.forward)
            if not outputs:
                continue
            saw = True
            for body in outputs:
                if "generated/" in _unescape_output(body):
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
    """Bash calls that run ``dotnet build``, from the deduped tool-call path.

    A file that only has other bash calls does not hide a build in a second
    file: the count is the calls that match, not the richest bash file.
    """
    calls = _metric_calls(
        paths,
        lambda call: call.tool == "bash" and _DOTNET_BUILD.search(call.forward) is not None,
    )
    return len(calls)


def edit_call_count(paths: list[Path]) -> int:
    """Edit and multiedit calls from the deduped tool-call path."""
    return len(_metric_calls(paths, lambda call: call.tool in {"edit", "multiedit"}))


def _text_ui_edit_count(paths: list[Path]) -> int:
    """Largest ``| Edit`` count in any one text file.

    ``_read_text`` skips session databases and WAL sidecars, so a repeated
    page copy cannot inflate this count.
    """
    best = 0
    for path in paths:
        text = _read_text(path)
        if not text:
            continue
        best = max(best, len(_TEXT_UI_EDIT.findall(text)))
    return best


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
        r'"type"\s*:\s*"text"|"status"\s*:\s*"completed"',
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


def _final_answer_fields(paths: list[Path], root: Path | None) -> tuple[str, str, bool]:
    """``(text, source, complete)`` for one cell.

    ``source`` is ``db`` when the OpenCode session database is in the evidence
    directory, and ``stdout`` only when that database is missing. Completeness
    for a database answer is the last assistant message's finish reason.
    """
    if root is None:
        return "", "stdout", False
    from obench.final_answer import final_answer_record
    try:
        record = final_answer_record(root)
    except OSError:
        record = {"text": "", "complete": None, "source": "stdout"}
    text = str(record.get("text") or "")
    source = str(record.get("source") or "stdout")
    if source == "db":
        return text, "db", bool(record.get("complete"))
    return text, "stdout", final_answer_complete(paths, root)


_FINISH_TYPES = frozenset({"step_finish", "step-finish"})


def _collect_finish_reasons(obj, children: set[str], found: list[str]) -> None:
    if isinstance(obj, dict):
        kind = str(obj.get("type") or "")
        reason = obj.get("reason") if isinstance(obj.get("reason"), str) else ""
        if not reason and isinstance(obj.get("finish"), str):
            reason = obj["finish"]
        session = ""
        for key in ("sessionID", "sessionId", "session_id"):
            if isinstance(obj.get(key), str):
                session = obj[key]
                break
        if kind in _FINISH_TYPES and reason and (not session or session not in children):
            found.append(reason)
        for value in obj.values():
            _collect_finish_reasons(value, children, found)
    elif isinstance(obj, list):
        for item in obj:
            _collect_finish_reasons(item, children, found)


def _finish_reasons_in_text(text: str, children: set[str]) -> list[str]:
    found: list[str] = []
    for line in (text or "").splitlines():
        stripped = line.strip()
        if not stripped or stripped[0] not in "{[":
            continue
        try:
            obj = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        _collect_finish_reasons(obj, children, found)
    if found:
        return found
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        return found
    _collect_finish_reasons(obj, children, found)
    return found


def _sqlite_finish_reasons(paths: list[Path], children: set[str]) -> list[str]:
    import sqlite3

    found: list[str] = []
    seen: set[str] = set()
    for path in paths:
        if not _is_sqlite_db(path):
            continue
        try:
            key = str(path.resolve())
        except OSError:
            key = str(path)
        if key in seen:
            continue
        seen.add(key)
        try:
            connection = _open_sqlite(path)
        except (OSError, sqlite3.Error):
            continue
        try:
            tables = {
                row[0]
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            if "part" not in tables:
                continue
            columns = [row[1] for row in connection.execute("PRAGMA table_info(part)")]
            if "data" not in columns:
                continue
            for (raw,) in connection.execute("SELECT data FROM part"):
                if not isinstance(raw, str) or not raw:
                    continue
                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                _collect_finish_reasons(payload, children, found)
        except sqlite3.Error:
            continue
        finally:
            _close_sqlite(connection)
    return found


def last_finish_reason(paths: list[Path], root: Path | None = None) -> str:
    """Finish reason of the last root-session assistant step, or ``""``.

    Only ``stop`` means the model ended the turn. A tool call, error, or
    permission rejection leaves some other reason (or none).
    """
    children = _children_for(paths)
    agent_paths = []
    if root is not None:
        agent = Path(root) / "agent-output.txt"
        if agent.is_file():
            agent_paths.append(agent)
    for path in paths:
        if path.name == "agent-output.txt" and path not in agent_paths:
            agent_paths.append(path)
    for path in agent_paths:
        text = _read_text(path)
        if text is None:
            continue
        reasons = _finish_reasons_in_text(text, children)
        if reasons:
            return reasons[-1]
    found: list[str] = []
    for path in paths:
        if path in agent_paths:
            continue
        text = _read_text(path)
        if text is None:
            continue
        found.extend(_finish_reasons_in_text(text, children))
    if found:
        return found[-1]
    sqlite_reasons = _sqlite_finish_reasons(paths, children)
    if sqlite_reasons:
        return sqlite_reasons[-1]
    return ""


def final_answer_complete(paths: list[Path], root: Path | None = None) -> bool:
    """True only when the last root assistant step finished with reason ``stop``."""
    return last_finish_reason(paths, root) == "stop"


def _raw_int(window: str, pattern: re.Pattern[str]) -> int | None:
    match = pattern.search(window)
    if not match:
        return None
    return int(match.group(1))


def _tool_output(window: str) -> str:
    match = re.search(r'"output"\s*:\s*"((?:\\.|[^"\\])*)"', window, re.DOTALL)
    if not match:
        return ""
    body = match.group(1)
    return (
        body.replace("\\n", "\n")
        .replace("\\t", "\t")
        .replace('\\"', '"')
        .replace("\\/", "/")
    )


def _is_members_path(path: str) -> bool:
    norm = _norm_path(path)
    return norm == "members.py" or norm.endswith("/members.py") or norm.endswith("catalog/members.py")


def _window_is_lines_3_to_7(window: str) -> bool:
    """The returned read window is exactly file lines 3 through 7."""
    output = _tool_output(window)
    if output:
        numbers = [int(value) for value in re.findall(r"(?m)^(\d+):", output)]
        if numbers:
            return numbers == [3, 4, 5, 6, 7]
    return _raw_int(window, _OFFSET) == 3 and _raw_int(window, _LIMIT) == 5


def members_read_metrics(paths: list[Path], answer: str) -> dict:
    """Screen metrics for trig-read-lines (PR 13198).

    Counts are the deduped read calls whose path is ``members.py``.
    ``first_read_offset`` is the raw offset argument of the first of those,
    not the default used when the argument is missing. ``exact_quote_pass``
    is whether the final answer contains line 3 verbatim.
    """
    reads = _metric_calls(
        paths,
        lambda call: call.tool == "read" and _is_members_path(_read_span(call.forward)[0]),
    )
    offset = _raw_int(reads[0].forward, _OFFSET) if reads else None
    return {
        "first_read_offset": offset,
        "first_window_exact": bool(reads) and _window_is_lines_3_to_7(reads[0].forward),
        "members_read_calls": len(reads),
        "exact_quote_pass": bool(_MEMBERS_LINE3) and _MEMBERS_LINE3 in (answer or ""),
    }


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
    answer, answer_source, answer_complete = _final_answer_fields(paths, root)
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
    row["rule_order"] = classify_rule_order(answer)
    row["final_answer_present"] = bool(answer.strip())
    row["final_answer_complete"] = answer_complete
    row["final_answer_source"] = answer_source
    if str(row.get("task") or "") == "trig-read-lines":
        row.update(members_read_metrics(paths, answer))
    row["child_plan_reminder"] = child_received_plan_reminder(paths)
    row["list_has_generated"] = generated
    row["dotnet_build_calls"] = dotnet_build_call_count(paths)
    # Recomputed from this evidence. Do not max() with the stored edit_calls:
    # an earlier pass counted WAL page copies, and that stale number must not
    # survive a rescore. The other count fields above are assigned the same
    # way. A text-UI edit has no JSON tool part, so that count fills in only
    # when the tool-call path sees none.
    edits = edit_call_count(paths)
    if edits == 0:
        edits = _text_ui_edit_count(paths)
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
            from thesis.ab.run_ab import leaked_temp_dir_names, scratch_dirs_left
            names = leaked_temp_dir_names(scratch)
            row["tmpdir_leaked_dirs"] = len(names)
            row["tmpdir_leaked_names"] = names
            row["scratch_dirs_left"] = scratch_dirs_left(scratch)
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
