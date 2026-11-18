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
# route_truncated: the model route ended the turn with finish "stop", no tool
# call and no text (wire_proxy.route_truncated). An infrastructure failure, like
# error and timeout: it never counts as a task fail.
# upstream_4xx: a 4xx ended or broke the trial (no successful main call after it; wire_proxy.classify_4xx).
# Also infrastructure. A 4xx that OpenCode retried and recovered from is not: it is the retried_4xx covariate.
# Set-aside statuses (Researcher rulings 2026-11-17), each trial classified on its own:
#   provider_blocked: the trial's last answered call had Gemini promptFeedback.blockReason.
#   model_refused: otherwise, any call refused or stopped for safety (Anthropic stop_reason "refusal", Gemini
#     finishReason SAFETY), recorded with the step it happened on.
# Both are neither pass nor fail: left out of the pass-rate denominator and the swap rule, reported per task and
# model (set_aside.json, provider_blocked.json) with a sensitivity check that counts them all as fails, and cells
# with any of them never go to credit assignment or ideation.
# agent_exit_pending_tool: OpenCode exited 0 with a tool call still pending (e.g. `opencode run` auto-rejected a
# permission request) - infrastructure, never a task fail. checker_error: the checker could not run (missing
# interpreter/tool in the task image, docker failure) - infrastructure.
STATUSES = ("completed", "error", "timeout", "route_truncated", "upstream_4xx", "provider_blocked",
            "model_refused", "agent_exit_pending_tool", "checker_error")
SET_ASIDE = ("provider_blocked", "model_refused")  # neither pass/fail nor infra; not in errors
# Run labels that fix which task population a run may use, so runs with different populations are never pooled.
# "repo pilot suite": the repo's pilot suite and pool only; tasks imported by obench.taskimport (their task.toml
# records docker_image_id_at_import) are refused.
SUITE_LABELS = {"repo pilot suite": {"suites": ("pilot",), "imported_tasks": False}}


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
    status: str                       # completed | error | timeout | route_truncated
    passed: bool | None               # checker verdict; None when the trial did not complete
    checker_exit: int | None = None
    steps: int | None = None
    cost_usd: float | None = None
    thinking_tokens: int | None = None        # sum of usage.thinking_tokens over steps
    thinking_flags: list = field(default_factory=list)
    served_models: list = field(default_factory=list)
    thinking_setting: dict | None = None      # the exact thinking setting sent (vertex_models.thinking_sent)
    thinking_tokens_per_step: list | None = None  # usage thinking tokens per trace step (None where not reported)
    thinking_tokens_status: dict | None = None    # {"reported": n, "unreported": m, ...} over steps
    route_counts: dict | None = None
    retried_4xx: dict | None = None           # {"429": n, ...}: 4xx calls OpenCode recovered from (covariate)
    image: dict | None = None                 # {ref, id, pinned, matches_pin}: what actually ran
    provider_blocked: dict | None = None      # raw {blockReason, blockReasonMessage, ...} when status is provider_blocked
    model_refused: dict | None = None         # {stop_reason, stop_details, call_index, step, refusals, ...}
    agent_exit: dict | None = None            # agent_exit_pending_tool: {last_finish, pending_tools, permission_rejected, ...}
    trace_warning: str | None = None          # the trace could not be built (e.g. step_call_mismatch); verdict kept
    cost_unpriced_calls: int = 0              # calls with no cost (e.g. killed mid-response); cost_usd sums the rest
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
    fixed_tasks: bool = False            # run exactly ``tasks`` (suite or pool), never swap: ideation arms
    suite_label: str | None = None       # SUITE_LABELS key; on every row; a run directory never mixes labels
    workers: int = 1                     # trials in parallel; fixed for the whole run (resume refuses another value)

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

    @property
    def fixed(self) -> bool:
        return self.patch_id is not None or self.fixed_tasks

    def validate(self) -> None:
        if self.fixed_tasks and not self.tasks:
            raise RunnerError("fixed_tasks needs tasks")
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
        if isinstance(self.workers, bool) or not isinstance(self.workers, int) or self.workers < 1:
            raise RunnerError(f"workers must be a positive int, got {self.workers!r}")
        if self.suite_label is not None:
            rule = SUITE_LABELS.get(self.suite_label)
            if rule is None:
                raise RunnerError(f"unknown suite_label {self.suite_label!r}; known: {sorted(SUITE_LABELS)}")
            if self.suite not in rule["suites"]:
                raise RunnerError(f"suite_label {self.suite_label!r} allows suites {rule['suites']}, not {self.suite!r}")


