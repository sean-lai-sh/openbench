"""Adapter for the `opencode` CLI (ChatGPT-subscription OAuth route).

Headless invocation:
    OPENAI_API_KEY unset in child env
    opencode run --dir <workdir> -m openai/gpt-5.5 --variant medium \
        --auto --format json <instruction>

Notes / quirks:
- OPENAI_API_KEY MUST be stripped from the child env. If it is present,
  opencode uses the API-key provider instead of the stored subscription
  OAuth credential (~/.local/share/opencode/auth.json); stripping it forces
  the subscription route (verified).
- `--variant medium` selects the reasoning effort for the model.
- `--auto` auto-approves tool permissions so file edits happen unattended.
  opencode `run` is non-interactive, but write/edit permission is otherwise
  gated; --auto is required for the agent to modify files headlessly.
- `--dir` sets the working directory the agent operates in.
- `--format json` emits a JSONL event stream. Each ``step_finish`` event is one
  model round and carries ``part.tokens={input,output,reasoning,cache{...}}``.
  Token accounting (see ``_parse_json``):
    tokens_input_uncached/cache/output/reasoning are summed across
    ``step_finish`` records. opencode reports visible output and reasoning as
    separate fields, so tokens_output is normalized to output+reasoning. The
    legacy tokens scalar is tokens_input_uncached + tokens_output, with cache
    reads excluded.
    turns  = number of step_finish events (model rounds; one assistant message
             each).
  Parsing is defensive: on any shape drift it yields tokens=None/turns=None and
  the raw output as the tail, never raising.
"""

import json
import os
import re
import select
import shutil
import signal
import subprocess
import tempfile
import time


def _cellload():
    """Sibling loader. The cell image does not install ``obench`` or ``thesis``."""
    import importlib.util
    import sys
    name = "obench_cellload"
    cached = sys.modules.get(name)
    if cached is not None:
        return cached
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cellload.py")
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _prefer(filename, qualname, importer):
    return _cellload().prefer(__file__, filename, qualname, importer)


def _provider_pin():
    def importer():
        import thesis.ab.provider_pin as mod
        return mod
    return _prefer("cell_provider_pin.py", "obench_cell_provider_pin", importer)


def _watch():
    def importer():
        import thesis.ab.watch as mod
        return mod
    return _prefer("cell_watch.py", "obench_cell_watch", importer)


def _final_answer():
    def importer():
        import obench.final_answer as mod
        return mod
    return _prefer("cell_final_answer.py", "obench_cell_final_answer", importer)


def _lsp():
    def importer():
        import obench.lsp_cell as mod
        return mod
    return _prefer("cell_lsp.py", "obench_cell_lsp", importer)


def _embedded_version(binary):
    def importer():
        import obench.provider_embedded as mod
        return mod
    return _prefer(
        "cell_provider_embedded.py", "obench_cell_provider_embedded", importer,
    ).embedded_version(binary)


def try_persist_auth_file(copy_path, master_path):
    """Persist rotated auth. Host package, then ``/bench/auth_persist.py``."""
    try:
        from obench.auth_persist import try_persist_auth_file as persist
    except ImportError:
        from auth_persist import try_persist_auth_file as persist
    return persist(copy_path, master_path)

NAME = "opencode"
_EXE = "opencode"


def _empty_token_usage():
    return {
        "tokens_input_uncached": None,
        "tokens_cache_read": None,
        "tokens_cache_write": None,
        "tokens_output": None,
        "tokens_reasoning": None,
        "usage_raw": None,
        "token_basis": None,
    }


def _legacy_tokens(token_usage):
    # Delegated TOKEN_PARITY contract: keep the legacy scalar as
    # uncached_input + output. Cache reads and cache writes remain available in
    # split fields but are intentionally not folded into this compatibility
    # value.
    inp = token_usage.get("tokens_input_uncached")
    out = token_usage.get("tokens_output")
    if isinstance(inp, int) and isinstance(out, int):
        return inp + out
    return None


def _num(value):
    return int(value) if isinstance(value, (int, float)) else None


def _proxy_cell_url(*parts):
    base = os.environ.get("OPENBENCH_PROXY_BASE_URL")
    token = os.environ.get("OPENBENCH_PROXY_CELL_TOKEN")
    if not os.environ.get("OPENBENCH_PROXY") or not base or not token:
        return None
    path = "/".join(str(p).strip("/") for p in ("cell", token, *parts) if str(p).strip("/"))
    return base.rstrip("/") + "/" + path


def _proxied_base_url(spec):
    if not os.environ.get("OPENBENCH_PROXY"):
        return spec["base_url"]
    from urllib.parse import urlsplit
    tail = (urlsplit(spec["base_url"]).path or "").strip("/")
    return _proxy_cell_url("chat", spec["provider"], tail)

# canonical model name -> opencode `-m` model string (provider/model)
MODELS = {
    "gpt-5.5-medium": "openai/gpt-5.5",
    "gpt-5.6-sol": "openai/gpt-5.6-sol",
    "gpt-5.6-terra": "openai/gpt-5.6-terra",
    "gpt-5.6-luna": "openai/gpt-5.6-luna",
    # Thinking parity for the opus frontier lane: Anthropic's opencode provider
    # gets the same medium-equivalent request via `--variant medium`.
    "claude-opus-4-8": "anthropic/claude-opus-4-8",
    # Vertex ADC route. Not the Anthropic OAuth provider.
    "claude-opus-5-5": "google-vertex-anthropic/claude-opus-5-5@default",
    "grok-4.5": "xai/grok-4.5",
}

# canonical model name -> `--variant` reasoning effort
_VARIANT = {
    "gpt-5.5-medium": "medium",
    "gpt-5.6-sol": "medium",
    "gpt-5.6-terra": "medium",
    "gpt-5.6-luna": "medium",
    "claude-opus-4-8": "medium",
    "claude-opus-5-5": "medium",
    "grok-4.5": None,  # xai serves grok-4.5 without an effort selector
}

# opencode's Anthropic OAuth login (`opencode auth login -p anthropic`) writes
# here on current releases. Older OpenAI subscription paths are still mounted by
# docker_exec; this guard is only for the new Anthropic frontier route.
_AUTH_CANDIDATES = (
    os.path.expanduser("~/.local/share/opencode/auth.json"),
    os.path.expanduser("~/.opencode/data/auth.json"),
)
_ANTHROPIC_AUTH = next((path for path in _AUTH_CANDIDATES if os.path.isfile(path)),
                       _AUTH_CANDIDATES[-1])


