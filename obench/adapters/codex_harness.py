"""Codex CLI harness-comparison adapter (hard-suite arm beside Pi and OpenCode).

Runs the pinned ``codex`` CLI on its shipped defaults with model traffic
pointed at the shared Vertex proxy, exactly like the Pi and OpenCode
comparison arms. Codex speaks only the OpenAI Responses API, so it is wired
as a custom model provider with ``wire_api = "responses"`` whose
``base_url`` is the cell proxy plus ``/v1``; Codex posts to
``${base_url}/responses`` and the proxy translates that to Anthropic Messages
on Vertex (``thesis/ab/responses_api.py``). Tokens and cost are metered from
the upstream Anthropic usage in the per-cell proxy ledger, the same source
the other two arms use.

Stage 4 AD-1 fixes (briefs/stage4-slot-contract-AD1-note-2026-10-26.md):

* AD1-codex-ctx: Codex has no model metadata for a Claude id and falls back
  to a 272k context window, so auto-compaction (90%) would fire after
  Claude's real limit. ``model_context_window = 200000`` is set.
* AD1-codex-edit (no change): stock Codex on Claude registers no
  ``apply_patch`` tool; edits go through the shell. Nothing is added.
* Thinking: none. The same fallback metadata sets
  ``supports_reasoning_summaries: false`` (models-manager/src/model_info.rs),
  so stock Codex sends no ``reasoning`` for a Claude id and Claude gets no
  thinking config. That matches the OpenCode arm, the Researcher's thinking
  reference (#196: ``thinking_sent=none`` on Sonnet 5.5), so nothing is
  overridden; the proxy also ignores ``reasoning`` on this path.

Trace parity with Pi: ``turns`` (the harness's own model-call count, which
``attach_proxy_trace`` compares with the proxy ledger) is the number of
model responses in Codex's session rollout (``token_count`` events with new
usage), read from the isolated ``CODEX_HOME`` before it is removed. Codex's
``--json`` stream only has one ``turn.completed`` per ``exec``; that count is
kept as ``codex_turn_events``.

Codex is pinned to ``PIN``; the binary's ``--version`` must report it or the
cell fails closed before any model call. ``CODEX_HOME`` is a fresh empty
directory: no auth, config, AGENTS.md, skills, MCP, rules or memories from
the machine owner. The custom provider needs no OpenAI credentials; its
``env_key`` carries a placeholder the proxy ignores.

Selected only by ``OBENCH_CODEX_HARNESS=1`` on a comparison model;
``codex.run`` dispatches here. ``OBENCH_VERTEX_PROXY_URL`` on its own never
selects this path (a Pi run may export it); it is read as the proxy address
only after the flag is set, and a flagged cell without it fails closed. ``thesis`` is not imported:
docker cells mount only ``obench/adapters``.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

PIN = "0.144.5"
PACKAGE = "@openai/codex"
RELEASE_TAG = "rust-v0.144.5"
REPO = "https://github.com/openai/codex"
LICENSE = "Apache-2.0"

COMPARISON_MODELS = ("claude-opus-5-5", "claude-sonnet-5-5")
PROVIDER_ID = "obench_vertex"
PROVIDER_NAME = "OpenBench Vertex proxy"
WIRE_API = "responses"
WIRE_PATH = "/v1/responses"
PROXY_KEY_ENV = "OBENCH_CODEX_PROXY_KEY"
PROXY_KEY_VALUE = "openbench-vertex-proxy"
CONTEXT_WINDOW = 200_000  # AD1-codex-ctx
REASONING_EFFORT = "medium"
ADAPTER_FIXES = ("AD1-codex-ctx",)
THINKING_REFERENCE = "opencode"  # Researcher ruling: Codex on Claude sends no thinking
# Shipped defaults for an unknown (Claude) model id at PIN. Not passed on
# the command line; recorded in the settings sidecar.
MODEL_INFO = "fallback"
EDIT_PATH = "shell (no apply_patch for a non-OpenAI model id)"
OUTPUT_TRUNCATION_BYTES = 10_000
AUTO_COMPACT_FRACTION = 0.9

_CELL_RE = re.compile(r"[A-Za-z0-9_.-]+")
_TOTAL_KEYS = ("calls", "input_uncached", "output", "cache_read", "cache_write")
_TRUTHY = {"1", "true", "yes", "on"}
_STRIPPED_ENV = (
    "OPENAI_API_KEY", "OPENAI_BASE_URL", "CODEX_API_KEY", "CODEX_HOME",
    "OPENBENCH_PROXY_BASE_URL", "OPENBENCH_PROXY_CELL_TOKEN",
)


class PinError(Exception):
    pass


def comparison_requested() -> bool:
    """True only for ``OBENCH_CODEX_HARNESS=1`` (or true/yes/on)."""
    flag = os.environ.get("OBENCH_CODEX_HARNESS", "").strip().lower()
    return flag in _TRUTHY


def cell_proxy_base(base_url: str, cell_id: str) -> str:
    """Cell proxy origin (no ``/v1``), as for the Pi arm."""
    base = base_url.strip().rstrip("/")
    if base.endswith("/v1"):
        base = base[:-3]
    return f"{base}/c/{cell_id}"


def provider_base_url(cell_base: str) -> str:
    """Codex ``base_url``: Codex appends ``/responses`` to it."""
    return cell_base.rstrip("/") + "/v1"


def _sibling(module_name: str, filename: str):
    """Load a sibling adapter file (docker cells have no ``obench`` package)."""
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
    """Host loopback proxy -> the bridge origin inside a docker cell."""
    return _sibling("proxy_loopback", "proxy_loopback.py").origin_for_this_process(url.strip())


def _codex_module():
    return _sibling("codex", "codex.py")


def provider_config(cell_base: str) -> list[str]:
    """``-c`` overrides that point Codex at the cell proxy."""
    prefix = f"model_providers.{PROVIDER_ID}"
    return [
        "-c", f'{prefix}.name="{PROVIDER_NAME}"',
        "-c", f'{prefix}.base_url="{provider_base_url(cell_base)}"',
        "-c", f'{prefix}.wire_api="{WIRE_API}"',
        "-c", f'{prefix}.env_key="{PROXY_KEY_ENV}"',
        "-c", f'model_provider="{PROVIDER_ID}"',
    ]


def build_command(binary: str, instruction: str, model: str, workdir: str, cell_base: str,
                  *, in_container: bool, feature_flags: list[str] | None = None) -> list[str]:
    """Headless argv. Shipped tools and prompt stay in place."""
    sandbox = (
        ["--dangerously-bypass-approvals-and-sandbox"]
        if in_container
        else ["-s", "workspace-write"]
    )
    flags = list(feature_flags) if feature_flags is not None else [
        "--disable", "apps", "--disable", "plugins", "--disable", "multi_agent",
    ]
    return [
        binary, "exec", "--json",
        *flags,
        "--skip-git-repo-check",
        "-C", workdir,
        *sandbox,
        *provider_config(cell_base),
        "-c", f"model_context_window={CONTEXT_WINDOW}",
        "-c", f'model_reasoning_effort="{REASONING_EFFORT}"',
        "-m", model,
        instruction,
    ]


def child_env(codex_home: str) -> dict:
    env = dict(os.environ)
    for name in _STRIPPED_ENV:
        env.pop(name, None)
    env["CODEX_HOME"] = codex_home
    env[PROXY_KEY_ENV] = PROXY_KEY_VALUE
    return env


def parse_version(text: str) -> str | None:
    match = re.search(r"(\d+\.\d+\.\d+(?:-[0-9A-Za-z.]+)?)", text or "")
    return match.group(1) if match else None


def require_pin(binary: str, runner=subprocess.run) -> str:
    """The binary's version, which must equal ``PIN``."""
    if not binary:
        raise PinError("Codex harness comparison needs OBENCH_CODEX_BIN pointing at the pinned codex")
    try:
        proc = runner([binary, "--version"], capture_output=True, text=True, timeout=30,
                      stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as exc:
        raise PinError(f"cannot run {binary} --version: {exc}") from exc
    found = parse_version((proc.stdout or "") + (proc.stderr or ""))
    if found != PIN:
        raise PinError(f"codex reports {found!r}; the comparison pin is {PIN}")
    return found


def rollout_model_calls(codex_home: str) -> list[dict]:
    """Per-model-response usage from Codex's session rollout(s).

    Each model response is persisted as ``{"type": "event_msg", "payload":
    {"type": "token_count", "info": {"total_token_usage", "last_token_usage",
    ...}}}``. Events with no ``info`` (rate-limit only) and repeats of an
    unchanged total are not new calls. Returns the ``last_token_usage`` of
    each call, in order.
    """
    calls: list[dict] = []
    root = os.path.join(codex_home, "sessions")
    paths = []
    for dirpath, _dirs, files in os.walk(root):
        paths.extend(os.path.join(dirpath, name) for name in files
                     if name.startswith("rollout-") and name.endswith(".jsonl"))
    for path in sorted(paths):
        last_total = None
        try:
            with open(path, encoding="utf-8") as fh:
                lines = fh.readlines()
        except OSError:
            continue
        for line in lines:
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            payload = obj.get("payload") if isinstance(obj, dict) else None
            if obj.get("type") != "event_msg" or not isinstance(payload, dict):
                continue
            if payload.get("type") != "token_count":
                continue
            info = payload.get("info")
            if not isinstance(info, dict) or not isinstance(info.get("last_token_usage"), dict):
                continue
            total = json.dumps(info.get("total_token_usage"), sort_keys=True)
            if total == last_total:
                continue
            last_total = total
            calls.append(info["last_token_usage"])
    return calls


def _stem(cell_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", cell_id)


def totals_path(ledger_dir: str, cell_id: str) -> str:
    return os.path.join(ledger_dir, f"{_stem(cell_id)}.totals.json")


def settings_destination(cell_id: str, ledger_dir: str) -> str:
    override = os.environ.get("OBENCH_CODEX_SETTINGS_PATH", "").strip()
    if override:
        return override
    if ledger_dir and cell_id:
        return os.path.join(ledger_dir, f"{_stem(cell_id)}.settings.json")
    return ""


def _as_int(value, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{label} must be a non-negative int")
    return value


def load_proxy_totals(ledger_dir: str, cell_id: str) -> dict:
    """``all``/``main``/``side`` buckets from the proxy totals file (as Pi)."""
    with open(totals_path(ledger_dir, cell_id), encoding="utf-8") as fh:
        payload = json.load(fh)
    if not isinstance(payload, dict):
        raise ValueError("proxy totals must be an object")

    def bucket(name: str) -> dict:
        raw = payload.get(name)
        if not isinstance(raw, dict):
            raise ValueError(f"proxy totals missing {name}")
        return {key: _as_int(raw.get(key), f"{name}.{key}") for key in _TOTAL_KEYS}

    all_bucket, main_bucket = bucket("all"), bucket("main")
    for key in _TOTAL_KEYS:
        if main_bucket[key] > all_bucket[key]:
            raise ValueError(f"main.{key} exceeds all.{key}")
    side = {key: all_bucket[key] - main_bucket[key] for key in _TOTAL_KEYS}
    return {"all": all_bucket, "main": main_bucket, "side": side}


def _observe_totals(ledger_dir: str, cell_id: str):
    if not ledger_dir:
        return None, "OBENCH_VERTEX_LEDGER_DIR is unset"
    if not os.path.isfile(totals_path(ledger_dir, cell_id)):
        return None, f"proxy totals missing: {totals_path(ledger_dir, cell_id)}"
    try:
        return load_proxy_totals(ledger_dir, cell_id), None
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return None, str(exc)


def planned_settings(model: str, timeout_s: int, cell_base: str, binary: str, version: str) -> dict:
    """Section-4 settings for one cell (the Codex column of the parts table)."""
    return {
        "harness": "codex",
        "pin": PIN,
        "version_reported": version,
        "package": PACKAGE,
        "release_tag": RELEASE_TAG,
        "repo": REPO,
        "license": LICENSE,
        "binary": binary,
        "model": model,
        "provider": PROVIDER_ID,
        "wire": {
            "api": WIRE_API,
            "path": WIRE_PATH,
            "base_url": provider_base_url(cell_base),
            "translated_by": "thesis/ab/responses_api.py",
        },
        "adapter_fixes": list(ADAPTER_FIXES),
        "model_info": MODEL_INFO,
        "model_context_window": CONTEXT_WINDOW,
        "auto_compact_at_tokens": int(CONTEXT_WINDOW * AUTO_COMPACT_FRACTION),
        "reasoning_effort": REASONING_EFFORT,
        "thinking": "none (stock fallback metadata; OpenCode is the thinking reference)",
        "trace_source": "CODEX_HOME/sessions rollout token_count events (one per model response)",
        "edit_path": EDIT_PATH,
        "output_truncation_bytes": OUTPUT_TRUNCATION_BYTES,
        "features_disabled": ["apps", "plugins", "multi_agent"],
        "codex_home": "fresh empty dir (no auth, config, AGENTS.md, skills, MCP)",
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
    try:
        return _codex_module()._empty_token_usage()
    except Exception:  # noqa: BLE001 - setup failures must still return a result
        return {}


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


def run(instruction: str, workdir: str, model: str, timeout_s: int, runner=subprocess.run) -> dict:
    if model not in COMPARISON_MODELS:
        return _fail(f"Codex harness comparison does not run model {model!r}")
    if not comparison_requested():
        return _fail("Codex harness comparison needs OBENCH_CODEX_HARNESS=1")
    proxy = os.environ.get("OBENCH_VERTEX_PROXY_URL", "").strip()
    cell_id = os.environ.get("OBENCH_VERTEX_CELL_ID", "").strip()
    ledger_dir = os.environ.get("OBENCH_VERTEX_LEDGER_DIR", "").strip()
    if not proxy:
        return _fail("Codex harness comparison: OBENCH_CODEX_HARNESS=1 is set but "
                     "OBENCH_VERTEX_PROXY_URL (the proxy address) is missing")
    if not _CELL_RE.fullmatch(cell_id or ""):
        return _fail("Codex harness comparison needs OBENCH_VERTEX_CELL_ID "
                     "(letters, digits, dot, underscore, hyphen)")
    binary = os.environ.get("OBENCH_CODEX_BIN", "").strip()
    try:
        version = require_pin(binary, runner=runner)
    except PinError as exc:
        return _fail(str(exc))

    cell_base = cell_proxy_base(rewrite_loopback(proxy), cell_id)
    codex = _codex_module()
    try:
        feature_flags = codex._feature_flags()
    except Exception:  # noqa: BLE001 - fall back to the shipped default flags
        feature_flags = None
    cmd = build_command(binary, instruction, model, workdir, cell_base,
                        in_container=bool(os.environ.get("BENCH_IN_CONTAINER")),
                        feature_flags=feature_flags)
    codex_home = tempfile.mkdtemp(prefix="codex_harness_home_")
    model_calls: list[dict] = []
    try:
        try:
            proc = runner(cmd, cwd=workdir, capture_output=True, text=True, timeout=timeout_s,
                          stdin=subprocess.DEVNULL, env=child_env(codex_home))
        except subprocess.TimeoutExpired as exc:
            out = exc.stdout if isinstance(exc.stdout, str) else (exc.stdout or b"").decode("utf-8", "replace")
            err = exc.stderr if isinstance(exc.stderr, str) else (exc.stderr or b"").decode("utf-8", "replace")
            combined = (out or "") + (err or "")
            calls = rollout_model_calls(codex_home)
            return {
                "completed": False,
                "error": f"timeout after {timeout_s}s",
                "failure_class": "timeout",
                "output_tail": combined[-2000:],
                "full_output": combined,
                "tokens": None,
                "turns": len(calls) if calls else None,
                "cmd": cmd,
                **_empty_usage(),
                "model_calls": len(calls),
                **({"usage_raw": calls} if calls else {}),
            }
        model_calls = rollout_model_calls(codex_home)
    finally:
        if not model_calls:
            model_calls = rollout_model_calls(codex_home)
        shutil.rmtree(codex_home, ignore_errors=True)

    stdout = proc.stdout or ""
    combined = stdout + (proc.stderr or "")
    try:
        tokens, turns, tail, token_usage = codex._parse_json_with_usage(stdout)
    except Exception:  # noqa: BLE001 - never let usage parsing break a run
        tokens, turns, tail, token_usage = None, None, "", _empty_usage()
    if not tail:
        tail = combined[-2000:]
    codex_turn_events = turns
    if model_calls:
        # Pi semantics: one trace entry per model call.
        turns = len(model_calls)
    totals, totals_error = _observe_totals(ledger_dir, cell_id)
    settings = planned_settings(model, timeout_s, cell_base, binary, version)
    settings["turns"] = turns
    settings["codex_turn_events"] = codex_turn_events
    settings["model_calls"] = len(model_calls)
    settings["proxy_totals"] = totals
    settings["proxy_totals_error"] = totals_error
    settings["side_calls"] = None if totals is None else totals["side"]["calls"]
    destination = settings_destination(cell_id, ledger_dir)
    if destination:
        _write_json(destination, settings)
    return {
        "completed": proc.returncode == 0,
        "error": None if proc.returncode == 0 else f"exit {proc.returncode}",
        "output_tail": tail,
        "full_output": combined,
        "tokens": tokens,
        "turns": turns,
        "cmd": cmd,
        "model_context_window": CONTEXT_WINDOW,
        "adapter_fixes": list(ADAPTER_FIXES),
        "harness_settings": settings,
        **token_usage,
        "codex_turn_events": codex_turn_events,
        "model_calls": len(model_calls),
        **({"usage_raw": model_calls} if model_calls else {}),
    }
