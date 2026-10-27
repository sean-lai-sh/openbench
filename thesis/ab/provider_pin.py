"""Exact provider pins for one OpenCode build and side.

``provider_pins.json`` records the ``@ai-sdk/anthropic`` version each step-8
box build left in its cache. ``with`` and ``without`` are different builds.
The runner copies a shared, lock-built template into the cell cache and
aborts the cell when that cache is empty or does not match the pin.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from thesis.ab.durable import exclusive_lock

_MANIFEST: dict | None = None
_EXACT = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
_LATEST_SPEC = re.compile(r"@ai-sdk/[A-Za-z0-9._-]+@latest\b", re.IGNORECASE)
_VERSION_LATEST = re.compile(r"\bversion=latest\b", re.IGNORECASE)
LOADED_LINE = re.compile(
    r"OBENCH_PROVIDER_LOADED\s+pkg=@ai-sdk/anthropic\s+version=(\S+)"
    r"(?:\s+path=(\S+))?"
)


class ProviderPinMismatch(Exception):
    """The cell would resolve a provider package other than its pin."""

    def __init__(self, reason: str, output: str = ""):
        super().__init__(reason)
        self.reason = reason
        self.output = output


class PinLookupError(LookupError):
    """The requested build is missing or is not a unique prefix."""


def manifest_path() -> Path:
    return Path(__file__).with_name("provider_pins.json")


def load_manifest(path: Path | None = None) -> dict:
    """Return the pin manifest. The committed file is cached."""
    global _MANIFEST
    target = Path(path) if path is not None else manifest_path()
    if path is None and _MANIFEST is not None:
        return _MANIFEST
    data = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise PinLookupError("provider pin manifest is not an object")
    if path is None:
        _MANIFEST = data
    return data


def pin_sha256(packages: dict) -> str:
    """SHA-256 of the canonical pin set (sorted keys, compact JSON)."""
    payload = json.dumps(packages, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _builds(manifest: dict | None = None) -> dict:
    data = manifest if manifest is not None else load_manifest()
    builds = data.get("builds")
    return builds if isinstance(builds, dict) else {}


def resolve_sha(sha: str, manifest: dict | None = None) -> str:
    """Return the full build SHA. A prefix must match exactly one build."""
    text = str(sha or "").strip().lower()
    builds = _builds(manifest)
    if not text:
        raise PinLookupError("missing build sha")
    if text in builds:
        return text
    matches = [key for key in builds if str(key).startswith(text)]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise PinLookupError(f"{text} matches more than one build")
    raise PinLookupError(f"no pin for {text}")


def _entry_packages(entry) -> dict | None:
    if not isinstance(entry, dict):
        return None
    packages = entry.get("packages")
    if not isinstance(packages, dict) or not packages:
        return None
    return {str(name): str(version) for name, version in packages.items()}


def lookup_entry(sha: str, side: str = "", pr: str = "", manifest: dict | None = None) -> dict | None:
    """Return the manifest entry for this build and side, plus ``sha`` and ``side``.

    An omitted side is used only when every side of the build recorded the
    same packages. A side that is not on the build returns None.
    """
    try:
        full = resolve_sha(sha, manifest)
    except PinLookupError:
        return None
    sides = _builds(manifest).get(full)
    if not isinstance(sides, dict):
        return None
    wanted = str(side or "").strip()
    if wanted:
        entry = sides.get(wanted)
        packages = _entry_packages(entry)
        if packages is None:
            return None
        return {"sha": full, "side": wanted, "entry": entry, "packages": packages}
    agreed: dict | None = None
    agreed_side = ""
    agreed_entry = None
    for name, entry in sides.items():
        packages = _entry_packages(entry)
        if packages is None:
            continue
        if agreed is None:
            agreed = packages
            agreed_side = str(name)
            agreed_entry = entry
            continue
        if json.dumps(packages, sort_keys=True) != json.dumps(agreed, sort_keys=True):
            if pr:
                continue
            return None
    if pr and agreed is None:
        return None
    if pr:
        for name, entry in sides.items():
            if isinstance(entry, dict) and str(entry.get("pr") or "") == str(pr):
                packages = _entry_packages(entry)
                if packages is not None:
                    return {"sha": full, "side": str(name), "entry": entry, "packages": packages}
    if agreed is None:
        return None
    return {"sha": full, "side": agreed_side, "entry": agreed_entry, "packages": dict(agreed)}


def lookup_packages(sha: str, side: str = "", pr: str = "", manifest: dict | None = None) -> dict | None:
    found = lookup_entry(sha, side, pr, manifest)
    if found is None:
        return None
    return dict(found["packages"])


def iter_sides(sha: str, side: str = "", manifest: dict | None = None) -> list[dict]:
    """Every matching side entry. ``side`` keeps one. An unknown build is empty."""
    try:
        full = resolve_sha(sha, manifest)
    except PinLookupError:
        return []
    sides = _builds(manifest).get(full)
    if not isinstance(sides, dict):
        return []
    wanted = str(side or "").strip()
    rows = []
    for name, entry in sides.items():
        if wanted and name != wanted:
            continue
        packages = _entry_packages(entry)
        if packages is None:
            continue
        rows.append({"sha": full, "side": str(name), "entry": entry, "packages": packages})
    return rows


def pin_source_for(entry) -> str:
    """Where this side's pin was read from.

    ``box_cache`` is the version a box cell left installed. ``vm_quarantine_log``
    is the version the quarantined F03-1 log installed for a side with no
    finished box cell. A checkout that is not in the manifest is ``lockfile``.
    """
    if not isinstance(entry, dict):
        return ""
    source = str(entry.get("pin_source") or "").strip()
    if source:
        return source
    evidence = str(entry.get("evidence") or "").strip()
    if evidence == "f03-1-seed":
        return "vm_quarantine_log"
    if evidence:
        return "box_cache"
    return ""


def apply_provider_pin(proxy: dict, cache, sha: str, side: str = "", pr: str = "") -> dict:
    """Copy ``proxy`` and attach the pin for this build and side.

    A manifest hit replaces the lockfile pin. A build that is not in the
    manifest keeps an exact lockfile pin already on ``proxy`` and still
    refuses ``latest``. ``pin_source`` records which of those produced the pin.
    """
    proxy = dict(proxy)
    found = lookup_entry(sha, side, pr)
    packages = dict(found["packages"]) if found else None
    source = pin_source_for(found.get("entry") if found else None)
    if not packages:
        pin = str(proxy.get("anthropic_sdk") or "").strip()
        if pin and pin != "latest":
            packages = {"@ai-sdk/anthropic": pin}
            source = "lockfile"
    if not packages:
        return proxy
    anthropic = str(packages.get("@ai-sdk/anthropic") or "").strip()
    if anthropic:
        proxy["anthropic_sdk"] = anthropic
    proxy["provider_pins"] = packages
    proxy["provider_pin_sha256"] = pin_sha256(packages)
    proxy["pin_store"] = str(Path(cache) / "provider-pins")
    if source:
        proxy["pin_source"] = source
    return proxy


def _version_of(path: Path) -> str:
    if not path.is_file():
        return ""
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    if not isinstance(parsed, dict):
        return ""
    return str(parsed.get("version") or "")


def installed_packages(cache, only: dict | None = None) -> dict:
    """Versions under ``cache/node_modules`` for scoped and unscoped packages."""
    root = Path(cache) / "node_modules"
    found: dict[str, str] = {}
    if root.is_dir():
        try:
            children = list(root.iterdir())
        except OSError:
            children = []
        for child in children:
            if not child.is_dir() or child.name == ".bun":
                continue
            if child.name.startswith("@"):
                try:
                    pkgs = list(child.iterdir())
                except OSError:
                    continue
                for pkg in pkgs:
                    version = _version_of(pkg / "package.json")
                    if version:
                        found[f"{child.name}/{pkg.name}"] = version
                continue
            version = _version_of(child / "package.json")
            if version:
                found[child.name] = version
    if only is None:
        return {
            name: version
            for name, version in found.items()
            if name.startswith("@ai-sdk/") or name == "@opencode-ai/plugin"
        }
    return {name: found[name] for name in only if name in found}


def resolved_versions(cache, packages: dict) -> dict:
    """Pinned package -> version on disk, or ``missing``."""
    found = installed_packages(cache)
    return {name: found.get(name) or "missing" for name in sorted(packages)}


def _cache_has_modules(cache) -> bool:
    root = Path(cache) / "node_modules"
    if not root.is_dir():
        return False
    for dirpath, _dirs, files in os.walk(root):
        if "package.json" in files and Path(dirpath).name != ".bun":
            if Path(dirpath) != root:
                return True
    return False


def mismatch_reason(cache, packages: dict) -> str:
    """Empty when every pinned package is the version on disk.

    An empty install tree and a version other than the pin are both
    ``provider_pin_mismatch``. ``latest`` is never a valid pin.
    """
    if not packages:
        return ""
    refused = [
        f"{name}@{version}"
        for name, version in sorted(packages.items())
        if not _EXACT.fullmatch(str(version or ""))
    ]
    if refused:
        return "provider_pin_mismatch: refused specifier " + ", ".join(refused)
    found = installed_packages(cache)
    if not found and not _cache_has_modules(cache):
        return "provider_pin_mismatch: empty cache"
    missing = [name for name in sorted(packages) if name not in found]
    if missing:
        return "provider_pin_mismatch: " + ", ".join(f"{name} missing" for name in missing)
    drifted = [
        name for name in sorted(packages) if found.get(name) != packages[name]
    ]
    if drifted:
        parts = [
            f"{name} found {found.get(name) or 'missing'} != pin {packages[name]}"
            for name in drifted
        ]
        return "provider_pin_mismatch: " + "; ".join(parts)
    return ""


def _pins_from(pins) -> dict:
    """Normalize a pin map or the ``OBENCH_PROVIDER_PINS`` JSON string."""
    if isinstance(pins, dict):
        raw = pins
    else:
        text = str(pins or "").strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return {}
        raw = parsed if isinstance(parsed, dict) else {}
    found = {}
    for name, version in raw.items():
        package = str(name or "").strip()
        pinned = str(version or "").strip()
        if package and pinned:
            found[package] = pinned
    return found


def loaded_line_mismatch(text: str, pins) -> str:
    """Mismatch when a live preload line names a version other than the pin.

    ``pins`` is the ``OBENCH_PROVIDER_PINS`` object or its JSON string. A line
    whose version equals the pin is not a violation. No pin means no check.
    """
    if not text:
        return ""
    match = None
    for match in LOADED_LINE.finditer(text):
        pass
    if match is None:
        return ""
    packages = _pins_from(pins)
    pin = packages.get("@ai-sdk/anthropic") or ""
    if not pin:
        return ""
    loaded = match.group(1)
    if loaded == pin:
        return ""
    return f"provider_pin_mismatch: loaded {loaded} != pin {pin}"


def violation_in_text(text: str, pins=None) -> str:
    """A log line that means the binary is resolving ``@latest`` or another SDK.

    A failed ``@opencode-ai/plugin@0.0.0--<build time>`` install is not a
    violation. That install fails on the box and the VM, and the box still
    uses the pre-seeded provider pin.

    A live ``OBENCH_PROVIDER_LOADED`` line is a violation when its version
    differs from the ``@ai-sdk/anthropic`` entry in ``pins`` (the cell's
    ``OBENCH_PROVIDER_PINS``). Callers that omit ``pins`` keep the previous
    ``@latest`` check only.
    """
    if not text:
        return ""
    if _VERSION_LATEST.search(text) or _LATEST_SPEC.search(text):
        return "provider_pin_mismatch: version=latest"
    if pins is None:
        return ""
    return loaded_line_mismatch(text, pins)


def _hoist(cache: Path, packages: dict) -> None:
    """Copy an isolated Bun store entry up to the hoisted package path."""
    root = cache / "node_modules" / ".bun"
    if not root.is_dir():
        return
    try:
        names = list(root.iterdir())
    except OSError:
        return
    for package, version in packages.items():
        dest = cache / "node_modules" / package
        if _version_of(dest / "package.json") == version:
            continue
        prefix = package.replace("/", "+") + f"@{version}"
        for entry in names:
            if entry.name != prefix and not entry.name.startswith(prefix + "+"):
                continue
            store = entry / "node_modules" / package
            if _version_of(store / "package.json") != version:
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(store, dest, dirs_exist_ok=True)
            break


def _prepare(dest: Path, packages: dict) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "package.json").write_text(
        json.dumps({"dependencies": packages}),
        encoding="utf-8",
    )
    (dest / "bunfig.toml").write_text(
        '[install]\nexact = true\nlinker = "hoisted"\n',
        encoding="utf-8",
    )


def _install_exact(dest: Path, packages: dict, bun: str, env: dict | None) -> None:
    specs = [f"{name}@{packages[name]}" for name in sorted(packages)]
    child = dict(env or os.environ)
    subprocess.run(
        [bun, "add", "--force", "--exact", "--cwd", str(dest), *specs],
        cwd=str(dest),
        env=child,
        stdin=subprocess.DEVNULL,
        timeout=120,
        check=False,
    )
    _hoist(dest, packages)


def _copy_template(src: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    modules = src / "node_modules"
    if modules.is_dir():
        shutil.copytree(modules, dest / "node_modules", dirs_exist_ok=True)
    for name in ("package.json", "bunfig.toml", "pins.json"):
        src_file = src / name
        if src_file.is_file():
            shutil.copy2(src_file, dest / name)


def seed_cell_cache(cell_cache, store, packages: dict, bun: str, env: dict | None = None) -> str:
    """Install ``packages`` once under ``store/<sha>`` and copy into the cell.

    The template is published under an exclusive lock, so concurrent cells
    (``--jobs 4``) share one finished tree. A ``latest`` specifier is refused
    and ``bun add`` is not run. Returns ``""`` when the cell cache matches,
    otherwise a ``provider_pin_mismatch`` reason.
    """
    packages = {str(name): str(version) for name, version in dict(packages).items()}
    refused = mismatch_reason(Path(cell_cache), packages)
    if refused.startswith("provider_pin_mismatch: refused"):
        return refused
    if not bun:
        return mismatch_reason(cell_cache, packages) or "provider_pin_mismatch: empty cache"
    digest = pin_sha256(packages)
    store_path = Path(store)
    template = store_path / digest
    staging = store_path / f".{digest}.{os.getpid()}.staging"
    try:
        with exclusive_lock(store_path / f"{digest}.lock"):
            if mismatch_reason(template, packages):
                if staging.exists():
                    shutil.rmtree(staging, ignore_errors=True)
                _prepare(staging, packages)
                try:
                    _install_exact(staging, packages, bun, env)
                except (OSError, subprocess.SubprocessError):
                    shutil.rmtree(staging, ignore_errors=True)
                    return "provider_pin_mismatch: seed did not install the pin"
                if mismatch_reason(staging, packages):
                    shutil.rmtree(staging, ignore_errors=True)
                    return "provider_pin_mismatch: seed did not install the pin"
                (staging / "pins.json").write_text(
                    json.dumps(packages, sort_keys=True, separators=(",", ":")),
                    encoding="utf-8",
                )
                if template.exists():
                    shutil.rmtree(template)
                os.replace(staging, template)
    except OSError:
        return "provider_pin_mismatch: seed did not install the pin"
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
    try:
        _copy_template(template, Path(cell_cache))
    except OSError:
        return "provider_pin_mismatch: seed did not install the pin"
    return mismatch_reason(cell_cache, packages)
