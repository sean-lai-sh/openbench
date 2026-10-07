"""Per-PR trigger fixtures read from the task map.

The ``options`` column is a semicolon-separated list of ``key=value`` pairs.
``run_ab --task-map`` copies those pairs onto each cell for that PR. Empty
options are allowed. A typo is an error so a misspelled flag is not skipped.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

# OpenCode session/compaction.ts isOverflow, PR 4838
# (aaa31f02af5cd1d90e11549ee7b291e2f2a913d2): usable context is
# limit.context minus min(limit.output, OUTPUT_TOKEN_MAX). OUTPUT_TOKEN_MAX
# is 32_000. The counted total is input + cache.read + output.
OUTPUT_TOKEN_MAX = 32_000

_FAULTS = frozenset({"http-529", "http-429", "sse-server-error"})
_LSP = frozenset({"pyright", "typescript", "dotnet"})
_KEYS = frozenset({"context", "fault", "mode", "permissions", "global-agents", "lsp"})


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
        return " ".join(parts)

    def payload(self) -> dict:
        return {
            "context": self.context,
            "fault": self.fault,
            "mode": self.mode,
            "permissions": self.permissions,
            "global_agents": self.global_agents,
            "lsp": list(self.lsp),
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
    return CellFixtures(
        context=context,
        fault=fault,
        mode=found.get("mode"),
        permissions=permissions,
        global_agents=global_agents,
        lsp=lsp,
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