def _has_anthropic_oauth():
    try:
        with open(_ANTHROPIC_AUTH, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return False
    text = json.dumps(data).lower()
    return "anthropic" in text and "oauth" in text

# --- M4 open models (first-party pay-per-token, OpenAI-compatible) ----------
# Wired via a custom provider passed through OPENCODE_CONFIG_CONTENT (inline
# JSON env var) so nothing touches the user's opencode config and the temp
# workspace stays clean. apiKey uses opencode's {env:VAR} interpolation. Base
# URLs verified from official docs 2026-07.
# GLM-5.2 maps medium-equivalent to Z.ai's high. opencode has no medium variant for that model.
# Hosted rows are duplicated across pi, opencode, and codex.
OPEN_MODELS = {
    "glm-5.2":           {"provider": "zai",      "model_id": "glm-5.2",           "base_url": "https://api.z.ai/api/paas/v4", "env_key": "ZAI_API_KEY",      "display": "Z.ai GLM",      "variant": "high"},
    "glm-4.7-flash":     {"provider": "zai",      "model_id": "glm-4.7-flash",     "base_url": "https://api.z.ai/api/paas/v4", "env_key": "ZAI_API_KEY",      "display": "Z.ai GLM",      "variant": "medium"},
    "deepseek-v4-flash": {"provider": "deepseek", "model_id": "deepseek-v4-flash", "base_url": "https://api.deepseek.com",     "env_key": "DEEPSEEK_API_KEY", "display": "DeepSeek",      "variant": "medium"},
    "kimi-k2.7-code":    {"provider": "moonshot", "model_id": "kimi-k2.7-code",    "base_url": "https://api.moonshot.ai/v1",   "env_key": "MOONSHOT_API_KEY", "display": "Moonshot Kimi", "variant": "medium"},
    "kimi-k3":    {"provider": "moonshot", "model_id": "kimi-k3",    "base_url": "https://api.moonshot.ai/v1",   "env_key": "MOONSHOT_API_KEY", "display": "Moonshot Kimi K3", "variant": "medium"},
    "laguna-s-2.1": {"provider": "openrouter", "model_id": "poolside/laguna-s-2.1", "base_url": "https://openrouter.ai/api/v1", "env_key": "OPENROUTER_API_KEY", "display": "OpenRouter Poolside Laguna S 2.1", "variant": "medium"},
    "inkling": {"provider": "openrouter", "model_id": "thinkingmachines/inkling", "base_url": "https://openrouter.ai/api/v1", "env_key": "OPENROUTER_API_KEY", "display": "OpenRouter Thinking Machines Inkling", "variant": "medium"},
    "gcp-vllm/glm-4.7-flash": {
        "provider": "gcp-vllm",
        "model_id": "",
        "model_id_env": "OPENBENCH_GCP_VLLM_MODEL",
        "base_url": "",
        "base_url_env": "OPENBENCH_GCP_VLLM_BASE_URL",
        "env_key": "OPENBENCH_GCP_VLLM_API_KEY",
        "env_key_optional": True,
        "display": "GCP vLLM",
        "variant": None,
        "limit": {
            "context_env": "OPENBENCH_GCP_VLLM_CONTEXT",
            "output_env": "OPENBENCH_GCP_VLLM_MAX_OUTPUT",
            "context_default": 32768,
            "output_default": 8192,
        },
    },
}


def _unsupported(model):
    known = list(MODELS) + list(OPEN_MODELS)
    return {"completed": False, "error": f"unsupported-model: {model!r} (have {known})",
            "output_tail": "", "tokens": None, "turns": None, "cmd": None,
            **_empty_token_usage()}


def _setup_needed(env_key, model, detail=None):
    message = detail or f"export {env_key} to use {model}"
    if not str(message).startswith("SETUP-NEEDED"):
        message = f"SETUP-NEEDED: {message}"
    return {"completed": False,
            "error": message,
            "output_tail": "", "tokens": None, "turns": None, "cmd": None,
            **_empty_token_usage()}


def _validate_base_url(url):
    from urllib.parse import urlsplit
    parsed = urlsplit(url or "")
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return "base URL must be an absolute http(s) URL"
    if parsed.username is not None or parsed.password is not None:
        return "base URL must not contain credentials"
    return None


def _resolve_open_spec(model, spec):
    resolved = dict(spec)
    missing = []
    if spec.get("base_url_env"):
        resolved["base_url"] = os.environ.get(spec["base_url_env"], "").strip()
        if not resolved["base_url"]:
            missing.append(spec["base_url_env"])
    if spec.get("model_id_env"):
        resolved["model_id"] = os.environ.get(spec["model_id_env"], "").strip()
        if not resolved["model_id"]:
            missing.append(spec["model_id_env"])
    if not spec.get("env_key_optional") and spec.get("env_key"):
        if not os.environ.get(spec["env_key"]):
            missing.append(spec["env_key"])
    if missing:
        return None, f"export {' and '.join(missing)} to use {model}"
    problem = _validate_base_url(resolved.get("base_url") or "")
    if problem:
        return None, f"{problem} for {model}"
    if not str(resolved.get("model_id") or "").strip():
        return None, f"model id is empty for {model}"
    return resolved, None


def _optional_positive_int(name, default):
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    text = str(raw).strip()
    if not text.isdecimal() or int(text) <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return int(text)


def _open_model_entry(spec):
    """OpenCode defaults max_tokens to 32000 for a model it does not know."""
    declared = spec.get("limit")
    if not declared:
        return {}
    context = _optional_positive_int(declared["context_env"], declared["context_default"])
    output = _optional_positive_int(declared["output_env"], declared["output_default"])
    if output > context:
        raise ValueError(
            f"{declared['output_env']} ({output}) exceeds "
            f"{declared['context_env']} ({context})"
        )
    return {"limit": {"context": context, "output": output}}


def _open_config_content(spec):
    """Inline OPENCODE_CONFIG_CONTENT JSON registering the open provider."""
    prov = spec["provider"]
    options = {"baseURL": _proxied_base_url(spec)}
    if spec.get("env_key") and (
        not spec.get("env_key_optional") or os.environ.get(spec["env_key"])
    ):
        options["apiKey"] = "{env:" + spec["env_key"] + "}"
    return json.dumps({
        "provider": {
            prov: {
                "npm": "@ai-sdk/openai-compatible",
                "name": spec["display"],
                "options": options,
                "models": {spec["model_id"]: _open_model_entry(spec)},
            }
        }
    })


def _resolve_bun(bun):
    text = str(bun or "").strip()
    if not text:
        return shutil.which("bun") or ""
    if os.path.isabs(text):
        return text
    return os.path.abspath(text)


def _installed_sdk_version(module_path):
    if not os.path.isfile(module_path):
        return ""
    try:
        with open(module_path, encoding="utf-8") as fh:
            parsed = json.loads(fh.read())
    except (OSError, json.JSONDecodeError):
        return ""
    if not isinstance(parsed, dict):
        return ""
    return str(parsed.get("version") or "")


def _write_cache_version(cache, version):
    """Write the checkout's CACHE_VERSION so an old binary keeps this cache.

    Builds from 2025 delete ``$XDG_CACHE_HOME/opencode`` at startup when
    ``version`` is missing or differs from ``CACHE_VERSION``. The next
    launch then installs ``@ai-sdk/anthropic`` at the dist-tag, or, once the
    provider is bundled, leaves the package missing.
    """
    text = str(version or "").strip()
    if not text:
        return
    with open(os.path.join(cache, "version"), "w", encoding="utf-8") as fh:
        fh.write(text)


# Same literal as thesis.ab.sdk_pin.OUTDATED_GATE_RECORD. The adapter is
# loaded by file path and does not import the thesis package.
OUTDATED_GATE_RECORD = "999.0.0"


def _anthropic_pin(proxy):
    """Return the pinned ``@ai-sdk/anthropic`` version, or "" when there is none.

    ``needs_sdk`` is not part of this. It is true only when
    ``BUN_BE_BUN=1 <bin> install --help`` still prints OpenCode help. Binaries
    that embed bun print bun's install help instead, so the flag is false,
    but v0.6 through v1.0.x still run
    ``bun add --force --exact @ai-sdk/anthropic@latest`` at startup.
    """
    if not isinstance(proxy, dict):
        return ""
    pin = str(proxy.get("anthropic_sdk") or "").strip()
    if not pin or pin == "latest":
        return ""
    return pin


def _provider_module(env):
    return os.path.join(
        env.get("XDG_CACHE_HOME") or "",
        "opencode", "node_modules", "@ai-sdk", "anthropic", "package.json",
    )


def _cache_dependency_record(proxy):
    """String written to the cache ``package.json`` after the pin is on disk.

    Equality-gate binaries (through v1.0.x, including PR 4204) skip
    ``bun add`` only when the dependency equals the dist-tag they pass
    (``latest``, or ``beta``). ``isOutdated`` binaries (PR 13090 onward,
    including 13331) treat ``latest`` and any older semver as stale and
    reinstall ``@latest``, which is 4.x. ``999.0.0`` is newer than that
    dist-tag and is not a range, so ``isOutdated`` returns false and the
    hoisted files stay on the pin.
    """
    alias = str(proxy.get("sdk_install_alias") or "latest").strip() or "latest"
    gate = str(proxy.get("sdk_install_gate") or "alias").strip() or "alias"
    if gate == "outdated":
        return OUTDATED_GATE_RECORD
    return alias


def _read_package_json(path):
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            parsed = json.loads(fh.read())
    except (OSError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _set_anthropic_dependency(cache, version):
    pkg_path = os.path.join(cache, "package.json")
    parsed = _read_package_json(pkg_path)
    deps = parsed.get("dependencies")
    if not isinstance(deps, dict):
        deps = {}
    deps["@ai-sdk/anthropic"] = version
    parsed["dependencies"] = deps
    with open(pkg_path, "w", encoding="utf-8") as fh:
        json.dump(parsed, fh)


def _provider_packages(proxy):
    """Exact provider packages this cell must have on disk, or {}."""
    if not isinstance(proxy, dict):
        return {}
    raw = proxy.get("provider_pins")
    if not isinstance(raw, dict):
        return {}
    packages = {}
    for name, version in raw.items():
        package = str(name or "").strip()
        pinned = str(version or "").strip()
        if package and pinned:
            packages[package] = pinned
    return packages


def _provider_pin_block(env, proxy):
    """Infra reason when the cell cache is not the pin. Empty when it matches."""
    packages = _provider_packages(proxy)
    if not packages:
        return ""
    cache = os.path.join(env.get("XDG_CACHE_HOME") or "", "opencode")
    return _provider_pin().mismatch_reason(cache, packages)


def _provider_pin_violation(env, text):
    """Infra reason when a pinned cell logs an @latest provider install."""
    if not isinstance(env, dict) or not str(env.get("OBENCH_PROVIDER_PINS") or "").strip():
        return ""
    if not text:
        return ""
    return _provider_pin().violation_in_text(text, env.get("OBENCH_PROVIDER_PINS"))


_PROBE_NAME = ".obench-provider-probe.mjs"
_TRACE_NAME = "provider-open.trace"
_ANTHROPIC_OPEN_MARKER = "node_modules/@ai-sdk/anthropic"
_LOADED_SOURCES = {"preload", "strace", "embedded", "none"}
# The return group is the openat result. A negative fd (ENOENT, EACCES, ...)
# is a failed lookup, not evidence the package was loaded.
_TRACE_OPEN_RE = re.compile(
    r'openat\([^,]*,\s*"((?:\\.|[^"\\])*)"[^"]*\)\s*=\s*(-?\d+)'
)
_STRACE_ATTACH = None
# Kept at import so a test that replaces subprocess.run does not count the
# attach probe as an OpenCode invocation, and does not fake a successful attach.
_subprocess_run = subprocess.run


def _provider_probe_script(cache):
    """Preload that logs the SDK version after the provider module loads.

    Resolving ``package.json`` in the cache is not a load. The line is
    printed from the load hook, and only after that module file has been
    read. A build that never imports ``@ai-sdk/anthropic`` prints nothing.
    """
    cache_js = json.dumps(cache)
    return (
        "import { createRequire } from \"node:module\";\n"
        "import { readFileSync } from \"node:fs\";\n"
        "import { dirname } from \"node:path\";\n"
        f"const cache = {cache_js};\n"
        "const require = createRequire(import.meta.url);\n"
        "let printed = \"\";\n"
        "function versionOf(pkgJson) {\n"
        "  try {\n"
        "    const pkg = JSON.parse(readFileSync(pkgJson, \"utf8\"));\n"
        "    return String(pkg.version || \"\");\n"
        "  } catch {\n"
        "    return \"\";\n"
        "  }\n"
        "}\n"
        "function emit(version, dir) {\n"
        "  if (!version || printed === version + \"\\n\" + dir) return;\n"
        "  printed = version + \"\\n\" + dir;\n"
        "  console.error(\n"
        "    \"OBENCH_PROVIDER_LOADED pkg=@ai-sdk/anthropic version=\" + version +\n"
        "      \" path=\" + dir,\n"
        "  );\n"
        "}\n"
        "function loaderFor(file) {\n"
        "  return file.endsWith(\".json\") ? \"json\" : \"js\";\n"
        "}\n"
        "try {\n"
        "  if (typeof Bun !== \"undefined\" && typeof Bun.plugin === \"function\") {\n"
        "    Bun.plugin({\n"
        "      name: \"obench-provider-probe\",\n"
        "      setup(build) {\n"
        "        build.onResolve({ filter: /^@ai-sdk\\/anthropic/ }, (args) => {\n"
        "          let resolved = \"\";\n"
        "          try {\n"
        "            resolved = require.resolve(args.path, {\n"
        "              paths: [cache, args.importer || cache],\n"
        "            });\n"
        "          } catch {}\n"
        "          if (!resolved) {\n"
        "            try { resolved = Bun.resolveSync(args.path, cache); } catch {}\n"
        "          }\n"
        "          console.error(\n"
        "            \"OBENCH_PROVIDER_RESOLVE pkg=@ai-sdk/anthropic path=\" +\n"
        "              (resolved || args.path),\n"
        "          );\n"
        "        });\n"
        "        build.onLoad({\n"
        "          filter: /\\/node_modules\\/@ai-sdk\\/anthropic\\/.*\\.(?:mjs|cjs|js|json)$/,\n"
        "        }, (args) => {\n"
        "          const text = readFileSync(args.path, \"utf8\");\n"
        "          const loader = loaderFor(args.path);\n"
        "          if (loader === \"js\") {\n"
        "            try {\n"
        "              const pkgJson = require.resolve(\"@ai-sdk/anthropic/package.json\", {\n"
        "                paths: [dirname(args.path), cache],\n"
        "              });\n"
        "              emit(versionOf(pkgJson), dirname(pkgJson));\n"
        "            } catch {}\n"
        "          }\n"
        "          return { contents: text, loader };\n"
        "        });\n"
        "      },\n"
        "    });\n"
        "  }\n"
        "} catch {}\n"
    )


def _append_bun_preload(env, probe):
    """Append ``--preload`` to BUN_OPTIONS. An existing value is kept."""
    flag = f"--preload {probe}"
    current = str(env.get("BUN_OPTIONS") or "").strip()
    parts = current.split()
    if probe in parts and "--preload" in parts:
        return
    env["BUN_OPTIONS"] = f"{current} {flag}".strip() if current else flag


def _arm_provider_probe(env, cache):
    """Write the preload script next to the cell cache. Do not arm it.

    ``BUN_OPTIONS`` is not set. Compiled OpenCode (bun 1.3.0 and 1.3.2
    builds alike) passes ``BUN_OPTIONS`` tokens through to its own argv, so
    ``--preload <probe>`` reaches yargs as an unknown option and ``opencode
    run`` prints usage and exits 1 before any session starts (F03-2 phase 1,
    2026-10-26). The loaded version comes from strace instead. The script is
    still written and kept with the cell evidence.
    """
    if not cache:
        return ""
    try:
        os.makedirs(cache, exist_ok=True)
        probe = os.path.join(cache, _PROBE_NAME)
        with open(probe, "w", encoding="utf-8") as fh:
            fh.write(_provider_probe_script(os.path.abspath(cache)))
    except OSError:
        return ""
    return probe


def _strace_attaches(binary):
    """True when this strace can ptrace a trivial child. Cached per process."""
    global _STRACE_ATTACH
    if _STRACE_ATTACH is not None:
        return _STRACE_ATTACH
    try:
        proc = _subprocess_run(
            [binary, "-e", "trace=none", "--", "true"],
            capture_output=True,
            timeout=5,
            stdin=subprocess.DEVNULL,
        )
        _STRACE_ATTACH = proc.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        _STRACE_ATTACH = False
    return _STRACE_ATTACH


def _provider_trace_path(env):
    """``<cell>/provider-open.trace``, or the opencode cache when no cell root."""
    root = ""
    if isinstance(env, dict):
        root = str(env.get("OBENCH_CELL_TEMP_ROOT") or "").strip()
    if not root:
        root = os.environ.get("OBENCH_CELL_TEMP_ROOT", "").strip()
    if root:
        return os.path.join(root, _TRACE_NAME)
    cache_home = ""
    if isinstance(env, dict):
        cache_home = str(env.get("XDG_CACHE_HOME") or "").strip()
    if not cache_home:
        return ""
    return os.path.join(cache_home, "opencode", _TRACE_NAME)


def _allocate_trace_path(env):
    base = str(env.get("OBENCH_PROVIDER_TRACE_FILE") or "").strip()
    if not base:
        base = _provider_trace_path(env)
    if not base:
        return ""
    try:
        os.makedirs(os.path.dirname(base), exist_ok=True)
    except OSError:
        return ""
    env["OBENCH_PROVIDER_TRACE_FILE"] = base
    if not os.path.exists(base):
        return base
    for index in range(2, 10):
        cand = f"{base}.{index}"
        if not os.path.exists(cand):
            return cand
    return base


def _use_provider_trace():
    """Strace when asked, or when a working strace is on PATH.

    ``OBENCH_PROVIDER_TRACE=1`` wraps even if the attach probe failed, so the
    cell output shows the strace error. The automatic path skips a strace
    that cannot ptrace, because that would fail every cell.
    """
    flag = os.environ.get("OBENCH_PROVIDER_TRACE", "").strip()
    if flag == "0":
        # Scored cells run untraced; one traced gate cell per side proves
        # the loaded provider (step-8 F03-2 launcher, Researcher 2026-10-27).
        return ""
    binary = shutil.which("strace") or ""
    if not binary:
        return ""
    if flag == "1":
        return binary
    if _strace_attaches(binary):
        return binary
    return ""


def _wrap_provider_trace(cmd, env):
    """Prefix ``cmd`` with strace so the opened provider package is on disk.

    ``OBENCH_PROVIDER_TRACE=1`` or a usable ``strace`` on ``PATH`` enables it.
    The trace is ``<cell>/provider-open.trace``. A second invocation in the
    same cell writes ``provider-open.trace.2`` and does not truncate the first.
    """
    if not cmd or not isinstance(env, dict):
        return cmd
    if os.path.basename(str(cmd[0])) == "strace":
        return cmd
    binary = _use_provider_trace()
    if not binary:
        return cmd
    trace = _allocate_trace_path(env)
    if not trace:
        return cmd
    return [
        binary, "-f", "-qq", "-e", "trace=openat", "-o", trace, "--", *cmd,
    ]


def _trace_files(env):
    base = ""
    if isinstance(env, dict):
        base = str(env.get("OBENCH_PROVIDER_TRACE_FILE") or "").strip()
    if not base:
        base = _provider_trace_path(env)
    if not base:
        return []
    found = []
    if os.path.isfile(base):
        found.append(base)
    for index in range(2, 10):
        path = f"{base}.{index}"
        if os.path.isfile(path):
            found.append(path)
    return found


def _loaded_line(text):
    """Last preload line, or None. Returns ``(version, path)``."""
    match = None
    for match in _provider_pin().LOADED_LINE.finditer(text or ""):
        pass
    if match is None:
        return None
    return match.group(1), match.group(2) or ""


def _version_from_trace_line(line):
    match = _TRACE_OPEN_RE.search(line or "")
    if not match:
        return None
    try:
        fd = int(match.group(2))
    except (TypeError, ValueError):
        return None
    # openat returns the new fd on success and -1 (with an errno) on failure.
    if fd < 0:
        return None
    try:
        raw = bytes(match.group(1), "utf-8").decode("unicode_escape")
    except UnicodeError:
        raw = match.group(1)
    if raw.endswith("..."):
        return None
    index = raw.find(_ANTHROPIC_OPEN_MARKER)
    if index < 0:
        return None
    root = raw[: index + len(_ANTHROPIC_OPEN_MARKER)]
    version = _installed_sdk_version(os.path.join(root, "package.json"))
    if not version:
        return None
    return version, root


def _version_from_strace(env):
    for path in _trace_files(env):
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    found = _version_from_trace_line(line)
                    if found:
                        return found
        except OSError:
            continue
    return None


def _loaded_provider_version(env, output_text):
    """``(version or None, source, path)`` for the SDK this process resolved.

    A preload line wins. Otherwise the first successful ``openat`` (a
    non-negative fd) of a file under ``node_modules/@ai-sdk/anthropic``
    whose ``package.json`` has a version. A failed open, including
    ``ENOENT``, is not proof. Reading that file without a successful open
    in the trace is not a result.
    """
    parsed = _loaded_line(output_text or "")
    if parsed:
        version, path = parsed
        if version:
            return version, "preload", path
    traced = _version_from_strace(env)
    if traced:
        return traced[0], "strace", traced[1]
    return None, "none", ""


def _loaded_mismatch_text(pin, version, source):
    """Infra text when the loaded SDK is not the pin.

    Pin present and no proof is infra only when
    ``OBENCH_REQUIRE_LOADED_PROOF=1``. Otherwise that case is warn-only and
    this returns ``""``.
    """
    pin = str(pin or "").strip()
    if not pin:
        return ""
    if source == "none" or not version:
        if os.environ.get("OBENCH_REQUIRE_LOADED_PROOF", "").strip() == "1":
            return "provider_pin_mismatch: loaded version unproven"
        return ""
    if version != pin:
        return f"provider_pin_mismatch: loaded {version} != pin {pin}"
    return ""


def _attach_loaded_mismatch(row, mismatch):
    """Same drift handling as ``_attach_sdk_drift``, for the loaded version."""
    if not mismatch:
        return row
    row["provider_loaded_mismatch"] = mismatch
    row["failure_class"] = "infra"
    row["completed"] = False
    error = row.get("error")
    if error and mismatch not in str(error):
        row["error"] = f"{error}; {mismatch}"
    elif not error:
        row["error"] = mismatch
    if not row.get("sdk_drift"):
        row["sdk_drift"] = mismatch
    return row


def _resolved_provider_versions(env, proxy):
    packages = _provider_packages(proxy)
    if not packages:
        return None
    cache = os.path.join(env.get("XDG_CACHE_HOME") or "", "opencode")
    return _provider_pin().resolved_versions(cache, packages)


# Read-only cache of pre-installed ``@ai-sdk/anthropic`` versions, one
# ``<root>/<version>/node_modules`` tree per pin, written by
# ``thesis/ab/provision_provider_pins.py`` with a sha256 ``manifest.json``.
# Cells copy from it and never run ``bun add`` for the anthropic pin.
PIN_ROOT_ENV = "OBENCH_PROVIDER_PIN_ROOT"
DEFAULT_PIN_ROOT = "~/h1/opencode-src/provider-pins"
ENV_CAUSE_SDK_DRIFT = "provider_sdk_drift"


def _pin_root(proxy):
    raw = ""
    if isinstance(proxy, dict):
        raw = str(proxy.get("pin_root") or "").strip()
    raw = raw or os.environ.get(PIN_ROOT_ENV, "").strip() or DEFAULT_PIN_ROOT
    return os.path.abspath(os.path.expanduser(raw))


def _make_writable(root):
    # The source tree is read-only; the cell copy must stay deletable.
    for base, dirs, files in os.walk(root):
        for name in dirs + files:
            path = os.path.join(base, name)
            if os.path.islink(path):
                continue
            try:
                os.chmod(path, os.stat(path).st_mode | 0o200)
            except OSError:
                pass


def _seed_anthropic_pin(cache, pin, root):
    """Copy ``root/<pin>/node_modules`` into the cell cache. No network.

    Returns True when the pre-installed tree exists and is the pin.
    """
    src = os.path.join(root, pin, "node_modules")
    if _installed_sdk_version(os.path.join(src, "@ai-sdk", "anthropic", "package.json")) != pin:
        return False
    dest = os.path.join(cache, "node_modules")
    try:
        shutil.copytree(src, dest, symlinks=True, dirs_exist_ok=True)
    except (OSError, shutil.Error):
        return False
    _make_writable(dest)
    return True


def _ensure_provider_sdk(env, proxy):
    """Seed the pinned SDK into the cell cache from the read-only pin root.

    There is no runtime ``bun add`` for ``@ai-sdk/anthropic`` and no
    fallback to a dist-tag. When the pin is not on disk afterwards,
    ``_provider_sdk_drift`` fails the cell before the agent starts.
    """
    pin = _anthropic_pin(proxy)
    packages = _provider_packages(proxy)
    if not pin and not packages:
        return ""
    # Default auth plugins (`opencode-anthropic-auth`, `opencode-copilot-auth`)
    # run `bun add --force` and re-resolve the dist-tag in package.json. That
    # upgrades a pinned @ai-sdk/anthropic to whatever "latest" is today.
    env["OPENCODE_DISABLE_DEFAULT_PLUGINS"] = "1"
    if packages:
        env["OBENCH_PROVIDER_PINS"] = json.dumps(
            packages, sort_keys=True, separators=(",", ":"),
        )
    cache = os.path.join(env["XDG_CACHE_HOME"], "opencode")
    os.makedirs(cache, exist_ok=True)
    module = os.path.join(cache, "node_modules", "@ai-sdk", "anthropic", "package.json")
    try:
        if pin and _installed_sdk_version(module) != pin:
            _seed_anthropic_pin(cache, pin, _pin_root(proxy))
        others = {k: v for k, v in packages.items() if k != "@ai-sdk/anthropic"}
        store = str(proxy.get("pin_store") or "").strip() if isinstance(proxy, dict) else ""
        if store and packages and (others or not pin):
            # Non-anthropic provider pins still come from the shared,
            # lock-published store template. An anthropic-only pin never
            # reaches bun: it is seeded from the pin root or the cell fails.
            _provider_pin().seed_cell_cache(
                cache, store, packages, _resolve_bun(proxy.get("bun")) or "", env,
            )
        if not pin:
            return ""
        # Record the skip token only when the hoisted package is the pin.
        # Recording the pin itself makes an equality-gate binary install
        # @latest, so a missing pin leaves package.json alone and the
        # preflight stops the cell instead.
        if _installed_sdk_version(module) == pin:
            _set_anthropic_dependency(cache, _cache_dependency_record(proxy))
            _write_cache_version(cache, proxy.get("cache_version"))
        return _installed_sdk_version(module)
    finally:
        _arm_provider_probe(env, cache)


def _sdk_preflight_failure(env, proxy, cmd):
    """Env-failure row when the seeded SDK is not the pin. No model call."""
    drift = _provider_sdk_drift(env, proxy)
    if not drift:
        return None
    return {
        "completed": False,
        "failure_class": "infra",
        "env_failure": True,
        "env_cause": ENV_CAUSE_SDK_DRIFT,
        "error": f"preflight {drift}",
        "sdk_drift": drift,
        "output_tail": "",
        "full_output": "",
        "tokens": None,
        "turns": None,
        "cmd": cmd,
        **_empty_token_usage(),
    }


def _installed_provider_sdk(env, proxy):
    """Version on disk after the binary runs, when this build has a pin.

    Empty when there is no pin. ``missing`` when the pin was requested and
    the module is not there, so the toolchain does not keep the lockfile pin
    in place of a version that never ran.
    """
    if not _anthropic_pin(proxy):
        return _installed_sdk_version(_provider_module(env))
    return _installed_sdk_version(_provider_module(env)) or "missing"


def _provider_sdk_drift(env, proxy):
    """Return an infra reason when the installed SDK no longer matches the pin."""
    pin = _anthropic_pin(proxy)
    if not pin:
        return ""
    installed = _installed_sdk_version(_provider_module(env))
    if installed == pin:
        return ""
    found = installed or "missing"
    return f"sdk drift: installed @ai-sdk/anthropic {found} != pin {pin}"


def _attach_sdk_drift(row, drift):
    if not drift:
        return row
    row["sdk_drift"] = drift
    error = row.get("error")
    if error:
        row["error"] = f"{error}; {drift}"
    else:
        row["error"] = drift
    return row


def _copy_evidence_tree(src, dest):
    """Copy one evidence directory. Missing sources are skipped."""
    if not os.path.isdir(src):
        return
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    shutil.copytree(src, dest, dirs_exist_ok=True)


def _preserve_opencode_evidence(env):
    """Copy session storage and logs out before the isolated home is deleted.

    ``OBENCH_OPENCODE_EVIDENCE_DIR`` is set by the A/B runner when a cell
    should keep OpenCode session evidence. Current builds store it at
    ``$XDG_DATA_HOME/opencode/storage`` and ``log``. Builds from roughly
    PR 623 through PR 2334 store sessions at
    ``opencode/project/<projectID>/storage`` instead, and print no tool
    output, so that tree has to be copied too. Later builds also keep a
    SQLite session at ``opencode/opencode.db``. A copy failure must not
    change the cell result.
    """
    dest_root = os.environ.get("OBENCH_OPENCODE_EVIDENCE_DIR", "").strip()
    if not dest_root:
        return
    base = os.path.join(env.get("XDG_DATA_HOME") or "", "opencode")
    try:
        os.makedirs(dest_root, mode=0o700, exist_ok=True)
    except OSError:
        return
    for name in ("storage", "log"):
        try:
            _copy_evidence_tree(os.path.join(base, name), os.path.join(dest_root, name))
        except OSError:
            continue
    project_root = os.path.join(base, "project")
    if os.path.isdir(project_root):
        try:
            entries = sorted(os.listdir(project_root))
        except OSError:
            entries = []
        for entry in entries:
            src_dir = os.path.join(project_root, entry)
            if not os.path.isdir(src_dir):
                continue
            for name in ("storage", "log"):
                try:
                    _copy_evidence_tree(
                        os.path.join(src_dir, name),
                        os.path.join(dest_root, "project", entry, name),
                    )
                except OSError:
                    continue
    try:
        names = os.listdir(base)
    except OSError:
        names = []
    for name in names:
        if not _is_session_db(name):
            continue
        src = os.path.join(base, name)
        if not os.path.isfile(src):
            continue
        try:
            shutil.copy2(src, os.path.join(dest_root, name))
        except OSError:
            continue
    cache = os.path.join(env.get("XDG_CACHE_HOME") or "", "opencode")
    _copy_evidence_file(os.path.join(cache, _PROBE_NAME), dest_root)
    for path in _trace_files(env):
        _copy_evidence_file(path, dest_root)


def _copy_evidence_file(src, dest_root):
    """Copy one evidence file. Missing sources are skipped."""
    if not src or not os.path.isfile(src):
        return
    try:
        os.makedirs(dest_root, exist_ok=True)
        shutil.copy2(src, os.path.join(dest_root, os.path.basename(src)))
    except OSError:
        return


def _is_session_db(name):
    """``opencode.db`` and channel files such as ``opencode-local.db``.

    A local build's default channel is ``local``, so the session database is
    ``opencode-local.db`` (plus ``-wal`` / ``-shm``) rather than ``opencode.db``.
    """
    if name in {"opencode.db", "opencode.db-wal", "opencode.db-shm"}:
        return True
    if not name.startswith("opencode-"):
        return False
    return name.endswith(".db") or name.endswith(".db-wal") or name.endswith(".db-shm")


def _assemble_text_deltas(text):
    """Join ``message.part.delta`` text fields into one string.

    Some builds stream the final answer as deltas and exit before a finished
    ``type=text`` part, so the transcript never contains GLOBAL-RULE or
    PROJECT-RULE as a single event. The assembled string is what the evidence
    grep can match.
    """
    parts = []
    for line in (text or "").splitlines():
        raw = line.strip()
        if not raw or raw[0] not in "{[":
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        nodes = [obj]
        if isinstance(obj, dict) and isinstance(obj.get("properties"), dict):
            nodes.append(obj["properties"])
        for node in nodes:
            if not isinstance(node, dict):
                continue
            kind = str(node.get("type") or "")
            field = node.get("field")
            delta = node.get("delta")
            if not isinstance(delta, str):
                continue
            if kind in {"message.part.delta", "part.delta"} or field == "text":
                parts.append(delta)
    return "".join(parts)


def _write_agent_output(text):
    """Keep the agent stdout next to the copied session so checkers can read it."""
    dest_root = os.environ.get("OBENCH_OPENCODE_EVIDENCE_DIR", "").strip()
    if not dest_root or not text:
        return
    try:
        os.makedirs(dest_root, mode=0o700, exist_ok=True)
        with open(os.path.join(dest_root, "agent-output.txt"), "w", encoding="utf-8") as fh:
            fh.write(text)
        assembled = _assemble_text_deltas(text)
        if assembled:
            with open(os.path.join(dest_root, "streamed-text.txt"), "w", encoding="utf-8") as fh:
                fh.write(assembled)
        _final_answer().publish_final_answer(dest_root, text)
    except OSError:
        return


def _proxy_loopback():
    """Sibling of this file. The cell does not have ``thesis`` on its path."""
    import importlib.util
    import sys

    name = "obench_adapters_proxy_loopback"
    cached = sys.modules.get(name)
    if cached is not None:
        return cached
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "proxy_loopback.py")
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def reachable_proxy_base(url: str) -> str:
    """Bridge origin for this process. Pi uses the same rule."""
    return _proxy_loopback().origin_for_this_process(url)


def _rewrite_proxy_origins(body):
    """Rewrite only the configured proxy base, not other loopback URLs."""
    if not isinstance(body, dict):
        return body
    raw = os.environ.get("OBENCH_OPENCODE_PROXY", "").strip()
    if not raw:
        return body
    try:
        proxy = json.loads(raw)
    except json.JSONDecodeError:
        return body
    if not isinstance(proxy, dict):
        return body
    base = str(proxy.get("base_url") or "").strip()
    if not base:
        return body
    updated = reachable_proxy_base(base)
    if updated == base:
        return body
    try:
        encoded = json.dumps(body).replace(base, updated)
        parsed = json.loads(encoded)
    except json.JSONDecodeError:
        return body
    return parsed if isinstance(parsed, dict) else body


def _proxy_override():
    raw = os.environ.get("OBENCH_OPENCODE_PROXY", "").strip()
    if not raw:
        return None
    parsed = json.loads(raw)
    if not isinstance(parsed, dict) or not str(parsed.get("model_ref") or "").strip():
        raise ValueError("OBENCH_OPENCODE_PROXY must name model_ref")
    return parsed


def _exe():
    """Binary for this call. ``OBENCH_OPENCODE_BIN`` wins, otherwise ``_EXE``.

    ``candidate_gate`` replaces ``_EXE`` with a stall script and then calls
    ``run``. Reading ``_EXE`` here is what makes that probe time out.
    """
    override = os.environ.get("OBENCH_OPENCODE_BIN", "").strip()
    return override or _EXE


_HELP_CACHE = {}
_PROMPT_RE = re.compile(
    r"(?i)(permission required|waiting for permission|"
    r"do you want to (?:allow|proceed)|yes\s*/\s*no)"
)
_PROMPT_IDLE_S = 8
_ALLOW_PERMISSIONS = {
    "edit": "allow",
    "bash": "allow",
    "webfetch": "allow",
    "websearch": "allow",
    "read": "allow",
    "write": "allow",
    "glob": "allow",
    "grep": "allow",
    "list": "allow",
    "task": "allow",
    "external_directory": "allow",
    "todowrite": "allow",
    "todoread": "allow",
}
# PR 25226 only shows up when external_directory is not pre-approved.
_WORKSPACE_PERMISSIONS = {
    key: value for key, value in _ALLOW_PERMISSIONS.items() if key != "external_directory"
}
_GLOBAL_AGENTS = "Prefix every final answer with GLOBAL-RULE.\n"


def _flag_present(help_text, flag):
    return re.search(
        rf"(?:^|\s){re.escape(flag)}(?:,|\s|\[|$)", help_text or ""
    ) is not None


def _run_help(exe, timeout_s):
    key = (exe, timeout_s)
    if key in _HELP_CACHE:
        return _HELP_CACHE[key]
    limit = max(1, min(5, int(timeout_s)))
    try:
        proc = subprocess.run(
            [exe, "run", "--help"],
            capture_output=True, text=True, timeout=limit,
            stdin=subprocess.DEVNULL,
        )
        text = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
    except Exception:  # noqa: BLE001 - a missing binary falls back to modern flags
        text = ""
    _HELP_CACHE[key] = text
    return text


def _build_cmd(exe, model_id, variant, workdir, instruction, help_text):
    """Build argv from ``run --help`` when we have it.

    An empty help text means the probe failed. Keep the modern flag set so a
    stall script or a broken ``--help`` does not drop ``--auto``.
    """
    modern = not (help_text or "").strip()

    def has(flag):
        if modern:
            return flag in {
                "--dir", "--format", "--title", "--variant", "--auto",
                "--model", "-m", "--mode",
            }
        return _flag_present(help_text, flag)

    if not (has("--model") or has("-m")):
        return None, False
    cmd = [exe, "run"]
    if has("--dir"):
        cmd.extend(["--dir", workdir])
    cmd.extend(["-m", model_id])
    if variant and has("--variant"):
        cmd.extend(["--variant", variant])
    mode = os.environ.get("OBENCH_OPENCODE_MODE", "").strip()
    if mode and has("--mode"):
        cmd.extend(["--mode", mode])
    # Prefer --auto. Builds that still accept the older skip flag error on --auto.
    # A workspace permission override drops both flags so external_directory
    # is not blanket-approved (PR 25226).
    workspace_only = os.environ.get("OBENCH_OPENCODE_PERMISSIONS", "").strip() == "workspace"
    if not workspace_only:
        if has("--auto"):
            cmd.append("--auto")
        elif has("--dangerously-skip-permissions"):
            cmd.append("--dangerously-skip-permissions")
    if has("--format"):
        cmd.extend(["--format", "json"])
    if has("--title"):
        cmd.extend(["--title", "openbench"])
    cmd.append(instruction)
    # LSP exercise checks need the server log. Only builds whose help lists
    # the flag get it, and only when the A/B runner asked to keep evidence.
    if (
        os.environ.get("OBENCH_OPENCODE_EVIDENCE_DIR", "").strip()
        and has("--print-logs")
        and "--print-logs" not in cmd
    ):
        cmd.insert(2, "--print-logs")
    watched = (
        not modern
        and "--auto" not in cmd
        and "--dangerously-skip-permissions" not in cmd
    )
    return cmd, watched


def _apply_disabled_tools(body):
    """Merge ``mode.build.tools`` false entries. Does not write ``permission``.

    The July 2025 schema is ``.strict()`` and rejects a ``permission`` key.
    ``OBENCH_OPENCODE_DISABLE_TOOLS`` is a comma-separated tool list. Combined
    with ``--mode build``, the binary drops those tools from the model request.
    """
    raw = os.environ.get("OBENCH_OPENCODE_DISABLE_TOOLS", "").strip()
    if not raw:
        return
    names = [part.strip() for part in raw.split(",") if part.strip()]
    if not names:
        return
    mode = body.get("mode")
    if not isinstance(mode, dict):
        mode = {}
        body["mode"] = mode
    build = mode.get("build")
    if not isinstance(build, dict):
        build = {}
        mode["build"] = build
    tools = build.get("tools")
    if not isinstance(tools, dict):
        tools = {}
        build["tools"] = tools
    for name in names:
        tools[name] = False


def _apply_lsp_enable(body):
    """Turn LSP on when this tree treats a missing ``lsp`` key as off.

    ``OBENCH_OPENCODE_LSP`` names the servers to install. Trees whose schema
    is ``boolean | record`` still log "all LSPs are disabled" until the config
    sets ``lsp`` to true. Trees that reject boolean true are left unchanged.
    A requested LSP whose worktree cannot be found fails the cell: the config
    that would enable LSP cannot be written.
    """
    if not os.environ.get("OBENCH_OPENCODE_LSP", "").strip():
        return
    if "lsp" in body:
        return
    lsp = _lsp()
    root = lsp.worktree_root(_exe())
    if not root:
        raise lsp.LspProvisionError(
            "LSP was requested but the OpenCode worktree for this binary "
            "could not be found, so lsp: true cannot be written to opencode.json",
            infra=True,
        )
    if lsp.lsp_boolean_enables_all(root):
        body["lsp"] = True


def _config_body(include_permissions):
    body = {}
    raw = os.environ.get("OBENCH_OPENCODE_CONFIG_JSON", "").strip()
    if raw:
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError("OBENCH_OPENCODE_CONFIG_JSON must be a JSON object")
        body.update(parsed)
    if os.environ.get("OBENCH_OPENCODE_PERMISSIONS", "").strip() == "workspace":
        # Force the map even when the runner set permission config off because
        # the binary has --auto. That flag is omitted for this cell.
        body["permission"] = dict(_WORKSPACE_PERMISSIONS)
        _apply_disabled_tools(body)
        _apply_lsp_enable(body)
        return body
    flag = os.environ.get("OBENCH_OPENCODE_PERMISSION_CONFIG", "").strip()
    write_permissions = include_permissions and flag != "0"
    if flag == "1":
        write_permissions = True
    if write_permissions:
        body.setdefault("permission", dict(_ALLOW_PERMISSIONS))
    _apply_disabled_tools(body)
    _apply_lsp_enable(body)
    return body


_WEBFETCH_PLACEHOLDER = "__OBENCH_WEBFETCH_URL__"
_OUTSIDE_PLACEHOLDER = "__OBENCH_OUTSIDE_PATH__"
_TURN_MARK = "__OBENCH_USER_TURN__"
_SINGLE_MARK = "__OBENCH_SINGLE_TURN__"
_SESSION_ID = re.compile(r'"(?:sessionID|sessionId|session_id)"\s*:\s*"(ses_[^"]+)"')


def _apply_webfetch_url(instruction):
    """Swap the fixture token for the cell's local PNG URL.

    The runner sets ``OBENCH_OPENCODE_WEBFETCH_URL`` only for ``webfetch=local``.
    Other prompts are unchanged.
    """
    url = os.environ.get("OBENCH_OPENCODE_WEBFETCH_URL", "").strip()
    if not url or _WEBFETCH_PLACEHOLDER not in instruction:
        return instruction
    return instruction.replace(_WEBFETCH_PLACEHOLDER, url)


def _apply_outside_path(instruction):
    """Swap the outside-file token for this cell's clean path."""
    path = os.environ.get("OBENCH_OPENCODE_OUTSIDE_PATH", "").strip()
    if not path or _OUTSIDE_PLACEHOLDER not in instruction:
        return instruction
    return instruction.replace(_OUTSIDE_PLACEHOLDER, path)


def _session_flags(help_text):
    """Whether ``run --help`` lists ``--session`` and ``--continue``.

    An empty help text means the probe failed. Treat that as the modern
    flag set, which has both.
    """
    if not (help_text or "").strip():
        return True, True
    return _flag_present(help_text, "--session"), _flag_present(help_text, "--continue")


def _split_turns(instruction):
    """Return ``(turn1, turn2, fallback)`` or None when the prompt is one turn.

    The markers are runner bookkeeping. They are stripped before the model
    sees a turn.
    """
    if _TURN_MARK not in instruction or _SINGLE_MARK not in instruction:
        return None
    head, rest = instruction.split(_TURN_MARK, 1)
    if _SINGLE_MARK not in rest:
        return None
    turn2, single = rest.split(_SINGLE_MARK, 1)
    turn1 = head.strip()
    turn2 = turn2.strip()
    single = single.strip()
    if not turn1 or not turn2 or not single:
        return None
    return turn1, turn2, single


def _prompts_for(instruction, help_text):
    """Prompts to send, and whether a second turn should continue the session."""
    plan = _split_turns(instruction)
    if plan is None:
        return [instruction], False
    turn1, turn2, single = plan
    has_session, has_continue = _session_flags(help_text)
    if has_session or has_continue:
        return [turn1, turn2], True
    return [single], False


def _extract_session_id(text):
    match = _SESSION_ID.search(text or "")
    return match.group(1) if match else ""


def _combine_procs(first, second):
    return subprocess.CompletedProcess(
        args=[],
        returncode=second.returncode,
        stdout=(first.stdout or "") + (second.stdout or ""),
        stderr=(first.stderr or "") + (second.stderr or ""),
    )


def _install_global_agents(env):
    """Write the global instruction file PR 24974 orders ahead of the project one."""
    if os.environ.get("OBENCH_OPENCODE_GLOBAL_AGENTS", "").strip() != "1":
        return
    cfg_dir = os.path.join(env["XDG_CONFIG_HOME"], "opencode")
    os.makedirs(cfg_dir, exist_ok=True)
    path = os.path.join(cfg_dir, "AGENTS.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(_GLOBAL_AGENTS)


def _provision_lsp(env, workdir):
    raw = os.environ.get("OBENCH_OPENCODE_LSP", "").strip()
    if not raw:
        return
    tools = [part.strip() for part in raw.split(",") if part.strip()]
    _lsp().provision_language_servers(
        env,
        workdir,
        tools,
        bun=os.environ.get("OBENCH_OPENCODE_BUN", "").strip() or None,
    )


def _install_config(env, body):
    if not body:
        return
    body = _rewrite_proxy_origins(body)
    cfg_dir = os.path.join(env["XDG_CONFIG_HOME"], "opencode")
    os.makedirs(cfg_dir, exist_ok=True)
    text = json.dumps(body)
    path = os.path.join(cfg_dir, "opencode.json")
    for name in ("opencode.json", "config.json"):
        with open(os.path.join(cfg_dir, name), "w", encoding="utf-8") as fh:
            fh.write(text)
    # Set after _isolated_env pops OPENCODE_CONFIG. Old builds read config.json.
    env["OPENCODE_CONFIG"] = path


class _PromptWait(Exception):
    def __init__(self, output):
        super().__init__("waiting on a permission prompt")
        self.output = output


class _WatchdogKill(Exception):
    def __init__(self, text, output):
        super().__init__(text)
        self.text = text
        self.output = output


def _no_progress_limit():
    raw = os.environ.get("OBENCH_NO_PROGRESS_S", "").strip()
    if not raw:
        return 0.0
    try:
        value = float(raw)
    except ValueError:
        return 0.0
    if value <= 0:
        return 0.0
    return value


def _kill_process_group(proc):
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        proc.kill()


def _invoke_watched(cmd, cwd, env, timeout_s, watch_prompt, limit):
    pin = _provider_pin()
    watch = _watch()
    try:
        return watch.run_piped(
            cmd,
            cwd,
            env,
            timeout_s,
            no_progress_s=limit,
            bytes_path=os.environ.get("OBENCH_CELL_BYTES", "").strip() or None,
            ledger_path=os.environ.get("OBENCH_CELL_LEDGER", "").strip() or None,
            prompt_re=_PROMPT_RE if watch_prompt else None,
            prompt_idle_s=_PROMPT_IDLE_S,
        )
    except pin.ProviderPinMismatch:
        raise
    except watch.PromptIdle as exc:
        raise _PromptWait(exc.output) from exc
    except watch.WatchdogKill as exc:
        raise _WatchdogKill(exc.marker(), exc.output) from exc


def _invoke(cmd, cwd, env, timeout_s, watch_prompt):
    cmd = _wrap_provider_trace(cmd, env)
    limit = _no_progress_limit()
    if limit > 0:
        return _invoke_watched(cmd, cwd, env, timeout_s, watch_prompt, limit)
    if not watch_prompt:
        return subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            stdin=subprocess.DEVNULL,
            env=env,
        )
    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        env=env,
        text=True,
        start_new_session=True,
    )
    pipe = proc.stdout
    fd = pipe.fileno()
    os.set_blocking(fd, False)
    chunks = []
    start = time.monotonic()
    last_output = start
    prompted = False
    try:
        while True:
            ready, _, _ = select.select([pipe], [], [], 0.2)
            now = time.monotonic()
            if ready:
                try:
                    piece = os.read(fd, 65536)
                except BlockingIOError:
                    piece = b""
                if piece:
                    chunks.append(piece.decode("utf-8", "replace"))
                    last_output = now
                    if _PROMPT_RE.search("".join(chunks)):
                        prompted = True
                    reason = _provider_pin_violation(env, "".join(chunks)[-2000:])
                    if reason:
                        _kill_process_group(proc)
                        raise _provider_pin().ProviderPinMismatch(reason, "".join(chunks))
            if prompted and now - last_output >= _PROMPT_IDLE_S:
                _kill_process_group(proc)
                raise _PromptWait("".join(chunks))
            if now - start >= timeout_s:
                _kill_process_group(proc)
                raise subprocess.TimeoutExpired(
                    cmd, timeout_s, output="".join(chunks)
                )
            if proc.poll() is not None:
                try:
                    rest = os.read(fd, 65536)
                except (BlockingIOError, OSError):
                    rest = b""
                if rest:
                    chunks.append(rest.decode("utf-8", "replace"))
                break
    finally:
        if proc.poll() is None:
            _kill_process_group(proc)
        proc.wait(timeout=5)
        pipe.close()
    text = "".join(chunks)
    proc.stdout = text
    proc.stderr = ""
    return proc