def code_commit(root: Path | None = None) -> dict:
    """The checkout the runner runs from: commit, branch, and whether it has uncommitted changes."""
    import subprocess
    root = root or Path(__file__).resolve().parents[2]
    git = lambda *a: subprocess.run(["git", "-C", str(root), *a], capture_output=True, text=True, timeout=30)
    head, branch, dirty = git("rev-parse", "HEAD"), git("rev-parse", "--abbrev-ref", "HEAD"), git("status", "--porcelain")
    return {"commit": head.stdout.strip() or None, "branch": branch.stdout.strip() or None,
            "dirty": bool(dirty.stdout.strip()) if dirty.returncode == 0 else None}


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


def _route_repair_summary(trials: list[dict]) -> dict:
    """How much of the cell rests on the gpt-oss route repair (zero for the other models: they are never rewritten).
    The share is over tool-call turns; trials with no wire counts (crashes) are left out and counted."""
    counted = [t["route_counts"] for t in trials if isinstance(t.get("route_counts"), dict)]
    total = lambda k: sum(int(c.get(k) or 0) for c in counted)
    repaired_trials = [t for t in trials if (t.get("route_counts") or {}).get("route_repairs")]
    return {"model_calls": total("model_calls"), "tool_call_turns": total("tool_call_turns"),
            "route_repairs": total("route_repairs"),
            "unknown_recipient_calls": total("unknown_recipient_calls"),
            "route_repair_share": round(total("route_repairs") / total("tool_call_turns"), 4) if total("tool_call_turns") else None,
            "trials_with_route_repair": len(repaired_trials),
            "passes_with_route_repair": sum(1 for t in repaired_trials if t.get("status") == "completed" and t.get("passed")),
            "trials_without_route_counts": len(trials) - len(counted)}


def _is_imported(task) -> bool:
    toml = Path(resolve(task)[0]) / task.id / "task.toml"
    if not toml.is_file():
        return False
    import tomllib
    return "docker_image_id_at_import" in tomllib.loads(toml.read_text(encoding="utf-8"))


def _sum_counts(dicts) -> dict:
    out: dict = {}
    for d in dicts:
        for k, v in (d or {}).items():
            out[k] = out.get(k, 0) + int(v)
    return dict(sorted(out.items()))


def _all_or_none(values) -> bool | None:
    """False if any trial ran an image that doesn't match its pin; True if all matched; None if no pin known."""
    values = list(values)
    if any(v is False for v in values):
        return False
    return True if values and all(v is True for v in values) else None


def _load() -> list | None:
    try:
        return [round(x, 2) for x in os.getloadavg()]
    except OSError:
        return None


def read_rows(path: Path) -> list[dict]:
    if not Path(path).exists():
        return []
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


