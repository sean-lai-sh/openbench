"""Hermes harness-comparison adapter (hard-suite arm beside Pi, OpenCode, Codex).

Runs the pinned Hermes agent (NousResearch/hermes-agent @ ``PIN``, MIT) with
model traffic pointed at the shared Vertex proxy. Hermes speaks Anthropic
Messages natively (``anthropic`` SDK), so no translator is needed: the cell
proxy is registered as a named custom provider with
``transport: anthropic_messages`` (``provider: anthropic`` would silently
replace a non-Anthropic base URL with api.anthropic.com). Tokens and cost are
metered from the per-cell proxy ledger, like the other arms.

Gating (same rule as the Codex arm): only ``OBENCH_HERMES_HARNESS=1`` plus
``OBENCH_VERTEX_PROXY_URL`` routes a cell here. Flag on without the URL fails
closed before any process starts; flag off is stock Hermes (``hermes.run``).

Benchmark config (each cell gets a fresh ``HERMES_HOME`` holding only
``config.yaml``; written as JSON, which is valid YAML):

* thinking: ``agent.reasoning_effort`` is left unset, so Hermes sends no
  ``thinking`` field (``thinking_sent=none``, matching OpenCode). Hermes's
  own "none" would send ``thinking: {type: between_tools}``.
* ``context_length`` = ``CONTEXT_LENGTH`` (1,000,000: Hermes's own default for
  claude-sonnet-5*, and Pi's models.json value). Pending the Researcher's call
  (1M for Pi/stock vs 200K for Codex AD-1). Set explicitly so Hermes does not
  probe non-model endpoints on the proxy.
* Title generation stays on (stock; AD1-hermes-side). It follows the main
  provider/model, is tagged ``side`` at the proxy, and is counted in traces.
* Stock ``hermes-cli`` toolset and stock prompt (SOUL.md, context files);
  no ``--ignore-rules``.
* Overrides (``BENCHMARK_OVERRIDES``): memory write-back off, approvals off,
  LSP off, model catalog / update checks / lazy installs off, curator and
  background review off, short gateway idle exit, onboarding profile build off.

Trace parity: ``turns`` = main-loop API calls + every auxiliary task's calls
(title included), from Hermes's ``--usage-file``. Every Hermes run starts a
background gateway daemon; the adapter stops it after the cell
(``hermes gateway stop``, then any process still carrying this cell's
``HERMES_HOME``) and removes the home.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

PIN = "4dcef215cfe41bd2d02c2d1dad6e257a18101216"
PIN_BRIEF = "4dcef215"
REPO = "https://github.com/NousResearch/hermes-agent"
LICENSE = "MIT"
NEAREST_TAGS = "533 commits after v0.22.5; ancestor of v0.22.6"

COMPARISON_MODELS = ("claude-opus-5-5", "claude-sonnet-5-5")
PROVIDER_NAME = "proxy"
TRANSPORT = "anthropic_messages"
WIRE_PATH = "/v1/messages"
PROXY_API_KEY = "openbench-vertex-proxy"
# Researcher decision pending: 1M (Hermes default for claude-sonnet-5*, Pi's
# models.json) vs 200K (Codex AD1-codex-ctx). Recorded per cell.
CONTEXT_LENGTH = 1_000_000
GATEWAY_IDLE_EXIT_S = 5
THINKING = "unset (no thinking field; OpenCode is the thinking reference)"

# Benchmark config overrides, each with the harness-comparison sheet row it
# belongs to (prereg/harness-components-2026-10-24.csv).
BENCHMARK_OVERRIDES = (
    ("memory.memory_enabled=false, memory.user_profile_enabled=false, memory.nudge_interval=0",
     14, "Memory files: write-back would leak across cells"),
    ("onboarding.profile_build=off", 14, "Memory files: no user-profile build"),
    ("skills.creation_nudge_interval=0", 14, "Memory files: no skill write-back nudges"),
    ("auxiliary.background_review.enabled=false", 14, "Memory files: background memory/skill review writes back"),
    ("curator.enabled=false", 14, "Memory files: curator consolidates memory/skills"),
    ("approvals.mode=off", 26, "Permission model: headless allow-all (rows 26-27; -z already auto-approves)"),
    ("lsp.enabled=false", 11, "Code search: LSP servers would auto-install over the network"),
    ("model_catalog.enabled=false", 6, "Provider routing: no catalog fetch from nousresearch.com"),
    ("updates.check=false", 32, "Headless CLI mode: no git update checks"),
    ("security.allow_lazy_installs=false", 32, "Headless CLI mode: no lazy PyPI/npm installs mid-cell"),
    (f"gateway.unmanaged_idle_exit_seconds={GATEWAY_IDLE_EXIT_S}", 32,
     "Headless CLI mode: the per-run gateway daemon exits right after the cell"),
    (f"providers.proxy.models.<model>.context_length={CONTEXT_LENGTH}", 13,
     "History compaction: explicit window (pending Researcher), no endpoint probes"),
)

_CELL_RE = re.compile(r"[A-Za-z0-9_.-]+")
_TRUTHY = {"1", "true", "yes", "on"}
_STRIPPED_ENV = (
    "ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN",
    "OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENROUTER_API_KEY", "NOUS_API_KEY",
    "HERMES_HOME", "HERMES_DUMP_REQUESTS",
    "OPENBENCH_PROXY_BASE_URL", "OPENBENCH_PROXY_CELL_TOKEN",
)


class PinError(Exception):
    pass


def comparison_requested() -> bool:
    """True only for ``OBENCH_HERMES_HARNESS=1`` (or true/yes/on)."""
    return os.environ.get("OBENCH_HERMES_HARNESS", "").strip().lower() in _TRUTHY


def cell_proxy_base(base_url: str, cell_id: str) -> str:
    """Cell proxy origin (no ``/v1``): the SDK appends ``/v1/messages``."""
    base = base_url.strip().rstrip("/")
    if base.endswith("/v1"):
        base = base[:-3]
    return f"{base}/c/{cell_id}"


def _sibling(module_name: str, filename: str):
    import importlib.util

    try:
        return __import__(f"obench.adapters.{module_name}", fromlist=["_"])
    except ImportError:
        pass
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), filename)
    for mod in list(sys.modules.values()):
        loaded = getattr(mod, "__file__", None)
        try:
            if loaded and os.path.abspath(loaded) == path:
                return mod
        except OSError:
            continue
    spec = importlib.util.spec_from_file_location(f"bench_adapter_{module_name}", path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[f"bench_adapter_{module_name}"] = module
    spec.loader.exec_module(module)
    return module


def rewrite_loopback(url: str) -> str:
    return _sibling("proxy_loopback", "proxy_loopback.py").origin_for_this_process(url.strip())


def benchmark_config(cell_base: str, model: str) -> dict:
    """The cell's ``config.yaml`` (JSON is valid YAML)."""
    return {
        "model": {"provider": f"custom:{PROVIDER_NAME}", "default": model},
        "providers": {PROVIDER_NAME: {
            "api": cell_base,
            "api_key": PROXY_API_KEY,
            "transport": TRANSPORT,
            "discover_models": False,
            "models": {model: {"context_length": CONTEXT_LENGTH}},
        }},
        "memory": {"memory_enabled": False, "user_profile_enabled": False, "nudge_interval": 0},
        "onboarding": {"profile_build": "off"},
        "skills": {"creation_nudge_interval": 0},
        "auxiliary": {"background_review": {"enabled": False}},
        "curator": {"enabled": False},
        "approvals": {"mode": "off"},
        "lsp": {"enabled": False},
        "model_catalog": {"enabled": False},
        "updates": {"check": False},
        "security": {"allow_lazy_installs": False},
        "gateway": {"unmanaged_idle_exit_seconds": GATEWAY_IDLE_EXIT_S},
    }


