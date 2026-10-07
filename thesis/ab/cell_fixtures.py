"""Per-PR trigger fixtures read from the task map.

The ``options`` column is a semicolon-separated list of ``key=value`` pairs.
``run_ab --task-map`` copies those pairs onto each cell for that PR. Empty
options are allowed. A typo is an error so a misspelled flag is not skipped.
"""

from __future__ import annotations

import json
import struct
import threading
import zlib
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# OpenCode session/compaction.ts isOverflow, PR 4838
# (aaa31f02af5cd1d90e11549ee7b291e2f2a913d2): usable context is
# limit.context minus min(limit.output, OUTPUT_TOKEN_MAX). OUTPUT_TOKEN_MAX
# is 32_000. The counted total is input + cache.read + output.
OUTPUT_TOKEN_MAX = 32_000

_FAULTS = frozenset({"http-529", "http-429", "sse-server-error"})
_LSP = frozenset({"pyright", "typescript", "dotnet"})
_MODALITIES = frozenset({"image"})
_WEBFETCH = frozenset({"local"})
_KEYS = frozenset({
    "context", "fault", "mode", "permissions", "global-agents", "lsp",
    "modalities", "webfetch",
})

# The task instruction contains this token. The cell replaces it with the
# local server URL so the prompt never depends on a public image host.
WEBFETCH_PLACEHOLDER = "__OBENCH_WEBFETCH_URL__"
FIXTURE_COLOUR = "red"

# Zod at PR 3052 requires both arrays when ``modalities`` is present.
# The read tool only checks that input includes "image".
IMAGE_MODALITIES = {"input": ["text", "image"], "output": ["text"]}


class FixtureError(ValueError):
    pass


@dataclass(frozen=True)
class CellFixtures:
    context: int | None = None
    fault: str | None = None
    mode: str | None = None
    permissions: str | None = None
    global_agents: bool = False
    lsp: tuple[str, ...] = ()
    modalities: str | None = None
    webfetch: str | None = None

    def as_text(self) -> str:
        parts: list[str] = []
        if self.context is not None:
            parts.append(f"context={self.context}")
        if self.fault:
            parts.append(f"fault={self.fault}")
        if self.mode:
            parts.append(f"mode={self.mode}")
        if self.permissions:
            parts.append(f"permissions={self.permissions}")
        if self.global_agents:
            parts.append("global-agents=1")
        if self.lsp:
            parts.append("lsp=" + ",".join(self.lsp))
        if self.modalities:
            parts.append(f"modalities={self.modalities}")
        if self.webfetch:
            parts.append(f"webfetch={self.webfetch}")
        return " ".join(parts)

    def payload(self) -> dict:
        return {
            "context": self.context,
            "fault": self.fault,
            "mode": self.mode,
            "permissions": self.permissions,
            "global_agents": self.global_agents,
            "lsp": list(self.lsp),
            "modalities": self.modalities,
            "webfetch": self.webfetch,
        }


def parse_options(text: str) -> CellFixtures:
    """Parse one task-map ``options`` cell. Blank means no fixtures."""
    raw = (text or "").strip()
    if not raw:
        return CellFixtures()
    found: dict[str, str] = {}
    for piece in raw.split(";"):
        item = piece.strip()
        if not item:
            continue
        if "=" not in item:
            raise FixtureError(f"option {item!r} must be key=value")
        key, value = item.split("=", 1)
        key = key.strip()
        value = value.strip()
        if key not in _KEYS:
            raise FixtureError(f"unknown option {key!r}")
        if key in found:
            raise FixtureError(f"duplicate option {key}")
        if not value:
            raise FixtureError(f"option {key} has an empty value")
        found[key] = value
    context = None
    if "context" in found:
        try:
            context = int(found["context"])
        except ValueError as exc:
            raise FixtureError(f"context must be an integer, got {found['context']!r}") from exc
        if context < 1:
            raise FixtureError("context must be >= 1")
    fault = found.get("fault")
    if fault is not None and fault not in _FAULTS:
        raise FixtureError(f"unknown fault {fault!r}")
    permissions = found.get("permissions")
    if permissions is not None and permissions != "workspace":
        raise FixtureError(f"unknown permissions mode {permissions!r}")
    global_agents = False
    if "global-agents" in found:
        if found["global-agents"] != "1":
            raise FixtureError("global-agents must be 1")
        global_agents = True
    lsp: tuple[str, ...] = ()
    if "lsp" in found:
        names = tuple(part.strip() for part in found["lsp"].split(",") if part.strip())
        if not names:
            raise FixtureError("lsp names no server")
        unknown = [name for name in names if name not in _LSP]
        if unknown:
            raise FixtureError("unknown lsp " + ", ".join(unknown))
        lsp = names
    modalities = found.get("modalities")
    if modalities is not None and modalities not in _MODALITIES:
        raise FixtureError(f"unknown modalities {modalities!r}")
    webfetch = found.get("webfetch")
    if webfetch is not None and webfetch not in _WEBFETCH:
        raise FixtureError(f"unknown webfetch {webfetch!r}")
    return CellFixtures(
        context=context,
        fault=fault,
        mode=found.get("mode"),
        permissions=permissions,
        global_agents=global_agents,
        lsp=lsp,
        modalities=modalities,
        webfetch=webfetch,
    )