class Runner:
    def __init__(self, config: RunConfig, run_dir: Path, executor: Executor, suites_dir: Path | None = None,
                 workers: int | None = None):
        if workers is not None:  # CLI --workers; part of the config, so a resume with another value is refused
            from dataclasses import replace as _replace
            config = _replace(config, workers=workers)
        config.validate()
        self.config, self.executor, self.workers = config, executor, config.workers
        if hasattr(executor, "set_run_context"):  # the executor records it on every cell too
            executor.set_run_context({"run_id": config.run_id, "workers": config.workers})
        import threading
        self._rows_lock = threading.Lock()
        self.run_dir = Path(run_dir)
        kwargs = {"suites_dir": suites_dir} if suites_dir else {}
        self.suite: Suite = load_suite(config.suite, **kwargs)
        if not self.suite.pool:
            raise RunnerError(f"suite {config.suite!r} names no harder pool")
        self.pool: Suite = load_suite(self.suite.pool, **kwargs)
        self.known = {t.id: t for t in (*self.suite.tasks, *self.pool.tasks)}
        if config.suite_label and not SUITE_LABELS[config.suite_label]["imported_tasks"]:
            imported = sorted(t.id for t in self.known.values() if _is_imported(t))
            if imported:
                raise RunnerError(f"suite_label {config.suite_label!r} excludes imported tasks: {imported}")
        self.code = code_commit()
        if config.tasks:
            allowed = set(self.known) if config.fixed else set(self.suite.ids())
            missing = sorted(set(config.tasks) - allowed)
            if missing:
                raise RunnerError(f"tasks not in suite {config.suite!r}" + (" or its pool" if config.fixed else "")
                                  + f": {missing}")
        self.trials_path = self.run_dir / "trials.jsonl"
        self.summary_path = self.run_dir / "summary.jsonl"

    # ---------------------------------------------------------------- plan / preflight

    def initial_tasks(self) -> list[str]:
        return list(self.config.tasks) if self.config.tasks else self.suite.ids()

    def plan(self, tasks_by_model: dict[str, list[str]]) -> list[TrialSpec]:
        """Trials interleaved across models (trial index, then slot, then model), so with ``workers > 1`` both
        models run side by side under the same load rather than one model after the other."""
        specs = []
        slots = max((len(t) for t in tasks_by_model.values()), default=0)
        for index in range(self.config.n_trials):
            for slot in range(slots):
                for model in self.config.models:
                    if slot >= len(tasks_by_model[model]):
                        continue
                    task = tasks_by_model[model][slot]
                    tasks_dir, _ = resolve(self.known[task])
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
        with self._rows_lock:
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
        previous = self.run_dir / "plan.json"
        if previous.exists():  # resuming: never pool a different population into this directory
            old = json.loads(previous.read_text(encoding="utf-8")).get("config") or {}
            for key in ("suite", "suite_label", "models", "patch_id", "n_trials", "workers"):
                was, now = old.get(key), asdict(self.config).get(key)
                if (list(was) if isinstance(was, (list, tuple)) else was) != (list(now) if isinstance(now, (list, tuple)) else now):
                    raise RunnerError(f"{self.run_dir} was started with {key}={was!r}, not {now!r}: use a new run directory")
        _write_json(self.run_dir / "plan.json", {"config": asdict(self.config), "cutoff": cutoff, "code": self.code,
                                                 "workers": self.workers, "host_cpus": os.cpu_count(),
                                                 "preflight": self.preflight(), "written_at": _now()})
        states = {m: self._swap_state(m) for m in self.config.models}
        done = {r["trial_id"] for r in read_rows(self.trials_path)}
        for round_no in range(1, self.config.max_rounds + 1):
            tasks_by_model = {m: self._round_tasks(states[m]) for m in self.config.models}
            stop = self._run_round([s for s in self.plan(tasks_by_model) if s.trial_id not in done], done,
                                   acknowledge_alerts)
            if stop is not None:
                return self._status(stop.pop("state"), round=round_no, **stop)
            summaries = self.write_summary(cutoff)
            swapped = False
            for model in self.config.models:
                states[model], swaps = self._apply_swaps(states[model], summaries, model, cutoff)
                swapped |= bool(swaps)
            self.write_verdicts(summaries, cutoff)
            if not swapped or self.config.fixed:
                break
        return self._status("done")

    def _run_round(self, specs: list[TrialSpec], done: set, acknowledge_alerts: tuple) -> dict | None:
        """Run a round's trials on ``self.workers`` threads (1 = one at a time, as before). Swaps happen only after
        the whole round, per model, so they are the same at any worker count. Before each trial starts, spend so
        far plus the estimate of every trial still running is checked against the alerts and the cap; on a stop,
        no new trial starts and the running ones finish and are recorded. Returns the stop status, or None."""
        from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
        cap, pending, running, stop = self.config.spend_cap_usd, list(specs), {}, None
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            while pending or running:
                while stop is None and pending and len(running) < self.workers:
                    spec = pending[0]
                    spent = self.spent()
                    crossed = [t for t in self.config.alert_thresholds_usd if spent >= t and t not in acknowledge_alerts]
                    if crossed:
                        stop = {"state": "alert", "threshold_usd": crossed[0]}
                        break
                    reserved = sum(self.executor.estimate_cost_usd(s.model) for s in running.values())
                    if cap is not None and spent + reserved + self.executor.estimate_cost_usd(spec.model) > cap:
                        stop = {"state": "capped", "spend_cap_usd": cap}
                        break
                    running[pool.submit(self._run_one, spec)] = pending.pop(0)
                if not running:
                    break
                finished, _ = wait(running, return_when=FIRST_COMPLETED)
                for future in finished:
                    spec = running.pop(future)
                    future.result()  # _run_one records executor crashes as trial errors; anything else is a bug
                    done.add(spec.trial_id)
        return stop

    def _round_tasks(self, state: dict) -> list[str]:
        if self.config.fixed:  # ideation arms: exactly the parent's task, even a swapped-in pool task
            return list(self.config.tasks or swap.current_tasks(state))
        if self.config.tasks:
            return [t for t in swap.current_tasks(state) if t in self.config.tasks or t not in self.suite.ids()]
        return swap.current_tasks(state)

    def _run_one(self, spec: TrialSpec) -> None:
        trial_dir = self.run_dir / spec.trial_dir
        trial_dir.mkdir(parents=True, exist_ok=True)
        started = _now()
        import time as _time
        t0, load_start = _time.monotonic(), _load()
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
               "wrong_model_served": wrong, "route_counts": result.route_counts,
               "suite_label": self.config.suite_label, "code_commit": self.code["commit"],
               "code_branch": self.code["branch"], "code_dirty": self.code["dirty"],
               "retried_4xx": result.retried_4xx or {}, "provider_blocked": result.provider_blocked,
               "model_refused": result.model_refused, "agent_exit": result.agent_exit,
               "trace_warning": result.trace_warning, "cost_unpriced_calls": result.cost_unpriced_calls,
               "workers": self.workers, "wall_seconds": round(_time.monotonic() - t0, 1),
               "host_load": {"start": load_start, "end": _load(), "cpus": os.cpu_count()},
               "image_ref": (result.image or {}).get("ref"), "image_id": (result.image or {}).get("id"),
               "image_matches_pin": (result.image or {}).get("matches_pin"),
               "thinking_setting": result.thinking_setting, "thinking_tokens_per_step": result.thinking_tokens_per_step,
               "thinking_tokens_status": result.thinking_tokens_status, "trace": result.trace, "wire": result.wire, "trial_dir": spec.trial_dir,
               "started_at": started, "finished_at": _now(), "error": result.error}
        with self._rows_lock:
            _append(self.trials_path, row)

    # ---------------------------------------------------------------- tables

    def write_summary(self, cutoff: float) -> list[dict]:
        rows = read_rows(self.trials_path)
        groups: dict[tuple, list[dict]] = {}
        for r in rows:
            groups.setdefault((r["task"], r["model"], r["patch_id"]), []).append(r)
        summaries = []
        for (task, model, patch_id), trials in sorted(groups.items(), key=lambda kv: (kv[0][1], kv[0][0], str(kv[0][2]))):
            blocked = [t for t in trials if t["status"] == "provider_blocked"]
            refused = [t for t in trials if t["status"] == "model_refused"]
            completed = [t for t in trials if t["status"] == "completed"]
            passes = sum(1 for t in completed if t["passed"])
            n = self.config.n_trials
            # Set-aside trials (blocked, refused) are neither pass nor fail: the verdict is over the completed trials
            # only, once every trial is in; a cell with nothing but set-aside trials is "excluded". The sensitivity
            # verdict counts every set-aside trial as a fail.
            aside = len(blocked) + len(refused)
            settled = len(completed) + aside >= n
            verdict = ("incomplete" if not settled
                       else "excluded" if not completed
                       else "pass" if swap.passed(passes, len(completed), cutoff) else "fail")
            verdict_all_fail = ("incomplete" if not settled
                                else "pass" if swap.passed(passes, len(completed) + aside, cutoff) else "fail")
            costs = [t["cost_usd"] for t in trials]
            thinking = [t["thinking_tokens"] for t in trials if isinstance(t.get("thinking_tokens"), int)]
            summaries.append({
                "schema": SUMMARY_SCHEMA, "run_id": self.config.run_id, "task": task, "model": model,
                "patch_id": patch_id, "planned": n, "trials": len(trials), "completed": len(completed),
                "passes": passes, "fails": len(completed) - passes,
                "errors": sum(1 for t in trials if t["status"] not in ("completed", *SET_ASIDE)),
                "route_truncated": sum(1 for t in trials if t["status"] == "route_truncated"),
                "upstream_4xx": sum(1 for t in trials if t["status"] == "upstream_4xx"),
                "provider_blocked": len(blocked),
                "model_refused": len(refused),
                "model_refused_checker_passes": sum(1 for t in refused if t.get("checker_exit") == 0),
                "set_aside": aside,
                "pass_rate_all_fail": round(passes / (len(completed) + aside), 4) if completed or aside else None,
                "verdict_all_fail": verdict_all_fail,
                "agent_exit_pending_tool": sum(1 for t in trials if t["status"] == "agent_exit_pending_tool"),
                "checker_error": sum(1 for t in trials if t["status"] == "checker_error"),
                "workers": sorted({t.get("workers") for t in trials if t.get("workers") is not None}),
                "retried_4xx": _sum_counts(t.get("retried_4xx") for t in trials),
                "image_ids": sorted({str(t.get("image_id")) for t in trials}),
                "image_matches_pin": _all_or_none(t.get("image_matches_pin") for t in trials),
                "suite_label": self.config.suite_label,
                "code_commits": sorted({str(t.get("code_commit")) for t in trials}),
                "pass_rate": round(passes / len(completed), 4) if completed else None,
                "cutoff": cutoff, "verdict": verdict,
                "spend_usd": round(sum(c for c in costs if c is not None), 6),
                "spend_complete": all(c is not None for c in costs) and not any(t.get("cost_unpriced_calls") for t in trials),
                "trace_warnings": sum(1 for t in trials if t.get("trace_warning")),
                "thinking_tokens_total": sum(thinking),
                "thinking_tokens_status": _sum_counts(t.get("thinking_tokens_status") for t in trials),
                "thinking_tokens_reported_trials": len(thinking),
                "thinking_flags": sorted({f for t in trials for f in t.get("thinking_flags") or []}),
                "wrong_model_trials": sum(1 for t in trials if t.get("wrong_model_served")),
                **_route_repair_summary(trials),
                "traces": f"trials/{model}/{task}/*/trace.jsonl",
            })
        tmp = self.summary_path.with_name("summary.jsonl.tmp")
        tmp.write_text("".join(json.dumps(s, sort_keys=True) + "\n" for s in summaries), encoding="utf-8")
        os.replace(tmp, self.summary_path)
        return summaries

    def rebuild_tables(self) -> dict:
        """Recompute summary.jsonl and verdicts.json from trials.jsonl (after an offline reclassification)."""
        cutoff = pass_cutoff()
        return self.write_verdicts(self.write_summary(cutoff), cutoff)

    def write_verdicts(self, summaries: list[dict], cutoff: float) -> dict:
        verdicts = {"cutoff": cutoff, "suite_label": self.config.suite_label, "code": self.code, "models": {}}
        for model in self.config.models:
            mine = [s for s in summaries if s["model"] == model and s["patch_id"] == self.config.patch_id]
            verdicts["models"][model] = {
                "pass": sorted(s["task"] for s in mine if s["verdict"] == "pass"),
                "fail": sorted(s["task"] for s in mine if s["verdict"] == "fail"),
                "incomplete": sorted(s["task"] for s in mine if s["verdict"] == "incomplete"),
                "excluded": sorted(s["task"] for s in mine if s["verdict"] == "excluded"),
                "model_refused": sorted(s["task"] for s in mine if s.get("model_refused")),
                # sensitivity: every set-aside trial counted as a fail
                "pass_all_fail": sorted(s["task"] for s in mine if s.get("verdict_all_fail") == "pass"),
                "provider_blocked": sorted(s["task"] for s in mine if s.get("provider_blocked")),
                "current_suite": swap.current_tasks(self._swap_state(model)),
                # tasks that ran an image other than the pinned one (--use-image-tag): label, never mix silently
                "image_matches_pin_false": sorted(s["task"] for s in mine if s.get("image_matches_pin") is False),
            }
        _write_json(self.run_dir / "verdicts.json", verdicts)
        self.write_provider_blocked()
        self.write_set_aside(summaries)
        return verdicts

    def write_set_aside(self, summaries: list[dict]) -> dict:
        """Per model and task: blocked and refused counts, the refusals with the step each happened on, and the
        sensitivity check (pass rate and verdict with every set-aside trial counted as a fail)."""
        rows = read_rows(self.trials_path)
        table: dict = {}
        for s in summaries:
            if not (s.get("provider_blocked") or s.get("model_refused")):
                continue
            refusals = [{"trial_id": r["trial_id"], **{k: (r.get("model_refused") or {}).get(k)
                                                       for k in ("stop_reason", "step", "call_index", "stop_details")}}
                        for r in rows if r["status"] == "model_refused" and r["task"] == s["task"]
                        and r["model"] == s["model"] and r["patch_id"] == s["patch_id"]]
            table.setdefault(s["model"], {})[s["task"] if s["patch_id"] is None else f"{s['task']}@{s['patch_id']}"] = {
                "trials": s["trials"], "completed": s["completed"], "passes": s["passes"],
                "provider_blocked": s["provider_blocked"], "model_refused": s["model_refused"],
                "pass_rate": s["pass_rate"], "verdict": s["verdict"],
                "pass_rate_all_fail": s["pass_rate_all_fail"], "verdict_all_fail": s["verdict_all_fail"],
                "refusals": refusals}
        doc = {"run_id": self.config.run_id, "suite_label": self.config.suite_label,
               "rule": "provider_blocked (last answered call had promptFeedback.blockReason) and model_refused (any "
                       "refusal / SAFETY finish): neither pass nor fail; left out of the denominator and the swap "
                       "rule; cells never sent to credit assignment or ideation. *_all_fail: sensitivity check "
                       "counting them all as fails.", "models": table}
        _write_json(self.run_dir / "set_aside.json", doc)
        return doc

    def write_provider_blocked(self) -> dict:
        """The per-task table of provider-blocked trials, per model: how many, out of how many, and the raw
        blockReason / blockReasonMessage values (``provider_blocked.json``)."""
        table: dict = {}
        rows = read_rows(self.trials_path)
        for r in rows:
            if r["status"] != "provider_blocked":
                continue
            cell = table.setdefault(r["model"], {}).setdefault(r["task"], {
                "trials_blocked": 0, "trials": sum(1 for x in rows if x["model"] == r["model"] and x["task"] == r["task"]
                                                   and x["patch_id"] == r["patch_id"]),
                "block_reasons": {}, "block_reason_messages": [], "inferred": 0})
            info = r.get("provider_blocked") or {}
            cell["trials_blocked"] += 1
            reason = str(info.get("blockReason"))
            cell["block_reasons"][reason] = cell["block_reasons"].get(reason, 0) + 1
            if info.get("blockReasonMessage") and info["blockReasonMessage"] not in cell["block_reason_messages"]:
                cell["block_reason_messages"].append(info["blockReasonMessage"])
            cell["inferred"] += bool(info.get("inferred"))
        doc = {"run_id": self.config.run_id, "suite_label": self.config.suite_label,
               "rule": "neither pass nor fail; excluded from the model's pass rate; no swap; never sent to credit "
                       "assignment or ideation", "models": table}
        _write_json(self.run_dir / "provider_blocked.json", doc)
        return doc

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
        Ideation arms (patched or fixed baselines) never swap the suite."""
        if self.config.fixed:
            return state, []
        current = set(swap.current_tasks(state))
        results = {s["task"]: (s["passes"], s["completed"]) for s in summaries
                   if s["model"] == model and s["patch_id"] is None and s["verdict"] in ("pass", "fail")
                   and s["task"] in current}
        new, swaps = swap.apply_results(state, results, self.suite, self.pool, cutoff)
        self._swap_path(model).parent.mkdir(parents=True, exist_ok=True)
        _write_json(self._swap_path(model), new)
        return new, swaps


def ideation_estimate(executor: Executor, failures: dict, n_alternatives: int = 5, n_trials: int = N_TRIALS,
                      candidate_fraction: float = 1.0) -> dict:
    """Spend estimate for ideation (SEA-110): selection runs ``n_alternatives
    x n_trials`` per failure, then every candidate gets a confirmation (a
    fresh ``n_trials`` alternative run **plus** a fresh ``n_trials`` baseline
    run). ``failures`` is ``{model: failed trials to ideate on}``.
    ``candidate_fraction`` = 1.0 is the worst case (every alternative
    becomes a candidate)."""
    per_model = {}
    for model, count in failures.items():
        unit = executor.estimate_cost_usd(model)
        selection = count * n_alternatives * n_trials * unit
        confirmation = count * n_alternatives * candidate_fraction * 2 * n_trials * unit
        per_model[model] = {"selection_usd": round(selection, 2), "confirmation_usd": round(confirmation, 2),
                            "total_usd": round(selection + confirmation, 2)}
    return {"n_alternatives": n_alternatives, "n_trials": n_trials, "candidate_fraction": candidate_fraction,
            "per_model": per_model,
            "selection_usd": round(sum(v["selection_usd"] for v in per_model.values()), 2),
            "confirmation_usd": round(sum(v["confirmation_usd"] for v in per_model.values()), 2),
            "total_usd": round(sum(v["total_usd"] for v in per_model.values()), 2)}


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
    parser.add_argument("--cell", action="store_true", help="real trials: one task-image container per trial (paid)")
    parser.add_argument("--opencode", type=Path, help="--cell: the pinned OpenCode binary (bin/<sha>/opencode)")
    parser.add_argument("--estimates", type=json.loads, default=None,
                        help='--cell: per-trial USD estimates for the preflight, e.g. {"claude-opus-5-5": 2.0}')
    parser.add_argument("--default-image", default="h1-env:1027-strace",
                        help="--cell: agent image for tasks that name none (openbench-tb-hard)")
    parser.add_argument("--use-image-tag", action="store_true",
                        help="--cell: when a task.toml digest ref isn't on this host, run its docker_image_tag (recorded)")
    parser.add_argument("--workers", type=int, default=1,
                        help="trials run in parallel (one container each); swaps stay per model, after each round")
    parser.add_argument("--acknowledge-alert", type=float, action="append", default=[])
    args = parser.parse_args(argv)
    if any(part in ("results", "data") for part in args.out.expanduser().resolve().parts):
        raise SystemExit("--out must be outside results/ and data/")
    config = RunConfig.load(args.config)
    if args.cell == (args.fixture is not None):
        raise SystemExit("choose exactly one executor: --cell (real trials) or --fixture (dry run)")
    if args.fixture is not None:
        raw = json.loads(args.fixture.read_text(encoding="utf-8"))
        executor = FixtureExecutor({tuple(k.split("|", 1)): v for k, v in raw.items()})
    else:
        import os as _os
        from obench.reflection.cell_executor import DEFAULT_ESTIMATES_USD, CellExecutor
        from thesis.ab.vertex_anthropic_proxy import AdcToken
        project = _os.environ.get("GOOGLE_CLOUD_PROJECT", "").strip()
        if not project or not args.opencode:
            raise SystemExit("--cell needs GOOGLE_CLOUD_PROJECT and --opencode")
        token = AdcToken()
        token()  # fail before any trial if credentials are missing
        executor = CellExecutor(args.opencode, project, token, estimates_usd={**DEFAULT_ESTIMATES_USD, **(args.estimates or {})},
                                default_image=args.default_image, use_image_tag=args.use_image_tag)
    runner = Runner(config, args.out, executor, workers=args.workers)
    if args.cell:  # every image must be on this host before the first paid call
        wanted = [(str(t.tasks_dir), t.id) for t in runner.known.values() if not config.tasks or t.id in config.tasks]
        missing = executor.missing_images(wanted)
        if missing:
            print(json.dumps({"missing_images": missing}, indent=2))
            return 4
    if args.preflight:
        print(json.dumps(runner.preflight(), indent=2))
        return 0
    status = runner.run(acknowledge_alerts=tuple(args.acknowledge_alert))
    print(json.dumps(status))
    return 0 if status["state"] == "done" else 3


if __name__ == "__main__":
    raise SystemExit(main())
