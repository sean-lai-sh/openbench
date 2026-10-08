"""Extract the assistant's final answer from an OpenCode cell.

``agent-output.txt`` is the raw stream. It starts with a log line that echoes
the prompt, and on ``--format json`` builds it also contains every tool result.
Checkers and the rule-prefix scorer must not search that file.

``final_text`` reads one evidence directory. On a JSON build it keeps the text
parts of the last root-session assistant message. On a plain-text build it
drops log lines and tool one-liners. ``publish_final_answer`` writes that text
to ``final-answer.txt`` and points ``OBENCH_FINAL_ANSWER`` at the file so a
checker can open it without reimplementing the parser.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

FINAL_ANSWER_NAME = "final-answer.txt"
FINAL_ANSWER_ENV = "OBENCH_FINAL_ANSWER"
_MAX_STORAGE_BYTES = 2 * 1024 * 1024
_ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
# A timestamp or level glued onto the end of an answer line, not at column 0.
_GLUED_LOG = re.compile(
    r"(?<=\S)(?=(?:INFO|DEBUG|WARN|ERROR)[ \t]|\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2})"
)
_LOG_LINE = re.compile(
    r"^(?:INFO|DEBUG|WARN|ERROR)(?:\s|$)"
    r"|^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?Z?[^\n]{0,80}\b(?:INFO|DEBUG|WARN|ERROR)\b"
)
_TOOL_LINE = re.compile(r"^\|\s+\S")
_JSON_TYPES = frozenset({
    "text",
    "tool_use",
    "tool",
    "step_start",
    "step_finish",
    "message.part.delta",
    "part.delta",
    "message.part.updated",
    "session",
})
_DELTA_TYPES = frozenset({"message.part.delta", "part.delta"})


class _Fragment:
    __slots__ = ("order", "session", "message", "part_id", "text", "kind")

    def __init__(self, order, session, message, part_id, text, kind):
        self.order = order
        self.session = session
        self.message = message
        self.part_id = part_id
        self.text = text
        self.kind = kind


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _json_events(raw: str) -> list[dict] | None:
    """JSON events, or None when the stream is plain text."""
    found: list[dict] = []
    for line in (raw or "").splitlines():
        stripped = line.strip()
        if not stripped or stripped[0] not in "{[":
            continue
        try:
            obj = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and str(obj.get("type") or "") in _JSON_TYPES:
            found.append(obj)
    if not found:
        return None
    return found


def _string(obj: dict, *names: str) -> str:
    for name in names:
        value = obj.get(name)
        if isinstance(value, str) and value:
            return value
    return ""


def _task_child_ids(obj: dict) -> set[str]:
    """Session ids a task call created or resumed, not the caller's session."""
    found: set[str] = set()
    if _string(obj, "tool") != "task":
        return found
    blobs = []
    if isinstance(obj.get("metadata"), dict):
        blobs.append(obj["metadata"])
    state = obj.get("state")
    if isinstance(state, dict):
        if isinstance(state.get("metadata"), dict):
            blobs.append(state["metadata"])
        entered = state.get("input")
        if isinstance(entered, dict):
            blobs.append(entered)
    for blob in blobs:
        for key in ("sessionID", "sessionId", "session_id", "task_id"):
            child = _string(blob, key)
            if child.startswith("ses_"):
                found.add(child)
    return found


def _collect_children(obj, found: set[str]) -> None:
    if isinstance(obj, dict):
        ident = _string(obj, "id")
        parent = _string(obj, "parentID", "parentId")
        if ident.startswith("ses_") and parent.startswith("ses_"):
            found.add(ident)
        found.update(_task_child_ids(obj))
        for value in obj.values():
            _collect_children(value, found)
    elif isinstance(obj, list):
        for item in obj:
            _collect_children(item, found)


