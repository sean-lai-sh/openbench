"""Pi harness-comparison adapter (baseline arm).

Runs the pinned ``pi`` coding agent on its shipped defaults, with model traffic
pointed at the merged Vertex proxy. Pi's Anthropic SDK posts to
``${baseUrl}/v1/messages``, so ``models.json`` ``baseUrl`` is the cell proxy
*without* a ``/v1`` suffix.

This path does not use the proxy's OpenAI ``/v1/chat/completions`` translator.
The A/B study path (``OBENCH_PI_VERTEX`` on ``claude-opus-5-5``) stays in
``pi.py`` and wins when both are configured.

The fetch-wrapping extension is OpenBench instrumentation. It sets
``X-OB-Call-Role`` from the request's system text and does not change the body
or Pi's defaults. Pi seals provider headers before the payload hook, and
compaction calls the model stream directly, so the wrapper sits on
``globalThis.fetch``.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

PIN = "d0aa218cb16c333c008f6aa3dcd670ac8b68383c"
PIN_BRIEF = "d0aa218"
PACKAGE = "@earendil-works/pi-coding-agent"
PACKAGE_VERSION = "1.4.0"
# Tag v1.4.0 points at this commit. It is 60 commits behind PIN.
NPM_TAG_V140 = "4a080252f06caf63a525d7873c5d94d3c23887e0"
REPO = "https://github.com/earendil-works/pi"

COMPARISON_MODELS = ("claude-opus-5-5", "claude-sonnet-5-5")
PROVIDER = "anthropic"
API = "anthropic-messages"
WIRE_PATH = "/v1/messages"
CONTEXT_WINDOW = 1_000_000
MAX_TOKENS = 128_000
CALL_ROLE_HEADER = "X-OB-Call-Role"

# Shipped defaults at PIN. Not passed on the command line.
DEFAULT_TOOLS = ("read", "bash", "edit", "write")
BUILTIN_EXTENSIONS = ("llama.cpp", "codemode", "tool-search", "mcp")
DEFAULT_MAX_LINES = 2000
DEFAULT_MAX_BYTES = 50 * 1024
COMPACTION_RESERVE_TOKENS = 16384
COMPACTION_KEEP_RECENT_TOKENS = 20000
RETRY_MAX = 3
RETRY_BASE_DELAY_MS = 2000
PROVIDER_MAX_RETRIES = 0
THINKING_LEVEL = "medium"
MODEL_COMPAT = {
    "supportsMidConvoEffort": True,
    "supportsMidConvoSystemMessages": True,
    "supportsMidConvoToolChanges": True,
    "forceAdaptiveThinking": True,
    "supportsTemperature": False,
    "supportsStrictTools": True,
}

_SUMMARY_NEEDLE = "context summarization assistant"
_HELPER_NEEDLE = "file a bug report about pi"
_SUBAGENT_RE = re.compile(r"you are a sub-?agent", re.IGNORECASE)
_CELL_RE = re.compile(r"[A-Za-z0-9_.-]+")
_TOTAL_KEYS = ("calls", "input_uncached", "output", "cache_read", "cache_write")
_TRUTHY = {"1", "true", "yes", "on"}


class PinError(Exception):
    pass


def comparison_requested() -> bool:
    """True when the cell asked for this path.

    ``OBENCH_PI_VERTEX`` is not consulted here. ``pi.run`` checks that spec
    first and keeps the A/B path.
    """
    flag = os.environ.get("OBENCH_PI_HARNESS", "").strip().lower()
    if flag in _TRUTHY:
        return True
    return bool(os.environ.get("OBENCH_VERTEX_PROXY_URL", "").strip())


def cell_proxy_base(base_url: str, cell_id: str) -> str:
    """Cell proxy origin Pi should use as ``baseUrl`` (no ``/v1`` suffix)."""
    base = base_url.strip().rstrip("/")
    if base.endswith("/v1"):
        base = base[:-3]
    return f"{base}/c/{cell_id}"


def rewrite_loopback(url: str) -> str:
    """Point a host loopback proxy at the shared bridge origin inside a cell.

    The same function OpenCode uses. Host-network cells
    (``OBENCH_DOCKER_NETWORK=host``) keep ``127.0.0.1``.
    """
    from thesis.ab.proxy_bridge import proxy_origin_for_network, runtime_network

    return proxy_origin_for_network(url.strip(), runtime_network())


def call_role_for_system(system_text: str) -> str:
    """Role for one request's system text. User and assistant text stay out."""
    text = system_text or ""
    lowered = text.lower()
    if _SUMMARY_NEEDLE in lowered:
        return "side:summary"
    if _HELPER_NEEDLE in lowered:
        return "side:helper"
    if _SUBAGENT_RE.search(text):
        return "side:subagent"
    return "main"


