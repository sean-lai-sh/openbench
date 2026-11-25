#!/usr/bin/env python3
"""Derive ``expected_counts.json`` from the committed wire summaries.

The summaries are one line per model call, with ``call_index``,
``call_role``, ``side_kind``, ``status``, and ``thinking_tokens``
(``response_usage.output_tokens_details.thinking_tokens``, null kept as
null). They were cut down from the scrubbed ``wire.jsonl`` files, which
are not committed. ``--wires`` points at those files so each trial's
sha256 can be recorded and the counts traced back.

Formulas, from the fixture README:

- **steps.** Records with ``call_role == "main"`` and ``status == 200``.
  A main call that returned 4xx is not a step (the two corewars trials
  end on a 400; that call is ``post_compaction_signature`` / the 4xx
  count, not a step).
- **compaction_steps.** Records with ``call_role == "side"``,
  ``side_kind == "compaction"``, and ``status == 200``. OpenCode emits
  one extra session ``step_start`` per compaction (the summary). That
  step is not a main step.
- **summary_steps.** 0. A summary side call does not emit a session
  step, same as a title call, and these fixtures have no
  ``side_kind == "summary"`` record. A summary step would be counted
  only when the event stream can tell it from a compaction step.
- **synthetic_continue_messages.** Equals the compaction count. Each
  compaction is followed by OpenCode's synthetic "Continue if you have
  next steps…" text, which is input, not a step.
- **thinking_tokens.** Sum of ``thinking_tokens`` over main status-200
  records, null counted as 0. Main turns only.
- **compaction_thinking_tokens.** The same sum over the compaction
  records. It is not added to ``thinking_tokens``. Title calls in these
  fixtures reported 0, so a sum over every side record matches this.
- **thinking_tokens_status.** Histogram over main status-200 records.
  Null ``thinking_tokens`` is ``unreported``; an int, including 0, is
  ``reported``.

Usage::

    python3 derive_expected.py --wires /path/to/parser-fixtures
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent

FORMULAS = {
    "steps": "main calls with status 200",
    "compaction_steps": "side calls with side_kind compaction and status 200",
    "summary_steps": "0; summary side calls are not session steps, and these fixtures have none",
    "synthetic_continue_messages": "equals the compaction count (one synthetic continue text each)",
    "thinking_tokens": "sum of thinking_tokens over main status-200 calls, null as 0",
    "compaction_thinking_tokens": "sum of thinking_tokens over compaction status-200 calls, null as 0; not added to thinking_tokens",
    "thinking_tokens_status": "main status-200 calls: null -> unreported, int (including 0) -> reported",
    "wire_sha256": "sha256 of the source wire.jsonl this summary was cut from; the wire file is not committed",
}


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _as_int(value) -> int:
    """Null counts as 0. A bool is not a count."""
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return value


def derive_trial(rows: list[dict]) -> dict:
    main_200 = [row for row in rows if row.get("call_role") == "main" and row.get("status") == 200]
    compaction = [row for row in rows
                  if row.get("call_role") == "side" and row.get("side_kind") == "compaction"
                  and row.get("status") == 200]
    statuses = ["unreported" if row.get("thinking_tokens") is None else "reported" for row in main_200]
    compaction_calls = [{"call_index": row.get("call_index"), "thinking_tokens": row.get("thinking_tokens")}
                        for row in sorted(compaction, key=lambda row: (not isinstance(row.get("call_index"), int),
                                                                      row.get("call_index") or 0))]
    return {
        "steps": len(main_200),
        "compaction_steps": len(compaction),
        "summary_steps": 0,
        "synthetic_continue_messages": len(compaction),
        "thinking_tokens": sum(_as_int(row.get("thinking_tokens")) for row in main_200),
        "compaction_thinking_tokens": sum(_as_int(row.get("thinking_tokens")) for row in compaction),
        "thinking_tokens_status": {key: statuses.count(key) for key in sorted(set(statuses))},
        "compaction_calls": compaction_calls,
    }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def trial_dirs(root: Path) -> list[Path]:
    return sorted(path for path in root.iterdir() if path.is_dir() and (path / "wire-summary.jsonl").is_file())


def derive(root: Path, wires: Path | None, previous: dict | None) -> dict:
    trials = {}
    old = (previous or {}).get("trials") or {}
    for directory in trial_dirs(root):
        counts = derive_trial(load_jsonl(directory / "wire-summary.jsonl"))
        if wires is not None:
            source = wires / directory.name / "wire.jsonl"
            if not source.is_file():
                raise SystemExit(f"no source wire: {source}")
            counts["wire_sha256"] = sha256_file(source)
        elif directory.name in old and old[directory.name].get("wire_sha256"):
            counts["wire_sha256"] = old[directory.name]["wire_sha256"]
        else:
            raise SystemExit(f"{directory.name}: pass --wires to record wire_sha256")
        trials[directory.name] = counts
    return {"formulas": FORMULAS, "trials": trials}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", type=Path, default=HERE)
    parser.add_argument("--wires", type=Path, default=None,
                        help="directory of <trial>/wire.jsonl files to hash; not committed")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)
    out = args.out or (args.fixtures / "expected_counts.json")
    previous = json.loads(out.read_text(encoding="utf-8")) if out.is_file() else None
    payload = derive(args.fixtures, args.wires, previous)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
