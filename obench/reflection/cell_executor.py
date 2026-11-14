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

A trace that can't be built makes the trial ``error``. The runner counts it,
the group's verdict becomes ``incomplete``, and missing traces never pass
silently.

Network: the container uses Docker's default bridge (TB tasks are built
with ``allow_internet = true``). Provider API hosts are sinkholed with
``--add-host``, so the only model route is the proxy.
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
from obench.reflection.wire_proxy import WireProxy

SINKHOLED_HOSTS = ("api.anthropic.com", "api.openai.com", "generativelanguage.googleapis.com", "openrouter.ai",
                   "aiplatform.googleapis.com", "us-central1-aiplatform.googleapis.com")
# Provisional per-trial cost estimates (USD) for the runner preflight; calibrate from the three smokes.
DEFAULT_ESTIMATES_USD = {"gemini-4-carbon": 1.50, "claude-opus-5-5": 2.00, "gpt-oss-120b": 0.10}


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
    proxy_host: str | None = None        # default: the docker bridge gateway
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
                "agent_timeout": int(meta.get("agent_timeout_s") or 1800)}
        if meta.get("docker_image"):
            return dict(task, image=meta["docker_image"], image_source="task.toml")
        checker = (task_dir / "checker.sh").read_text(encoding="utf-8") if (task_dir / "checker.sh").is_file() else ""
        found = re.search(r'(?m)^IMAGE="(?:\$\{BENCH_TASK_IMAGE:-)?([^"}]+)\}?"', checker)
        if found:
            workdir = re.search(r'(?m)^WORKDIR="?([^"\s]+)"?', checker)
            return dict(task, image=found.group(1), image_source="checker.sh",
                        workdir=workdir.group(1) if workdir else task["workdir"])
        if self.default_image:
            return dict(task, image=self.default_image, image_source="default_image")
        raise CellError(f"{spec.task}: no docker_image in task.toml, no image in checker.sh, and no default_image")

    def docker_args(self, spec: TrialSpec, task: dict, workspace: Path, model: vm.VertexModel, proxy_base: str,
                    instruction: str) -> list[str]:
        name = f"obench-reflect-{spec.trial_id}"
        args = ["run", "--rm", "--name", name, "--platform", self.platform,
                "-v", f"{workspace}:{task['workdir']}", "-v", f"{self.mount_root}:{self.mount_root}:ro",
                "-w", task["workdir"], "-e", "HOME=/tmp/opencode-home",
                "-e", f"OPENCODE_CONFIG_CONTENT={vm.opencode_config_env(model, proxy_base)}",
                "-e", "OPENCODE_DISABLE_AUTOUPDATE=1"]
        for host in SINKHOLED_HOSTS:
            args += ["--add-host", f"{host}:0.0.0.0"]
        return args + [task["image"], *oc.run_command(self.opencode, instruction, vm.opencode_model_arg(model))]

    def run_trial(self, spec: TrialSpec, run_dir: Path) -> TrialResult:
        from obench.workspace import materialize_workspace

        model = vm.resolve(spec.model)
        task = self._task(spec)
        if task["image_id"] and self.docker.image_id(task["image"]) != task["image_id"]:
            raise CellError(f"{spec.task}: {task['image']} is not the pinned image {task['image_id']}")
        trial_dir = Path(run_dir) / spec.trial_dir
        workspace = trial_dir / "workspace"
        if workspace.exists():
            shutil.rmtree(workspace)
        workspace.mkdir(parents=True)
        materialize_workspace(str(task["dir"]), str(workspace))
        instruction = (task["dir"] / "instruction.md").read_text(encoding="utf-8")
        wire_path, events_path = trial_dir / "wire.jsonl", trial_dir / "opencode-events.jsonl"
        wire_path.unlink(missing_ok=True)
        host = self.proxy_host or self.docker.bridge_gateway()
        proxy = WireProxy(self.project, wire_path, self.token, host=host, upstream_host=self.upstream_host,
                          patch=spec.patch, patch_id=spec.patch_id)
        try:
            args = self.docker_args(spec, task, workspace, model, proxy.base_url, instruction)
            code, timed_out = self.docker.run_agent(args, events_path, task["agent_timeout"])
        finally:
            proxy.close()
        rel = lambda p: str(Path(p).relative_to(run_dir))
        wires = [json.loads(l) for l in wire_path.read_text(encoding="utf-8").splitlines() if l.strip()] \
            if wire_path.exists() else []
        served = sorted({w.get("upstream_model") for w in wires if w.get("upstream_model")})
        costs = [w.get("cost_usd") for w in wires]
        cost = round(sum(c for c in costs if c is not None), 6) if costs and all(c is not None for c in costs) else (
            None if costs else 0.0)
        if timed_out:
            return TrialResult(status="timeout", passed=None, cost_usd=cost, served_models=served,
                               wire=rel(wire_path), error=f"agent timed out after {task['agent_timeout']}s")
        (trial_dir / "cell.json").write_text(json.dumps({"image": task["image"], "image_source": task["image_source"],
                                                         "workdir": task["workdir"], "opencode_exit": code,
                                                         "opencode_sha": self.pin["sha"]}, sort_keys=True) + "\n")
        checker_exit = self._check(task, workspace)
        try:
            events = tr.parse_events(events_path.read_text(encoding="utf-8").splitlines())
            records = tr.build_trace(events, wires, run={"run_id": spec.run_id, "trial_id": spec.trial_id,
                                                          "task": spec.task, "model": spec.model, "patch_id": spec.patch_id},
                                     cost_fn=lambda rec: (vm.cost_usd(model, rec["usage"]), "reflection.vertex_models"),
                                     count_thinking_tokens=vm.THINKING_TOKENS_FROM_TEXT.get(model.key))
            tr.write_trace(trial_dir / "trace.jsonl", records)
        except tr.TraceError as exc:
            return TrialResult(status="error", passed=None, checker_exit=checker_exit, cost_usd=cost,
                               served_models=served, wire=rel(wire_path), error=f"trace_error: {exc}")
        thinking = [r["usage"]["thinking_tokens"] for r in records if isinstance(r["usage"]["thinking_tokens"], int)]
        flags = sorted({r["thinking"]["flag"] for r in records if r["thinking"].get("flag")})
        return TrialResult(status="completed", passed=checker_exit == 0, checker_exit=checker_exit, steps=len(records),
                           cost_usd=cost, thinking_tokens=sum(thinking) if thinking else None, thinking_flags=flags,
                           served_models=served, trace=rel(trial_dir / "trace.jsonl"), wire=rel(wire_path),
                           error=None if code == 0 else f"opencode exited {code}")

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