def extension_source() -> str:
    """ESM extension: tag fetch calls, leave the body alone."""
    header = json.dumps(CALL_ROLE_HEADER)
    summary = json.dumps(_SUMMARY_NEEDLE)
    helper = json.dumps(_HELPER_NEEDLE)
    return f"""// OpenBench instrumentation. Tags the Anthropic system text only.
// A later main turn that quotes a summary in user or assistant text stays main.
const HEADER = {header};
const SUMMARY = {summary};
const HELPER = {helper};
const SUBAGENT = /you are a sub-?agent/i;

function systemText(body) {{
  const chunks = [];
  const system = body && body.system;
  if (typeof system === "string") chunks.push(system);
  else if (Array.isArray(system)) {{
    for (const part of system) {{
      if (typeof part === "string") chunks.push(part);
      else if (part && typeof part.text === "string") chunks.push(part.text);
    }}
  }}
  const messages = body && body.messages;
  if (Array.isArray(messages)) {{
    for (const message of messages) {{
      if (!message || message.role !== "system") continue;
      const content = message.content;
      if (typeof content === "string") chunks.push(content);
      else if (Array.isArray(content)) {{
        for (const part of content) {{
          if (part && typeof part.text === "string") chunks.push(part.text);
        }}
      }}
    }}
  }}
  return chunks.join("\\n");
}}

function textOf(body) {{
  if (typeof body === "string") return body;
  if (body instanceof Uint8Array) return new TextDecoder().decode(body);
  return "";
}}

function roleFor(init) {{
  if (!init || init.body == null) return "main";
  const raw = textOf(init.body);
  if (!raw || raw[0] !== "{{") return "main";
  let parsed;
  try {{
    parsed = JSON.parse(raw);
  }} catch (_err) {{
    return "main";
  }}
  const system = systemText(parsed).toLowerCase();
  if (system.includes(SUMMARY)) return "side:summary";
  if (system.includes(HELPER)) return "side:helper";
  if (SUBAGENT.test(system)) return "side:subagent";
  return "main";
}}

const originalFetch = globalThis.fetch;
if (typeof originalFetch === "function" && !globalThis.__obenchPiCallRole) {{
  globalThis.__obenchPiCallRole = true;
  globalThis.fetch = function obenchPiFetch(input, init) {{
    try {{
      if (init && init.body != null) {{
        const headers = new Headers(init.headers);
        if (!headers.has(HEADER)) headers.set(HEADER, roleFor(init));
        init = Object.assign({{}}, init, {{ headers }});
      }}
    }} catch (_err) {{
      /* keep the original request */
    }}
    return originalFetch.call(this, input, init);
  }};
}}

export default function obenchCallRole() {{}}
"""


def build_command(binary: str, instruction: str, model: str, extension_path: str) -> list[str]:
    """Headless argv. Shipped thinking, tools, and extensions stay in place."""
    return [
        binary,
        "-p",
        instruction,
        "--mode", "json",
        "--no-approve",
        "-e", extension_path,
        "--provider", PROVIDER,
        "--model", model,
    ]


def models_document(cell_base: str, model_id: str) -> str:
    """``models.json`` body. ``cell_base`` must not end in ``/v1``."""
    if model_id == "claude-opus-5-5":
        name = "Claude Opus 5.5"
    elif model_id == "claude-sonnet-5-5":
        name = "Claude Sonnet 5.5"
    else:
        name = model_id
    document = {
        "providers": {
            PROVIDER: {
                "baseUrl": cell_base,
                "apiKey": "proxy",
                "api": API,
                "auth": "apiKey",
                "models": [{
                    "id": model_id,
                    "name": name,
                    "api": API,
                    "reasoning": True,
                    "input": ["text", "image"],
                    "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
                    "contextWindow": CONTEXT_WINDOW,
                    "maxTokens": MAX_TOKENS,
                    # Same compat the pinned pi-ai catalog ships for the
                    # built-in claude-{opus,sonnet}-5-5. Without
                    # forceAdaptiveThinking Pi sends thinking.type "enabled",
                    # which Vertex rejects for these models (400).
                    "compat": dict(MODEL_COMPAT),
                }],
            }
        }
    }
    return json.dumps(document, indent=2) + "\n"


