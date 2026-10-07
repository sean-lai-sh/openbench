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

try:
    from obench.auth_persist import try_persist_auth_file
except ImportError:  # file-path / Docker mount layout
    from auth_persist import try_persist_auth_file

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
    ``version`` is missing or differs from ``CACHE_VERSION`` in
    ``packages/opencode/src/global/index.ts``. The next launch then installs
    ``@ai-sdk/anthropic`` at the dist-tag, which is not the pin.
    """
    text = str(version or "").strip()
    if not text:
        return
    with open(os.path.join(cache, "version"), "w", encoding="utf-8") as fh:
        fh.write(text)


def _ensure_provider_sdk(env, proxy):
    if not proxy.get("needs_sdk"):
        return ""
    # Default auth plugins (`opencode-anthropic-auth`, `opencode-copilot-auth`)
    # run `bun add --force` and re-resolve the dist-tag in package.json. That
    # upgrades a pinned @ai-sdk/anthropic to whatever "latest" is today.
    env["OPENCODE_DISABLE_DEFAULT_PLUGINS"] = "1"
    pin = str(proxy.get("anthropic_sdk") or "").strip()
    if not pin or pin == "latest":
        return ""
    bun = _resolve_bun(proxy.get("bun"))
    if not bun:
        return ""
    cache = os.path.join(env["XDG_CACHE_HOME"], "opencode")
    os.makedirs(cache, exist_ok=True)
    module = os.path.join(cache, "node_modules", "@ai-sdk", "anthropic", "package.json")
    if _installed_sdk_version(module) != pin:
        subprocess.run(
            [bun, "add", f"@ai-sdk/anthropic@{pin}"],
            cwd=cache,
            env=env,
            stdin=subprocess.DEVNULL,
            timeout=120,
            check=False,
        )
    pkg_path = os.path.join(cache, "package.json")
    parsed = {}
    if os.path.isfile(pkg_path):
        try:
            with open(pkg_path, encoding="utf-8") as fh:
                parsed = json.loads(fh.read())
        except (OSError, json.JSONDecodeError):
            parsed = {}
    if not isinstance(parsed, dict):
        parsed = {}
    deps = parsed.get("dependencies")
    if not isinstance(deps, dict):
        deps = {}
    # BunProc.install skips only when package.json stores the dist-tag this
    # binary passes ("latest", or "beta" on the July 2025 builds). The files
    # in node_modules stay on the pin.
    alias = str(proxy.get("sdk_install_alias") or "latest").strip() or "latest"
    recorded = alias if _installed_sdk_version(module) == pin else pin
    deps["@ai-sdk/anthropic"] = recorded
    parsed["dependencies"] = deps
    with open(pkg_path, "w", encoding="utf-8") as fh:
        json.dump(parsed, fh)
    _write_cache_version(cache, proxy.get("cache_version"))
    return _installed_sdk_version(module)


def _provider_sdk_drift(env, proxy):
    """Return an infra reason when the installed SDK no longer matches the pin."""
    if not isinstance(proxy, dict) or not proxy.get("needs_sdk"):
        return ""
    pin = str(proxy.get("anthropic_sdk") or "").strip()
    if not pin or pin == "latest":
        return ""
    module = os.path.join(
        env.get("XDG_CACHE_HOME") or "",
        "opencode", "node_modules", "@ai-sdk", "anthropic", "package.json",
    )
    installed = _installed_sdk_version(module)
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
    for name in ("opencode.db", "opencode.db-wal", "opencode.db-shm"):
        src = os.path.join(base, name)
        if not os.path.isfile(src):
            continue
        try:
            shutil.copy2(src, os.path.join(dest_root, name))
        except OSError:
            continue


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
                "--model", "-m",
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
    # Prefer --auto. Builds that still accept the older skip flag error on --auto.
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


def _config_body(include_permissions):
    body = {}
    raw = os.environ.get("OBENCH_OPENCODE_CONFIG_JSON", "").strip()
    if raw:
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError("OBENCH_OPENCODE_CONFIG_JSON must be a JSON object")
        body.update(parsed)
    flag = os.environ.get("OBENCH_OPENCODE_PERMISSION_CONFIG", "").strip()
    write_permissions = include_permissions and flag != "0"
    if flag == "1":
        write_permissions = True
    if write_permissions:
        body.setdefault("permission", dict(_ALLOW_PERMISSIONS))
    return body


def _install_config(env, body):
    if not body:
        return
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


def _kill_process_group(proc):
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        proc.kill()


def _invoke(cmd, cwd, env, timeout_s, watch_prompt):
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


def run(instruction: str, workdir: str, model: str, timeout_s: int) -> dict:
    auth_source = next((path for path in _AUTH_CANDIDATES if os.path.isfile(path)), None)
    env, iso_home = _isolated_env()
    installed_anthropic = ""
    proxy = None
    observed = {"done": False, "drift": ""}

    def _stamp(row):
        if installed_anthropic:
            row["installed_anthropic"] = installed_anthropic
        return row

    def _observe():
        if observed["done"]:
            return
        observed["done"] = True
        observed["drift"] = _provider_sdk_drift(env, proxy)
        _preserve_opencode_evidence(env)

    def _finish(row):
        _observe()
        return _stamp(_attach_sdk_drift(row, observed["drift"]))
    exe = _exe()
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
            if proxy.get("base_url_env"):
                env["ANTHROPIC_BASE_URL"] = str(proxy.get("base_url") or "")
            else:
                env.pop("ANTHROPIC_BASE_URL", None)
            env.pop("VERTEX_LOCATION", None)
            installed_anthropic = _ensure_provider_sdk(env, proxy) or ""
        elif model == "claude-opus-5-5" and not env.get("VERTEX_LOCATION"):
            env["VERTEX_LOCATION"] = "global"
        try:
            _install_config(env, _config_body(watch_prompt))
        except ValueError as exc:
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
        except ValueError as exc:
            shutil.rmtree(iso_home, ignore_errors=True)
            return {"completed": False, "error": str(exc),
                    "output_tail": "", "tokens": None, "turns": None, "cmd": cmd,
                    **_empty_token_usage()}
    else:
        shutil.rmtree(iso_home, ignore_errors=True)
        return _unsupported(model)

    try:
        try:
            proc = _invoke(cmd, workdir, env, timeout_s, watch_prompt)
        except _PromptWait as e:
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
        except subprocess.TimeoutExpired as e:
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
        # The cache and session live under the temp home. Read the pin and
        # copy storage/logs before that tree is removed.
        _observe()
        if model in MODELS and auth_source is not None:
            isolated_auth = os.path.join(env["XDG_DATA_HOME"], "opencode", "auth.json")
            try_persist_auth_file(isolated_auth, auth_source)
        shutil.rmtree(iso_home, ignore_errors=True)

    combined = (proc.stdout or "") + (proc.stderr or "")
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
