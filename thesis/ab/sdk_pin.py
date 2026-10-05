from __future__ import annotations

import json
import re
from pathlib import Path

_TRAILING_COMMA = re.compile(r",(\s*[}\]])")
_INDEX: dict[str, str] | None = None


def load_jsonc(text: str) -> dict:
    previous = None
    while previous != text:
        previous = text
        text = _TRAILING_COMMA.sub(r"\1", text)
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise json.JSONDecodeError("lockfile is not an object", text, 0)
    return parsed


def version_sort_key(version: str) -> tuple:
    main, sep, pre = version.strip().partition("-")
    nums = []
    for part in main.split("."):
        if part.isdigit():
            nums.append(int(part))
        else:
            break
    if not sep:
        return (tuple(nums), 1, ())
    pieces = []
    for piece in pre.split("."):
        if piece.isdigit():
            pieces.append((0, int(piece), ""))
        else:
            pieces.append((1, 0, piece))
    return (tuple(nums), 0, tuple(pieces))


def _entry(packages: dict, name: str) -> tuple[str | None, str | None]:
    entry = packages.get(name)
    if not isinstance(entry, list) or not entry or not isinstance(entry[0], str):
        return None, None
    ident = entry[0]
    version = ident.rsplit("@", 1)[1] if "@" in ident else None
    meta = entry[2] if len(entry) > 2 and isinstance(entry[2], dict) else {}
    deps = meta.get("dependencies") if isinstance(meta.get("dependencies"), dict) else {}
    provider = deps.get("@ai-sdk/provider")
    if not isinstance(provider, str) or not provider.strip():
        provider = None
    else:
        provider = provider.strip()
    return version, provider


def npm_anthropic_provider_index() -> dict[str, str]:
    global _INDEX
    if _INDEX is not None:
        return _INDEX
    import urllib.request
    request = urllib.request.Request(
        "https://registry.npmjs.org/@ai-sdk/anthropic",
        headers={"Accept": "application/json", "User-Agent": "openbench"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        payload = json.load(response)
    index: dict[str, str] = {}
    versions = payload.get("versions") if isinstance(payload, dict) else None
    if isinstance(versions, dict):
        for version, info in versions.items():
            if not isinstance(info, dict):
                continue
            deps = info.get("dependencies") if isinstance(info.get("dependencies"), dict) else {}
            provider = deps.get("@ai-sdk/provider")
            if isinstance(provider, str) and provider.strip():
                index[str(version)] = provider.strip()
    _INDEX = index
    return index


def select_anthropic_pin(lock: dict, registry: dict[str, str] | None = None) -> str | None:
    """Return the anthropic SDK version for this lockfile.

    The locked version wins when it depends on the same `@ai-sdk/provider`
    release as `ai`. Otherwise the highest published version with that
    provider dependency is used. ``registry`` maps anthropic versions to
    provider versions. It is fetched from npm when omitted.
    """
    packages = lock.get("packages") if isinstance(lock.get("packages"), dict) else {}
    _ai_version, ai_provider = _entry(packages, "ai")
    anthropic_version, anthropic_provider = _entry(packages, "@ai-sdk/anthropic")
    if anthropic_version and ai_provider and anthropic_provider == ai_provider:
        return anthropic_version
    if not ai_provider:
        return anthropic_version
    if registry is None:
        try:
            registry = npm_anthropic_provider_index()
        except OSError:
            return None
    matches = [version for version, provider in registry.items() if provider == ai_provider]
    if not matches:
        return None
    return max(matches, key=version_sort_key)


def _exact(value) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text[:1].isdigit():
        return text
    return None


def _pin_from_package_json(root: Path) -> str | None:
    for relative in ("packages/opencode/package.json", "package.json"):
        path = root / relative
        if not path.is_file():
            continue
        try:
            parsed = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(parsed, dict):
            continue
        deps = parsed.get("dependencies") if isinstance(parsed.get("dependencies"), dict) else {}
        pin = _exact(deps.get("@ai-sdk/anthropic"))
        if pin:
            return pin
    return None


def anthropic_pin_for_tree(root: Path, registry: dict[str, str] | None = None) -> str | None:
    """Read `bun.lock` when it exists. Fall back to an exact package.json pin."""
    root = Path(root)
    lock_path = root / "bun.lock"
    if lock_path.is_file():
        try:
            lock = load_jsonc(lock_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return select_anthropic_pin(lock, registry=registry)
    return _pin_from_package_json(root)