def planned_settings(model: str, timeout_s: int, cell_base: str, binary: str, pin_file: str) -> dict:
    """Section-4 settings for one cell, before the process is observed."""
    return {
        "harness": "pi",
        "pin": PIN,
        "pin_brief": PIN_BRIEF,
        "pin_file": pin_file,
        "repo": REPO,
        "package": PACKAGE,
        "package_version_at_pin": PACKAGE_VERSION,
        "npm_tag_v1_4_0": NPM_TAG_V140,
        "npm_tag_is_pin": False,
        "binary": binary,
        "model": model,
        "provider": PROVIDER,
        "wire": {
            "api": API,
            "path": WIRE_PATH,
            "base_url": cell_base,
            "openai_chat_completions": False,
        },
        "thinking": {
            "level": THINKING_LEVEL,
            "argv_override": False,
            "model_reasoning": True,
        },
        "temperature": None,
        "tools": list(DEFAULT_TOOLS),
        "tools_argv_override": False,
        "built_in_extensions": list(BUILTIN_EXTENSIONS),
        "shell_timeout_s": None,
        "output_max_lines": DEFAULT_MAX_LINES,
        "output_max_bytes": DEFAULT_MAX_BYTES,
        "read_max_lines": DEFAULT_MAX_LINES,
        "read_max_bytes": DEFAULT_MAX_BYTES,
        "compaction": {
            "enabled": True,
            "reserve_tokens": COMPACTION_RESERVE_TOKENS,
            "keep_recent_tokens": COMPACTION_KEEP_RECENT_TOKENS,
        },
        "subagents": False,
        "permission_mode": "no-approve",
        "retry": {
            "enabled": True,
            "max_retries": RETRY_MAX,
            "base_delay_ms": RETRY_BASE_DELAY_MS,
            "provider_max_retries": PROVIDER_MAX_RETRIES,
        },
        "cell_cap_s": timeout_s,
        "call_role_header": CALL_ROLE_HEADER,
        "instrumentation": (
            "fetch wrapper sets X-OB-Call-Role from the system text only"
        ),
    }


def count_compactions(stdout: str) -> int:
    """Count ``compaction_end`` events that were not aborted."""
    found = 0
    for line in (stdout or "").splitlines():
        stripped = line.strip()
        if "compaction_end" not in stripped:
            continue
        try:
            event = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict) or event.get("type") != "compaction_end":
            continue
        if event.get("aborted") is True:
            continue
        found += 1
    return found


def _stem(cell_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", cell_id)


def totals_path(ledger_dir: str, cell_id: str) -> str:
    return os.path.join(ledger_dir, f"{_stem(cell_id)}.totals.json")


def settings_destination(cell_id: str, ledger_dir: str) -> str:
    override = os.environ.get("OBENCH_PI_SETTINGS_PATH", "").strip()
    if override:
        return override
    if ledger_dir and cell_id:
        return os.path.join(ledger_dir, f"{_stem(cell_id)}.settings.json")
    return ""


def _as_int(value, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label} must be an int")
    if value < 0:
        raise ValueError(f"{label} must be >= 0")
    return value


def parse_proxy_totals(payload: dict) -> dict:
    """``all``, ``main``, and ``side`` (all minus main) from a totals file.

    ``side`` is derived. A main bucket larger than all is rejected.
    """
    if not isinstance(payload, dict):
        raise ValueError("proxy totals must be an object")

    def bucket(name: str) -> dict:
        raw = payload.get(name)
        if not isinstance(raw, dict):
            raise ValueError(f"proxy totals missing {name}")
        return {key: _as_int(raw.get(key), f"{name}.{key}") for key in _TOTAL_KEYS}

    all_bucket = bucket("all")
    main_bucket = bucket("main")
    for key in _TOTAL_KEYS:
        if main_bucket[key] > all_bucket[key]:
            raise ValueError(f"main.{key} exceeds all.{key}")
    side = {key: all_bucket[key] - main_bucket[key] for key in _TOTAL_KEYS}
    return {"all": all_bucket, "main": main_bucket, "side": side}


def load_proxy_totals(ledger_dir: str, cell_id: str) -> dict:
    path = totals_path(ledger_dir, cell_id)
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return parse_proxy_totals(data)


def _write_json(path: str, payload: dict) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)
        fh.write("\n")
    os.replace(temporary, path)


def _pin_stamp_path(binary: str) -> str:
    explicit = os.environ.get("OBENCH_PI_PIN_FILE", "").strip()
    if explicit:
        return explicit
    if binary and os.path.isabs(binary):
        return binary + ".pin"
    return ""


def _require_pin(binary: str) -> str:
    if not binary:
        raise PinError("Pi harness comparison needs OBENCH_PI_BIN pointing at the pinned build")
    path = _pin_stamp_path(binary)
    if not path:
        raise PinError("Pi harness comparison needs OBENCH_PI_PIN_FILE when OBENCH_PI_BIN is not absolute")
    if not os.path.isfile(path):
        raise PinError(f"Pi pin stamp is missing ({path})")
    text = Path(path).read_text(encoding="utf-8").strip()
    if text != PIN:
        raise PinError(f"Pi pin stamp is {text!r}; the comparison pin is {PIN}")
    return path


