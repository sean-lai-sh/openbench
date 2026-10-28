"""Replay the F03-2 projection on the merged 1027 run.

Source is ``results/step8-f032-1027`` at 41877c92 (the cells and gate.json
committed on main). No model calls. Prints the resume decision and the
final spend against the $70 stop used for that resume and the launcher's
configured $60 stop.

The resume instant is the driver.log line ``gate already passed (GATE-DONE);
resuming`` at 2026-10-27 04:03:16 EDT. Cells with ``ended_et`` before that
instant are the directory the resume projected.
"""
from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from thesis.ab.step8_project import load, phase_cap, project

ROOT = Path(__file__).resolve().parents[2]
COMMIT = "41877c9274300ebb1f06f31678c5585f66a31aef"
RUN = "results/step8-f032-1027"
PRIOR = 2.08
STOP_RUN = 70.0
STOP_CONFIGURED = 60.0
# driver.log: 2026-10-27 04:03:16 EDT gate already passed; resuming
RESUME_BEFORE = "2026-10-27T04:03:16"


def _git_bytes_many(paths: list[str]) -> dict[str, bytes]:
    """Read blobs in one ``git cat-file --batch`` pass.

    Requests and replies are interleaved. Writing every request before reading
    deadlocks once the pipe buffer fills.
    """
    out = {}
    with subprocess.Popen(
            ["git", "cat-file", "--batch"], cwd=ROOT,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE) as proc:
        assert proc.stdin is not None and proc.stdout is not None
        for path in paths:
            proc.stdin.write(f"{COMMIT}:{path}\n".encode())
            proc.stdin.flush()
            header = proc.stdout.readline().decode()
            size = int(header.split()[2])
            out[path] = proc.stdout.read(size)
            proc.stdout.read(1)  # trailing newline
        proc.stdin.close()
    if proc.returncode not in (0, None):
        raise RuntimeError("git cat-file --batch failed")
    return out


def _cell_paths() -> list[str]:
    out = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", COMMIT, RUN],
        cwd=ROOT, check=True, capture_output=True, text=True)
    paths = []
    for line in out.stdout.splitlines():
        rel = line[len(RUN) + 1:]
        parts = rel.split("/")
        if len(parts) == 6 and parts[2] == "cells" and parts[-1].endswith(".json"):
            paths.append(line)
    return paths


def _load_run() -> tuple[dict, list[tuple[str, dict]]]:
    """gate.json plus (relative path, cell) for every cell file. Read once."""
    cells = _cell_paths()
    blobs = _git_bytes_many([f"{RUN}/gate.json", *cells])
    gate = json.loads(blobs[f"{RUN}/gate.json"])
    rows = []
    for path in cells:
        # Projection reads cost, route, rerun, and the traced/gate markers.
        # The committed cells are much larger; keep only those fields.
        full = json.loads(blobs[path])
        rows.append((path[len(RUN) + 1:], {
            "requests_cost_usd": full.get("requests_cost_usd") or 0,
            "route": full.get("route") or "",
            "rerun": full.get("rerun") or 0,
            "strace_on": full.get("strace_on") is True,
            "gate_cell": full.get("gate_cell") is True,
            "ended_et": full.get("ended_et") or "",
        }))
    return gate, rows


def materialize(dest: Path, gate: dict, rows: list[tuple[str, dict]], before: str | None = None) -> dict:
    """Write gate.json and cell jsons. ``before`` keeps cells ended earlier."""
    (dest / "gate.json").write_text(json.dumps(gate))
    kept = {"gate": 0, "scored": 0, "rerun": 0, "off_route": 0}
    for rel, cell in rows:
        ended = str(cell.get("ended_et") or "")
        if before is not None and not ended < before:
            continue
        phase = rel.split("/")[0]
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(cell))
        kept[phase] = kept.get(phase, 0) + 1
        if not str(cell.get("route") or "").startswith("on:"):
            kept["off_route"] += 1
    return kept


def _num(value) -> str:
    return json.dumps(value)


def _decision(projected: float, stop: float) -> str:
    return "RESUME" if projected <= stop else "HOLD"


def report() -> str:
    gate, rows = _load_run()
    with tempfile.TemporaryDirectory() as final_dir, tempfile.TemporaryDirectory() as resume_dir:
        final_counts = materialize(Path(final_dir), gate, rows)
        resume_counts = materialize(Path(resume_dir), gate, rows, before=RESUME_BEFORE)
        final_gate, final_scored, final_spent, final_blocked = load(final_dir)
        final = project(final_gate, final_scored, final_spent, prior=PRIOR, blocked=final_blocked)
        resume_gate, resume_scored, resume_spent, resume_blocked = load(resume_dir)
        resume = project(resume_gate, resume_scored, resume_spent, prior=PRIOR, blocked=resume_blocked)
        total_exact = PRIOR + final_spent
        total = round(total_exact, 2)
        cap = phase_cap(resume_dir, "scored", STOP_RUN, PRIOR)
        scored_only = round(sum(
            c["requests_cost_usd"] for rel, c in rows if rel.startswith("scored/")), 4)
        lines = [
            "F03-2 projection replay",
            f"source: {COMMIT} {RUN}",
            f"prior_usd: {_num(PRIOR)}",
            f"cells: {sum(final_counts[k] for k in ('gate', 'scored', 'rerun'))} "
            f"(gate {final_counts['gate']}, scored {final_counts['scored']}, "
            f"off_route {final_counts['off_route']})",
            f"cell_spend_usd: {_num(round(final_spent, 4))}",
            f"total_spend_usd: {_num(total)}",
            f"total_spend_exact_usd: {_num(round(total_exact, 4))}",
            f"resume_at: {RESUME_BEFORE}-04:00",
            f"resume_cells: {sum(resume_counts[k] for k in ('gate', 'scored', 'rerun'))}",
            f"resume_spent_usd: {_num(resume['spent'])}",
            f"resume_projected_usd: {_num(resume['projected'])}",
            f"resume_decision_stop_70: {_decision(resume['projected'], STOP_RUN)}",
            f"resume_decision_stop_60_configured: {_decision(resume['projected'], STOP_CONFIGURED)}",
            f"resume_scored_phase_cap_usd: {_num(cap)}",
            f"scored_spend_usd: {_num(scored_only)}",
            f"scored_spend_under_resume_cap: {'yes' if scored_only <= cap else 'no'}",
            f"final_done_prs: {len(final['done_prs'])}",
            f"final_remaining_usd: {_num(final['remaining'])}",
            f"final_projected_usd: {_num(final['projected'])}",
            f"final_spend_under_stop_70: {'yes' if total <= STOP_RUN else 'no'}",
            f"final_spend_under_stop_60: {'yes' if total <= STOP_CONFIGURED else 'no'}",
            "",
        ]
    return "\n".join(lines)


def main() -> int:
    print(report(), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
