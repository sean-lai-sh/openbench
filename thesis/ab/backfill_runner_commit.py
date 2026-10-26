"""Fill ``runner_commit`` on stored cells from a driver log.

The in-container runner used to record ``runner_commit: null`` because the
worktree ``.git`` file points outside the mount. Host driver logs still have
``runner=<sha>``. This script writes that sha onto cell JSON files and JSONL
rows whose ``runner_commit`` is missing, null, or empty. A cell that already
has a commit is left unchanged. Disagreeing ``runner=`` lines abort before
any write.

JSONL is updated one row at a time. Only an empty ``runner_commit`` is
filled; every other field stays as it was, and the line count stays the
same. A row that does not need a fill is copied through unchanged, so its
bytes round-trip. A filled row is written with ``json.dumps(sort_keys=True)``,
the same encoding the per-cell JSONL writer uses.

Usage:
    python3 -m thesis.ab.backfill_runner_commit DRIVER_LOG CELLS_DIR

Do not point it at a results tree unless those cells should be rewritten.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_RUNNER = re.compile(r"\brunner=([0-9a-fA-F]{7,40})\b")


class BackfillError(RuntimeError):
    """The driver log has no usable runner sha, or the shas disagree."""


def runner_sha_from_log(text: str) -> str:
    """Return the runner sha. A short sha and its full sha count as one."""
    found = [item.lower() for item in _RUNNER.findall(text or "")]
    if not found:
        raise BackfillError("driver log has no runner=<sha> line")
    unique = sorted(set(found), key=len)
    longest = unique[-1]
    for item in unique:
        if not (longest.startswith(item) or item.startswith(longest)):
            raise BackfillError(
                "driver log has disagreeing runner shas: " + ", ".join(unique)
            )
    return longest


def _needs_fill(row: dict) -> bool:
    if "task" not in row or "trial" not in row:
        return False
    current = row.get("runner_commit")
    return current is None or current == ""


def _fill_jsonl_line(line: bytes, sha: str) -> tuple[bytes, bool]:
    """Return the line to keep, and whether ``runner_commit`` was filled.

    Lines that are blank, not a cell object, or already committed are
    returned unchanged so they round-trip byte for byte.
    """
    if not line.strip():
        return line, False
    try:
        parsed = json.loads(line)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return line, False
    if not isinstance(parsed, dict) or not _needs_fill(parsed):
        return line, False
    parsed["runner_commit"] = sha
    return json.dumps(parsed, sort_keys=True).encode("utf-8"), True


def _backfill_jsonl(path: Path, sha: str) -> int:
    """Fill empty commits in one JSONL file. Return how many rows changed.

    The file is left untouched when no row needs a fill. Otherwise each
    unchanged line is copied as-is and each filled row is serialized with
    ``json.dumps(sort_keys=True)``. A trailing newline is preserved, and
    the number of lines does not change.
    """
    try:
        raw = path.read_bytes()
    except OSError:
        return 0
    if not raw:
        return 0
    trailing_nl = raw.endswith(b"\n")
    body = raw[:-1] if trailing_nl else raw
    lines = body.split(b"\n")
    rewritten = [_fill_jsonl_line(line, sha) for line in lines]
    updated = sum(1 for _, did in rewritten if did)
    if updated == 0:
        return 0
    payload = b"\n".join(line for line, _ in rewritten)
    if trailing_nl:
        payload += b"\n"
    path.write_bytes(payload)
    return updated


def backfill_runner_commit(driver_log: Path, cells_dir: Path) -> int:
    """Write the log's runner sha onto empty cell commits. Return the count.

    The sha is parsed before any cell is opened for write. Disagreeing shas
    raise ``BackfillError`` and leave the tree untouched. ``*.json`` cells
    are rewritten whole; ``*.jsonl`` cells are rewritten row by row.
    """
    sha = runner_sha_from_log(Path(driver_log).read_text(encoding="utf-8", errors="replace"))
    updated = 0
    root = Path(cells_dir)
    for path in sorted(root.rglob("*.json")):
        try:
            parsed = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(parsed, dict) or not _needs_fill(parsed):
            continue
        parsed["runner_commit"] = sha
        path.write_text(json.dumps(parsed, sort_keys=True) + "\n", encoding="utf-8")
        updated += 1
    for path in sorted(root.rglob("*.jsonl")):
        updated += _backfill_jsonl(path, sha)
    return updated


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Backfill cell runner_commit from a driver log")
    parser.add_argument("driver_log", type=Path, help="driver log containing runner=<sha>")
    parser.add_argument("cells_dir", type=Path, help="directory of cell JSON and JSONL files")
    args = parser.parse_args(argv)
    try:
        count = backfill_runner_commit(args.driver_log, args.cells_dir)
    except BackfillError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"updated {count} cell(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