def build_command(binary: str, instruction: str, usage_file: str) -> list[str]:
    """One-shot headless run. Model and provider come from config.yaml (no
    ``-m``/``--provider``: they trigger a consent guard)."""
    return [binary, "-z", instruction, "--usage-file", usage_file]


def child_env(home: str) -> dict:
    env = dict(os.environ)
    for name in _STRIPPED_ENV:
        env.pop(name, None)
    env["HERMES_HOME"] = home
    return env


def pin_stamp_path(binary: str) -> str:
    explicit = os.environ.get("OBENCH_HERMES_PIN_FILE", "").strip()
    if explicit:
        return explicit
    root = os.environ.get("OBENCH_HERMES_ROOT", "").strip()
    if root:
        return os.path.join(root, "PIN")
    return binary + ".pin" if binary and os.path.isabs(binary) else ""


def require_pin(binary: str) -> str:
    """The install's pin stamp (written by data/hermes-harness-smoke/prep.sh)
    must equal ``PIN``. Hermes's own version string is a 0.0.0 placeholder."""
    if not binary:
        raise PinError("Hermes harness comparison needs OBENCH_HERMES_BIN pointing at the pinned hermes")
    path = pin_stamp_path(binary)
    if not path or not os.path.isfile(path):
        raise PinError(f"Hermes pin stamp is missing ({path or 'set OBENCH_HERMES_ROOT or OBENCH_HERMES_PIN_FILE'})")
    text = Path(path).read_text(encoding="utf-8").strip()
    if text != PIN:
        raise PinError(f"Hermes pin stamp is {text!r}; the comparison pin is {PIN}")
    return text


