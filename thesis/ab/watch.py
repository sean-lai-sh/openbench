"""No-progress watchdog for one A/B cell.

Progress is new stdout, a ``message.part.updated`` event on stdout or in
the OpenCode logs, growth under ``$XDG_DATA_HOME/opencode`` (logs and
storage), a larger per-cell request ledger, or a larger in-flight byte
counter beside that ledger. The ledger is the file that records every
finished ``/c/<cell_id>/`` request. A stream does not append that file
until the request ends, so chunks also update the sibling ``.bytes`` file.
Either of those stream signals (a part update, or streamed bytes) resets
the idle clock. A fatal ``Aborted(`` or tree-sitter wasm ENOENT line kills
the process immediately. Silence for ``no_progress_s`` (``NO_PROGRESS_S``,
300s) kills it as ``no_progress``.
"""

from __future__ import annotations

import os
import re
import select
import signal
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Shared with run_ab, the monorepo smoke gate, and scoring-parity replay.
# Replay classifies through apply_watchdog_class; it does not re-time the cell.
NO_PROGRESS_S = 300.0
PART_UPDATED = "message.part.updated"
# Last part update at least this close to 300s is the event that started the
# idle clock, not a stream that continued through it.
# OpenCode log stamps are whole seconds, so the real event is up to 1.0s
# after the stamp and a computed gap is up to 1.0s too large. The watchdog
# polls on a 0.2s select, and recorded idle_s in the deferred batch overshoots
# 300 by at most about 0.4s. opus/26821 without regex-chess trial 3 is
# gap 299.4s against idle_s 300.2 (0.8s inside the recorded idle). A 2.0s
# band around 300 covers that clock and poll error.
STREAM_BOUNDARY_S = 2.0
# Relabel only when the last update is this far inside the idle limit.
# 30s is an order of magnitude past the 2s boundary band, so the event
# happened while the watchdog was already counting silence.
STREAM_CLEAR_INSIDE_S = 30.0
_KIND_RANK = {
    "part_updated": 0,
    "stream_bytes": 1,
    "stdout": 2,
    "log": 3,
    "ledger": 4,
    "storage": 5,
}
_LOG_TS_RE = re.compile(
    r"(?P<ts>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?)"
)

FATAL_RE = re.compile(
    r"failed to asynchronously prepare wasm|Aborted\(|ENOENT:[^\n]*tree-sitter[^\n]*\.wasm"
)
_MARKER_RE = re.compile(
    r"openbench-infra:(no_progress|wasm_abort) idle_s=([0-9]+(?:\.[0-9]+)?)"
)


def infra_marker(reason: str, idle_s: float) -> str:
    return f"openbench-infra:{reason} idle_s={idle_s:.1f}"


class PromptIdle(Exception):
    def __init__(self, output: str):
        super().__init__("waiting on a permission prompt")
        self.output = output


class WatchdogKill(Exception):
    def __init__(self, reason: str, idle_s: float, output: str, last_progress_kind=None):
        self.reason = reason
        self.idle_s = float(idle_s)
        self.output = output
        self.last_progress_kind = last_progress_kind
        super().__init__(self.marker())

    def marker(self) -> str:
        return infra_marker(self.reason, self.idle_s)


class _Done:
    def __init__(self, returncode: int, stdout: str, last_progress_kind=None):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = ""
        self.last_progress_kind = last_progress_kind


def _file_size(path: str | Path | None) -> int | None:
    if not path:
        return None
    try:
        return Path(path).stat().st_size
    except OSError:
        return None


def read_byte_total(path: str | Path | None) -> int | None:
    """Return the counter, or None when the file is missing or not an integer.

    A failed parse is not progress. Callers keep the last good value.
    """
    if not path:
        return None
    try:
        text = Path(path).read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not text.isdigit():
        return None
    return int(text)


def _data_root(env: dict | None) -> Path | None:
    if not env:
        return None
    raw = env.get("XDG_DATA_HOME")
    if not raw:
        return None
    return Path(raw) / "opencode"


def _tree_signature(root: Path | None) -> tuple | None:
    if root is None or not root.is_dir():
        return None
    count = 0
    total = 0
    newest = 0
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            count += 1
            try:
                st = os.stat(os.path.join(dirpath, name))
            except OSError:
                continue
            total += st.st_size
            if st.st_mtime_ns > newest:
                newest = st.st_mtime_ns
    return (count, total, newest)


def _log_dirs(root: Path | None) -> list[Path]:
    if root is None or not root.is_dir():
        return []
    found = []
    log_dir = root / "log"
    if log_dir.is_dir():
        found.append(log_dir)
    project = root / "project"
    if project.is_dir():
        try:
            children = list(project.iterdir())
        except OSError:
            children = []
        for child in children:
            nested = child / "log"
            if nested.is_dir():
                found.append(nested)
    return found