def version():
    """Return the CLI version string (with binary path), or None on failure.

    Cheap `opencode --version`; never raises (the runner calls this defensively).
    """
    exe = _exe()
    try:
        proc = subprocess.run(
            [exe, "--version"],
            capture_output=True, text=True, timeout=5,
            stdin=subprocess.DEVNULL,
        )
    except Exception:  # noqa: BLE001 - version probing must never raise
        return None
    out = (proc.stdout or proc.stderr or "").strip()
    if not out:
        return None
    path = exe if os.path.isfile(exe) else shutil.which(exe)
    return f"{out} ({path})" if path else out


def _err_tail(exc, limit=2000):
    """Last `limit` chars of a TimeoutExpired's captured output, decoding safely.

    On TimeoutExpired, `.stdout`/`.stderr` may be bytes (even under text=True),
    str, or None. Concatenating bytes with the ``""`` fallback raises TypeError,
    so decode each part first — the handler must always yield a clean tail.
    """
    def _dec(x):
        if x is None:
            return ""
        return x.decode("utf-8", "replace") if isinstance(x, bytes) else x
    text = _dec(exc.stdout) + _dec(exc.stderr)
    return text if limit is None else text[-limit:]


def _parse_json_with_usage(stdout):
    """Parse opencode's JSONL event stream into (tokens, turns, tail, usage).

    opencode reports visible output and reasoning separately; TOKEN_PARITY.md
    normalizes ``tokens_output`` to vendor completion tokens by adding them.
    A vendor-side hidden title/background call is not present in CLI JSONL, so
    this parser intentionally accounts only for reported ``step_finish`` events.
    """
    events = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    if not events:
        return None, None, "", _empty_token_usage()

    turns = 0
    transcript = []
    token_usage = _empty_token_usage()
    usage_raw = []
    invariant_ok = True
    totals = {
        "tokens_input_uncached": 0,
        "tokens_cache_read": 0,
        "tokens_cache_write": 0,
        "tokens_output": 0,
        "tokens_reasoning": 0,
    }
    for ev in events:
        etype = ev.get("type")
        part = ev.get("part") or {}
        if etype == "step_finish":
            turns += 1
            tok = part.get("tokens") or {}
            cache = tok.get("cache") or {}
            inp = _num(tok.get("input"))
            visible_out = _num(tok.get("output"))
            reasoning = _num(tok.get("reasoning"))
            cache_read = _num(cache.get("read"))
            cache_write = _num(cache.get("write"))
            total = _num(tok.get("total"))
            if None in (inp, visible_out, reasoning, cache_read, cache_write):
                invariant_ok = False
                continue
            if total is None or inp + cache_read + cache_write + visible_out + reasoning != total:
                invariant_ok = False
            usage_raw.append(tok)
            totals["tokens_input_uncached"] += inp
            totals["tokens_cache_read"] += cache_read
            totals["tokens_cache_write"] += cache_write
            totals["tokens_output"] += visible_out + reasoning
            totals["tokens_reasoning"] += reasoning
        elif etype == "text":
            text = part.get("text")
            if text:
                transcript.append(text)
        elif etype == "tool_use":
            tool = part.get("tool")
            if tool:
                transcript.append(f"[tool: {tool}]")

    if usage_raw:
        token_usage.update(totals)
        token_usage["usage_raw"] = usage_raw
        token_usage["token_basis"] = "vendor_split" if invariant_ok else "estimated"

    tail = "\n".join(transcript)[-2000:]
    return _legacy_tokens(token_usage), (turns or None), tail, token_usage