def _text_piece(event: dict) -> tuple[str, str, str, str, str] | None:
    """Return ``(kind, text, message, session, part_id)`` for one event."""
    kind = str(event.get("type") or "")
    props = event.get("properties") if isinstance(event.get("properties"), dict) else {}
    part = event.get("part") if isinstance(event.get("part"), dict) else {}
    nested = props.get("part") if isinstance(props.get("part"), dict) else {}

    for node in (event, props):
        if not isinstance(node, dict) or not isinstance(node.get("delta"), str):
            continue
        node_type = str(node.get("type") or kind)
        field = node.get("field")
        if node_type not in _DELTA_TYPES and field != "text" and kind not in _DELTA_TYPES:
            continue
        if field not in (None, "text") and node_type not in _DELTA_TYPES:
            continue
        return (
            "delta",
            node["delta"],
            _string(node, "messageID", "messageId") or _string(props, "messageID", "messageId"),
            _string(node, "sessionID", "sessionId") or _string(event, "sessionID", "sessionId"),
            _string(node, "partID", "partId", "id"),
        )

    candidates = [item for item in (part, nested) if item]
    if kind == "text":
        candidates.append(event)
    for cand in candidates:
        if not isinstance(cand, dict) or not isinstance(cand.get("text"), str):
            continue
        cand_type = str(cand.get("type") or "")
        if cand is not event and cand_type not in {"", "text"}:
            continue
        if cand is event and kind != "text":
            continue
        text = cand["text"]
        if not text.strip():
            continue
        return (
            "text",
            text,
            _string(cand, "messageID", "messageId") or _string(event, "messageID", "messageId"),
            _string(cand, "sessionID", "sessionId") or _string(event, "sessionID", "sessionId"),
            _string(cand, "id", "partID", "partId"),
        )
    return None


def _join_message(parts: list[_Fragment]) -> str:
    complete = [item for item in parts if item.kind == "text"]
    use = complete or parts
    latest: dict[str, str] = {}
    order: list[str] = []
    for item in use:
        if item.part_id not in latest:
            order.append(item.part_id)
        latest[item.part_id] = item.text
    return "".join(latest[key] for key in order)


def _json_final_answer(events: list[dict]) -> str:
    children: set[str] = set()
    for event in events:
        _collect_children(event, children)
    fragments: list[_Fragment] = []
    for index, event in enumerate(events):
        piece = _text_piece(event)
        if piece is None:
            continue
        kind, text, message, session, part_id = piece
        if not message:
            message = f"event-{index}"
        if not part_id:
            part_id = f"part-{index}"
        fragments.append(_Fragment(index, session, message, part_id, text, kind))
    if not fragments:
        return ""
    visible = [item for item in fragments if not item.session or item.session not in children]
    chosen = visible or fragments
    last = max(chosen, key=lambda item: item.order)
    parts = [item for item in chosen if item.message == last.message]
    return _join_message(parts).strip()


def _prepare_plain(raw: str) -> str:
    """Strip colour codes and split a log fragment glued onto an answer line."""
    text = _ANSI.sub("", raw or "")
    return _GLUED_LOG.sub("\n", text)


def _dedupe_exact_repeat(text: str) -> str:
    """Drop a final answer that is the same block twice.

    One-line answers that are a single token repeated without a newline stay.
    ``hello\\nhello`` and a two-line block copied back-to-back collapse.
    """
    body = (text or "").strip()
    lines = body.splitlines()
    if len(lines) < 2 or len(lines) % 2 != 0:
        return body
    mid = len(lines) // 2
    if lines[:mid] == lines[mid:] and any(line.strip() for line in lines[:mid]):
        return "\n".join(lines[:mid]).strip()
    return body


def _plain_final_answer(raw: str) -> str:
    kept = []
    for line in _prepare_plain(raw).splitlines():
        if _LOG_LINE.match(line) or _TOOL_LINE.match(line):
            continue
        kept.append(line)
    return _dedupe_exact_repeat("\n".join(kept))


def extract_final_answer(raw: str) -> str:
    """Final answer text from one raw OpenCode stdout.

    JSON builds use the last root-session assistant text. Plain-text builds
    drop ``INFO``/``DEBUG``/``WARN``/``ERROR`` lines and ``| tool`` one-liners.
    A JSON stream with no assistant text returns an empty string so tool
    output cannot stand in for the answer.
    """
    events = _json_events(raw or "")
    if events is None:
        return _plain_final_answer(raw or "")
    return _json_final_answer(events)


def _created(obj: dict) -> float | None:
    stamp = obj.get("time")
    if isinstance(stamp, dict):
        value = stamp.get("created")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
    for key in ("created", "timestamp"):
        value = obj.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
    return None


def _storage_objects(root: Path) -> list[tuple[int, dict]]:
    found = []
    seq = 0
    if not root.is_dir():
        return found
    for path in sorted(root.rglob("*.json")):
        if path.name in {FINAL_ANSWER_NAME, "agent-output.txt", "streamed-text.txt"}:
            continue
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if size > _MAX_STORAGE_BYTES or size == 0:
            continue
        try:
            obj = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(obj, dict):
            found.append((seq, obj))
            seq += 1
    return found


