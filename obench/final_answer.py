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


def final_text(evidence_dir: Path | str) -> str:
    """Final answer for one cell's evidence directory.

    Prefers a JSON or plain-text extraction of ``agent-output.txt``. When that
    is empty, uses storage text parts from the root session's last assistant
    message, then ``streamed-text.txt`` for a delta-only capture.
    """
    directory = Path(evidence_dir)
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


def publish_final_answer(dest_root: str, raw_text: str) -> str:
    """Write ``final-answer.txt`` and export ``OBENCH_FINAL_ANSWER``.

    Storage copied into ``dest_root`` fills in when the stdout has no
    assistant text. The returned text is what checkers should score.
    """
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
