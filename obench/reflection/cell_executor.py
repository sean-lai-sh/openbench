"""Containerized trial executor for the reflection runner (SEA-107 / needed by SEA-111).

One trial = one container of the task's own image (``task.toml``
``docker_image``), running the pinned OpenCode against a per-trial recording
proxy, then the task's checker on the result:

1. Copy the task workspace into ``<trial_dir>/workspace`` (``obench.workspace``).
2. Start a ``WireProxy`` for this trial (with the ideation patch, if any). It
   is bound to the Docker bridge gateway so the container can reach it, and
   writes ``<trial_dir>/wire.jsonl``.
3. ``docker run`` the task image:
   - the workspace mounted at the task's WORKDIR;
   - the pinned OpenCode tree mounted read-only at its own path;
   - ``OPENCODE_CONFIG_CONTENT`` limited to this model's route;
   - ``opencode run --format json --thinking --model ...``.

   stdout is the event stream (``opencode-events.jsonl``). On timeout the
   container is killed.
4. Run the task's ``checker.sh`` on the workspace (``BENCH_TASK_IMAGE`` set,
   checker timeout from ``task.toml``). Exit 0 means passed.
5. Build ``trace.jsonl`` (``trace.build_trace``) from the events and the wire
   records. Return the cost (sum of the wire records), thinking tokens
   (usage), flags and served models.

If the last model call ended with finish reason stop, no tool call and no
text (``wire_proxy.route_truncated``), the trial is ``route_truncated``: an
infrastructure failure with ``passed: None``, never a task fail. Its trace,
wire record and checker exit are still saved.

A 4xx that ended or broke the trial (a main call came back 4xx and no main
call after it succeeded; ``wire_proxy.classify_4xx``) makes the trial
``upstream_4xx``: also an infrastructure failure with ``passed: None``. A 4xx
OpenCode retried and recovered from is the ``retried_4xx`` covariate. Each
trial records the image ref and id that actually ran and ``matches_pin``.
``finish_trial`` classifies from the files on disk, so finished trials can be
reclassified offline (``obench.reflection.reclassify``).
Every result carries the exact thinking setting sent (configured and as seen
on the wire) and the usage thinking tokens per step.

A trace that can't be built makes the trial ``error``. The runner counts it,
the group's verdict becomes ``incomplete``, and missing traces never pass
silently.

Network (parity with import validation): it follows ``task.toml``
``solution_needs_network``, which the importer sets by running the reference
``solve.sh`` offline first.

- ``true``: Docker's default ``bridge``, with internet, the same access the
  reference solution needed.
- ``false``: the internal network ``openbench-agent-offline``
  (``docker network create --internal``). There is no route out; the
  container can reach only the per-trial proxy, which binds to that
  network's gateway. OpenCode's models.dev fetch is turned off
  (``OPENCODE_DISABLE_MODELS_FETCH=1``).
- Missing (tasks imported before the flag, hand-made tasks):
  ``unflagged_network``, default ``bridge``, which was the only behavior
  before. ``cell.json`` records it as unflagged.

On every network, provider API hosts are sinkholed with ``--add-host``, so
the only model route is the proxy. ``cell.json`` records ``agent_network``
and ``solution_needs_network``.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from obench.reflection import opencode as oc
from obench.reflection import trace as tr
from obench.reflection import vertex_models as vm
from obench.reflection.runner import TrialResult, TrialSpec
from obench.reflection.wire_proxy import WireProxy, classify_4xx, route_repair_counts, route_truncated

SINKHOLED_HOSTS = ("api.anthropic.com", "api.openai.com", "generativelanguage.googleapis.com", "openrouter.ai",
                   "aiplatform.googleapis.com", "us-central1-aiplatform.googleapis.com")
# Provisional per-trial cost estimates (USD) for the runner preflight; calibrate from the three smokes.
DEFAULT_ESTIMATES_USD = {"gemini-4-carbon": 1.50, "claude-opus-5-5": 2.00, "gpt-oss-120b": 0.10}


OFFLINE_NETWORK = "openbench-agent-offline"


class CellError(RuntimeError):
    pass


class TrialDocker:
    """``docker`` calls the executor makes; replaced by a fake in tests."""

    def bridge_gateway(self) -> str:
        out = subprocess.run(["docker", "network", "inspect", "bridge", "--format",
                              "{{(index .IPAM.Config 0).Gateway}}"], capture_output=True, text=True, timeout=30)
        if out.returncode != 0 or not out.stdout.strip():
            raise CellError(f"cannot read the docker bridge gateway: {out.stderr.strip()}")
        return out.stdout.strip()

    def offline_gateway(self, name: str = OFFLINE_NETWORK) -> str:
        """Gateway of the internal (no route out) network, created on first use. The proxy binds here."""
        inspect = ["docker", "network", "inspect", name, "--format", "{{.Internal}} {{(index .IPAM.Config 0).Gateway}}"]
        out = subprocess.run(inspect, capture_output=True, text=True, timeout=30)
        if out.returncode != 0:
            subprocess.run(["docker", "network", "create", "--internal", name], capture_output=True, text=True, timeout=60)
            out = subprocess.run(inspect, capture_output=True, text=True, timeout=30)
        internal, _, gateway = out.stdout.strip().partition(" ")
        if out.returncode != 0 or internal != "true" or not gateway:
            raise CellError(f"network {name} is missing, not --internal, or has no gateway: {out.stdout.strip()} "
                            f"{out.stderr.strip()}")
        return gateway

    def has_image(self, ref: str) -> bool:
        return subprocess.run(["docker", "image", "inspect", ref], capture_output=True, timeout=60).returncode == 0

    def image_id(self, ref: str) -> str:
        out = subprocess.run(["docker", "image", "inspect", ref, "--format", "{{.Id}}"], capture_output=True, text=True,
                             timeout=60)
        if out.returncode != 0:
            raise CellError(f"task image {ref} is not on this host: {out.stderr.strip()}")
        return out.stdout.strip()

    def run_agent(self, args: list[str], stdout_path: Path, timeout: int) -> tuple[int | None, bool]:
        """``(exit code, timed_out)``. stdout goes to ``stdout_path``."""
        name = args[args.index("--name") + 1]
        with stdout_path.open("w", encoding="utf-8") as out:
            try:
                proc = subprocess.run(["docker", *args], stdout=out, stderr=subprocess.DEVNULL, timeout=timeout,
                                      stdin=subprocess.DEVNULL)
                return proc.returncode, False
            except subprocess.TimeoutExpired:
                subprocess.run(["docker", "kill", name], capture_output=True, timeout=60)
                return None, True
            finally:
                subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=60)


@dataclass
class CellExecutor:
    opencode: Path                       # pinned binary, bin/<sha>/opencode
    project: str
    token: Callable[[], str]
    estimates_usd: dict = field(default_factory=lambda: dict(DEFAULT_ESTIMATES_USD))
    docker: TrialDocker = field(default_factory=TrialDocker)
    platform: str = "linux/amd64"
    default_image: str | None = "h1-env:1027-strace"   # tasks with no image of their own (e.g. openbench-tb-hard)
    proxy_host: str | None = None        # default: the gateway of the trial's network
    use_image_tag: bool = False          # task.toml digest ref missing locally -> run docker_image_tag (recorded)
    unflagged_network: str = "bridge"    # tasks with no solution_needs_network: "bridge" (as before) or "offline"
    upstream_host: str | None = None     # tests only: fake Vertex
    checker_runner: Callable = subprocess.run

    def __post_init__(self):
        self.opencode = Path(self.opencode)
        self.pin = oc.verify_binary(self.opencode)
        # The cache root (…/opencode-src) is mounted at its own path: wrapper builds exec absolute paths in it.
        self.mount_root = self.opencode.parents[2]

    def estimate_cost_usd(self, model: str) -> float:
        return float(self.estimates_usd[model])

    def _task(self, spec: TrialSpec) -> dict:
        """The agent's image, in order: ``task.toml`` ``docker_image`` (id
        checked when recorded); the pinned image ``checker.sh`` names (the
        upstream environment plus verifier deps); ``default_image``."""
        task_dir = Path(spec.tasks_dir) / spec.task
        meta = tomllib.loads((task_dir / "task.toml").read_text(encoding="utf-8")) if (task_dir / "task.toml").is_file() else {}
        task = {"dir": task_dir, "image_id": meta.get("docker_image_id"), "workdir": meta.get("docker_workdir") or "/app",
                "agent_timeout": int(meta.get("agent_timeout_s") or 1800),
                "solution_needs_network": meta.get("solution_needs_network")}
        if meta.get("docker_image"):
            return dict(task, image=meta["docker_image"], image_source="task.toml", image_tag=meta.get("docker_image_tag"))
        checker = (task_dir / "checker.sh").read_text(encoding="utf-8") if (task_dir / "checker.sh").is_file() else ""
        found = re.search(r'(?m)^IMAGE="(?:\$\{BENCH_TASK_IMAGE:-)?([^"}]+)\}?"', checker)
        if found:
            workdir = re.search(r'(?m)^WORKDIR="?([^"\s]+)"?', checker)
            return dict(task, image=found.group(1), image_source="checker.sh",
                        workdir=workdir.group(1) if workdir else task["workdir"])
        if self.default_image:
            return dict(task, image=self.default_image, image_source="default_image")
        raise CellError(f"{spec.task}: no docker_image in task.toml, no image in checker.sh, and no default_image")

    def agent_network(self, task: dict) -> str:
        """``bridge`` or ``offline``, following the task's ``solution_needs_network``."""
        needs = task.get("solution_needs_network")
        if needs is None:
            if self.unflagged_network not in ("bridge", "offline"):
                raise CellError(f"unflagged_network must be bridge or offline, not {self.unflagged_network!r}")
            return self.unflagged_network
        return "bridge" if needs else "offline"

    def resolve_image(self, task: dict, name: str) -> dict:
        """The image must be on this host before any model call. A ``task.toml`` digest ref
        (``name@sha256:...``, e.g. openbench-tb-mid's, recorded from an arm64 build) does not exist after a
        local build; with ``use_image_tag`` the trial runs ``docker_image_tag`` instead and ``cell.json``
        records both refs and the id actually used."""
        if self.docker.has_image(task["image"]):
            return dict(task, image_pin=None)
        tag = task.get("image_tag")
        if self.use_image_tag and tag and self.docker.has_image(tag):
            return dict(task, image=tag, image_pin={"pinned": task["image"], "used": tag,
                                                    "used_id": self.docker.image_id(tag), "match": False})
        hint = (f"; build {tag} and pass --use-image-tag to run it" if tag and not self.use_image_tag else
                f"; {tag} is not on this host either" if tag else "")
        raise CellError(f"{name}: image {task['image']} ({task['image_source']}) is not on this host{hint}")

    def missing_images(self, tasks: list[tuple[str, str]]) -> dict[str, str]:
        """``{task: reason}`` for every ``(tasks_dir, task)`` whose image can't be resolved here (preflight)."""
        missing = {}
        for tasks_dir, name in tasks:
            spec = TrialSpec(run_id="preflight", trial_id="preflight", task=name, tasks_dir=tasks_dir, model="",
                             trial_index=0, patch_id=None, patch=None, trial_dir="")
            try:
                self.resolve_image(self._task(spec), name)
            except (CellError, OSError, tomllib.TOMLDecodeError) as exc:
                missing[name] = str(exc)
        return missing

    def docker_args(self, spec: TrialSpec, task: dict, workspace: Path, model: vm.VertexModel, proxy_base: str,
                    instruction: str, network: str = "bridge") -> list[str]:
        name = f"obench-reflect-{spec.trial_id}"
        args = ["run", "--rm", "--name", name, "--platform", self.platform,
                "--network", OFFLINE_NETWORK if network == "offline" else "bridge",
                "-v", f"{workspace}:{task['workdir']}", "-v", f"{self.mount_root}:{self.mount_root}:ro",
                "-w", task["workdir"], "-e", "HOME=/tmp/opencode-home",
                "-e", f"OPENCODE_CONFIG_CONTENT={vm.opencode_config_env(model, proxy_base)}",
                "-e", "OPENCODE_DISABLE_AUTOUPDATE=1"]
        if network == "offline":
            args += ["-e", "OPENCODE_DISABLE_MODELS_FETCH=1"]
        for host in SINKHOLED_HOSTS:
            args += ["--add-host", f"{host}:0.0.0.0"]
        return args + [task["image"], *oc.run_command(self.opencode, instruction, vm.opencode_model_arg(model))]

    def image_record(self, task: dict) -> dict:
        """What actually runs: the ref, its local image id, the pin, and whether the pin was honoured
        (``False`` when ``--use-image-tag`` ran ``docker_image_tag``; ``None`` when the task pins nothing)."""
        pin = task.get("image_pin")
        pinned = pin["pinned"] if pin else (task["image"] if "@sha256:" in task["image"] else task.get("image_id"))
        matches = False if pin else (True if pinned else None)
        return {"ref": task["image"], "id": pin["used_id"] if pin else self.docker.image_id(task["image"]),
                "pinned": pinned, "matches_pin": matches}

    def run_trial(self, spec: TrialSpec, run_dir: Path) -> TrialResult:
        from obench.workspace import materialize_workspace

        model = vm.resolve(spec.model)
        task = self.resolve_image(self._task(spec), spec.task)
        if task["image_id"] and self.docker.image_id(task["image"]) != task["image_id"]:
            raise CellError(f"{spec.task}: {task['image']} is not the pinned image {task['image_id']}")
        image = self.image_record(task)
        trial_dir = Path(run_dir) / spec.trial_dir
        workspace = trial_dir / "workspace"
        if workspace.exists():
            shutil.rmtree(workspace)
        workspace.mkdir(parents=True)
        materialize_workspace(str(task["dir"]), str(workspace))
        instruction = (task["dir"] / "instruction.md").read_text(encoding="utf-8")
        wire_path, events_path = trial_dir / "wire.jsonl", trial_dir / "opencode-events.jsonl"
        wire_path.unlink(missing_ok=True)
        network = self.agent_network(task)
        host = self.proxy_host or (self.docker.offline_gateway() if network == "offline" else self.docker.bridge_gateway())
        proxy = WireProxy(self.project, wire_path, self.token, host=host, upstream_host=self.upstream_host,
                          patch=spec.patch, patch_id=spec.patch_id)
        try:
            args = self.docker_args(spec, task, workspace, model, proxy.base_url, instruction, network)
            code, timed_out = self.docker.run_agent(args, events_path, task["agent_timeout"])
        finally:
            proxy.close()
        # Everything the classification needs is on disk from here, so finish_trial can be rerun offline.
        (trial_dir / "cell.json").write_text(json.dumps({
            "image": task["image"], "image_source": task["image_source"], "image_record": image,
            "workdir": task["workdir"], "opencode_exit": code, "timed_out": timed_out, "agent_timeout": task["agent_timeout"],
            "agent_network": network, "image_pin": task["image_pin"],
            "solution_needs_network": task["solution_needs_network"],
            "network_unflagged": task["solution_needs_network"] is None,
            "opencode_sha": self.pin["sha"]}, sort_keys=True) + "\n")
        return self.finish_trial(spec, run_dir, task)

    def finish_trial(self, spec: TrialSpec, run_dir: Path, task: dict | None = None,
                     run_checker: bool = True) -> TrialResult:
        """Classify a trial from what is on disk: ``cell.json``, ``wire.jsonl``, the event stream and the workspace.
        No model calls. ``run_checker=False`` (offline reclassification of a trial that was already graded)
        reuses nothing it can't recompute and leaves ``checker_exit`` to the caller."""
        model = vm.resolve(spec.model)
        trial_dir = Path(run_dir) / spec.trial_dir
        cell = json.loads((trial_dir / "cell.json").read_text(encoding="utf-8")) if (trial_dir / "cell.json").is_file() else {}
        if task is None:
            task = self._task(spec)
            task = dict(task, image=cell.get("image", task["image"]), image_pin=cell.get("image_pin"))
        image = cell.get("image_record") or self.image_record(task)
        code, timed_out = cell.get("opencode_exit"), bool(cell.get("timed_out"))
        workspace = trial_dir / "workspace"
        wire_path, events_path = trial_dir / "wire.jsonl", trial_dir / "opencode-events.jsonl"
        rel = lambda p: str(Path(p).relative_to(run_dir))
        wires = [json.loads(l) for l in wire_path.read_text(encoding="utf-8").splitlines() if l.strip()] \
            if wire_path.exists() else []
        served = sorted({w.get("upstream_model") for w in wires if w.get("upstream_model")})
        counts = route_repair_counts(wires)
        sent = {json.dumps(tr.thinking_setting(w["provider_wire"], w["request"]), sort_keys=True)
                for w in wires if isinstance(w.get("request"), dict) and w.get("provider_wire")}
        thinking_setting = {"configured": model.thinking_sent(), "sent": [json.loads(x) for x in sorted(sent)]}
        costs = [w.get("cost_usd") for w in wires]
        cost = round(sum(c for c in costs if c is not None), 6) if costs and all(c is not None for c in costs) else (
            None if costs else 0.0)
        fours = classify_4xx(wires)
        common = dict(cost_usd=cost, served_models=served, route_counts=counts, thinking_setting=thinking_setting,
                      retried_4xx=fours["retried"], image=image, wire=rel(wire_path))
        if fours["breaking"]:  # a 4xx ended or broke the trial: infrastructure, never a task fail
            (trial_dir / "upstream_4xx.json").write_text(json.dumps(fours, sort_keys=True) + "\n")
            return TrialResult(status="upstream_4xx", passed=None, **common,
                               error="upstream 4xx: " + ", ".join(f"call {c['call_index']} -> {c['status']}"
                                                                  for c in fours["breaking"]))
        (trial_dir / "upstream_4xx.json").unlink(missing_ok=True)
        if timed_out:
            return TrialResult(status="timeout", passed=None, **common,
                               error=f"agent timed out after {cell.get('agent_timeout') or task['agent_timeout']}s")
        checker_exit = self._check(task, workspace) if run_checker else None
        try:
            events = tr.parse_events(events_path.read_text(encoding="utf-8").splitlines())
            records = tr.build_trace(events, wires, run={"run_id": spec.run_id, "trial_id": spec.trial_id,
                                                          "task": spec.task, "model": spec.model, "patch_id": spec.patch_id},
                                     cost_fn=lambda rec: (vm.cost_usd(model, rec["usage"]), "reflection.vertex_models"),
                                     count_thinking_tokens=vm.THINKING_TOKENS_FROM_TEXT.get(model.key))
            tr.write_trace(trial_dir / "trace.jsonl", records)
        except tr.TraceError as exc:
            return TrialResult(status="error", passed=None, checker_exit=checker_exit, **common, error=f"trace_error: {exc}")
        thinking = [r["usage"]["thinking_tokens"] for r in records if isinstance(r["usage"]["thinking_tokens"], int)]
        per_step = [r["usage"]["thinking_tokens"] if isinstance(r["usage"]["thinking_tokens"], int) else None for r in records]
        flags = sorted({r["thinking"]["flag"] for r in records if r["thinking"].get("flag")})
        done = dict(common, checker_exit=checker_exit, steps=len(records), thinking_tokens=sum(thinking) if thinking else None,
                    thinking_flags=flags, thinking_tokens_per_step=per_step, trace=rel(trial_dir / "trace.jsonl"))
        truncated = route_truncated(wires)
        if truncated is not None:
            (trial_dir / "route_truncated.json").write_text(json.dumps(truncated, sort_keys=True) + "\n")
            return TrialResult(status="route_truncated", passed=None, **done,
                               error=f"route_truncated: model call {truncated['call_index']} ended "
                                     f"{truncated['finish_reasons']} with no tool call and no text")
        return TrialResult(status="completed", passed=checker_exit == 0 if checker_exit is not None else None, **done,
                           error=None if code in (0, None) else f"opencode exited {code}")

    def _check(self, task: dict, workspace: Path) -> int:
        from obench.checker_timeout import checker_timeout_s

        env = dict(os.environ, TASK_DIR=str(task["dir"]), BENCH_TASK_IMAGE=str(task["image"]))
        env.pop("OPENBENCH_SOLUTION_OVERLAY", None)
        try:
            proc = self.checker_runner(["bash", str(task["dir"] / "checker.sh")], cwd=str(workspace), env=env,
                                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                       timeout=checker_timeout_s(task["dir"].name, str(task["dir"])))
        except subprocess.TimeoutExpired:
            return 124
        (workspace.parent / "checker-output.txt").write_text(proc.stdout or "", encoding="utf-8")
        return proc.returncode