def _storage_final_text(root: Path) -> str:
    """Text parts of the root session's last assistant message."""
    objects = _storage_objects(root)
    if not objects:
        return ""
    children: set[str] = set()
    messages = []
    parts: list[tuple[int, str, str, str, float | None]] = []
    for seq, obj in objects:
        _collect_children(obj, children)
        ident = _string(obj, "id")
        parent = _string(obj, "parentID", "parentId")
        if ident.startswith("ses_") and parent.startswith("ses_"):
            children.add(ident)
        role = _string(obj, "role")
        session = _string(obj, "sessionID", "sessionId")
        if role == "assistant" and ident:
            messages.append((seq, ident, session, _created(obj)))
        message_id = _string(obj, "messageID", "messageId")
        if obj.get("type") == "text" and isinstance(obj.get("text"), str) and message_id:
            if obj["text"].strip():
                parts.append((seq, message_id, _string(obj, "id") or f"part-{seq}", obj["text"], _created(obj)))
        nested = obj.get("parts")
        if isinstance(nested, list) and ident:
            for offset, part in enumerate(nested):
                if not isinstance(part, dict) or part.get("type") != "text":
                    continue
                text = part.get("text")
                if not isinstance(text, str) or not text.strip():
                    continue
                parts.append((
                    seq * 1000 + offset,
                    ident,
                    _string(part, "id") or f"part-{seq}-{offset}",
                    text,
                    _created(part),
                ))
    if not messages or not parts:
        return ""
    visible = [item for item in messages if item[2] not in children]
    pool = visible or messages

    def sort_key(item):
        seq, ident, _session, created = item
        return (created is not None, created or -1, ident, seq)

    _seq, message_id, _session, _created_at = max(pool, key=sort_key)
    chosen = [item for item in parts if item[1] == message_id]
    if not chosen:
        return ""
    chosen.sort(key=lambda item: ((item[4] is not None), item[4] or -1, item[2], item[0]))
    latest: dict[str, str] = {}
    order: list[str] = []
    for _seq, _message, part_id, text, _when in chosen:
        if part_id not in latest:
            order.append(part_id)
        latest[part_id] = text
    return "".join(latest[key] for key in order).strip()


def _is_opencode_session_db(name: str) -> bool:
    """``opencode.db`` and channel files such as ``opencode-local.db``."""
    lowered = name.lower()
    if lowered.endswith(".db-wal") or lowered.endswith(".db-shm"):
        return False
    if lowered == "opencode.db":
        return True
    return lowered.startswith("opencode-") and lowered.endswith(".db")