def parse_usage(path: str) -> dict:
    """Main and auxiliary API-call counts from Hermes's ``--usage-file``.

    ``api_calls`` counts main-loop calls; ``auxiliary.by_task`` maps each side
    task (title_generation, compression, ...) to its own counts. Field names
    are read defensively (``api_calls`` / ``calls`` / ``api_call_count``).
    """
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"present": False, "main_calls": None, "aux_calls": {}, "total_calls": None, "raw": None}
    if not isinstance(data, dict):
        return {"present": False, "main_calls": None, "aux_calls": {}, "total_calls": None, "raw": data}

    def count(obj):
        if not isinstance(obj, dict):
            return None
        for key in ("api_calls", "calls", "api_call_count", "requests"):
            value = obj.get(key)
            if isinstance(value, int) and not isinstance(value, bool):
                return value
        return None

    main = count(data)
    by_task = ((data.get("auxiliary") or {}).get("by_task") or {}) if isinstance(data.get("auxiliary"), dict) else {}
    aux = {}
    for task, info in (by_task.items() if isinstance(by_task, dict) else []):
        value = count(info)
        if value:
            aux[str(task)] = value
    total = None if main is None else main + sum(aux.values())
    return {"present": True, "main_calls": main, "aux_calls": aux, "total_calls": total, "raw": data}


def _proc_pids_with_home(home: str, proc_root: str = "/proc") -> list[int]:
    """PIDs whose environment carries ``HERMES_HOME=<home>`` (Linux)."""
    found = []
    marker = f"HERMES_HOME={home}".encode("utf-8")
    try:
        entries = os.listdir(proc_root)
    except OSError:
        return found
    for entry in entries:
        if not entry.isdigit() or int(entry) == os.getpid():
            continue
        try:
            with open(os.path.join(proc_root, entry, "environ"), "rb") as fh:
                environ = fh.read().split(b"\0")
        except OSError:
            continue
        if marker in environ:
            found.append(int(entry))
    return found


def stop_gateway(binary: str, home: str, runner=subprocess.run, find_pids=_proc_pids_with_home,
                 kill=os.kill, sleep=time.sleep) -> dict:
    """Stop the per-run gateway daemon: ``hermes gateway stop``, then signal
    any process still carrying this cell's ``HERMES_HOME``."""
    result = {"stop_command": None, "signalled": [], "survivors": []}
    try:
        proc = runner([binary, "gateway", "stop"], capture_output=True, text=True, timeout=20,
                      stdin=subprocess.DEVNULL, env=child_env(home))
        result["stop_command"] = proc.returncode
    except (OSError, subprocess.SubprocessError) as exc:
        result["stop_command"] = f"error: {type(exc).__name__}"
    pids = find_pids(home)
    for pid in pids:
        try:
            kill(pid, signal.SIGTERM)
            result["signalled"].append(pid)
        except OSError:
            pass
    if pids:
        sleep(2)
        for pid in find_pids(home):
            try:
                kill(pid, signal.SIGKILL)
                result["survivors"].append(pid)
            except OSError:
                pass
    return result


