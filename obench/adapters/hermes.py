"""Adapter for the Hermes agent CLI (NousResearch/hermes-agent).

Stock path: ``hermes -z <instruction> --usage-file <tmp>`` in the workdir with
the operator's own Hermes home and provider config. It is never routed
through the Vertex proxy.

Hard-suite comparison arm: ``hermes_harness.py``. A cell on a Claude model id
goes there only when ``OBENCH_HERMES_HARNESS=1`` is set; that path also needs
``OBENCH_VERTEX_PROXY_URL`` and fails closed without it. With the flag off,
even a set proxy URL leaves the cell on the stock path.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile

NAME = "hermes"
_EXE = "hermes"
_COMPARISON_MODELS = ("claude-opus-5-5", "claude-sonnet-5-5")


def _comparison_env_set() -> bool:
    return os.environ.get("OBENCH_HERMES_HARNESS", "").strip().lower() in {"1", "true", "yes", "on"}


def _load_comparison_harness():
    try:
        from obench.adapters import hermes_harness
        return hermes_harness
    except ImportError:
        import importlib.util
        import sys

        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hermes_harness.py")
        module = sys.modules.get("hermes_harness")
        loaded = getattr(module, "__file__", None) if module is not None else None
        if loaded and os.path.abspath(loaded) == path:
            return module
        spec = importlib.util.spec_from_file_location("hermes_harness", path)
        module = importlib.util.module_from_spec(spec)
        sys.modules["hermes_harness"] = module
        spec.loader.exec_module(module)
        return module


def version():
    binary = os.environ.get("OBENCH_HERMES_BIN", "").strip() or shutil.which(_EXE)
    if not binary:
        return None
    try:
        proc = subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=30,
                              stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return None
    text = ((proc.stdout or "") + (proc.stderr or "")).strip()
    return text.splitlines()[0] if text else None


def _empty_token_usage():
    return {
        "tokens_input_uncached": None, "tokens_cache_read": None, "tokens_cache_write": None,
        "tokens_output": None, "tokens_reasoning": None, "token_basis": None,
    }


def run(instruction: str, workdir: str, model: str, timeout_s: int) -> dict:
    if model in _COMPARISON_MODELS and _comparison_env_set():
        return _load_comparison_harness().run(instruction, workdir, model, timeout_s)
    binary = shutil.which(_EXE)
    if not binary:
        return {"completed": False, "error": "SETUP-NEEDED: hermes is not on PATH", "output_tail": "",
                "full_output": "", "tokens": None, "turns": None, "cmd": None, **_empty_token_usage()}
    scratch = tempfile.mkdtemp(prefix="hermes_stock_")
    usage_file = os.path.join(scratch, "usage.json")
    cmd = [binary, "-z", instruction, "--usage-file", usage_file]
    try:
        try:
            proc = subprocess.run(cmd, cwd=workdir, capture_output=True, text=True, timeout=timeout_s,
                                  stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            return {"completed": False, "error": f"timeout after {timeout_s}s", "failure_class": "timeout",
                    "output_tail": "", "full_output": "", "tokens": None, "turns": None, "cmd": cmd,
                    **_empty_token_usage()}
        try:
            usage = json.loads(open(usage_file, encoding="utf-8").read())
        except (OSError, json.JSONDecodeError):
            usage = None
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    combined = (proc.stdout or "") + (proc.stderr or "")
    calls = usage.get("api_calls") if isinstance(usage, dict) else None
    return {
        "completed": proc.returncode == 0,
        "error": None if proc.returncode == 0 else f"exit {proc.returncode}",
        "output_tail": combined[-2000:],
        "full_output": combined,
        "tokens": None,
        "turns": calls if isinstance(calls, int) else None,
        "cmd": cmd,
        **_empty_token_usage(),
        **({"usage_raw": usage} if usage is not None else {}),
    }