def compaction_usable(context: int, output_limit: int, output_cap: int = OUTPUT_TOKEN_MAX) -> int:
    """Tokens isOverflow will allow before compacting.

    Mirrors ``min(limit.output, OUTPUT_TOKEN_MAX)`` subtracted from
    ``limit.context``. A context of 0 disables compaction in OpenCode; this
    helper still returns the arithmetic result so callers can show it.
    """
    output = min(int(output_limit), int(output_cap)) or int(output_cap)
    return int(context) - output


def compaction_overflow(context: int, output_limit: int, counted: int, output_cap: int = OUTPUT_TOKEN_MAX) -> bool:
    """True when ``counted`` (input + cache.read + output) exceeds usable context."""
    if int(context) == 0:
        return False
    return int(counted) > compaction_usable(context, output_limit, output_cap)


def apply_context_limit(config: dict, limit: int) -> dict:
    """Return a copy of an OpenCode config with every model context limit set.

    The output limit is left as it was. A config with no model entry gets the
    proxy route's ``anthropic/claude-opus-5-5`` entry so the override still
    lands on the model the cell runs.
    """
    if limit < 1:
        raise FixtureError("context must be >= 1")
    body = json.loads(json.dumps(config or {}))
    if not isinstance(body, dict):
        raise FixtureError("config must be an object")
    providers = body.get("provider")
    if not isinstance(providers, dict) or not providers:
        body["provider"] = {
            "anthropic": {
                "models": {
                    "claude-opus-5-5": {
                        "name": "Claude Opus 5.5",
                        "limit": {"context": int(limit), "output": 128000},
                    }
                }
            }
        }
        return body
    wrote = False
    for provider in providers.values():
        if not isinstance(provider, dict):
            continue
        models = provider.get("models")
        if not isinstance(models, dict):
            continue
        for model in models.values():
            if not isinstance(model, dict):
                continue
            current = model.get("limit")
            if not isinstance(current, dict):
                current = {}
                model["limit"] = current
            current["context"] = int(limit)
            wrote = True
    if not wrote:
        raise FixtureError("config has no model entry to override")
    return body


def apply_image_modalities(config: dict) -> dict:
    """Return a copy whose models accept image input.

    PR 3052's read tool attaches a PNG only when ``modalities.input`` includes
    ``image``. The default is text-only, which takes the error branch. The
    object includes ``output: ["text"]`` because the model schema requires
    both arrays once ``modalities`` is set. Other model fields, including
    ``limit``, are left in place.
    """
    body = json.loads(json.dumps(config or {}))
    if not isinstance(body, dict):
        raise FixtureError("config must be an object")
    modalities = json.loads(json.dumps(IMAGE_MODALITIES))
    providers = body.get("provider")
    if not isinstance(providers, dict) or not providers:
        body["provider"] = {
            "anthropic": {
                "models": {
                    "claude-opus-5-5": {
                        "name": "Claude Opus 5.5",
                        "limit": {"context": 1000000, "output": 128000},
                        "modalities": modalities,
                    }
                }
            }
        }
        return body
    wrote = False
    for provider in providers.values():
        if not isinstance(provider, dict):
            continue
        models = provider.get("models")
        if not isinstance(models, dict):
            continue
        for model in models.values():
            if not isinstance(model, dict):
                continue
            model["modalities"] = json.loads(json.dumps(IMAGE_MODALITIES))
            wrote = True
    if not wrote:
        raise FixtureError("config has no model entry to override")
    return body


def _png_rgb(red: int, green: int, blue: int) -> bytes:
    """One uncompressed RGB pixel, so the dominant colour is unambiguous."""
    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    raw = b"\x00" + bytes((red, green, blue))
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


RED_PNG = _png_rgb(255, 0, 0)


class _PngHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler name
        path = self.path.split("?", 1)[0]
        if path != "/color.png":
            self.send_error(404)
            return
        body = RED_PNG
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        return


class LocalPngServer:
    """Serve the fixture PNG on 127.0.0.1 with no external network.

    OpenCode's webfetch image branch (PR 13331) returns
    ``Image fetched successfully`` only when the response content-type is
    ``image/*`` and not SVG. Each cell binds port 0 so parallel cells do not
    share a port.
    """

    def __init__(self) -> None:
        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), _PngHandler)
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        self._closed = False

    @property
    def url(self) -> str:
        host, port = self._httpd.server_address
        return f"http://{host}:{port}/color.png"

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._httpd.shutdown()
        self._httpd.server_close()
        self._thread.join(timeout=5)


def bind_local_webfetch(env: dict, fixtures: dict | None) -> LocalPngServer | None:
    """Start the PNG server when this cell's options say ``webfetch=local``."""
    body = fixtures if isinstance(fixtures, dict) else {}
    kind = str(body.get("webfetch") or "").strip()
    if kind != "local":
        env.pop("OBENCH_OPENCODE_WEBFETCH_URL", None)
        return None
    server = LocalPngServer()
    env["OBENCH_OPENCODE_WEBFETCH_URL"] = server.url
    return server