def _stem(cell_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", cell_id)


def totals_path(ledger_dir: str, cell_id: str) -> str:
    return os.path.join(ledger_dir, f"{_stem(cell_id)}.totals.json")


def settings_destination(cell_id: str, ledger_dir: str) -> str:
    override = os.environ.get("OBENCH_HERMES_SETTINGS_PATH", "").strip()
    if override:
        return override
    if ledger_dir and cell_id:
        return os.path.join(ledger_dir, f"{_stem(cell_id)}.settings.json")
    return ""


def load_proxy_totals(ledger_dir: str, cell_id: str) -> dict:
    """``all``/``main``/``side`` buckets from the proxy totals file."""
    keys = ("calls", "input_uncached", "output", "cache_read", "cache_write")
    with open(totals_path(ledger_dir, cell_id), encoding="utf-8") as fh:
        payload = json.load(fh)

    def bucket(name):
        raw = payload.get(name)
        if not isinstance(raw, dict):
            raise ValueError(f"proxy totals missing {name}")
        return {k: int(raw.get(k) or 0) for k in keys}

    all_bucket, main_bucket = bucket("all"), bucket("main")
    return {"all": all_bucket, "main": main_bucket,
            "side": {k: all_bucket[k] - main_bucket[k] for k in keys}}


def _observe_totals(ledger_dir: str, cell_id: str):
    if not ledger_dir:
        return None, "OBENCH_VERTEX_LEDGER_DIR is unset"
    path = totals_path(ledger_dir, cell_id)
    if not os.path.isfile(path):
        return None, f"proxy totals missing: {path}"
    try:
        return load_proxy_totals(ledger_dir, cell_id), None
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return None, str(exc)


def planned_settings(model: str, timeout_s: int, cell_base: str, binary: str) -> dict:
    return {
        "harness": "hermes",
        "pin": PIN,
        "repo": REPO,
        "license": LICENSE,
        "nearest_tags": NEAREST_TAGS,
        "binary": binary,
        "install_root": os.environ.get("OBENCH_HERMES_ROOT", ""),
        "model": model,
        "provider": f"custom:{PROVIDER_NAME}",
        "wire": {"transport": TRANSPORT, "path": WIRE_PATH, "base_url": cell_base},
        "context_length": CONTEXT_LENGTH,
        "context_length_status": "pending Researcher decision (1M Pi/stock vs 200K Codex AD-1)",
        "thinking": THINKING,
        "title_generation": "on (stock; tagged side at the proxy; counted in traces)",
        "toolset": "stock hermes-cli",
        "rules": "stock (SOUL.md, context files); --ignore-rules not used",
        "benchmark_overrides": [
            {"setting": setting, "sheet_row": row, "why": why} for setting, row, why in BENCHMARK_OVERRIDES
        ],
        "trace_source": "--usage-file: api_calls + auxiliary.by_task calls",
        "timeout_s": timeout_s,
    }


def _write_json(path: str, payload: dict) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, path)


def _empty_usage() -> dict:
    return {
        "tokens_input_uncached": None, "tokens_cache_read": None, "tokens_cache_write": None,
        "tokens_output": None, "tokens_reasoning": None, "token_basis": None,
    }


def _fail(message: str) -> dict:
    return {
        "completed": False,
        "error": message,
        "output_tail": "",
        "full_output": "",
        "tokens": None,
        "turns": None,
        "cmd": None,
        **_empty_usage(),
    }


