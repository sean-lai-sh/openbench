"""Per-binary permission flags and Vertex model support.

Old OpenCode builds do not share one non-interactive flag. ``--auto`` is the
recent flag. ``--dangerously-skip-permissions`` is the one before it. Builds
with neither flag get an allow-all ``opencode.json`` when their config schema
accepts a ``permission`` key. A schema that rejects the key (the July 2025
tree is ``.strict()`` and has no such key) is left alone, and a run that still
stops on a prompt fails in the adapter instead of waiting out the task timeout.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from obench.adapters.opencode import _ALLOW_PERMISSIONS, _flag_present

MODEL_ID = "google-vertex-anthropic/claude-opus-5-5@default"
PROVIDER_ID = "google-vertex-anthropic"
NPM_SPEC = "@ai-sdk/google-vertex/anthropic"

_INCOMPATIBLE_MARKERS = (
    "ProviderModelNotFoundError",
    "ProviderInitError",
    "BunInstallFailedError",
    "ModelNotFoundError",
    "Unrecognized key",
    "ConfigInvalidError",
)


@dataclass(frozen=True)
class Assessment:
    status: str  # native, configured, incompatible
    reason: str
    config: dict
    permission_config: bool


def help_text(binary: str, timeout_s: int = 15) -> str:
    try:
        proc = subprocess.run(
            [binary, "run", "--help"],
            capture_output=True, text=True, timeout=timeout_s,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"{exc}"
    return ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()


def permission_args(help_text_value: str) -> list[str]:
    if _flag_present(help_text_value, "--auto"):
        return ["--auto"]
    if _flag_present(help_text_value, "--dangerously-skip-permissions"):
        return ["--dangerously-skip-permissions"]
    return []


def vertex_provider_config() -> dict:
    return {
        "provider": {
            PROVIDER_ID: {
                "npm": NPM_SPEC,
                "name": "Vertex (Anthropic)",
                "models": {
                    "claude-opus-5-5@default": {
                        "name": "Claude Opus 5.5",
                        "limit": {"context": 1000000, "output": 128000},
                    }
                },
            }
        }
    }


def _isolated_env(root: Path, extra: dict | None = None) -> dict:
    env = dict(os.environ)
    for name in (
        "GOOGLE_APPLICATION_CREDENTIALS",
        "GOOGLE_CLOUD_PROJECT",
        "GCLOUD_PROJECT",
        "GCP_PROJECT",
        "VERTEX_LOCATION",
        "GOOGLE_CLOUD_LOCATION",
        "OPENCODE_CONFIG",
        "OPENCODE_CONFIG_DIR",
        "OPENCODE_CONFIG_CONTENT",
    ):
        env.pop(name, None)
    home = root / "home"
    config = root / "config"
    data = root / "data"
    state = root / "state"
    cache = root / "cache"
    for path in (home, config / "opencode", data, state, cache):
        path.mkdir(parents=True, exist_ok=True)
    env["HOME"] = str(home)
    env["XDG_CONFIG_HOME"] = str(config)
    env["XDG_DATA_HOME"] = str(data)
    env["XDG_STATE_HOME"] = str(state)
    env["XDG_CACHE_HOME"] = str(cache)
    if extra is not None:
        text = json.dumps(extra)
        for name in ("opencode.json", "config.json"):
            (config / "opencode" / name).write_text(text, encoding="utf-8")
        env["OPENCODE_CONFIG"] = str(config / "opencode" / "opencode.json")
    return env


def _run(binary: str, args: list[str], env: dict, timeout_s: int) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            [binary, *args],
            capture_output=True, text=True, timeout=timeout_s,
            stdin=subprocess.DEVNULL, env=env,
        )
    except subprocess.TimeoutExpired as exc:
        out = ""
        if exc.stdout:
            out += exc.stdout if isinstance(exc.stdout, str) else exc.stdout.decode("utf-8", "replace")
        if exc.stderr:
            out += exc.stderr if isinstance(exc.stderr, str) else exc.stderr.decode("utf-8", "replace")
        return 124, out
    except OSError as exc:
        return 127, str(exc)
    return proc.returncode, ((proc.stdout or "") + "\n" + (proc.stderr or ""))


def permission_schema_accepts(binary: str) -> bool:
    """True when a permission object does not fail config load."""
    with tempfile.TemporaryDirectory(prefix="opencode-perm-") as tmp:
        env = _isolated_env(Path(tmp), {"permission": dict(_ALLOW_PERMISSIONS)})
        code, text = _run(binary, ["models", "--print-logs"], env, 20)
    if "Unrecognized key" in text and "permission" in text:
        return False
    if "ConfigInvalidError" in text and "permission" in text:
        return False
    return code != 127


def _marked_incompatible(text: str) -> str | None:
    for marker in _INCOMPATIBLE_MARKERS:
        if marker in text:
            return marker
    return None


def assess(binary: str) -> Assessment:
    """Decide whether this binary can target the Vertex Opus model.

    Credentials are stripped for the probe. A missing-credentials failure after
    the provider loads is compatible. A model-lookup or package-install failure
    is not, and it happens before a Vertex request on the builds we checked.
    """
    flags = permission_args(help_text(binary))
    permission_ok = False if flags else permission_schema_accepts(binary)
    with tempfile.TemporaryDirectory(prefix="opencode-assess-") as tmp:
        root = Path(tmp)
        bare_env = _isolated_env(root / "bare")
        _code, listed = _run(binary, ["models"], bare_env, 30)
        native = MODEL_ID in listed
        config = {} if native else vertex_provider_config()
        if permission_ok:
            config = dict(config)
            config["permission"] = dict(_ALLOW_PERMISSIONS)
        probe_env = _isolated_env(root / "probe", config or None)
        _code, ran = _run(
            binary,
            ["run", "--print-logs", "-m", MODEL_ID, "ping"],
            probe_env,
            25,
        )
    marker = _marked_incompatible(ran)
    if marker:
        return Assessment(
            status="incompatible",
            reason=f"{marker} while loading {MODEL_ID}",
            config={},
            permission_config=False,
        )
    if native:
        return Assessment(
            status="native",
            reason=f"{MODEL_ID} is listed and the probe did not reject it",
            config={"permission": dict(_ALLOW_PERMISSIONS)} if permission_ok else {},
            permission_config=permission_ok,
        )
    return Assessment(
        status="configured",
        reason=f"provider config supplied {MODEL_ID}",
        config=config,
        permission_config=permission_ok,
    )