def _session_db_paths(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    found = []
    for path in root.rglob("*"):
        if path.is_file() and _is_opencode_session_db(path.name):
            found.append(path)
    return sorted(found)


# sqlite3.Connection has no instance dict on Python 3.12.
_DB_TEMPDIRS: dict[int, object] = {}


def _copy_parent() -> str | None:
    if os.path.isdir("/tmp") and os.access("/tmp", os.W_OK):
        return "/tmp"
    return None


def _open_session_db(path: Path):
    """Copy the db plus WAL/SHM and return an open connection.

    The copy is so a read does not checkpoint the stored evidence in place.
    A garbage sidecar is dropped and the database file is opened alone.
    """
    import shutil
    import sqlite3
    import tempfile

    def prepare(keep_sidecars: bool):
        temporary = tempfile.TemporaryDirectory(dir=_copy_parent())
        dest = Path(temporary.name) / path.name
        shutil.copy2(path, dest)
        if keep_sidecars:
            for suffix in ("-wal", "-shm"):
                sidecar = Path(str(path) + suffix)
                if sidecar.is_file():
                    shutil.copy2(sidecar, Path(str(dest) + suffix))
        connection = sqlite3.connect(str(dest))
        try:
            connection.execute("PRAGMA wal_checkpoint(PASSIVE)")
            connection.execute("SELECT name FROM sqlite_master LIMIT 1")
        except sqlite3.Error:
            connection.close()
            temporary.cleanup()
            raise
        _DB_TEMPDIRS[id(connection)] = temporary
        return connection

    try:
        return prepare(True)
    except (OSError, sqlite3.Error):
        try:
            return prepare(False)
        except (OSError, sqlite3.Error):
            return None


def _close_session_db(connection) -> None:
    temporary = _DB_TEMPDIRS.pop(id(connection), None)
    try:
        connection.close()
    except Exception:
        pass
    if temporary is not None:
        temporary.cleanup()


def _column_map(connection, table: str) -> dict[str, int]:
    return {
        str(row[1]): position
        for position, row in enumerate(connection.execute(f"PRAGMA table_info({table})"))
    }


def _pick(index: dict[str, int], *names: str) -> int | None:
    folded = {key.lower(): value for key, value in index.items()}
    for name in names:
        if name in index:
            return index[name]
        lowered = folded.get(name.lower())
        if lowered is not None:
            return lowered
    return None


def _load_json(value) -> dict:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value.startswith("{"):
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _message_role(payload: dict) -> str:
    role = payload.get("role")
    if isinstance(role, str):
        return role
    info = payload.get("info")
    if isinstance(info, dict) and isinstance(info.get("role"), str):
        return info["role"]
    return ""


def _message_time(payload: dict, column) -> int:
    if isinstance(column, int):
        return column
    stamp = payload.get("time")
    if isinstance(stamp, dict) and isinstance(stamp.get("created"), int):
        return stamp["created"]
    if isinstance(payload.get("time_created"), int):
        return payload["time_created"]
    return 0


def _part_text(payload: dict) -> str:
    kind = str(payload.get("type") or "")
    if kind != "text":
        nested = payload.get("part")
        if isinstance(nested, dict):
            return _part_text(nested)
        return ""
    text = payload.get("text")
    return text if isinstance(text, str) else ""


def _part_reason(payload: dict) -> str:
    kind = str(payload.get("type") or "")
    if kind in {"step-finish", "step_finish"}:
        reason = payload.get("reason")
        if isinstance(reason, str) and reason:
            return reason
    nested = payload.get("part")
    if isinstance(nested, dict):
        return _part_reason(nested)
    return ""


def _read_one_session_db(path: Path) -> tuple[int, str, str] | None:
    """Last root assistant message in one database.

    Returns ``(time, text, finish_reason)``. ``None`` when this file is not a
    usable session database. A usable database with no assistant message
    returns time ``-1`` and empty text.
    """
    import sqlite3

    connection = _open_session_db(path)
    if connection is None:
        return None
    try:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        if "message" not in tables or "part" not in tables:
            return None
        roots: set[str] | None = None
        if "session" in tables:
            roots = set()
            columns = _column_map(connection, "session")
            id_at = _pick(columns, "id")
            parent_at = _pick(columns, "parent_id", "parentID")
            data_at = _pick(columns, "data")
            if id_at is None:
                roots = None
            else:
                for row in connection.execute("SELECT * FROM session"):
                    ident = row[id_at]
                    if not isinstance(ident, str) or not ident:
                        continue
                    parent = row[parent_at] if parent_at is not None else None
                    if not parent and data_at is not None:
                        payload = _load_json(row[data_at])
                        parent = payload.get("parentID") or payload.get("parentId")
                    if not parent:
                        roots.add(ident)
        messages = _column_map(connection, "message")
        id_at = _pick(messages, "id")
        session_at = _pick(messages, "session_id", "sessionID")
        time_at = _pick(messages, "time_created", "timeCreated")
        data_at = _pick(messages, "data")
        if id_at is None or data_at is None:
            return None
        chosen = None
        for row in connection.execute("SELECT * FROM message"):
            payload = _load_json(row[data_at])
            if _message_role(payload) != "assistant":
                continue
            session = row[session_at] if session_at is not None else ""
            if not isinstance(session, str) or not session:
                session = str(payload.get("sessionID") or payload.get("sessionId") or "")
            if roots is not None and session and session not in roots:
                continue
            ident = row[id_at]
            if not isinstance(ident, str) or not ident:
                ident = str(payload.get("id") or "")
            if not ident:
                continue
            stamp = row[time_at] if time_at is not None else None
            when = _message_time(payload, stamp if isinstance(stamp, int) else None)
            if chosen is None or when >= chosen[0]:
                chosen = (when, ident, payload)
        if chosen is None:
            return (-1, "", "")
        when, message_id, message = chosen
        parts = _column_map(connection, "part")
        part_message = _pick(parts, "message_id", "messageID")
        part_time = _pick(parts, "time_created", "timeCreated")
        part_data = _pick(parts, "data")
        if part_data is None:
            return (when, "", "")
        collected = []
        for row in connection.execute("SELECT * FROM part"):
            payload = _load_json(row[part_data])
            owner = row[part_message] if part_message is not None else None
            if not isinstance(owner, str) or not owner:
                owner = str(payload.get("messageID") or payload.get("messageId") or "")
            if owner != message_id:
                continue
            stamp = row[part_time] if part_time is not None else None
            part_when = stamp if isinstance(stamp, int) else 0
            collected.append((part_when, payload))
        collected.sort(key=lambda item: item[0])
        texts = []
        reason = ""
        for _part_when, payload in collected:
            text = _part_text(payload)
            if text:
                texts.append(text)
            found = _part_reason(payload)
            if found:
                reason = found
        if not reason:
            for key in ("finish", "reason"):
                if isinstance(message.get(key), str) and message[key]:
                    reason = message[key]
                    break
        return (when, "".join(texts).strip(), reason)
    except sqlite3.Error:
        return None
    finally:
        _close_session_db(connection)


def db_final_answer(evidence_dir: Path | str) -> tuple[str, str] | None:
    """Final answer stored in the cell's OpenCode sqlite database.

    ``None`` when no usable session database is present. Otherwise
    ``(text, finish_reason)`` from the last root-session assistant message.
    Stdout is not consulted.
    """
    paths = _session_db_paths(Path(evidence_dir))
    if not paths:
        return None
    best = None
    usable = False
    for path in paths:
        parsed = _read_one_session_db(path)
        if parsed is None:
            continue
        usable = True
        if best is None or parsed[0] >= best[0]:
            best = parsed
    if not usable or best is None:
        return None
    return best[1], best[2]


def _stdout_final_text(directory: Path) -> str:
    """Final answer from stdout and the copied storage tree."""
    extracted = ""
    agent = directory / "agent-output.txt"
    if agent.is_file():
        try:
            extracted = extract_final_answer(_read(agent))
        except OSError:
            extracted = ""
        if extracted.strip():
            return extracted
    try:
        stored = _storage_final_text(directory)
    except OSError:
        stored = ""
    if stored.strip():
        return stored
    streamed = directory / "streamed-text.txt"
    if streamed.is_file():
        try:
            body = _read(streamed).strip()
        except OSError:
            body = ""
        if body:
            return body
    written = directory / FINAL_ANSWER_NAME
    if written.is_file() and not agent.is_file():
        try:
            return _plain_final_answer(_read(written))
        except OSError:
            return ""
    return extracted


def final_answer_record(evidence_dir: Path | str) -> dict:
    """Extracted answer, whether it ended on ``stop``, and which source won.

    The session database wins whenever it is present. ``source`` is ``db`` or
    ``stdout``. ``complete`` is set for a database answer and left ``None``
    when the caller still has to read the finish reason from stdout.
    """
    directory = Path(evidence_dir)
    stored = db_final_answer(directory)
    if stored is not None:
        text, reason = stored
        return {"text": text, "complete": reason == "stop", "source": "db"}
    return {"text": _stdout_final_text(directory), "complete": None, "source": "stdout"}


def final_text(evidence_dir: Path | str) -> str:
    """Final answer for one cell's evidence directory.

    The OpenCode session database is the source when it was copied into the
    evidence directory. Stdout (``agent-output.txt``, then storage, then
    ``streamed-text.txt``) is used only when that database is missing.
    """
    return final_answer_record(evidence_dir)["text"]


def publish_final_answer(dest_root: str, raw_text: str) -> str:
    """Write ``final-answer.txt`` and export ``OBENCH_FINAL_ANSWER``.

    A session database already copied into ``dest_root`` supplies the text.
    Otherwise the stdout is extracted, and storage fills in when that stdout
    has no assistant text.
    """
    stored = db_final_answer(dest_root)
    if stored is not None:
        text = stored[0]
    else:
        text = extract_final_answer(raw_text or "")
        if not text.strip():
            text = _storage_final_text(Path(dest_root))
    path = os.path.join(dest_root, FINAL_ANSWER_NAME)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    os.environ[FINAL_ANSWER_ENV] = path
    return text


def checker_text() -> str:
    """Final answer visible to ``checker.sh``.

    A live cell sets ``OBENCH_OPENCODE_EVIDENCE_DIR``. The helper extracts the
    answer from that directory, so a checker does not need to know whether the
    build spoke JSON. ``OBENCH_FINAL_ANSWER`` is the path of ``final-answer.txt``
    when the directory was not published.
    """
    root = os.environ.get("OBENCH_OPENCODE_EVIDENCE_DIR", "").strip()
    if root:
        try:
            return final_text(root)
        except OSError:
            return ""
    path = os.environ.get(FINAL_ANSWER_ENV, "").strip()
    if path and os.path.isfile(path):
        try:
            return Path(path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""
    return ""
