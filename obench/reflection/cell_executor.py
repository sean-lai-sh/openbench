"""Containerized trial executor for the reflection runner (SEA-107 / needed by SEA-111).

One trial = one container of the task's own image (``task.toml``
``docker_image``), running the pinned OpenCode against a per-trial recording
proxy, then the task's checker on the result:

1. Seed ``<trial_dir>/workspace`` the way ``obench run --exec docker`` does: the task
   image's WORKDIR contents (``docker cp``), then the task's own ``workspace/`` on top,
   then ``.openbench-image-hydrated`` (``seed_workspace``). The bind mount then shows
   the agent the image's full WORKDIR. Tasks on the generic default image keep their
   own workspace only.
2. Start a ``WireProxy`` for this trial (with the ideation patch, if any). It
   is bound to the Docker bridge gateway so the container can reach it, and
   writes ``<trial_dir>/wire.jsonl``.
3. ``docker run`` the task image:
   - the workspace mounted at the task's WORKDIR;
   - only the pinned OpenCode binary's directory, read-only at /opt/opencode/<sha>
     (a wrapper build still needs its source tree; ``cell.json`` says which);
   - OpenCode permissions that ``opencode run`` would otherwise auto-reject
     (``AGENT_PERMISSIONS``);
   - ``OPENCODE_CONFIG_CONTENT`` limited to this model's route;
   - ``opencode run --format json --thinking --model ...``.

   stdout is the event stream (``opencode-events.jsonl``). On timeout the
   container is killed.
4. Run the task's ``checker.sh`` on the workspace (``BENCH_TASK_IMAGE`` set,
   checker timeout from ``task.toml``). Exit 0 means passed. Agent-written code
   never runs on the host: a checker that ``docker run``s the task image itself
   runs as is; every other checker runs whole inside the task image (``_check``).
   ``checker_error`` only when the checker container itself fails to launch.
5. Build ``trace.jsonl`` (``trace.build_trace``) from the events and the wire
   records. Return the cost (sum of the wire records), thinking tokens
   (usage), flags and served models.

If the last model call ended with finish reason stop, no tool call and no
text (``wire_proxy.route_truncated``), the trial is ``route_truncated``: an
infrastructure failure with ``passed: None``, never a task fail. Its trace,
wire record and checker exit are still saved.

A prompt the provider blocked (Gemini ``promptFeedback.blockReason``, HTTP 200
with no candidates) ends the trial at once: the proxy stops the container and
refuses OpenCode's retries, and the trial is ``provider_blocked`` (raw
blockReason and blockReasonMessage kept): neither pass nor fail, excluded from
the model's pass rate, never swapped (Researcher ruling 2026-11-17). The cell
still enters credit assignment and ideation when its set-aside count is at
most 3 (about 10% of 30).

Otherwise, any refusal or safety stop in the trial (Anthropic ``stop_reason:
"refusal"``, Gemini ``finishReason: SAFETY``) makes it ``model_refused``, recorded
with the step it happened on; it is set aside the same way, and the checker
still runs. OpenCode exiting 0 with a tool call pending is
``agent_exit_pending_tool`` (``agent_exit.json``): infrastructure, never a task
fail. A final side request rejected for a thinking-block signature bound to
another conversation is ``side_thinking_signature`` instead
(``side_signature.json``, ``env_cause=vertex_thinking_signature``): the last
tool had already finished, and the 400 is not a pending tool. A main turn
rejected for that signature after a side call in the same trial is
``post_compaction_signature`` (``post_compaction.json``, same env_cause):
the side response's thinking block was replayed. That outranks
``upstream_4xx`` and ``agent_exit_pending_tool``. If the last call is the
side signature 400, ``side_thinking_signature`` still wins.

Timeouts (Researcher ruling 2026-11-17): the cap is the task's agent timeout
(``task.toml`` ``agent_timeout_s``, else 1800 s, the same for both models). A
trial that hits it while a model call finished in the last 5 minutes before the
cap was still working: a task FAIL (``completed``, ``passed: False``,
``timed_out: True``; checker and trace still run). Otherwise it is ``timeout``
(infrastructure). A trace/step-accounting problem is only a logged warning
(``trace_warning``) and never drops the trial.

Each ``cell.json`` also records the run's fixed ``workers`` value, the agent's
wall time and the host load average before and after, so contention-driven
timeouts are visible.

A 4xx that ended or broke the trial (a main call came back 4xx and no main
call after it succeeded; ``wire_proxy.classify_4xx``) makes the trial
``upstream_4xx``: also an infrastructure failure with ``passed: None``. A 4xx
OpenCode retried and recovered from is the ``retried_4xx`` covariate. Each
trial records the image ref and id that actually ran and ``matches_pin``.
For gpt-oss, every tool call the proxy rebuilt from text is logged per cell in
``<model>/<task>/route_repairs.jsonl``, and calls to tools we never offered
are counted in ``cell_counters.json`` as ``model_errors.unknown_tool``.
``finish_trial`` classifies from the files on disk, so finished trials can be
reclassified offline (``obench.reflection.reclassify``).
Every result carries the exact thinking setting sent (configured and as seen
on the wire) and the usage thinking tokens per step.

A trace that can't be built makes the trial ``error``. The runner counts it,
the group's verdict becomes ``incomplete``, and missing traces never pass
silently.

Isolation: no trial container may reach the GCE metadata server. Agents and
in-container checkers run on the dedicated bridge ``openbench-agent``
(interface ``obench-agent0``), never Docker's default bridge; one DOCKER-USER
rule drops its traffic to 169.254.169.254 (``obench.reflection.isolation``).
Before the first trial, a live probe - a container on each trial network,
started with the trial containers' own platform and --add-host settings -
must fail to connect to 169.254.169.254:80 and metadata.google.internal:80
(3 s timeout each) and must reach the proxy's address; otherwise the executor
refuses to run (``isolation_preflight``; recorded as ``isolation`` in plan.json
and every cell.json).

Network (parity with import validation): it follows ``task.toml``
``solution_needs_network``, which the importer sets by running the reference
``solve.sh`` offline first.

- ``true``: the agent bridge ``openbench-agent``, with internet (no metadata server), the same access the
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
from datetime import datetime, timezone
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from obench.reflection import opencode as oc
from obench.reflection import trace as tr
from obench.reflection import vertex_models as vm
from obench.reflection.runner import TrialResult, TrialSpec, code_commit
from obench.reflection.wire_proxy import (WireProxy, classify_4xx, last_vertex_request, model_refused,
                                          post_compaction_detail, provider_blocked, route_repair_counts,
                                          route_truncated, side_kind_counts, signature_400_count,
                                          stripped_side_thinking_total, terminating_side_signature,
                                          thinking_binding_seen)

SINKHOLED_HOSTS = ("api.anthropic.com", "api.openai.com", "generativelanguage.googleapis.com", "openrouter.ai",
                   "aiplatform.googleapis.com", "us-central1-aiplatform.googleapis.com")
# Provisional per-trial cost estimates (USD) for the runner preflight; calibrate from the three smokes.
DEFAULT_ESTIMATES_USD = {"gemini-4-carbon": 1.50, "claude-opus-5-5": 2.00, "gpt-oss-120b": 0.10}


OFFLINE_NETWORK = "openbench-agent-offline"
# Agents and in-container checkers that may use the internet run on this bridge, never on docker's default one.
# Its interface has a fixed name so one DOCKER-USER rule can drop the GCE metadata server for it (the host's own
# metadata access, which the proxy's ADC token uses, is untouched: DOCKER-USER only sees forwarded traffic).
AGENT_NETWORK = "openbench-agent"
AGENT_BRIDGE_IF = "obench-agent0"
METADATA_IP = "169.254.169.254"
METADATA_TARGETS = [(METADATA_IP, 80), ("metadata.google.internal", 80)]  # both must fail to connect
METADATA_RULE = ["DOCKER-USER", "-i", AGENT_BRIDGE_IF, "-d", f"{METADATA_IP}/32", "-j", "DROP"]


def _load() -> list | None:
    try:
        return [round(x, 2) for x in os.getloadavg()]
    except OSError:
        return None


# `opencode run` auto-rejects every permission request; the default agent asks for paths outside the project
# (external_directory: /tmp, /usr, ...), for a third identical tool call (doom_loop) and for reading *.env. A rejected
# permission ends the run with the tool call pending. In a disposable container these are allowed (the last matching
# rule wins at the pin, so these override the defaults; no tool is added or removed, so tool definitions sent to the
# model are unchanged).
AGENT_PERMISSIONS = {"external_directory": "allow", "doom_loop": "allow", "read": "allow"}
OPENCODE_IN_CONTAINER = "/opt/opencode"   # the pinned standalone binary's directory, mounted read-only
CHECKER_LAUNCHED = "__openbench_checker_launched__"  # printed in the checker container before checker.sh runs
_RUNTIME_MEDIAN = re.compile(
    r"""['"](?P<name>golden|solution)['"]\s*:\s*\{[^{}]*?['"]median_s['"]\s*:\s*"""
    r"""(?P<median>[0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?)""")


