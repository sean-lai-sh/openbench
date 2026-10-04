"""Custom model file for one Pi or Oh My Pi checkout.

Pi reads ``~/.pi/agent/models.json`` from v0.9.4 on. The v0.10 schema requires
``id``, ``name``, ``reasoning``, ``input``, ``cost``, ``contextWindow``,
``maxTokens``, and a provider ``baseUrl`` plus ``apiKey``. Later checkouts
made some of those optional and added ``compat.supportsStrictTools``. Oh My
Pi reads ``models.yml`` with the same fields. The file written here is the
required early shape, plus strict tools only when that checkout's source
names the field.
"""

from __future__ import annotations

import json
from pathlib import Path

PROVIDER = "vertex-anthropic"
MODEL_ID = "claude-opus-5-5"
CONTEXT = 1_000_000
MAX_TOKENS = 128_000


def _src_files(root: Path):
    src = root / "packages" / "coding-agent" / "src"
    if not src.is_dir():
        return
    for path in src.rglob("*"):
        if not path.is_file() or path.suffix not in {".ts", ".js", ".mjs"}:
            continue
        if "node_modules" in path.parts:
            continue
        yield path


def _read(path: Path) -> str:
    if path.stat().st_size > 2_000_000:
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def supports_custom_models(root: Path) -> bool:
    for path in _src_files(root):
        text = _read(path)
        if "models.json" in text or "models.yml" in text:
            return True
    return False


def supports_strict_tools(root: Path) -> bool:
    bases = (root / "packages" / "coding-agent", root / "packages" / "ai")
    for base in bases:
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix not in {".ts", ".tsx", ".js", ".mjs", ".md"}:
                continue
            if "node_modules" in path.parts or "dist" in path.parts:
                continue
            if "supportsStrictTools" in _read(path):
                return True
    return False


def model_document(root: Path, proxy_base: str, filename: str) -> str:
    """Return the models file body for ``proxy_base`` (no ``/v1`` suffix)."""
    model = {
        "id": MODEL_ID,
        "name": "Claude Opus 5.5",
        "api": "anthropic-messages",
        "reasoning": True,
        "input": ["text", "image"],
        "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
        "contextWindow": CONTEXT,
        "maxTokens": MAX_TOKENS,
    }
    if supports_strict_tools(root):
        model["compat"] = {"supportsStrictTools": True}
    provider = {
        "baseUrl": proxy_base,
        "apiKey": "proxy",
        "api": "anthropic-messages",
        "models": [model],
    }
    document = {"providers": {PROVIDER: provider}}
    if filename.endswith(".yml") or filename.endswith(".yaml"):
        return _yaml(document)
    return json.dumps(document, indent=2) + "\n"


def _yaml_value(value, indent: int) -> str:
    pad = "  " * indent
    if isinstance(value, dict):
        lines = []
        for key, item in value.items():
            if isinstance(item, (dict, list)):
                lines.append(f"{pad}{key}:")
                lines.append(_yaml_value(item, indent + 1))
            elif isinstance(item, bool):
                lines.append(f"{pad}{key}: {'true' if item else 'false'}")
            elif isinstance(item, str):
                lines.append(f"{pad}{key}: {json.dumps(item)}")
            else:
                lines.append(f"{pad}{key}: {item}")
        return "\n".join(lines)
    if isinstance(value, list):
        lines = []
        for item in value:
            if isinstance(item, dict):
                rendered = _yaml_value(item, indent + 1).splitlines()
                head = rendered[0].lstrip()
                lines.append(f"{pad}- {head}")
                lines.extend(rendered[1:])
            else:
                text = json.dumps(item) if isinstance(item, str) else str(item)
                lines.append(f"{pad}- {text}")
        return "\n".join(lines)
    return f"{pad}{value}"


def _yaml(document: dict) -> str:
    return _yaml_value(document, 0) + "\n"