def _new_log_text(root: Path | None, offsets: dict[str, int]) -> str:
    parts = []
    for directory in _log_dirs(root):
        try:
            paths = [path for path in directory.rglob("*") if path.is_file()]
        except OSError:
            continue
        for path in paths:
            key = str(path)
            try:
                size = path.stat().st_size
            except OSError:
                continue
            prev = offsets.get(key, 0)
            if size < prev:
                prev = 0
            if size == prev:
                continue
            try:
                with path.open("rb") as handle:
                    handle.seek(prev)
                    data = handle.read(size - prev)
            except OSError:
                continue
            offsets[key] = size
            parts.append(data.decode("utf-8", "replace"))
    return "".join(parts)


def kill_process_group(proc) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            proc.kill()
        except OSError:
            return


def _best_kind(*kinds: str | None) -> str | None:
    """The stream signal in this poll, if one moved; otherwise the other kind."""
    chosen = None
    for kind in kinds:
        if not kind:
            continue
        if chosen is None or _KIND_RANK[kind] < _KIND_RANK[chosen]:
            chosen = kind
    return chosen


def _text_kind(text: str, *, fallback: str) -> str | None:
    if not text:
        return None
    if PART_UPDATED in text:
        return "part_updated"
    return fallback


def _proxy_progress(
    *,
    bytes_path: str | None,
    ledger_path: str | None,
    last_bytes: int | None,
    last_ledger: int | None,
    last_stream: int | None,
) -> tuple[str | None, int | None, int | None, int | None]:
    """Return which proxy file moved, plus the new marks.

    ``ledger_path`` is the per-cell request JSONL. A finished request appends
    a line, so a larger file is progress (``ledger``). ``bytes_path``, or the
    ``.bytes`` sibling of the ledger, is the in-flight stream total
    (``stream_bytes``). A value that does not parse is ignored. Streamed
    bytes outrank a ledger append in the same poll: the request row is
    written only when the stream ends.
    """
    kind = None
    current = read_byte_total(bytes_path)
    if current is not None and (last_bytes is None or current > last_bytes):
        last_bytes = current
        kind = "stream_bytes"
    size = _file_size(ledger_path)
    if size is not None and (last_ledger is None or size > last_ledger):
        last_ledger = size
        if kind is None:
            kind = "ledger"
    stream_path = None
    if ledger_path and not bytes_path:
        stream_path = str(Path(ledger_path).with_suffix(".bytes"))
    stream = read_byte_total(stream_path)
    if stream is not None and (last_stream is None or stream > last_stream):
        last_stream = stream
        kind = "stream_bytes"
    return kind, last_bytes, last_ledger, last_stream