def parse_checker_runtime(text: str | None) -> dict:
    """Pull query-optimize's printed medians out of checker output.

    The checker prints a dict with ``golden.median_s`` and ``solution.median_s``.
    ``runtime_measured_s`` is the solution median, ``runtime_golden_s`` is the
    golden median, and ``runtime_ratio`` is measured / golden. The last pair
    in the output wins (pytest prints the summary, then may echo it). All
    three are null when either median is missing. This does not re-time the query.
    """
    empty = {"runtime_measured_s": None, "runtime_golden_s": None, "runtime_ratio": None}
    if not text:
        return empty
    found: dict[str, float] = {}
    for match in _RUNTIME_MEDIAN.finditer(text):
        found[match.group("name")] = float(match.group("median"))
    golden, measured = found.get("golden"), found.get("solution")
    if golden is None or measured is None or golden == 0:
        return empty
    return {"runtime_measured_s": measured, "runtime_golden_s": golden,
            "runtime_ratio": round(measured / golden, 6)}
PERMISSION_LINE = re.compile(r"permission requested: (\S+) \(([^)]*)\); auto-rejecting")


def wire_cost(wires: list[dict]) -> tuple[float, int]:
    """``(cost_usd, unpriced_calls)`` from a trial's wire records, for every outcome including timeouts. Calls
    with a cost are summed even when some have none (e.g. the call a timeout cut off before usage arrived); the
    unpriced answered calls are counted, so the total is a known lower bound rather than missing. It is what the
    runner adds to spend, so it counts toward the cap and the alert stops."""
    costs = [w.get("cost_usd") for w in wires if w.get("status") == 200 or w.get("cost_usd") is not None]
    return round(sum(c for c in costs if c is not None), 6), sum(1 for c in costs if c is None)


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

    def agent_gateway(self, name: str = AGENT_NETWORK) -> str:
        """Gateway of the agent bridge (created on first use, interface ``obench-agent0``). The proxy binds here."""
        inspect = ["docker", "network", "inspect", name, "--format",
                   '{{.Internal}} {{index .Options "com.docker.network.bridge.name"}} {{(index .IPAM.Config 0).Gateway}}']
        out = subprocess.run(inspect, capture_output=True, text=True, timeout=30)
        if out.returncode != 0:
            subprocess.run(["docker", "network", "create", "--driver", "bridge",
                            "-o", f"com.docker.network.bridge.name={AGENT_BRIDGE_IF}", name],
                           capture_output=True, text=True, timeout=60)
            out = subprocess.run(inspect, capture_output=True, text=True, timeout=30)
        parts = out.stdout.split()
        if out.returncode != 0 or len(parts) != 3 or parts[0] != "false" or parts[1] != AGENT_BRIDGE_IF:
            raise CellError(f"network {name} is missing or not a bridge on {AGENT_BRIDGE_IF}: {out.stdout.strip()} "
                            f"{out.stderr.strip()}")
        return parts[2]

    def probe(self, network: str, image: str, targets: list[tuple[str, int]],
              run_args: list[str] | None = None) -> dict[str, bool]:
        """Live probe: a throwaway container on ``network``, started with the trial containers' own ``run_args``
        (platform, --add-host entries), tries a TCP connection to each ``(host, port)`` with a 3 s timeout.
        Returns ``{"host:port": connected}``."""
        checks = "; ".join(f'(timeout 3 bash -c "</dev/tcp/{h}/{p}") >/dev/null 2>&1 && echo "{h}:{p} open" '
                           f'|| echo "{h}:{p} closed"' for h, p in targets)
        out = subprocess.run(["docker", "run", "--rm", "--network", network, *(run_args or []),
                              "--entrypoint", "bash", image, "-c", checks],
                             capture_output=True, text=True, timeout=120)
        if out.returncode != 0:
            raise CellError(f"isolation probe could not run on {network} with {image}: {out.stderr.strip()[:300]}")
        found = dict(line.rsplit(" ", 1) for line in out.stdout.splitlines() if line.strip())
        return {f"{h}:{p}": found.get(f"{h}:{p}") == "open" for h, p in targets}

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

    def hydrate(self, image: str, workdir: str, dest: Path) -> None:
        """Copy the image's WORKDIR contents into ``dest`` (what the agent would see without a mount)."""
        from obench.run import hydrate_image_workdir
        try:
            hydrate_image_workdir(image, workdir, str(dest))
        except RuntimeError as exc:
            raise CellError(str(exc)) from exc

    def run_checker(self, args: list[str], timeout: int) -> tuple[int, str]:
        """``docker run`` a checker inside the task image; ``(exit, output)``. Killed on timeout (exit 124)."""
        name = args[args.index("--name") + 1]
        try:
            proc = subprocess.run(["docker", *args], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                  timeout=timeout, stdin=subprocess.DEVNULL)
            return proc.returncode, proc.stdout or ""
        except subprocess.TimeoutExpired as exc:
            subprocess.run(["docker", "kill", name], capture_output=True, timeout=60)
            return 124, (exc.stdout or "") if isinstance(exc.stdout, str) else ""
        finally:
            subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=60)

    def kill(self, name: str) -> None:
        subprocess.run(["docker", "kill", name], capture_output=True, timeout=60)

    def run_agent(self, args: list[str], stdout_path: Path, timeout: int,
                  stderr_path: Path | None = None) -> tuple[int | None, bool]:
        """``(exit code, timed_out)``. stdout goes to ``stdout_path``, stderr (OpenCode's warnings, e.g.
        auto-rejected permissions) to ``stderr_path``."""
        name = args[args.index("--name") + 1]
        with stdout_path.open("w", encoding="utf-8") as out, \
                (stderr_path.open("w", encoding="utf-8") if stderr_path else open(os.devnull, "w")) as err:
            try:
                proc = subprocess.run(["docker", *args], stdout=out, stderr=err, timeout=timeout,
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
    probe_image: str | None = None       # image for the isolation probe (needs bash); default: default_image
    proxy_host: str | None = None        # default: the gateway of the trial's network
    use_image_tag: bool = False          # task.toml digest ref missing locally -> run docker_image_tag (recorded)
    unflagged_network: str = "bridge"    # tasks with no solution_needs_network: "bridge" (as before) or "offline"
    upstream_host: str | None = None     # tests only: fake Vertex
    checker_runner: Callable = subprocess.run
    check_pin: bool = True          # reference validation builds an executor with no OpenCode binary
    smoke_compaction: bool = False  # opt-in smoke profile: lower OpenCode limit.context (default off)

    def __post_init__(self):
        self.code = code_commit()  # recorded by the executor itself on every trial (cell.json)
        import threading
        self._record_lock = threading.Lock()  # trials of one cell may finish together (runner --workers)
        self.run_context: dict = {}
        self._isolation, self._isolation_lock = None, threading.Lock()
        if not self.check_pin:
            self.opencode = Path(self.opencode) if self.opencode else None
            self.pin = None
            self.standalone = False
            self.mount_root = None
            return
        self.opencode = Path(self.opencode)
        self.pin = oc.verify_binary(self.opencode)
        # A standalone build (compile / build.ts) needs only its own bin/<sha>/ directory, mounted read-only at a
        # neutral path, so the host's source tree and worktrees are not visible in the container. Wrapper builds
        # (bun-run / monorepo) exec absolute paths in the cache root and still need it (recorded in cell.json).
        self.standalone = (self.pin.get("build_stamp") or {}).get("kind") in ("compile", "build.ts")
        self.mount_root = self.opencode.parents[2]

    def isolation_preflight(self) -> dict:
        """Fail closed unless live probes show the GCE metadata server unreachable from every kind of container
        that runs agent code, each started with that container's own settings:

        - ``agent``: the agent container on ``openbench-agent`` (must also reach the host proxy);
        - ``agent_offline``: the agent container on the internal network;
        - ``checker``: an in-container checker (``openbench-agent``, as ``_check`` starts it);
        - ``checker_self_containerized``: the grading container a self-containerized checker starts
          (``--network none``, which ``_check`` enforces).

        Each tries TCP to 169.254.169.254:80 and metadata.google.internal:80 (3 s timeout); any connection fails
        the preflight. Probed once per executor (before the first trial; the runner probes before any spend) and
        recorded in plan.json and every trial's cell.json."""
        with self._isolation_lock:
            if self._isolation is not None:
                return self._isolation
            import socket
            image = self.probe_image or self.default_image
            if not image:
                raise CellError("no probe image for the isolation preflight (set default_image or probe_image)")
            agent_args = ["--platform", self.platform]
            for host in SINKHOLED_HOSTS:
                agent_args += ["--add-host", f"{host}:0.0.0.0"]
            plan = [("agent", AGENT_NETWORK, agent_args, self.docker.agent_gateway()),
                    ("agent_offline", OFFLINE_NETWORK, agent_args, self.docker.offline_gateway()),
                    ("checker", AGENT_NETWORK, ["--platform", self.platform, "-w", "/app"], None),
                    ("checker_self_containerized", "none", ["--platform", self.platform], None)]
            result = {"agent_network": AGENT_NETWORK, "bridge_interface": AGENT_BRIDGE_IF, "probe_image": image,
                      "metadata_rule": "iptables -I " + " ".join(METADATA_RULE), "probes": {}}
            for role, network, run_args, gateway in plan:
                targets, listener, proxy_target = list(METADATA_TARGETS), None, None
                try:
                    if gateway is not None:
                        listener = socket.socket()
                        listener.bind((self.proxy_host or gateway, 0))
                        listener.listen(8)
                        port = listener.getsockname()[1]
                        targets.append((self.proxy_host or gateway, port))
                        proxy_target = f"{self.proxy_host or gateway}:{port}"
                    seen = self.docker.probe(network, image, targets, run_args)
                finally:
                    if listener is not None:
                        listener.close()
                metadata = {t: seen[t] for t in (f"{h}:{p}" for h, p in METADATA_TARGETS)}
                result["probes"][role] = {"network": network, "run_args": run_args,
                                          "metadata_reachable": any(metadata.values()), "metadata_targets": metadata,
                                          "proxy_reachable": seen[proxy_target] if proxy_target else None}
            # metadata unreachable everywhere; the proxy reachable from the agent (the offline network's proxy
            # reachability is checked when a trial actually needs it)
            bad = {r: v for r, v in result["probes"].items()
                   if v["metadata_reachable"] or (r == "agent" and not v["proxy_reachable"])}
            result.update(ok=not bad, checked_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
            if bad:
                raise CellError(f"isolation preflight failed: {bad}. Run `python3 -m obench.reflection.isolation "
                                f"--apply` (adds: iptables -I {' '.join(METADATA_RULE)}) and retry.")
            self._isolation = result
            return result

    def set_run_context(self, context: dict) -> None:
        """Set by the runner: ``{run_id, workers}``, recorded on every trial's cell.json."""
        self.run_context = dict(context)

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
                "--network", OFFLINE_NETWORK if network == "offline" else AGENT_NETWORK,
                "-v", f"{workspace}:{task['workdir']}", "-v", self.opencode_mount(),
                "-w", task["workdir"], "-e", "HOME=/tmp/opencode-home",
                "-e", f"OPENCODE_CONFIG_CONTENT={self.opencode_config(model, proxy_base)}",
                "-e", "OPENCODE_DISABLE_AUTOUPDATE=1"]
        if network == "offline":
            args += ["-e", "OPENCODE_DISABLE_MODELS_FETCH=1"]
        for host in SINKHOLED_HOSTS:
            args += ["--add-host", f"{host}:0.0.0.0"]
        return args + [task["image"], *oc.run_command(self.opencode_in_container(), instruction, vm.opencode_model_arg(model))]

    def solve_docker_args(self, task: dict, workspace: Path, solve: Path, network: str) -> list[str]:
        """The reference solution in the task image: same platform, network, sinkholes and workspace mount as
        ``docker_args``, then ``bash`` on the solution script. No OpenCode and no proxy.

        Host paths are absolute. Docker treats a bind source as a host path only when it is absolute or starts
        with ``.``; a relative path such as ``oracle-work/task/workspace`` is not mounted.
        """
        workspace, solve = Path(workspace).resolve(), Path(solve).resolve()
        name = f"obench-oracle-{task['dir'].name}-{os.getpid()}"
        args = ["run", "--rm", "--name", name, "--platform", self.platform,
                "--network", OFFLINE_NETWORK if network == "offline" else AGENT_NETWORK,
                "-v", f"{workspace}:{task['workdir']}",
                "-v", f"{solve.parent}:/openbench-solution:ro",
                "-w", task["workdir"]]
        for host in SINKHOLED_HOSTS:
            args += ["--add-host", f"{host}:0.0.0.0"]
        return args + [task["image"], "bash", f"/openbench-solution/{solve.name}"]

    def run_solve(self, task: dict, workspace: Path, solve: Path, network: str,
                  stdout_path: Path, stderr_path: Path) -> tuple[int | None, str, str]:
        """Run ``solve.sh`` / ``solution.sh`` via ``TrialDocker.run_agent`` (the same ``docker run`` path as a trial)."""
        code, _timed_out = self.docker.run_agent(
            self.solve_docker_args(task, workspace, solve, network), stdout_path,
            int(task.get("agent_timeout") or 600), stderr_path=stderr_path)
        stdout = stdout_path.read_text(encoding="utf-8", errors="replace") if stdout_path.exists() else ""
        stderr = stderr_path.read_text(encoding="utf-8", errors="replace") if stderr_path.exists() else ""
        return code, stdout, stderr

    def opencode_mount(self) -> str:
        if self.standalone:
            return f"{self.opencode.parent}:{OPENCODE_IN_CONTAINER}/{self.pin['sha']}:ro"
        return f"{self.mount_root}:{self.mount_root}:ro"

    def opencode_in_container(self) -> Path:
        if self.standalone:
            return Path(OPENCODE_IN_CONTAINER) / self.pin["sha"] / self.opencode.name
        return self.opencode

    def opencode_config(self, model: vm.VertexModel, proxy_base: str) -> str:
        body = vm.opencode_config(model, proxy_base, smoke_compaction=self.smoke_compaction)
        return json.dumps(dict(body, permission=dict(AGENT_PERMISSIONS)), sort_keys=True)

    def image_record(self, task: dict) -> dict:
        """What actually runs: the ref, its local image id, the pin, and whether the pin was honoured
        (``False`` when ``--use-image-tag`` ran ``docker_image_tag``; ``None`` when the task pins nothing).

        A recorded image keeps the flag from the original trials. It is not recomputed, so a recorded
        ``matches_pin`` of false stays false.
        """
        if task.get("image_source") == "recorded":
            image_id = task.get("image_id") or self.docker.image_id(task["image"])
            return {"ref": task["image"], "id": image_id, "pinned": task.get("image_id"),
                    "matches_pin": task.get("recorded_matches_pin")}
        pin = task.get("image_pin")
        pinned = pin["pinned"] if pin else (task["image"] if "@sha256:" in task["image"] else task.get("image_id"))
        matches = False if pin else (True if pinned else None)
        return {"ref": task["image"], "id": pin["used_id"] if pin else self.docker.image_id(task["image"]),
                "pinned": pinned, "matches_pin": matches}

    def prepare_task(self, spec: TrialSpec) -> dict:
        """The image this trial runs.

        ``recorded_image`` on the spec is the image the cell's original trials ran. It is reused as
        that ref and id. ``resolve_image`` is not called, so a missing digest is not replaced with
        ``docker_image_tag`` and the pin is not looked up again.
        """
        recorded = getattr(spec, "recorded_image", None)
        if not recorded:
            task = self.resolve_image(self._task(spec), spec.task)
            if task["image_id"] and self.docker.image_id(task["image"]) != task["image_id"]:
                raise CellError(f"{spec.task}: {task['image']} is not the pinned image {task['image_id']}")
            return task
        if not isinstance(recorded, dict) or not isinstance(recorded.get("ref"), str) or not recorded["ref"]:
            raise CellError(f"{spec.task}: recorded_image needs a ref, got {recorded!r}")
        ref = recorded["ref"]
        if not self.docker.has_image(ref):
            raise CellError(f"{spec.task}: recorded image {ref} is not on this host; refusing to re-pin")
        image_id = recorded.get("id")
        local_id = self.docker.image_id(ref)
        if image_id and local_id != image_id:
            raise CellError(f"{spec.task}: recorded image {ref} is {local_id}, not {image_id}; refusing to re-pin")
        task = self._task(spec)
        return dict(task, image=ref, image_source="recorded", image_id=image_id, image_pin=None, image_tag=None,
                    recorded_matches_pin=recorded.get("matches_pin"))

    def seed_workspace(self, task: dict, workspace: Path) -> dict:
        """The agent starts from the task image's WORKDIR, as ``obench run --exec docker`` stages it: the image's
        WORKDIR contents, then the task's own ``workspace/`` on top, then ``.openbench-image-hydrated`` so
        checkers don't hydrate again (tb-mid checkers re-copy the image over the workspace without it). The
        bind mount then shows the agent the full ``/app`` (query-optimize's database, corewars' ``warriors/``,
        sanitize-git-repo's ``dclm``). Tasks on the generic default image keep their own workspace only."""
        from obench.workspace import materialize_workspace
        if task["image_source"] == "default_image":
            materialize_workspace(str(task["dir"]), str(workspace))
            return {"hydrated_from": None, "workdir": task["workdir"],
                    "files": sum(len(f) for _, _, f in os.walk(workspace))}
        self.docker.hydrate(task["image"], task["workdir"], workspace)
        import tempfile
        staged = Path(tempfile.mkdtemp(prefix="obench_task_overlay_", dir=str(workspace.parent)))
        try:
            materialize_workspace(str(task["dir"]), str(staged))
            for item in staged.iterdir():
                if item.name == ".gitkeep":
                    continue
                dest = workspace / item.name
                if item.is_dir() and not item.is_symlink():
                    shutil.copytree(item, dest, dirs_exist_ok=True, symlinks=True)
                else:
                    shutil.copy2(item, dest, follow_symlinks=False)
        finally:
            shutil.rmtree(staged, ignore_errors=True)
        (workspace / ".openbench-image-hydrated").write_text(task["image"] + "\n", encoding="utf-8")
        files = sum(len(f) for _, _, f in os.walk(workspace))
        return {"hydrated_from": task["image"], "workdir": task["workdir"], "files": files}

    def run_trial(self, spec: TrialSpec, run_dir: Path) -> TrialResult:
        if self.pin is None:
            raise CellError("CellExecutor has no pinned OpenCode binary")
        from obench.workspace import materialize_workspace

        model = vm.resolve(spec.model)
        task = self.prepare_task(spec)
        image = self.image_record(task)
        trial_dir = Path(run_dir) / spec.trial_dir
        workspace = trial_dir / "workspace"
        if workspace.exists():
            shutil.rmtree(workspace)
        workspace.mkdir(parents=True)
        seed = self.seed_workspace(task, workspace)
        instruction = (task["dir"] / "instruction.md").read_text(encoding="utf-8")
        wire_path, events_path = trial_dir / "wire.jsonl", trial_dir / "opencode-events.jsonl"
        wire_path.unlink(missing_ok=True)
        network = self.agent_network(task)
        isolation = self.isolation_preflight()
        if network == "offline" and not isolation["probes"]["agent_offline"]["proxy_reachable"]:
            raise CellError(f"{OFFLINE_NETWORK}: the proxy is not reachable from the internal network on this host")
        host = self.proxy_host or (self.docker.offline_gateway() if network == "offline" else self.docker.agent_gateway())
        # A blocked prompt (Gemini promptFeedback.blockReason) ends the trial at once: the proxy refuses OpenCode's
        # retries and the container is stopped, instead of looping until the agent timeout.
        proxy = WireProxy(self.project, wire_path, self.token, host=host, upstream_host=self.upstream_host,
                          patch=spec.patch, patch_id=spec.patch_id,
                          on_provider_blocked=lambda info: self.docker.kill(f"obench-reflect-{spec.trial_id}"))
        import time as _time
        load_before, t0 = _load(), _time.monotonic()
        agent_started_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        try:
            args = self.docker_args(spec, task, workspace, model, proxy.base_url, instruction, network)
            code, timed_out = self.docker.run_agent(args, events_path, task["agent_timeout"],
                                                    stderr_path=trial_dir / "opencode-stderr.txt")
        finally:
            proxy.close()
        agent_seconds, load_after = round(_time.monotonic() - t0, 1), _load()
        # Everything the classification needs is on disk from here, so finish_trial can be rerun offline.
        (trial_dir / "cell.json").write_text(json.dumps({
            "image": task["image"], "image_source": task["image_source"], "image_record": image,
            "workdir": task["workdir"], "opencode_exit": code, "timed_out": timed_out, "agent_timeout": task["agent_timeout"],
            "agent_started_at": agent_started_at,
            "agent_network": network, "image_pin": task["image_pin"],
            "solution_needs_network": task["solution_needs_network"],
            "network_unflagged": task["solution_needs_network"] is None,
            "opencode_sha": self.pin["sha"], "code": self.code,
            "workers": self.run_context.get("workers"), "agent_seconds": agent_seconds,
            "workspace_seed": seed, "opencode_mount": "standalone" if self.standalone else "source_tree",
            "agent_permissions": AGENT_PERMISSIONS, "isolation": isolation,
            "smoke_compaction": vm.smoke_compaction_profile(self.smoke_compaction),
            "host_load": {"before": load_before, "after": load_after, "cpus": os.cpu_count()}}, sort_keys=True) + "\n")
        return self.record(spec, run_dir, self.finish_trial(spec, run_dir, task))

    def record(self, spec: TrialSpec, run_dir: Path, result: TrialResult) -> TrialResult:
        """The executor's own record of the outcome and covariates, independent of the runner: added to the
        trial's ``cell.json``, then summed over the cell's trials into ``<model>/<task>/cell_counters.json``."""
        with self._record_lock:
            return self._record(spec, run_dir, result)

    def _record(self, spec: TrialSpec, run_dir: Path, result: TrialResult) -> TrialResult:
        trial_dir = Path(run_dir) / spec.trial_dir
        path = trial_dir / "cell.json"
        cell = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        cell.update({"status": result.status, "passed": result.passed, "retried_4xx": result.retried_4xx or {},
                     "provider_blocked": result.provider_blocked,
                     "thinking_tokens_status": result.thinking_tokens_status, "code": cell.get("code") or self.code})
        path.write_text(json.dumps(cell, sort_keys=True) + "\n", encoding="utf-8")
        trials = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(trial_dir.parent.glob("*/cell.json"))]
        add = lambda key: {k: sum(int((t.get(key) or {}).get(k, 0)) for t in trials)
                           for k in sorted({k for t in trials for k in (t.get(key) or {})})}
        counters = {"task": spec.task, "model": spec.model, "patch_id": spec.patch_id, "trials": len(trials),
                    "workers": sorted({t.get("workers") for t in trials if t.get("workers") is not None}),
                    "status": {s: sum(1 for t in trials if t.get("status") == s) for s in sorted({str(t.get("status")) for t in trials})},
                    "retried_4xx": add("retried_4xx"), "thinking_tokens_status": add("thinking_tokens_status"),
                    "code_commits": sorted({str((t.get("code") or {}).get("commit")) for t in trials})}
        # Every tool call the proxy rebuilt from gpt-oss text, for the whole cell, regenerated from the trials' wire
        # records (so a rerun or reclassification never duplicates lines).
        repairs = []
        for wire_path in sorted(trial_dir.parent.glob("*/wire.jsonl")):
            for line in wire_path.read_text(encoding="utf-8").splitlines():
                rec = json.loads(line) if line.strip() else {}
                if (rec.get("route_repair") or {}).get("applied"):
                    repairs.append({"trial_id": wire_path.parent.name, "call_index": rec.get("call_index"),
                                    "route": rec.get("route"), **rec["route_repair"]})
        (trial_dir.parent / "route_repairs.jsonl").write_text(
            "".join(json.dumps(r, sort_keys=True) + "\n" for r in repairs), encoding="utf-8")
        counters["route_repairs"] = len(repairs)
        # A call to a tool we never offered is the model's error (OpenCode answers it via its invalid tool).
        counters["model_errors"] = {"unknown_tool": sum(1 for r in repairs if r.get("known_tool") is False)}
        (trial_dir.parent / "cell_counters.json").write_text(json.dumps(counters, indent=1, sort_keys=True) + "\n",
                                                             encoding="utf-8")
        return result

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
        cost, unpriced = wire_cost(wires)
        live_path = trial_dir / "last_vertex_request.json"
        live = json.loads(live_path.read_text(encoding="utf-8")) if live_path.is_file() else None
        fours = classify_4xx(wires)
        blocked = provider_blocked(wires)
        common = dict(cost_usd=cost, served_models=served, route_counts=counts, thinking_setting=thinking_setting,
                      retried_4xx=fours["retried"], image=image, wire=rel(wire_path),
                      cost_unpriced_calls=unpriced, last_vertex_request=last_vertex_request(wires, live),
                      signature_400s=signature_400_count(wires), side_kinds=side_kind_counts(wires),
                      stripped_side_thinking_blocks=stripped_side_thinking_total(wires),
                      thinking_block_binding=thinking_binding_seen(wires))
        if blocked is not None:  # the provider refused the prompt: neither pass nor fail
            (trial_dir / "provider_blocked.json").write_text(json.dumps(blocked, sort_keys=True) + "\n")
            return TrialResult(status="provider_blocked", passed=None, provider_blocked=blocked, **common,
                               error=f"provider blocked: {blocked.get('blockReason')}"
                                     + (" (inferred from empty responses)" if blocked.get("inferred") else ""))
        # Researcher ruling 2026-11-17: each trial classified on its own - blocked (last call) first, otherwise any
        # refusal / SAFETY stop makes it model_refused, before the infrastructure outcomes. The checker still runs.
        refused = model_refused(wires)
        # Signature-400 precedence (first match wins):
        # 1. side_thinking_signature — last call is a side signature 400 and the last step
        #    still has a tool call. Checked after the trace. A breaking main 4xx does not
        #    steal it; that 4xx is deferred until this check misses.
        # 2. post_compaction_signature — a breaking main-turn signature 400 follows a side
        #    call, and the last call is not a side signature 400. Outranks upstream_4xx
        #    and agent_exit_pending_tool.
        # 3. upstream_4xx — every other breaking main 4xx, including a main-turn signature
        #    400 with no earlier side call.
        # 4. agent_exit_pending_tool — exit 0 with a tool call still pending.
        post = post_compaction_detail(wires)
        deferred_breaking = False
        if fours["breaking"] and refused is None:
            if post is not None:
                (trial_dir / "post_compaction.json").write_text(json.dumps(post, sort_keys=True) + "\n")
                (trial_dir / "upstream_4xx.json").unlink(missing_ok=True)
                kind = f" after {post.get('prior_side_kind')}" if post.get("prior_side_kind") else ""
                return TrialResult(status="post_compaction_signature", passed=None,
                                   env_cause="vertex_thinking_signature", post_compaction=post, **common,
                                   error="main turn rejected after a side request: thinking block signature "
                                         "is bound to a different conversation" + kind)
            if terminating_side_signature(wires) is None:
                (trial_dir / "upstream_4xx.json").write_text(json.dumps(fours, sort_keys=True) + "\n")
                return TrialResult(status="upstream_4xx", passed=None, **common,
                                   error="upstream 4xx: " + ", ".join(f"call {c['call_index']} -> {c['status']}"
                                                                      for c in fours["breaking"]))
            deferred_breaking = True
        (trial_dir / "upstream_4xx.json").unlink(missing_ok=True)
        timeout_detail = None
        if timed_out and refused is None and not deferred_breaking:
            timeout_detail = self.timeout_detail(wires, cell.get("agent_started_at"),
                                                 cell.get("agent_timeout") or task["agent_timeout"])
            if not timeout_detail["still_working"]:  # no model call finished in the 5 min before the cap: infra
                return TrialResult(status="timeout", passed=None, timed_out=True, timeout_detail=timeout_detail,
                                   **common, error=f"agent timed out after {timeout_detail['cap_seconds']}s "
                                                   "with no model call in the last 5 minutes")
        # Still working at the cap: a task FAIL (Researcher ruling 2026-11-17). The checker and trace still run
        # (the checker exit is recorded), but the verdict is fail.
        # A deferred breaking 4xx already outranks a timeout (it used to return
        # upstream_4xx before this check). Keep that order unless the trace says
        # the trial actually died on the side signature 400.
        working_timeout = timed_out and refused is None and not deferred_breaking
        if run_checker:
            checker_exit, checker_mode, checker_out = self._check(task, workspace)
        else:
            checker_exit, checker_mode, checker_out = None, None, ""
            saved = trial_dir / "checker-output.txt"
            if saved.is_file():
                checker_out = saved.read_text(encoding="utf-8", errors="replace")
        common.update(parse_checker_runtime(checker_out))
        if refused is None and checker_mode == "container_not_launched" and checker_exit in (125, 126, 127):
            # Only a launch failure of the checker container itself (docker error 125, bash not invocable 126 / not
            # found 127, before the launch marker was printed) is checker_error. A command missing inside the task's
            # own checker or the agent's code is a real fail and stays in the denominator.
            return TrialResult(status="checker_error", passed=None, checker_exit=checker_exit, **common,
                               error=f"checker could not run ({checker_mode}, exit {checker_exit})")
        try:
            events = tr.parse_events(events_path.read_text(encoding="utf-8").splitlines())
            records = tr.build_trace(events, wires, run={"run_id": spec.run_id, "trial_id": spec.trial_id,
                                                          "task": spec.task, "model": spec.model, "patch_id": spec.patch_id},
                                     cost_fn=lambda rec: (vm.cost_usd(model, rec["usage"]), "reflection.vertex_models"),
                                     count_thinking_tokens=vm.THINKING_TOKENS_FROM_TEXT.get(model.key))
            side = tr.trace_side_counts(events, wires)
            tr.write_trace(trial_dir / "trace.jsonl", records)
        except tr.TraceError as exc:
            if refused is not None:
                return self._refused(trial_dir, refused, [], dict(common, checker_exit=checker_exit))
            if deferred_breaking:
                (trial_dir / "upstream_4xx.json").write_text(json.dumps(fours, sort_keys=True) + "\n")
                return TrialResult(status="upstream_4xx", passed=None, checker_exit=checker_exit, **common,
                                   error="upstream 4xx: " + ", ".join(f"call {c['call_index']} -> {c['status']}"
                                                                      for c in fours["breaking"]))
            # A trace/accounting problem (e.g. step_call_mismatch) is a logged warning only, never a status that
            # drops the trial: the checker's verdict stands (no trace is written for this trial).
            warning = f"{exc.code}: {exc}" if getattr(exc, "code", None) else str(exc)
            (trial_dir / "trace_warning.txt").write_text(warning + "\n", encoding="utf-8")
            passed = False if working_timeout else (checker_exit == 0 if checker_exit is not None else None)
            return TrialResult(status="completed", passed=passed, checker_exit=checker_exit, **common,
                               trace_warning=warning, timed_out=timed_out, timeout_detail=timeout_detail,
                               error=None if code in (0, None) else f"opencode exited {code}")
        thinking = [r["usage"]["thinking_tokens"] for r in records if isinstance(r["usage"]["thinking_tokens"], int)]
        per_step = [r["usage"]["thinking_tokens"] if isinstance(r["usage"]["thinking_tokens"], int) else None for r in records]
        flags = sorted({r["thinking"]["flag"] for r in records if r["thinking"].get("flag")})
        statuses = [r["usage"].get("thinking_tokens_status", "reported") for r in records]
        done = dict(common, checker_exit=checker_exit, steps=len(records), thinking_tokens=sum(thinking) if thinking else None,
                    thinking_tokens_status={k: statuses.count(k) for k in sorted(set(statuses))},
                    compaction_steps=side["compaction_steps"], summary_steps=side["summary_steps"],
                    synthetic_continue_messages=side["synthetic_continue_messages"],
                    compaction_thinking_tokens=side["compaction_thinking_tokens"],
                    trace_warnings=side["trace_warnings"],
                    thinking_flags=flags, thinking_tokens_per_step=per_step, trace=rel(trial_dir / "trace.jsonl"))
        if refused is not None:
            return self._refused(trial_dir, refused, records, done)
        if working_timeout:
            return TrialResult(status="completed", passed=False, timed_out=True, timeout_detail=timeout_detail, **done,
                               error=f"agent still working at the {timeout_detail['cap_seconds']}s cap (task fail)")
        last_finish = records[-1].get("finish_reason") if records else None
        signature = terminating_side_signature(wires)
        if signature and last_finish in ("tool-calls", "tool_calls", "tool_use"):
            # The last tool already finished. OpenCode died on a side request (title, summary, or compaction)
            # whose replayed thinking block was signed for the main conversation. Not a pending tool.
            info = dict(signature, last_finish=last_finish,
                        pending_tools=[c.get("name") for c in records[-1].get("tool_calls") or []],
                        opencode_exit=code)
            (trial_dir / "side_signature.json").write_text(json.dumps(info, sort_keys=True) + "\n")
            kind = f" ({info['side_kind']})" if info.get("side_kind") else ""
            return TrialResult(status="side_thinking_signature", passed=None, env_cause="vertex_thinking_signature",
                               side_signature=info, **done,
                               error="side request rejected: thinking block signature is bound to a different conversation"
                                     + kind)
        if deferred_breaking:  # side signature did not take the trial; the breaking main 4xx still did
            (trial_dir / "upstream_4xx.json").write_text(json.dumps(fours, sort_keys=True) + "\n")
            return TrialResult(status="upstream_4xx", passed=None, **done,
                               error="upstream 4xx: " + ", ".join(f"call {c['call_index']} -> {c['status']}"
                                                                  for c in fours["breaking"]))
        if last_finish in ("tool-calls", "tool_calls", "tool_use") and code in (0, None):
            # OpenCode exited 0 with a tool call pending: infrastructure, never a task fail. Usually `opencode run`
            # auto-rejecting a permission request; also an upstream stream reset mid-response.
            stderr = (trial_dir / "opencode-stderr.txt").read_text(encoding="utf-8", errors="replace") \
                if (trial_dir / "opencode-stderr.txt").exists() else ""
            abort = {"last_finish": last_finish, "pending_tools": [c.get("name") for c in records[-1].get("tool_calls") or []],
                     "permission_rejected": [{"permission": m.group(1), "patterns": m.group(2)}
                                             for m in PERMISSION_LINE.finditer(stderr)],
                     "stream_errors": [{"call_index": w.get("call_index"), "error": w["stream_error"]}
                                       for w in wires if w.get("stream_error")],
                     "opencode_exit": code}
            (trial_dir / "agent_exit.json").write_text(json.dumps(abort, sort_keys=True) + "\n")
            return TrialResult(status="agent_exit_pending_tool", passed=None, agent_exit=abort, **done,
                               error="OpenCode exited 0 with a tool call pending"
                                     + (f" (auto-rejected {', '.join(p['permission'] for p in abort['permission_rejected'])})"
                                        if abort["permission_rejected"] else "")
                                     + (" (upstream stream reset)" if abort["stream_errors"] else ""))
        if last_finish in ("tool-calls", "tool_calls", "tool_use"):  # OpenCode crashed mid-turn: infrastructure
            return TrialResult(status="error", passed=None, **done,
                               error=f"opencode exited {code} with a tool call pending")
        truncated = route_truncated(wires)
        if truncated is not None:
            (trial_dir / "route_truncated.json").write_text(json.dumps(truncated, sort_keys=True) + "\n")
            return TrialResult(status="route_truncated", passed=None, **done,
                               error=f"route_truncated: model call {truncated['call_index']} ended "
                                     f"{truncated['finish_reasons']} with no tool call and no text")
        return TrialResult(status="completed", passed=checker_exit == 0 if checker_exit is not None else None, **done,
                           error=None if code in (0, None) else f"opencode exited {code}")

    @staticmethod
    def timeout_detail(wires: list[dict], started_at: str | None, cap_seconds: int, window: int = 300) -> dict:
        """Was the agent still working when it hit the cap? Yes iff a model call (status 200) finished in the
        ``window`` seconds before the cap. The cap is the task's agent timeout (task.toml, else 1800 s)."""
        def when(stamp):
            return datetime.fromisoformat(stamp) if stamp else None
        ends = [when(w.get("ended_at") or w.get("ts")) for w in wires if w.get("status") == 200]
        ends = [e for e in ends if e is not None]
        start = when(started_at) or (min(when(w.get("ts")) for w in wires if w.get("ts")) if wires else None)
        if start is None or not ends:
            return {"cap_seconds": cap_seconds, "last_call_ended_before_cap_s": None, "still_working": False}
        before_cap = round(start.timestamp() + cap_seconds - max(ends).timestamp(), 1)
        return {"cap_seconds": cap_seconds, "last_call_ended_before_cap_s": before_cap,
                "still_working": before_cap <= window}

    @staticmethod
    def _refused(trial_dir: Path, refused: dict, records: list[dict], fields: dict) -> TrialResult:
        """``model_refused``, with the trace step each refused call became (``step``; None without a trace)."""
        steps = {(r.get("request") or {}).get("call_index"): r.get("step") for r in records}
        refusals = [dict(x, step=steps.get(x["call_index"])) for x in refused["refusals"]]
        info = dict(refused, refusals=refusals, step=refusals[0]["step"])
        (trial_dir / "model_refused.json").write_text(json.dumps(info, sort_keys=True) + "\n")
        return TrialResult(status="model_refused", passed=None, model_refused=info, **fields,
                           error=f"model refused ({info['stop_reason']}) at step {info['step']}")

    def _check(self, task: dict, workspace: Path) -> tuple[int, str, str]:
        """Run the task's checker; ``(exit, mode, output)``. Agent-written code never runs on the host:

        - ``self_containerized``: the checker itself ``docker run``s the task image on the workspace (TB2 and
          tb-mid imports); only its wrapper (reading the reward file) runs on the host.
        - ``in_task_container``: every other checker (the host-native openbench-tb-hard checkers, which run the
          agent's code, e.g. model-extraction's ``steal.py`` and filter-js's ``filter.py``) runs whole inside the
          task image, with the workspace at its WORKDIR and the task directory read-only at /openbench-task.
          The container first prints a launch marker; if it never appears, the mode is
          ``container_not_launched`` and exit 125/126/127 is ``checker_error``. Any exit after launch (including
          127 from a command missing in the agent's code) is the checker's verdict.
        """
        from obench.checker_timeout import checker_timeout_s

        script = (task["dir"] / "checker.sh").read_text(encoding="utf-8", errors="replace")
        timeout = checker_timeout_s(task["dir"].name, str(task["dir"]))
        if re.search(r"\bdocker\s+(run|create)\b", script):
            mode = "self_containerized"
            # Its containers run the agent's code: every `docker run` must be --network none (no metadata server).
            joined = re.sub(r"\\\n", " ", script)
            loose = [l.strip()[:120] for l in joined.splitlines()
                     if re.search(r"\bdocker\s+run\b", l) and not re.search(r"--network[ =]none\b", l)]
            if loose:
                raise CellError(f"{task['dir'].name}: checker runs containers with network access: {loose}")
            env = dict(os.environ, TASK_DIR=str(task["dir"]), BENCH_TASK_IMAGE=str(task["image"]))
            env.pop("OPENBENCH_SOLUTION_OVERLAY", None)
            try:
                proc = self.checker_runner(["bash", str(task["dir"] / "checker.sh")], cwd=str(workspace), env=env,
                                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=timeout)
                code, out = proc.returncode, proc.stdout or ""
            except subprocess.TimeoutExpired:
                code, out = 124, ""
        else:
            mode = "in_task_container"
            args = ["run", "--rm", "--name", f"obench-check-{workspace.parent.name}", "--platform", self.platform,
                    "--network", AGENT_NETWORK,  # verifier deps (uv / pytest installs); no metadata server
                    "-v", f"{workspace}:{task['workdir']}", "-v", f"{task['dir']}:/openbench-task:ro",
                    "-e", "TASK_DIR=/openbench-task", "-e", f"BENCH_TASK_IMAGE={task['image']}",
                    "-w", task["workdir"], task["image"],
                    "bash", "-c", f"echo {CHECKER_LAUNCHED}; exec bash /openbench-task/checker.sh"]
            code, out = self.docker.run_checker(args, timeout)
            if CHECKER_LAUNCHED in out:
                out = out.replace(CHECKER_LAUNCHED + "\n", "", 1)
            else:
                mode = "container_not_launched"
                out = f"[openbench] checker container did not launch (exit {code})\n" + out
        (workspace.parent / "checker-output.txt").write_text(out, encoding="utf-8")
        (workspace.parent / "checker-mode.txt").write_text(mode + "\n", encoding="utf-8")
        return code, mode, out
