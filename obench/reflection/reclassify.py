"""Offline reclassification of finished trials (no model calls, no rerun).

Researcher ruling 2026-11-16: a 4xx that OpenCode retried and recovered from is
not an infrastructure failure. Trials run before that ruling (#265 at
954286aa or earlier) were marked ``upstream_4xx`` on any 4xx, and were not
graded or traced. This tool rereads each trial's ``wire.jsonl`` and fills in
what's needed:

- ``upstream_4xx`` trials whose 4xx was retried and recovered from (a later
  main call returned 200) are finished as the executor now would: the task
  checker runs on the trial's saved workspace (the agent's final state; it was
  never graded) and the trace is built. The new status is ``completed``, or
  ``route_truncated`` / ``error`` / ``timeout``.
- Every row gets the new covariate and image fields: ``retried_4xx``,
  ``image_ref``, ``image_id``, ``image_matches_pin``.

Old ``upstream_4xx`` trials have no ``cell.json`` (it was written after the
4xx check), so it isn't recorded whether OpenCode finished or timed out. The
tool treats the trial as finished only if the event stream ends with a final
``step_finish``. Otherwise the row stays ``upstream_4xx`` with
``reclassified.note = "unknown_timeout"`` for review.

Dry run by default (prints what would change). With ``--apply`` it keeps the
old file as ``trials.pre-reclassify-<UTC>.jsonl``, rewrites ``trials.jsonl``
(each changed row gets ``reclassified: {from, at, code_commit}``) and rebuilds
``summary.jsonl`` and ``verdicts.json``. Needs Docker and the task images (the
checker), on the VM:

    python3 -m obench.reflection.reclassify --run <run dir> --opencode <bin/<sha>/opencode> [--apply]
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from obench.hardsuite.suite import resolve
from obench.reflection import trace as tr
from obench.reflection.runner import RunConfig, Runner, TrialSpec, code_commit, read_rows
from obench.reflection.wire_proxy import classify_4xx

FINAL_REASONS = ("stop", "end_turn", "length", "max_tokens")


def _wires(trial_dir: Path) -> list[dict]:
    path = trial_dir / "wire.jsonl"
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()] if path.exists() else []


def _finished_by_itself(trial_dir: Path) -> bool:
    path = trial_dir / "opencode-events.jsonl"
    if not path.exists():
        return False
    try:
        events = tr.parse_events(path.read_text(encoding="utf-8").splitlines())
    except tr.TraceError:
        return False
    last = events[-1] if events else {}
    return last.get("type") == "step_finish" and (last.get("part") or {}).get("reason") in FINAL_REASONS


def reclassify(run_dir: Path, executor, apply: bool = False, suites_dir: Path | None = None) -> dict:
    run_dir = Path(run_dir)
    plan = json.loads((run_dir / "plan.json").read_text(encoding="utf-8"))
    config = RunConfig.from_dict(plan["config"])
    runner = Runner(config, run_dir, executor, suites_dir=suites_dir)
    rows = read_rows(run_dir / "trials.jsonl")
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    commit = code_commit()["commit"]
    out, changes = [], []
    for row in rows:
        trial_dir = run_dir / row["trial_dir"]
        spec = TrialSpec(run_id=row["run_id"], trial_id=row["trial_id"], task=row["task"],
                         tasks_dir=resolve(runner.known[row["task"]])[0], model=row["model"],
                         trial_index=row["trial_index"], patch_id=row["patch_id"], patch=config.patch,
                         trial_dir=row["trial_dir"])
        new = dict(row)
        fours = classify_4xx(_wires(trial_dir))
        task = executor.resolve_image(executor._task(spec), spec.task) if not (trial_dir / "cell.json").exists() else None
        if row["status"] == "upstream_4xx" and not fours["breaking"]:
            if not (trial_dir / "cell.json").exists():
                if not _finished_by_itself(trial_dir):
                    new["reclassified"] = {"from": row["status"], "at": now, "code_commit": commit, "note": "unknown_timeout"}
                    out.append(new)
                    changes.append({"trial_id": row["trial_id"], "from": row["status"], "to": row["status"],
                                    "note": "unknown_timeout"})
                    continue
                (trial_dir / "cell.json").write_text(json.dumps({
                    "image": task["image"], "image_source": task["image_source"], "image_pin": task["image_pin"],
                    "image_record": executor.image_record(task), "workdir": task["workdir"], "opencode_exit": None,
                    "timed_out": False, "reconstructed_by": "reclassify", "reconstructed_at": now},
                    sort_keys=True) + "\n")
            result = executor.finish_trial(spec, run_dir)
            new.update({"status": result.status, "passed": result.passed if result.status == "completed" else None,
                        "checker_exit": result.checker_exit, "steps": result.steps,
                        "thinking_tokens": result.thinking_tokens, "thinking_flags": sorted(set(result.thinking_flags)),
                        "thinking_tokens_per_step": result.thinking_tokens_per_step,
                        "thinking_setting": result.thinking_setting, "trace": result.trace, "error": result.error})
            new["reclassified"] = {"from": row["status"], "at": now, "code_commit": commit}
            changes.append({"trial_id": row["trial_id"], "task": row["task"], "model": row["model"],
                            "from": row["status"], "to": result.status, "passed": new["passed"],
                            "retried_4xx": fours["retried"]})
        # covariate + image fields on every row
        cell = json.loads((trial_dir / "cell.json").read_text(encoding="utf-8")) if (trial_dir / "cell.json").exists() else {}
        if cell.get("image_record"):
            image = cell["image_record"]
        else:
            t = task or executor._task(spec)
            t = dict(t, image=cell.get("image", t["image"]), image_pin=cell.get("image_pin"))
            image = executor.image_record(t)
        new.update({"retried_4xx": fours["retried"], "image_ref": image["ref"], "image_id": image["id"],
                    "image_matches_pin": image["matches_pin"]})
        out.append(new)
    report = {"run": str(run_dir), "trials": len(rows), "changed": changes, "applied": apply}
    if apply:
        trials = run_dir / "trials.jsonl"
        shutil.copy2(trials, run_dir / f"trials.pre-reclassify-{now.replace(':', '')}.jsonl")
        tmp = trials.with_name("trials.jsonl.tmp")
        tmp.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in out), encoding="utf-8")
        tmp.replace(trials)
        runner.rebuild_tables()
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reclassify finished trials offline (no model calls)")
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--opencode", type=Path, required=True, help="the pinned OpenCode binary (pin check only)")
    parser.add_argument("--use-image-tag", action="store_true", help="as the run used it")
    parser.add_argument("--apply", action="store_true", help="rewrite trials.jsonl and rebuild the tables")
    args = parser.parse_args(argv)
    from obench.reflection.cell_executor import CellExecutor
    executor = CellExecutor(args.opencode, "offline", lambda: "", use_image_tag=args.use_image_tag)
    print(json.dumps(reclassify(args.run, executor, apply=args.apply), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