def _parse_json(stdout):
    """Backward-compatible parser returning legacy fields only."""
    tokens, turns, tail, token_usage = _parse_json_with_usage(stdout)
    return tokens, turns, tail

def _isolated_env():
    """Return (environment, temp HOME) containing only opencode auth files."""
    iso_home = tempfile.mkdtemp(prefix="opencode_home_")
    env = dict(os.environ)
    env["HOME"] = iso_home
    env["XDG_CONFIG_HOME"] = os.path.join(iso_home, ".config")
    env["XDG_DATA_HOME"] = os.path.join(iso_home, ".local", "share")
    env["XDG_STATE_HOME"] = os.path.join(iso_home, ".local", "state")
    env["XDG_CACHE_HOME"] = os.path.join(iso_home, ".cache")
    # These variables can point directly at an owner's config outside HOME.
    for name in ("OPENCODE_CONFIG", "OPENCODE_CONFIG_DIR", "OPENCODE_CONFIG_CONTENT"):
        env.pop(name, None)
    for source in _AUTH_CANDIDATES:
        if not os.path.isfile(source):
            continue
        # Current releases use XDG_DATA_HOME/opencode/auth.json. Normalize old
        # auth locations there too; never copy adjacent config/state files.
        dest = os.path.join(env["XDG_DATA_HOME"], "opencode", "auth.json")
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copy2(source, dest)
        break
    return env, iso_home