def run_piped(
    cmd,
    cwd,
    env,
    timeout_s: float,
    *,
    no_progress_s: float,
    bytes_path: str | None = None,
    ledger_path: str | None = None,
    prompt_re: re.Pattern[str] | None = None,
    prompt_idle_s: float = 8,
):
    """Stream one agent process. Return a completed process, or raise.

    ``PromptIdle`` is a permission prompt that went quiet. ``WatchdogKill``
    is ``no_progress`` or ``wasm_abort``. ``TimeoutExpired`` is the cell cap.
    Storage and proxy bytes do not reset the permission-prompt timer.
    """
    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        env=env,
        start_new_session=True,
    )
    pipe = proc.stdout
    fd = pipe.fileno()
    os.set_blocking(fd, False)
    chunks: list[str] = []
    carry = ""
    log_carry = ""
    log_offsets: dict[str, int] = {}
    start = time.monotonic()
    last_progress = start
    last_stdout = start
    last_kind = None
    prompted = False
    data_root = _data_root(env)
    last_sig = _tree_signature(data_root)
    last_bytes = read_byte_total(bytes_path)
    last_ledger = _file_size(ledger_path)
    stream_path = None
    if ledger_path and not bytes_path:
        stream_path = str(Path(ledger_path).with_suffix(".bytes"))
    last_stream = read_byte_total(stream_path)
    pin_raw = ""
    if isinstance(env, dict):
        pin_raw = str(env.get("OBENCH_PROVIDER_PINS") or "").strip()
    pin_violation = None
    pin_error = None
    if pin_raw:
        from thesis.ab.provider_pin import ProviderPinMismatch, violation_in_text
        pin_violation = violation_in_text
        pin_error = ProviderPinMismatch

    def output() -> str:
        return "".join(chunks)

    def pin_reason(text: str) -> str:
        if pin_violation is None or not text:
            return ""
        return pin_violation(text, pin_raw)

    def note_text(text: str) -> bool:
        nonlocal carry
        if not text:
            return False
        chunks.append(text)
        carry = (carry + text)[-400:]
        return bool(FATAL_RE.search(carry))

    def read_stdout(wait_s: float) -> str:
        """Read what is already buffered, after an optional short wait.

        One poll can spend a long time walking a large OpenCode tree
        (regex-chess and model-extraction sessions). Bytes that arrive
        during that walk must still count before the idle decision.
        """
        pieces = []
        timeout = wait_s
        while len(pieces) < 8:
            ready, _, _ = select.select([pipe], [], [], timeout)
            timeout = 0
            if not ready:
                break
            try:
                piece = os.read(fd, 65536)
            except BlockingIOError:
                break
            if not piece:
                break
            pieces.append(piece.decode("utf-8", "replace"))
        return "".join(pieces)

    def observe(kind: str | None) -> None:
        nonlocal last_progress, last_kind
        if not kind:
            return
        # Stamp the observation, not the start of a slow poll.
        last_progress = time.monotonic()
        last_kind = kind

    try:
        while True:
            fatal = False
            decoded = read_stdout(0.2)
            if decoded:
                fatal = note_text(decoded) or fatal
                last_stdout = time.monotonic()
                reason = pin_reason(decoded) or pin_reason(carry)
                if reason and pin_error is not None:
                    kill_process_group(proc)
                    raise pin_error(reason, output())
            log_text = _new_log_text(data_root, log_offsets)
            if log_text:
                log_carry = (log_carry + log_text)[-400:]
                reason = pin_reason(log_text) or pin_reason(log_carry)
                if reason and pin_error is not None:
                    kill_process_group(proc)
                    raise pin_error(reason, output())
                if FATAL_RE.search(log_carry):
                    fatal = True
            signature = _tree_signature(data_root)
            storage_kind = None
            if signature != last_sig:
                last_sig = signature
                storage_kind = "storage"
            proxy_kind, last_bytes, last_ledger, last_stream = _proxy_progress(
                bytes_path=bytes_path,
                ledger_path=ledger_path,
                last_bytes=last_bytes,
                last_ledger=last_ledger,
                last_stream=last_stream,
            )
            # The tree walk above can outlast the idle window. Drain the
            # pipe and the byte counter again so a part update or chunk
            # that landed during the walk still resets the clock.
            extra = read_stdout(0)
            if extra:
                fatal = note_text(extra) or fatal
                last_stdout = time.monotonic()
                decoded = decoded + extra
                reason = pin_reason(extra) or pin_reason(carry)
                if reason and pin_error is not None:
                    kill_process_group(proc)
                    raise pin_error(reason, output())
            extra_log = _new_log_text(data_root, log_offsets)
            if extra_log:
                log_text = (log_text or "") + extra_log
                log_carry = (log_carry + extra_log)[-400:]
                reason = pin_reason(extra_log) or pin_reason(log_carry)
                if reason and pin_error is not None:
                    kill_process_group(proc)
                    raise pin_error(reason, output())
                if FATAL_RE.search(log_carry):
                    fatal = True
            proxy_again, last_bytes, last_ledger, last_stream = _proxy_progress(
                bytes_path=bytes_path,
                ledger_path=ledger_path,
                last_bytes=last_bytes,
                last_ledger=last_ledger,
                last_stream=last_stream,
            )
            kind = _best_kind(
                _text_kind(decoded, fallback="stdout"),
                _text_kind(log_text, fallback="log"),
                storage_kind,
                proxy_kind,
                proxy_again,
            )
            if fatal:
                idle = max(0.0, time.monotonic() - last_progress)
                kill_process_group(proc)
                raise WatchdogKill(
                    "wasm_abort", idle, output(), kind or last_kind,
                )
            observe(kind)
            if proc.poll() is not None:
                try:
                    rest = os.read(fd, 65536)
                except (BlockingIOError, OSError):
                    rest = b""
                if rest:
                    decoded = rest.decode("utf-8", "replace")
                    wasm = note_text(decoded)
                    rest_kind = _text_kind(decoded, fallback="stdout")
                    reason = pin_reason(decoded) or pin_reason(output()[-2000:])
                    if reason and pin_error is not None:
                        kill_process_group(proc)
                        raise pin_error(reason, output())
                    if wasm:
                        idle = max(0.0, time.monotonic() - last_progress)
                        kill_process_group(proc)
                        raise WatchdogKill(
                            "wasm_abort", idle, output(), rest_kind or last_kind,
                        )
                    observe(rest_kind)
                break
            if prompt_re is not None and not prompted and prompt_re.search(output()):
                prompted = True
            now = time.monotonic()
            if prompted and now - last_stdout >= prompt_idle_s:
                kill_process_group(proc)
                raise PromptIdle(output())
            if no_progress_s > 0 and now - last_progress >= no_progress_s:
                kill_process_group(proc)
                raise WatchdogKill(
                    "no_progress",
                    max(0.0, now - last_progress),
                    output(),
                    last_kind,
                )
            if now - start >= timeout_s:
                text = output()
                kill_process_group(proc)
                raise subprocess.TimeoutExpired(cmd, timeout_s, output=text)
        code = proc.wait(timeout=5)
        return _Done(code, output(), last_kind)
    finally:
        if proc.poll() is None:
            kill_process_group(proc)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            kill_process_group(proc)
            proc.wait(timeout=5)
        pipe.close()