def _pi_module():
    try:
        from obench.adapters import pi as pi_mod
        return pi_mod
    except ImportError:
        mod = sys.modules.get("bench_adapter_pi")
        if mod is None:
            raise
        return mod


def _fail(message: str) -> dict:
    try:
        empty = _pi_module()._empty_token_usage()
    except Exception:  # noqa: BLE001 - setup failures must still return a result
        empty = {}
    return {
        "completed": False,
        "error": message,
        "output_tail": "",
        "full_output": "",
        "tokens": None,
        "turns": None,
        "cmd": None,
        **empty,
    }


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


def run(instruction: str, workdir: str, model: str, timeout_s: int) -> dict:
    if model not in COMPARISON_MODELS:
        return _fail(f"Pi harness comparison does not run model {model!r}")
    if not comparison_requested():
        return _fail(
            "Pi harness comparison needs OBENCH_PI_HARNESS or OBENCH_VERTEX_PROXY_URL"
        )
    proxy = os.environ.get("OBENCH_VERTEX_PROXY_URL", "").strip()
    cell_id = os.environ.get("OBENCH_VERTEX_CELL_ID", "").strip()
    ledger_dir = os.environ.get("OBENCH_VERTEX_LEDGER_DIR", "").strip()
    if not proxy:
        return _fail("Pi harness comparison needs OBENCH_VERTEX_PROXY_URL")
    if not _CELL_RE.fullmatch(cell_id or ""):
        return _fail(
            "Pi harness comparison needs OBENCH_VERTEX_CELL_ID "
            "(letters, digits, dot, underscore, hyphen)"
        )
    binary = os.environ.get("OBENCH_PI_BIN", "").strip()
    try:
        pin_file = _require_pin(binary)
    except PinError as exc:
        return _fail(str(exc))

    cell_base = cell_proxy_base(rewrite_loopback(proxy), cell_id)
    pi = _pi_module()
    iso_home = tempfile.mkdtemp(prefix="pi_harness_home_")
    try:
        env = dict(os.environ)
        env["HOME"] = iso_home
        agent_dir = os.path.join(iso_home, ".pi", "agent")
        os.makedirs(agent_dir, exist_ok=True)
        env["PI_CODING_AGENT_DIR"] = agent_dir
        env.pop("PI_CODING_AGENT_SESSION_DIR", None)
        env.pop("PI_PACKAGE_DIR", None)
        with open(os.path.join(agent_dir, "models.json"), "w", encoding="utf-8") as fh:
            fh.write(models_document(cell_base, model))
        extension_path = os.path.join(iso_home, "obench-call-role.mjs")
        with open(extension_path, "w", encoding="utf-8") as fh:
            fh.write(extension_source())
        cmd = build_command(binary, instruction, model, extension_path)
        stdout_text, stderr_text, returncode, stop = pi._run_streaming(
            cmd, workdir, timeout_s, env,
        )
        combined = stdout_text + stderr_text
        turn_error = None if stop else pi._last_turn_error(stdout_text)
        if stop:
            error = pi._timeout_error(stop, timeout_s)
            completed = False
        elif turn_error:
            error = turn_error
            completed = False
        else:
            error = None if returncode == 0 else f"exit {returncode}"
            completed = returncode == 0
        tokens, turns, tail, token_usage = pi._parse_json_with_usage(stdout_text)
        if not tail:
            tail = combined[-2000:]
        totals, totals_error = _observe_totals(ledger_dir, cell_id)
        settings = planned_settings(model, timeout_s, cell_base, binary, pin_file)
        settings["compactions_fired"] = count_compactions(stdout_text)
        settings["turns"] = turns
        settings["proxy_totals"] = totals
        settings["proxy_totals_error"] = totals_error
        settings["side_calls"] = None if totals is None else totals["side"]["calls"]
        destination = settings_destination(cell_id, ledger_dir)
        if destination:
            _write_json(destination, settings)
        result = {
            "completed": completed,
            "error": error,
            "output_tail": tail,
            "full_output": combined,
            "tokens": tokens,
            "turns": turns,
            "cmd": cmd,
            "model_context_window": CONTEXT_WINDOW,
            "model_max_tokens": MAX_TOKENS,
            "harness_settings": settings,
            **token_usage,
        }
        if stop == "tool":
            result["failure_class"] = "timeout"
        return result
    finally:
        shutil.rmtree(iso_home, ignore_errors=True)