def run(instruction: str, workdir: str, model: str, timeout_s: int, runner=subprocess.run,
        gateway_stopper=stop_gateway) -> dict:
    if model not in COMPARISON_MODELS:
        return _fail(f"Hermes harness comparison does not run model {model!r}")
    if not comparison_requested():
        return _fail("Hermes harness comparison needs OBENCH_HERMES_HARNESS=1")
    proxy = os.environ.get("OBENCH_VERTEX_PROXY_URL", "").strip()
    if not proxy:
        # Fail closed: no hermes process, no gateway, no model call.
        return _fail("Hermes harness comparison: OBENCH_HERMES_HARNESS=1 is set but "
                     "OBENCH_VERTEX_PROXY_URL (the proxy address) is missing")
    cell_id = os.environ.get("OBENCH_VERTEX_CELL_ID", "").strip()
    ledger_dir = os.environ.get("OBENCH_VERTEX_LEDGER_DIR", "").strip()
    if not _CELL_RE.fullmatch(cell_id or ""):
        return _fail("Hermes harness comparison needs OBENCH_VERTEX_CELL_ID "
                     "(letters, digits, dot, underscore, hyphen)")
    binary = os.environ.get("OBENCH_HERMES_BIN", "").strip()
    try:
        require_pin(binary)
    except PinError as exc:
        return _fail(str(exc))

    cell_base = cell_proxy_base(rewrite_loopback(proxy), cell_id)
    home = tempfile.mkdtemp(prefix="hermes_harness_home_")
    usage_file = os.path.join(home, "usage.json")
    gateway = None
    usage = {"present": False, "main_calls": None, "aux_calls": {}, "total_calls": None, "raw": None}
    timed_out = False
    try:
        with open(os.path.join(home, "config.yaml"), "w", encoding="utf-8") as fh:
            json.dump(benchmark_config(cell_base, model), fh, indent=2, sort_keys=True)
            fh.write("\n")
        cmd = build_command(binary, instruction, usage_file)
        try:
            proc = runner(cmd, cwd=workdir, capture_output=True, text=True, timeout=timeout_s,
                          stdin=subprocess.DEVNULL, env=child_env(home))
            stdout, stderr, returncode = proc.stdout or "", proc.stderr or "", proc.returncode
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            stdout = exc.stdout if isinstance(exc.stdout, str) else (exc.stdout or b"").decode("utf-8", "replace")
            stderr = exc.stderr if isinstance(exc.stderr, str) else (exc.stderr or b"").decode("utf-8", "replace")
            returncode = None
        usage = parse_usage(usage_file)
    finally:
        try:
            gateway = gateway_stopper(binary, home)
        finally:
            shutil.rmtree(home, ignore_errors=True)

    combined = (stdout or "") + (stderr or "")
    totals, totals_error = _observe_totals(ledger_dir, cell_id)
    settings = planned_settings(model, timeout_s, cell_base, binary)
    settings.update({
        "turns": usage["total_calls"],
        "main_calls": usage["main_calls"],
        "aux_calls": usage["aux_calls"],
        "usage_file_present": usage["present"],
        "gateway_stop": gateway,
        "proxy_totals": totals,
        "proxy_totals_error": totals_error,
        "side_calls": None if totals is None else totals["side"]["calls"],
    })
    destination = settings_destination(cell_id, ledger_dir)
    if destination:
        _write_json(destination, settings)
    result = {
        "completed": (not timed_out) and returncode == 0,
        "error": (f"timeout after {timeout_s}s" if timed_out
                  else None if returncode == 0 else f"exit {returncode}"),
        "output_tail": combined[-2000:],
        "full_output": combined,
        "tokens": None,
        "turns": usage["total_calls"],
        "cmd": cmd,
        "context_length": CONTEXT_LENGTH,
        "harness_pin": PIN,
        "harness_settings": settings,
        **_empty_usage(),
        "main_calls": usage["main_calls"],
        "aux_calls": usage["aux_calls"],
        **({"usage_raw": usage["raw"]} if usage["raw"] is not None else {}),
    }
    if timed_out:
        result["failure_class"] = "timeout"
    return result
