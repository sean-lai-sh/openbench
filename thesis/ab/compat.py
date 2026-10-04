"""Per-binary permission flags and the Opus model route.

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
PROXY_MODEL_REF = "anthropic/claude-opus-5-5"
PROXY_MODEL_ID = "claude-opus-5-5"
PROXY_API_KEY = "proxy"

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
    vertex: dict | None = None
    harness: str = "opencode"
    proxy: dict | None = None


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


def sdk_base_url(proxy_url: str) -> str:
    base = proxy_url.rstrip("/")
    if base.endswith("/v1"):
        return base
    return base + "/v1"


def _needs_host_sdk(binary: str) -> bool:
    try:
        proc = subprocess.run(
            [binary, "install", "--help"],
            capture_output=True,
            text=True,
            timeout=10,
            stdin=subprocess.DEVNULL,
            env={**os.environ, "BUN_BE_BUN": "1"},
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    text = (proc.stdout or "") + (proc.stderr or "")
    return "opencode run" in text or "start opencode" in text


def anthropic_proxy_config(base_url: str, *, include_endpoint: bool) -> dict:
    provider = {
        "models": {
            PROXY_MODEL_ID: {
                "name": "Claude Opus 5.5",
                "limit": {"context": 1000000, "output": 128000},
            }
        }
    }
    if include_endpoint:
        provider["api"] = base_url
        provider["options"] = {"apiKey": PROXY_API_KEY, "baseURL": base_url}
    return {"provider": {"anthropic": provider}}


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


def _with_permission(config: dict, permission_ok: bool) -> dict:
    if not permission_ok:
        return config
    body = dict(config)
    body["permission"] = dict(_ALLOW_PERMISSIONS)
    return body


def _models_text(binary: str, root: Path, config: dict, extra_env: dict) -> str:
    env = _isolated_env(root, config or None)
    env.pop("ANTHROPIC_BASE_URL", None)
    env.update(extra_env)
    _code, text = _run(binary, ["models"], env, 40)
    return text


def _model_listed(text: str) -> bool:
    return PROXY_MODEL_REF in text and _marked_incompatible(text) is None


def _proxy_assessment(config: dict, permission_ok: bool, proxy_url: str, base_url_env: bool, how: str, needs_sdk: bool) -> Assessment:
    return Assessment(
        status="configured",
        reason=f"anthropic provider uses {how}",
        config=config,
        permission_config=permission_ok and "permission" in config,
        proxy={
            "model_ref": PROXY_MODEL_REF,
            "api_key": PROXY_API_KEY,
            "base_url": sdk_base_url(proxy_url),
            "base_url_env": base_url_env,
            "needs_sdk": needs_sdk,
        },
    )


def _assess_proxy(binary: str, permission_ok: bool, proxy_url: str) -> Assessment:
    if not proxy_url:
        return Assessment(
            status="incompatible",
            reason="proxy route has no base URL",
            config={},
            permission_config=False,
        )
    endpoint = sdk_base_url(proxy_url)
    needs_sdk = _needs_host_sdk(binary)
    full = _with_permission(anthropic_proxy_config(endpoint, include_endpoint=True), permission_ok)
    key_env = {"ANTHROPIC_API_KEY": PROXY_API_KEY}
    with tempfile.TemporaryDirectory(prefix="opencode-proxy-") as tmp:
        root = Path(tmp)
        first = _models_text(binary, root / "full", full, key_env)
        if _model_listed(first):
            return _proxy_assessment(full, permission_ok, proxy_url, False, "provider options", needs_sdk)
        models_only = _with_permission(
            anthropic_proxy_config(endpoint, include_endpoint=False), permission_ok,
        )
        second = _models_text(
            binary, root / "env", models_only,
            {**key_env, "ANTHROPIC_BASE_URL": endpoint},
        )
        if _model_listed(second):
            return _proxy_assessment(models_only, permission_ok, proxy_url, True, "ANTHROPIC_BASE_URL", needs_sdk)
    marker = _marked_incompatible(second) or _marked_incompatible(first) or "not listed"
    return Assessment(
        status="incompatible",
        reason=f"{marker} while loading {PROXY_MODEL_REF}",
        config={},
        permission_config=False,
    )


def assess(binary: str, *, route: str = "vertex", proxy_url: str = "") -> Assessment:
    """Decide whether this binary can run Claude Opus 5.5.

    ``route="proxy"`` lists models with the stock anthropic provider pointed at
    ``proxy_url``. ``route="vertex"`` probes the native Vertex id. A
    missing-credentials failure after the provider loads is compatible. A
    model-lookup or package-install failure is not.
    """
    flags = permission_args(help_text(binary))
    permission_ok = False if flags else permission_schema_accepts(binary)
    if route == "proxy":
        return _assess_proxy(binary, permission_ok, proxy_url)
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