def apply_watchdog_class(row: dict) -> dict:
    """Mark a watchdog kill on the cell row. The checker score is discarded.

    ``run_cell`` keeps a fixed field set, so the adapter puts
    ``openbench-infra:<reason> idle_s=<seconds>`` in ``error``. A fatal
    wasm line with no marker is still ``wasm_abort``. ``no_progress_idle_s``
    is set only for a no-progress kill.
    """
    if not isinstance(row, dict):
        return row
    text = "\n".join(
        str(row.get(key) or "") for key in ("error", "output_tail", "full_output")
    )
    match = _MARKER_RE.search(text)
    if match:
        reason = match.group(1)
        idle = float(match.group(2))
        reason_text = match.group(0)
    elif FATAL_RE.search(text):
        reason = "wasm_abort"
        idle = None
        reason_text = "wasm_abort"
    else:
        return row
    requests = row.get("requests_count")
    made_requests = (
        isinstance(requests, (int, float)) and not isinstance(requests, bool) and requests > 0
    )
    if reason == "no_progress" and made_requests:
        # Silent after real model calls: the agent hung mid-session. That is a
        # scored failure (in the solve denominator, tokens kept), not infra.
        row["failure_class"] = "hang"
        row["failure_reason"] = reason_text
        row.pop("infra_reason", None)
        row["hang_reason"] = reason
        row["success"] = False
        row["score"] = 0.0
        row["completed"] = False
        if idle is not None:
            row["no_progress_idle_s"] = idle
        return row
    row.pop("hang_reason", None)
    row["failure_class"] = "infra"
    row["failure_reason"] = reason_text
    row["infra_reason"] = reason
    row["success"] = False
    row["score"] = 0.0
    row["completed"] = False
    if reason == "no_progress" and idle is not None:
        row["no_progress_idle_s"] = idle
    else:
        row.pop("no_progress_idle_s", None)
    return row


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_log_ts(value: str) -> datetime | None:
    try:
        if "." in value:
            parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%f")
        else:
            parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return None
    return _as_utc(parsed)


def _row_text(row: dict, logs: str | None = None) -> str:
    parts = [str(row.get(key) or "") for key in ("error", "output_tail", "full_output")]
    if logs:
        parts.append(logs)
    return "\n".join(parts)


def _is_no_progress_kill(row: dict) -> bool:
    if row.get("hang_reason") == "no_progress" or row.get("infra_reason") == "no_progress":
        return True
    match = _MARKER_RE.search(_row_text(row))
    return bool(match and match.group(1) == "no_progress")


def _idle_limit(row: dict) -> float:
    value = row.get("no_progress_idle_s")
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
        return float(value)
    match = _MARKER_RE.search(_row_text(row))
    if match and match.group(1) == "no_progress":
        return float(match.group(2))
    return NO_PROGRESS_S


def _kill_time(row: dict) -> datetime | None:
    """When the watchdog fired, from the cell clock, not a re-run."""
    started = row.get("started_at")
    elapsed = row.get("t_agent_s")
    if (
        isinstance(started, str)
        and isinstance(elapsed, (int, float))
        and not isinstance(elapsed, bool)
    ):
        try:
            start = datetime.fromisoformat(started)
        except ValueError:
            start = None
        if start is not None:
            return _as_utc(start) + timedelta(seconds=float(elapsed))
    for key in ("ended_at", "ended_et"):
        raw = row.get(key)
        if not isinstance(raw, str) or "T" not in raw:
            continue
        try:
            return _as_utc(datetime.fromisoformat(raw))
        except ValueError:
            continue
    return None