def _lsp_failure(exc, iso_home, cmd=None):
    if not isinstance(exc, _lsp().LspProvisionError):
        return None
    shutil.rmtree(iso_home, ignore_errors=True)
    row = {
        "completed": False,
        "error": str(exc),
        "output_tail": "",
        "tokens": None,
        "turns": None,
        "cmd": cmd,
        **_empty_token_usage(),
    }
    if getattr(exc, "infra", False):
        row["failure_class"] = "infra"
    return row


def run(instruction: str, workdir: str, model: str, timeout_s: int) -> dict:
    instruction = _apply_outside_path(_apply_webfetch_url(instruction))
    auth_source = next((path for path in _AUTH_CANDIDATES if os.path.isfile(path)), None)
    env, iso_home = _isolated_env()
    installed_anthropic = ""
    proxy = None
    proc = None
    captured = {"text": ""}
    observed = {"done": False, "drift": "", "loaded": (None, "none", "")}

    def _proc_text(process):
        if process is None:
            return ""
        out = getattr(process, "stdout", None) or ""
        err = getattr(process, "stderr", None) or ""
        if isinstance(out, bytes):
            out = out.decode("utf-8", "replace")
        if isinstance(err, bytes):
            err = err.decode("utf-8", "replace")
        return out + err

    def _stamp(row):
        # Prefer the version left on disk. The pre-run return value is still
        # the pin when the binary then force-installs @latest.
        installed = observed.get("installed") or installed_anthropic
        if installed:
            row["installed_anthropic"] = installed
        if isinstance(proxy, dict):
            pin_sha = str(proxy.get("provider_pin_sha256") or "").strip()
            if pin_sha:
                row["provider_pin_sha256"] = pin_sha
            source = str(proxy.get("pin_source") or "").strip()
            if source:
                row["pin_source"] = source
        versions = observed.get("versions")
        if isinstance(versions, dict):
            row["provider_versions"] = versions
        loaded = observed.get("loaded") or (None, "none", "")
        version, loaded_source, _path = loaded
        if loaded_source not in _LOADED_SOURCES:
            loaded_source = "none"
        if not version:
            # Bundled provider: strace sees no package open, so read the
            # version compiled into the binary.
            bundled = _embedded_version(exe)
            if bundled:
                version, loaded_source = bundled, "embedded"
        row["provider_loaded_source"] = loaded_source
        row["probe_method"] = loaded_source if loaded_source in ("strace", "embedded") else ""
        if version:
            row["provider_loaded_version"] = version
        pin = _anthropic_pin(proxy) if isinstance(proxy, dict) else ""
        mismatch = _loaded_mismatch_text(pin, version, loaded_source)
        if mismatch:
            row = _attach_loaded_mismatch(row, mismatch)
        return row

    def _observe(output_text=""):
        if observed["done"]:
            return
        observed["done"] = True
        text = output_text or captured["text"]
        if not text:
            text = _proc_text(proc)
            if text:
                captured["text"] = text
        observed["loaded"] = _loaded_provider_version(env, text)
        observed["drift"] = _provider_sdk_drift(env, proxy)
        observed["installed"] = _installed_provider_sdk(env, proxy)
        observed["versions"] = _resolved_provider_versions(env, proxy)
        _preserve_opencode_evidence(env)

    turn_state = {"mode": None, "exit": None, "failure": None}

    def _finish(row):
        text = row.get("full_output") or row.get("output_tail") or ""
        if text:
            captured["text"] = text
        _observe(captured["text"])
        mode = os.environ.get("OBENCH_OPENCODE_MODE", "").strip()
        if mode:
            row["agent_mode"] = mode
        if turn_state["mode"]:
            row["turn_mode"] = turn_state["mode"]
        if turn_state["exit"] is not None:
            row["turn1_exit"] = turn_state["exit"]
        if turn_state["failure"]:
            row["failure_class"] = "infra"
            row["completed"] = False
            row["error"] = turn_state["failure"]
        pin_error = row.get("error")
        if isinstance(pin_error, str) and pin_error.startswith("provider_pin_mismatch"):
            row["failure_class"] = "infra"
            row["completed"] = False
            row["error"] = pin_error
            row["sdk_drift"] = pin_error
            _write_agent_output(row.get("full_output") or row.get("output_tail") or "")
            return _stamp(row)
        _write_agent_output(row.get("full_output") or row.get("output_tail") or "")
        stamped = _stamp(_attach_sdk_drift(row, observed["drift"]))
        return stamped
    exe = _exe()
    try:
        _install_global_agents(env)
        _provision_lsp(env, workdir)
    except Exception as exc:  # noqa: BLE001 - a missing toolchain is a cell error, not a crash
        stopped = _lsp_failure(exc, iso_home)
        if stopped is not None:
            return stopped
        raise
    probe = bool(os.environ.get("OBENCH_OPENCODE_BIN", "").strip()) or model == "claude-opus-5-5"
    watch_prompt = False
    if model in MODELS:
        if model == "claude-opus-4-8" and not _has_anthropic_oauth():
            shutil.rmtree(iso_home, ignore_errors=True)
            return {"completed": False,
                    "error": f"SETUP-NEEDED: run `opencode auth login -p anthropic` (missing {_ANTHROPIC_AUTH})",
                    "output_tail": "", "tokens": None, "turns": None, "cmd": None,
                    **_empty_token_usage()}
        variant = _VARIANT.get(model)
        try:
            proxy = _proxy_override() if model == "claude-opus-5-5" else None
        except ValueError as exc:
            shutil.rmtree(iso_home, ignore_errors=True)
            return {"completed": False, "error": str(exc),
                    "output_tail": "", "tokens": None, "turns": None, "cmd": None,
                    **_empty_token_usage()}
        model_flag = proxy["model_ref"] if proxy else MODELS[model]
        if probe:
            cmd, watch_prompt = _build_cmd(
                exe, model_flag, variant, workdir, instruction,
                _run_help(exe, timeout_s),
            )
        else:
            cmd = [
                exe, "run",
                "--dir", workdir,
                "-m", model_flag,
                # xai rejects --variant with a server error (grok-4.5 has no
                # selectable effort); omit the flag when the map holds None.
                *(["--variant", variant] if variant else []),
                "--auto",
                "--format", "json",
                "--title", "openbench",
                instruction,
            ]
        if cmd is None:
            shutil.rmtree(iso_home, ignore_errors=True)
            return {"completed": False,
                    "error": "opencode run has no model flag",
                    "output_tail": "", "tokens": None, "turns": None, "cmd": None,
                    **_empty_token_usage()}
        env.pop("OPENAI_API_KEY", None)  # force subscription OAuth route
        if model == "claude-opus-4-8":
            env.pop("ANTHROPIC_API_KEY", None)  # force Anthropic OAuth route
        if proxy:
            env["ANTHROPIC_API_KEY"] = str(proxy.get("api_key") or "proxy")
            # Both routes: config baseURL (from compat) and the env var.
            if proxy.get("base_url"):
                env["ANTHROPIC_BASE_URL"] = reachable_proxy_base(str(proxy.get("base_url")))
            else:
                env.pop("ANTHROPIC_BASE_URL", None)
            env.pop("VERTEX_LOCATION", None)
            # Builds from late 2025 drop any models.dev entry with an
            # ``experimental`` key from ``run`` (provider.ts filter). Today's
            # registry tags claude-opus-5-5 that way (fast mode), so those
            # builds exit 1 with ProviderModelNotFoundError and print usage.
            env["OPENCODE_ENABLE_EXPERIMENTAL_MODELS"] = "1"
            installed_anthropic = _ensure_provider_sdk(env, proxy) or ""
        elif model == "claude-opus-5-5" and not env.get("VERTEX_LOCATION"):
            env["VERTEX_LOCATION"] = "global"
        try:
            _install_config(env, _config_body(watch_prompt))
        except (ValueError, Exception) as exc:
            stopped = _lsp_failure(exc, iso_home, cmd)
            if stopped is not None:
                return _stamp(stopped)
            if not isinstance(exc, ValueError):
                raise
            shutil.rmtree(iso_home, ignore_errors=True)
            return _stamp({"completed": False, "error": str(exc),
                    "output_tail": "", "tokens": None, "turns": None, "cmd": cmd,
                    **_empty_token_usage()})
    elif model in OPEN_MODELS:
        spec, detail = _resolve_open_spec(model, OPEN_MODELS[model])
        if detail:
            shutil.rmtree(iso_home, ignore_errors=True)
            return _setup_needed(OPEN_MODELS[model].get("env_key") or "", model, detail)
        model_id = f'{spec["provider"]}/{spec["model_id"]}'
        variant = spec.get("variant")
        if probe:
            cmd, watch_prompt = _build_cmd(
                exe, model_id, variant, workdir, instruction,
                _run_help(exe, timeout_s),
            )
        else:
            cmd = [exe, "run", "--dir", workdir, "-m", model_id]
            if variant:
                cmd.extend(["--variant", variant])
            cmd.extend([
                "--auto",
                "--format", "json",
                "--title", "openbench",
                instruction,
            ])
        if cmd is None:
            shutil.rmtree(iso_home, ignore_errors=True)
            return {"completed": False,
                    "error": "opencode run has no model flag",
                    "output_tail": "", "tokens": None, "turns": None, "cmd": None,
                    **_empty_token_usage()}
        try:
            env["OPENCODE_CONFIG_CONTENT"] = _open_config_content(spec)
            _install_config(env, _config_body(watch_prompt))
        except (ValueError, Exception) as exc:
            stopped = _lsp_failure(exc, iso_home, cmd)
            if stopped is not None:
                return stopped
            if not isinstance(exc, ValueError):
                raise
            shutil.rmtree(iso_home, ignore_errors=True)
            return {"completed": False, "error": str(exc),
                    "output_tail": "", "tokens": None, "turns": None, "cmd": cmd,
                    **_empty_token_usage()}
    else:
        shutil.rmtree(iso_home, ignore_errors=True)
        return _unsupported(model)

    turn_help = _run_help(exe, timeout_s) if os.environ.get("OBENCH_OPENCODE_BIN", "").strip() else ""
    prompts, two_turn = _prompts_for(instruction, turn_help)
    cmd = list(cmd)
    cmd[-1] = prompts[0]
    if _split_turns(instruction) and not two_turn:
        turn_state["mode"] = "single"

    proc = None
    try:
        try:
            preflight = _sdk_preflight_failure(env, proxy, cmd) if isinstance(proxy, dict) else None
            if preflight is not None:
                return _finish(preflight)
            block = _provider_pin_block(env, proxy)
            if block:
                return _finish({
                    "completed": False,
                    "failure_class": "infra",
                    "error": block,
                    "output_tail": "",
                    "full_output": "",
                    "tokens": None,
                    "turns": None,
                    "cmd": cmd,
                    **_empty_token_usage(),
                })
            proc = _invoke(cmd, workdir, env, timeout_s, watch_prompt)
            if two_turn and len(prompts) == 2:
                turn_state["exit"] = proc.returncode
                if proc.returncode != 0:
                    turn_state["mode"] = "turn-failure"
                    turn_state["failure"] = (
                        f"turn 1 exited {proc.returncode}; turn 2 was not run"
                    )
                else:
                    session_id = _extract_session_id((proc.stdout or "") + (proc.stderr or ""))
                    has_session, has_continue = _session_flags(turn_help)
                    extra = []
                    if has_session and session_id:
                        extra = ["--session", session_id]
                    elif has_continue:
                        extra = ["--continue"]
                    if extra:
                        turn_state["mode"] = "two-turn"
                        cmd = list(cmd[:-1]) + extra + [prompts[1]]
                        second = _invoke(cmd, workdir, env, timeout_s, watch_prompt)
                        proc = _combine_procs(proc, second)
                    else:
                        turn_state["mode"] = "turn-failure"
                        turn_state["failure"] = (
                            "turn 1 finished but the session could not be continued; "
                            "turn 2 was not run"
                        )
        except _PromptWait as e:
            if two_turn and turn_state["mode"] is None:
                turn_state["mode"] = "turn-failure"
            full_output = e.output or ""
            return _finish({
                "completed": False,
                "error": "waiting on a permission prompt",
                "output_tail": full_output[-2000:],
                "full_output": full_output,
                "tokens": None,
                "turns": None,
                "cmd": cmd,
                **_empty_token_usage(),
            })
        except _WatchdogKill as e:
            if two_turn and turn_state["mode"] is None:
                turn_state["mode"] = "turn-failure"
            full_output = e.output or ""
            return _finish({
                "completed": False,
                "error": e.text,
                "output_tail": full_output[-2000:],
                "full_output": full_output,
                "tokens": None,
                "turns": None,
                "cmd": cmd,
                **_empty_token_usage(),
            })
        except _provider_pin().ProviderPinMismatch as e:
            if two_turn and turn_state["mode"] is None:
                turn_state["mode"] = "turn-failure"
            full_output = e.output or ""
            return _finish({
                "completed": False,
                "failure_class": "infra",
                "env_failure": True,
                "env_cause": "provider_pin_mismatch",
                "error": e.reason or str(e),
                "output_tail": full_output[-2000:],
                "full_output": full_output,
                "tokens": None,
                "turns": None,
                "cmd": cmd,
                **_empty_token_usage(),
            })
        except subprocess.TimeoutExpired as e:
            if two_turn and turn_state["mode"] is None:
                turn_state["mode"] = "turn-failure"
            full_output = _err_tail(e, limit=None)
            return _finish({
                "completed": False,
                "error": f"timeout after {timeout_s}s",
                "output_tail": full_output[-2000:],
                "full_output": full_output,
                "tokens": None,
                "turns": None,
                "cmd": cmd,
                **_empty_token_usage(),
            })
    finally:
        # The cache and session live under the temp home. Read the pin, the
        # opened provider package, and copy storage/logs before that tree
        # is removed. On the success path the process output is still on
        # ``proc`` here; ``_finish`` runs after this block.
        if not observed["done"]:
            if not captured["text"]:
                captured["text"] = _proc_text(proc)
            _observe(captured["text"])
        if model in MODELS and auth_source is not None:
            isolated_auth = os.path.join(env["XDG_DATA_HOME"], "opencode", "auth.json")
            try_persist_auth_file(isolated_auth, auth_source)
        shutil.rmtree(iso_home, ignore_errors=True)

    combined = (proc.stdout or "") + (proc.stderr or "")
    violation = _provider_pin_violation(env, combined)
    if violation:
        return _finish({
            "completed": False,
            "failure_class": "infra",
            "error": violation,
            "output_tail": combined[-2000:],
            "full_output": combined,
            "tokens": None,
            "turns": None,
            "cmd": cmd,
            **_empty_token_usage(),
        })
    try:
        tokens, turns, tail, token_usage = _parse_json_with_usage(proc.stdout or "")
    except Exception:  # noqa: BLE001 - never let usage parsing break a run
        tokens, turns, tail, token_usage = None, None, "", _empty_token_usage()
    if not tail:
        tail = combined[-2000:]

    return _finish({
        "completed": proc.returncode == 0,
        "error": None if proc.returncode == 0 else f"exit {proc.returncode}",
        "output_tail": tail,
        # Optional (ADAPTER_SPEC v1): full untruncated stdout+stderr for the
        # runner's local transcript. LOCAL-ONLY; never published unscrubbed.
        "full_output": combined,
        "tokens": tokens,
        "turns": turns,
        "cmd": cmd,
        **token_usage,
    })
