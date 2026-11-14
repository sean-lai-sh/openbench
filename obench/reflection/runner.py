"""N-trial runner for the reflection loop (SEA-107). Schema: RUNNER_TABLES.md.

For a suite (``obench.hardsuite``) and the reflection models
(``vertex_models``), the runner executes N trials (default ``N_TRIALS`` =
30) per task per model through an ``Executor``, writes the per-trial and
per-(task, model) tables, issues each model's verdict at the single cutoff
(``obench.hardsuite.config.pass_cutoff``), and applies the harder-swap rule
for that model only. A swapped-in task is then run in the next round, so
each model keeps its planned suite size (up to ``max_rounds``).

Determinism: a trial's id is ``sha256(run_id, task, model, patch, index)``.
The same plan always gives the same ids, a rerun into the same directory
skips trials that already have rows (resume), and every row is attributable
to its index.

Spend: ``preflight`` estimates the plan's cost before anything runs. The run
stops before a trial that would push spend past ``spend_cap_usd``, and pauses
(writing ``status.json``) when spend crosses an alert threshold ($5K, $10K,
$15K by default), so a person can look before it continues.

Layout (all paths in rows are relative to the run directory, so tables can be
committed after scrubbing)::

    <run>/plan.json  trials.jsonl  summary.jsonl  verdicts.json  swaps/<model>.json  status.json
    <run>/trials/<model>/<task>/<trial_id>/   (executor output: trace.jsonl, wire.jsonl, ...)
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from obench.hardsuite import swap
from obench.hardsuite.config import pass_cutoff
from obench.hardsuite.suite import Suite, load_suite, resolve
from obench.reflection import vertex_models as vm

N_TRIALS = 30
ALERT_THRESHOLDS_USD = (5_000.0, 10_000.0, 15_000.0)
TRIAL_SCHEMA = "openbench.reflection.trial/v1"
SUMMARY_SCHEMA = "openbench.reflection.summary/v1"
STATUSES = ("completed", "error", "timeout")


class RunnerError(Exception):
    pass


@dataclass(frozen=True)
class TrialSpec:
    run_id: str
    trial_id: str
    task: str
    tasks_dir: str
    model: str
    trial_index: int
    patch_id: str | None
    patch: dict | None
    trial_dir: str            # relative to the run directory

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class TrialResult:
    status: str                       # completed | error | timeout
    passed: bool | None               # checker verdict; None when the trial did not complete
    checker_exit: int | None = None
    steps: int | None = None
    cost_usd: float | None = None
    thinking_tokens: int | None = None        # sum of usage.thinking_tokens over steps
    thinking_flags: list = field(default_factory=list)
    served_models: list = field(default_factory=list)
    trace: str | None = None                  # relative path
    wire: str | None = None                   # relative path
    error: str | None = None


class Executor(Protocol):
    def estimate_cost_usd(self, model: str) -> float:
        """Expected cost of one trial on ``model`` (for the preflight)."""

    def run_trial(self, spec: TrialSpec, run_dir: Path) -> TrialResult:
        ...


@dataclass(frozen=True)
class RunConfig:
    run_id: str
    suite: str
    models: tuple
    n_trials: int = N_TRIALS
    spend_cap_usd: float | None = None
    alert_thresholds_usd: tuple = ALERT_THRESHOLDS_USD
    max_rounds: int = 3
    patch_id: str | None = None
    patch: dict | None = None
    tasks: tuple | None = None           # restrict to these suite tasks (ideation, dry runs)

    @classmethod
    def load(cls, path: Path) -> "RunConfig":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls.from_dict(raw)

    @classmethod
    def from_dict(cls, raw: dict) -> "RunConfig":
        unknown = set(raw) - set(cls.__dataclass_fields__)
        if unknown:
            raise RunnerError(f"unknown run config keys: {sorted(unknown)}")
        cfg = cls(**{k: tuple(v) if k in ("models", "alert_thresholds_usd", "tasks") and v is not None else v
                     for k, v in raw.items()})
        cfg.validate()
        return cfg

    def validate(self) -> None:
        if not self.run_id or "/" in self.run_id:
            raise RunnerError("run_id must be a non-empty name without '/'")
        if not self.models:
            raise RunnerError("models must name at least one reflection model")
        for model in self.models:
            vm.resolve(model)  # raises UnknownModel: no Sonnet, no Qwen, no fallback
        if isinstance(self.n_trials, bool) or not isinstance(self.n_trials, int) or self.n_trials < 1:
            raise RunnerError(f"n_trials must be a positive int, got {self.n_trials!r}")
        if self.max_rounds < 1:
            raise RunnerError("max_rounds must be >= 1")
        if (self.patch is None) != (self.patch_id is None):
            raise RunnerError("patch and patch_id go together")


def trial_id(run_id: str, task: str, model: str, patch_id: str | None, index: int) -> str:
    key = json.dumps([run_id, task, model, patch_id, index])
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _append(path: Path, row: dict) -> None:
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, sort_keys=True) + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def _write_json(path: Path, payload) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def read_rows(path: Path) -> list[dict]:
    if not Path(path).exists():
        return []
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


class Runner:
    def __init__(self, config: RunConfig, run_dir: Path, executor: Executor, suites_dir: Path | None = None):
        config.validate()
        self.config, self.executor = config, executor
        self.run_dir = Path(run_dir)
        kwargs = {"suites_dir": suites_dir} if suites_dir else {}
        self.suite: Suite = load_suite(config.suite, **kwargs)
        if not self.suite.pool:
            raise RunnerError(f"suite {config.suite!r} names no harder pool")
        self.pool: Suite = load_suite(self.suite.pool, **kwargs)
        self.known = {t.id: t for t in (*self.suite.tasks, *self.pool.tasks)}
        if config.tasks:
            missing = sorted(set(config.tasks) - set(self.suite.ids()))
            if missing:
                raise RunnerError(f"tasks not in suite {config.suite!r}: {missing}")
        self.trials_path = self.run_dir / "trials.jsonl"
        self.summary_path = self.run_dir / "summary.jsonl"

    # ---------------------------------------------------------------- plan / preflight

    def initial_tasks(self) -> list[str]:
        return list(self.config.tasks) if self.config.tasks else self.suite.ids()

    def plan(self, tasks_by_model: dict[str, list[str]]) -> list[TrialSpec]:
        specs = []
        for model in self.config.models:
            for task in tasks_by_model[model]:
                tasks_dir, _ = resolve(self.known[task])
                for index in range(self.config.n_trials):
                    tid = trial_id(self.config.run_id, task, model, self.config.patch_id, index)
                    specs.append(TrialSpec(
                        run_id=self.config.run_id, trial_id=tid, task=task, tasks_dir=tasks_dir, model=model,
                        trial_index=index, patch_id=self.config.patch_id, patch=self.config.patch,
                        trial_dir=f"trials/{model}/{task}/{tid}"))
        return specs

    def preflight(self) -> dict:
        """Cost estimate for round 1 (and the worst case if every slot swaps
        every round), checked against the cap before anything runs."""
        tasks = self.initial_tasks()
        per_model = {m: len(tasks) * self.config.n_trials * self.executor.estimate_cost_usd(m)
                     for m in self.config.models}
        round_one = sum(per_model.values())
        estimate = {"round_one_usd": round(round_one, 2), "per_model_usd": {m: round(v, 2) for m, v in per_model.items()},
                    "worst_case_usd": round(round_one * self.config.max_rounds, 2),
                    "trials_round_one": len(tasks) * self.config.n_trials * len(self.config.models),
                    "spend_cap_usd": self.config.spend_cap_usd,
                    "within_cap": self.config.spend_cap_usd is None or round_one <= self.config.spend_cap_usd}
        return estimate

    # ---------------------------------------------------------------- run

    def spent(self) -> float:
        return round(sum(r.get("cost_usd") or 0.0 for r in read_rows(self.trials_path)), 6)

    def _status(self, state: str, **extra) -> dict:
        status = {"run_id": self.config.run_id, "state": state, "spent_usd": self.spent(), "at": _now(), **extra}
        _write_json(self.run_dir / "status.json", status)
        return status

    def run(self, *, acknowledge_alerts: tuple = ()) -> dict:
        """Run (or resume) the plan. Returns the final status. ``state`` is
        ``done``, ``capped`` (the next trial would pass the spend cap), or
        ``alert`` (spend crossed an alert threshold not in
        ``acknowledge_alerts``; rerun with it acknowledged to continue)."""
        self.run_dir.mkdir(parents=True, exist_ok=True)
        (self.run_dir / "swaps").mkdir(exist_ok=True)
        cutoff = pass_cutoff()
        _write_json(self.run_dir / "plan.json", {"config": asdict(self.config), "cutoff": cutoff,
                                                 "preflight": self.preflight(), "written_at": _now()})
        states = {m: self._swap_state(m) for m in self.config.models}
        done = {r["trial_id"] for r in read_rows(self.trials_path)}
        for round_no in range(1, self.config.max_rounds + 1):
            tasks_by_model = {m: self._round_tasks(states[m]) for m in self.config.models}
            for spec in self.plan(tasks_by_model):
                if spec.trial_id in done:
                    continue
                spent = self.spent()
                crossed = [t for t in self.config.alert_thresholds_usd if spent >= t and t not in acknowledge_alerts]
                if crossed:
                    return self._status("alert", threshold_usd=crossed[0], round=round_no)
                cap = self.config.spend_cap_usd
                if cap is not None and spent + self.executor.estimate_cost_usd(spec.model) > cap:
                    return self._status("capped", spend_cap_usd=cap, round=round_no)
                self._run_one(spec)
                done.add(spec.trial_id)
            summaries = self.write_summary(cutoff)
            swapped = False
            for model in self.config.models:
                states[model], swaps = self._apply_swaps(states[model], summaries, model, cutoff)
                swapped |= bool(swaps)
            self.write_verdicts(summaries, cutoff)
            if not swapped or self.config.patch_id is not None:
                break
        return self._status("done")

    def _round_tasks(self, state: dict) -> list[str]:
        if self.config.tasks:
            return [t for t in swap.current_tasks(state) if t in self.config.tasks or t not in self.suite.ids()]
        return swap.current_tasks(state)

    def _run_one(self, spec: TrialSpec) -> None:
        trial_dir = self.run_dir / spec.trial_dir
        trial_dir.mkdir(parents=True, exist_ok=True)
        started = _now()
        try:
            result = self.executor.run_trial(spec, self.run_dir)
        except Exception as exc:  # an executor crash is a trial error, never a silent skip
            result = TrialResult(status="error", passed=None, error=f"{type(exc).__name__}: {exc}")
        if result.status not in STATUSES:
            result = TrialResult(status="error", passed=None, error=f"executor returned status {result.status!r}")
        model = vm.resolve(spec.model)
        wrong = [s for s in result.served_models if s and not vm.served_matches(model, s)]
        task = self.known[spec.task]
        row = {"schema": TRIAL_SCHEMA, "run_id": spec.run_id, "trial_id": spec.trial_id, "task": spec.task,
               "bench": task.bench["bench"], "bench_commit": task.bench["commit"], "model": spec.model,
               "vertex_id": model.vertex_id, "trial_index": spec.trial_index, "patch_id": spec.patch_id,
               "status": result.status, "passed": result.passed if result.status == "completed" else None,
               "checker_exit": result.checker_exit, "steps": result.steps, "cost_usd": result.cost_usd,
               "price_verified": model.price_verified, "thinking_tokens": result.thinking_tokens,
               "thinking_flags": sorted(set(result.thinking_flags)), "served_models": sorted(set(result.served_models)),
               "wrong_model_served": wrong, "trace": result.trace, "wire": result.wire, "trial_dir": spec.trial_dir,
               "started_at": started, "finished_at": _now(), "error": result.error}
        _append(self.trials_path, row)

    # ---------------------------------------------------------------- tables

    def write_summary(self, cutoff: float) -> list[dict]:
        rows = read_rows(self.trials_path)
        groups: dict[tuple, list[dict]] = {}
        for r in rows:
            groups.setdefault((r["task"], r["model"], r["patch_id"]), []).append(r)
        summaries = []
        for (task, model, patch_id), trials in sorted(groups.items(), key=lambda kv: (kv[0][1], kv[0][0], str(kv[0][2]))):
            completed = [t for t in trials if t["status"] == "completed"]
            passes = sum(1 for t in completed if t["passed"])
            n = self.config.n_trials
            verdict = ("incomplete" if len(completed) < n
                       else "pass" if swap.passed(passes, len(completed), cutoff) else "fail")
            costs = [t["cost_usd"] for t in trials]
            thinking = [t["thinking_tokens"] for t in trials if isinstance(t.get("thinking_tokens"), int)]
            summaries.append({
                "schema": SUMMARY_SCHEMA, "run_id": self.config.run_id, "task": task, "model": model,
                "patch_id": patch_id, "planned": n, "trials": len(trials), "completed": len(completed),
                "passes": passes, "fails": len(completed) - passes,
                "errors": sum(1 for t in trials if t["status"] != "completed"),
                "pass_rate": round(passes / len(completed), 4) if completed else None,
                "cutoff": cutoff, "verdict": verdict,
                "spend_usd": round(sum(c for c in costs if c is not None), 6),
                "spend_complete": all(c is not None for c in costs),
                "thinking_tokens_total": sum(thinking),
                "thinking_tokens_reported_trials": len(thinking),
                "thinking_flags": sorted({f for t in trials for f in t.get("thinking_flags") or []}),
                "wrong_model_trials": sum(1 for t in trials if t.get("wrong_model_served")),
                "traces": f"trials/{model}/{task}/*/trace.jsonl",
            })
        tmp = self.summary_path.with_name("summary.jsonl.tmp")
        tmp.write_text("".join(json.dumps(s, sort_keys=True) + "\n" for s in summaries), encoding="utf-8")
        os.replace(tmp, self.summary_path)
        return summaries

    def write_verdicts(self, summaries: list[dict], cutoff: float) -> dict:
        verdicts = {"cutoff": cutoff, "models": {}}
        for model in self.config.models:
            mine = [s for s in summaries if s["model"] == model and s["patch_id"] == self.config.patch_id]
            verdicts["models"][model] = {
                "pass": sorted(s["task"] for s in mine if s["verdict"] == "pass"),
                "fail": sorted(s["task"] for s in mine if s["verdict"] == "fail"),
                "incomplete": sorted(s["task"] for s in mine if s["verdict"] == "incomplete"),
                "current_suite": swap.current_tasks(self._swap_state(model)),
            }
        _write_json(self.run_dir / "verdicts.json", verdicts)
        return verdicts

    # ---------------------------------------------------------------- swaps

    def _swap_path(self, model: str) -> Path:
        return self.run_dir / "swaps" / f"{model}.json"

    def _swap_state(self, model: str) -> dict:
        path = self._swap_path(model)
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        return swap.initial_state(model, self.suite)

    def _apply_swaps(self, state: dict, summaries: list[dict], model: str, cutoff: float) -> tuple[dict, list]:
        """Harder-swap for this model only, on its completed baseline rows.
        Ideation runs (patch_id set) never swap the suite."""
        if self.config.patch_id is not None:
            return state, []
        current = set(swap.current_tasks(state))
        results = {s["task"]: (s["passes"], s["completed"]) for s in summaries
                   if s["model"] == model and s["patch_id"] is None and s["verdict"] != "incomplete"
                   and s["task"] in current}
        new, swaps = swap.apply_results(state, results, self.suite, self.pool, cutoff)
        self._swap_path(model).parent.mkdir(parents=True, exist_ok=True)
        _write_json(self._swap_path(model), new)
        return new, swaps


class FixtureExecutor:
    """Offline executor for dry runs and tests: outcomes come from a table
    ``{(task, model): pass_count}`` (the first ``pass_count`` indices pass).
    Writes a one-line trace so pointers resolve. Costs ``cost_per_trial``."""

    def __init__(self, passes: dict, cost_per_trial: float = 0.01, thinking_tokens: int = 10,
                 errors: dict | None = None):
        self.passes, self.cost, self.thinking = passes, cost_per_trial, thinking_tokens
        self.errors = errors or {}
        self.calls: list[TrialSpec] = []

    def estimate_cost_usd(self, model: str) -> float:
        return self.cost

    def run_trial(self, spec: TrialSpec, run_dir: Path) -> TrialResult:
        self.calls.append(spec)
        if spec.trial_index in self.errors.get((spec.task, spec.model), ()):
            return TrialResult(status="error", passed=None, cost_usd=self.cost, error="fixture error")
        trace = f"{spec.trial_dir}/trace.jsonl"
        (Path(run_dir) / trace).write_text(json.dumps({"step": 1, "fixture": True}) + "\n", encoding="utf-8")
        passed = spec.trial_index < self.passes.get((spec.task, spec.model), 0)
        return TrialResult(status="completed", passed=passed, checker_exit=0 if passed else 1, steps=1,
                           cost_usd=self.cost, thinking_tokens=self.thinking,
                           served_models=[vm.resolve(spec.model).vertex_id], trace=trace)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Reflection-loop N-trial runner (SEA-107)")
    parser.add_argument("--config", type=Path, required=True, help="RunConfig JSON")
    parser.add_argument("--out", type=Path, required=True, help="run directory (outside results/ and data/)")
    parser.add_argument("--preflight", action="store_true", help="print the cost estimate and exit")
    parser.add_argument("--fixture", type=Path, help="dry run: JSON {\"task|model\": passes} for FixtureExecutor")
    parser.add_argument("--acknowledge-alert", type=float, action="append", default=[])
    args = parser.parse_args(argv)
    if any(part in ("results", "data") for part in args.out.expanduser().resolve().parts):
        raise SystemExit("--out must be outside results/ and data/")
    config = RunConfig.load(args.config)
    if args.fixture is None:
        raise SystemExit("only --fixture dry runs are wired here; the containerized cell executor is the next step "
                         "(see RUNNER_TABLES.md, 'Executors')")
    raw = json.loads(args.fixture.read_text(encoding="utf-8"))
    executor = FixtureExecutor({tuple(k.split("|", 1)): v for k, v in raw.items()})
    runner = Runner(config, args.out, executor)
    if args.preflight:
        print(json.dumps(runner.preflight(), indent=2))
        return 0
    status = runner.run(acknowledge_alerts=tuple(args.acknowledge_alert))
    print(json.dumps(status))
    return 0 if status["state"] == "done" else 3


if __name__ == "__main__":
    raise SystemExit(main())