def part_updated_times(text: str) -> list[datetime]:
    """Timestamps of ``message.part.updated`` lines in an OpenCode log or tail.

    A line without its own timestamp uses the previous timestamped line, which
    is how a JSON event sits under the ``--print-logs`` line that emitted it.
    OpenCode's log clock is UTC.
    """
    found = []
    last = None
    for line in (text or "").splitlines():
        match = _LOG_TS_RE.search(line)
        if match:
            parsed = _parse_log_ts(match.group("ts"))
            if parsed is not None:
                last = parsed
        if PART_UPDATED in line and last is not None:
            found.append(last)
    return found


def last_part_updated_gap_s(row: dict, logs: str | None = None) -> float | None:
    """Seconds from the last ``message.part.updated`` to the kill.

    None when the row is not a no-progress kill, the kill time is unknown,
    or the logs have no part-update timestamp. The gap uses the latest
    event only: an earlier update does not count once a later one exists.
    """
    if not isinstance(row, dict) or not _is_no_progress_kill(row):
        return None
    kill = _kill_time(row)
    if kill is None:
        return None
    times = part_updated_times(_row_text(row, logs))
    if not times:
        return None
    return (kill - max(times)).total_seconds()


def stream_kill_verdict(row: dict, logs: str | None = None) -> str | None:
    """``relabel``, ``stays_hang``, or ``borderline`` for a measured gap.

    ``stays_hang`` when the last update is at least ``NO_PROGRESS_S`` before
    the kill, or within ``STREAM_BOUNDARY_S`` of that (gap >= 298s). That
    update started the idle clock. ``relabel`` when the gap is clearly
    inside the window: more than ``STREAM_CLEAR_INSIDE_S`` (30s) before
    both 300s and the cell's recorded idle. Anything between those two
    cuts is ``borderline`` and is not relabeled.
    """
    gap = last_part_updated_gap_s(row, logs)
    if gap is None:
        return None
    if gap >= NO_PROGRESS_S - STREAM_BOUNDARY_S:
        return "stays_hang"
    idle = _idle_limit(row)
    clear_before = min(idle, NO_PROGRESS_S) - STREAM_CLEAR_INSIDE_S
    if 0 <= gap < clear_before:
        return "relabel"
    return "borderline"


def part_updated_within_idle(row: dict, logs: str | None = None) -> bool:
    """True when the last part update is clearly inside the idle window.

    That is ``stream_kill_verdict`` == ``relabel``. A last update within
    ``STREAM_BOUNDARY_S`` of 300s stays a hang.
    """
    return stream_kill_verdict(row, logs) == "relabel"


def label_watchdog_stream(row: dict, logs: str | None = None) -> dict:
    """Label an old streaming kill without re-running it.

    Sets ``failure_class=env_failure`` and ``env_cause=watchdog_stream``
    only when ``stream_kill_verdict`` is ``relabel``. A boundary gap
    (``stays_hang``) and a ``borderline`` gap keep the stored class.
    Scoring replay does not call this: ``apply_watchdog_class`` stays the
    live and replay classifier.
    """
    if not isinstance(row, dict):
        return row
    if stream_kill_verdict(row, logs) == "relabel":
        row["failure_class"] = "env_failure"
        row["env_cause"] = "watchdog_stream"
    return row


def rescore(out_dir) -> dict:
    """Re-apply ``apply_watchdog_class`` to every stored cell under ``out_dir``.

    Rewrites only cells whose class changes, then re-projects each side's
    JSONL. Returns ``{pr/side: {old->new: count}}``.
    """
    import json
    from pathlib import Path
    from thesis.ab.run_ab import project_side, read_cell, publish_text

    out_dir = Path(out_dir)
    changes: dict = {}
    for side_dir in sorted(out_dir.glob("*/cells/*")):
        if not side_dir.is_dir():
            continue
        pr, side = side_dir.parent.parent.name, side_dir.name
        touched = False
        for path in sorted(side_dir.glob("*/*.json")):
            row = read_cell(path)
            if not isinstance(row, dict):
                continue
            before = row.get("failure_class")
            apply_watchdog_class(row)
            after = row.get("failure_class")
            if before != after:
                key = f"{before}->{after}"
                bucket = changes.setdefault(f"{pr}/{side}", {})
                bucket[key] = bucket.get(key, 0) + 1
                publish_text(path, json.dumps(row, sort_keys=True))
                touched = True
        if touched:
            project_side(out_dir, pr, side)
    return changes


def main(argv=None) -> int:
    import argparse
    import json
    parser = argparse.ArgumentParser(description="Rescore watchdog kills in stored A/B cells")
    parser.add_argument("out", help="A/B output directory")
    args = parser.parse_args(argv)
    print(json.dumps(rescore(args.out), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
