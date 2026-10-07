"""No-progress watchdog for one A/B cell.

Progress is new stdout, growth under ``$XDG_DATA_HOME/opencode`` (logs and
storage), a larger per-cell request ledger, or a larger in-flight byte
counter beside that ledger. The ledger is the file that records every
finished ``/c/<cell_id>/`` request. A stream does not append that file
until the request ends, so chunks also update the sibling ``.bytes`` file.
A fatal ``Aborted(`` or tree-sitter wasm ENOENT line kills the process
immediately. Silence for ``no_progress_s`` kills it as ``no_progress``.
"""

from __future__ import annotations

import os
import re
import select
import signal
import subprocess
import time
from pathlib import Path

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
    def __init__(self, reason: str, idle_s: float, output: str):
        self.reason = reason
        self.idle_s = float(idle_s)
        self.output = output
        super().__init__(self.marker())

    def marker(self) -> str:
        return infra_marker(self.reason, self.idle_s)


class _Done:
    def __init__(self, returncode: int, stdout: str):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = ""


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


def _proxy_progress(
    *,
    bytes_path: str | None,
    ledger_path: str | None,
    last_bytes: int | None,
    last_ledger: int | None,
    last_stream: int | None,
) -> tuple[bool, int | None, int | None, int | None]:
    """Return whether the cell's proxy accounting moved, plus the new marks.

    ``ledger_path`` is the per-cell request JSONL. A finished request appends
    a line, so a larger file is progress. ``bytes_path``, or the ``.bytes``
    sibling of the ledger, is the in-flight stream total. A value that does
    not parse is ignored.
    """
    progressed = False
    current = read_byte_total(bytes_path)
    if current is not None and (last_bytes is None or current > last_bytes):
        last_bytes = current
        progressed = True
    size = _file_size(ledger_path)
    if size is not None and (last_ledger is None or size > last_ledger):
        last_ledger = size
        progressed = True
    stream_path = None
    if ledger_path and not bytes_path:
        stream_path = str(Path(ledger_path).with_suffix(".bytes"))
    stream = read_byte_total(stream_path)
    if stream is not None and (last_stream is None or stream > last_stream):
        last_stream = stream
        progressed = True
    return progressed, last_bytes, last_ledger, last_stream


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
    prompted = False
    data_root = _data_root(env)
    last_sig = _tree_signature(data_root)
    last_bytes = read_byte_total(bytes_path)
    last_ledger = _file_size(ledger_path)
    stream_path = None
    if ledger_path and not bytes_path:
        stream_path = str(Path(ledger_path).with_suffix(".bytes"))
    last_stream = read_byte_total(stream_path)

    def output() -> str:
        return "".join(chunks)

    def note_text(text: str) -> bool:
        nonlocal carry
        if not text:
            return False
        chunks.append(text)
        carry = (carry + text)[-400:]
        return bool(FATAL_RE.search(carry))

    try:
        while True:
            ready, _, _ = select.select([pipe], [], [], 0.2)
            now = time.monotonic()
            progressed = False
            fatal = False
            if ready:
                try:
                    piece = os.read(fd, 65536)
                except BlockingIOError:
                    piece = b""
                if piece:
                    fatal = note_text(piece.decode("utf-8", "replace")) or fatal
                    last_stdout = now
                    progressed = True
            log_text = _new_log_text(data_root, log_offsets)
            if log_text:
                progressed = True
                log_carry = (log_carry + log_text)[-400:]
                if FATAL_RE.search(log_carry):
                    fatal = True
            signature = _tree_signature(data_root)
            if signature != last_sig:
                last_sig = signature
                progressed = True
            moved, last_bytes, last_ledger, last_stream = _proxy_progress(
                bytes_path=bytes_path,
                ledger_path=ledger_path,
                last_bytes=last_bytes,
                last_ledger=last_ledger,
                last_stream=last_stream,
            )
            if moved:
                progressed = True
            if fatal:
                kill_process_group(proc)
                raise WatchdogKill(
                    "wasm_abort", max(0.0, now - last_progress), output()
                )
            if progressed:
                last_progress = now
            if proc.poll() is not None:
                try:
                    rest = os.read(fd, 65536)
                except (BlockingIOError, OSError):
                    rest = b""
                if rest and note_text(rest.decode("utf-8", "replace")):
                    kill_process_group(proc)
                    raise WatchdogKill(
                        "wasm_abort", max(0.0, now - last_progress), output()
                    )
                break
            if prompt_re is not None and not prompted and prompt_re.search(output()):
                prompted = True
            if prompted and now - last_stdout >= prompt_idle_s:
                kill_process_group(proc)
                raise PromptIdle(output())
            if no_progress_s > 0 and now - last_progress >= no_progress_s:
                kill_process_group(proc)
                raise WatchdogKill(
                    "no_progress", max(0.0, now - last_progress), output()
                )
            if now - start >= timeout_s:
                text = output()
                kill_process_group(proc)
                raise subprocess.TimeoutExpired(cmd, timeout_s, output=text)
        code = proc.wait(timeout=5)
        return _Done(code, output())
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
