"""Pre-install every pinned ``@ai-sdk/anthropic`` into a read-only cache.

Each version gets ``<root>/<version>/node_modules`` plus ``manifest.json``
with the sha256 of every file. The OpenCode adapter copies from that tree
at cell start and never runs ``bun add`` for the pin, so a cell cannot pull
``latest`` or come up with the package missing.

    python -m thesis.ab.provision_provider_pins            # all pins
    python -m thesis.ab.provision_provider_pins --verify   # check manifests only

Network is used here, once, never inside a cell.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

DEFAULT_ROOT = Path("~/h1/opencode-src/provider-pins").expanduser()
PINS_FILE = Path(__file__).with_name("provider_pins.json")
VERSIONS_FILE = Path(__file__).with_name("provider_versions.toml")
PACKAGE = "@ai-sdk/anthropic"
# Pins observed in H2 cells (2.0.77, 3.0.64, 2.0.0) and the #201 capture.
EXTRA_PINS = ("2.0.0", "2.0.58", "2.0.77", "3.0.64")
_EXACT = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")


def _walk_pins(node, out: set) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if key in (PACKAGE, "anthropic_sdk") and isinstance(value, str):
                out.add(value.strip())
            else:
                _walk_pins(value, out)
    elif isinstance(node, list):
        for value in node:
            _walk_pins(value, out)


def referenced_pins() -> list[str]:
    found: set[str] = set(EXTRA_PINS)
    if PINS_FILE.is_file():
        _walk_pins(json.loads(PINS_FILE.read_text(encoding="utf-8")), found)
    if VERSIONS_FILE.is_file():
        found.update(re.findall(r'provider_version\s*=\s*"([^"]+)"', VERSIONS_FILE.read_text(encoding="utf-8")))
    return sorted(v for v in found if _EXACT.match(v))


def _installed(tree: Path) -> str:
    pkg = tree / "node_modules" / "@ai-sdk" / "anthropic" / "package.json"
    try:
        return str(json.loads(pkg.read_text(encoding="utf-8")).get("version") or "")
    except (OSError, ValueError):
        return ""


def file_hashes(tree: Path) -> dict[str, str]:
    out = {}
    base = tree / "node_modules"
    for path in sorted(base.rglob("*")):
        if path.is_file() and not path.is_symlink():
            out[str(path.relative_to(tree))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


def tree_sha256(hashes: dict[str, str]) -> str:
    blob = json.dumps(hashes, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(blob).hexdigest()


def verify(root: Path, version: str) -> str:
    """Empty when ``root/version`` is the pin and matches its manifest."""
    tree = root / version
    manifest = tree / "manifest.json"
    if not manifest.is_file():
        return "missing manifest"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    if _installed(tree) != version or data.get("version") != version:
        return f"installed {_installed(tree) or 'missing'} != pin {version}"
    if tree_sha256(file_hashes(tree)) != data.get("tree_sha256"):
        return "sha256 mismatch"
    return ""


def _read_only(tree: Path) -> None:
    for path in [*tree.rglob("*"), tree]:
        if path.is_symlink():
            continue
        mode = path.stat().st_mode
        path.chmod(mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))


def _writable(tree: Path) -> None:
    for path in [tree, *tree.rglob("*")]:
        if not path.is_symlink():
            path.chmod(path.stat().st_mode | stat.S_IWUSR)


def provision(root: Path, version: str, bun: str) -> str:
    if not verify(root, version):
        return "ok (cached)"
    tree = root / version
    staging = root / f".{version}.staging"
    for path in (staging, tree):
        if path.exists():
            _writable(path)
            shutil.rmtree(path)
    staging.mkdir(parents=True)
    (staging / "package.json").write_text(
        json.dumps({"name": "obench-provider-pin", "private": True,
                    "dependencies": {PACKAGE: version}}), encoding="utf-8")
    (staging / "bunfig.toml").write_text('[install]\nexact = true\nlinker = "hoisted"\n', encoding="utf-8")
    proc = subprocess.run(
        [bun, "install", "--cwd", str(staging)], cwd=staging,
        capture_output=True, text=True, timeout=300,
    )
    got = _installed(staging)
    if proc.returncode != 0 or got != version:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-1:] or [""]
        shutil.rmtree(staging, ignore_errors=True)
        return f"FAILED: installed {got or 'missing'} != pin {version} {tail[0]}"
    hashes = file_hashes(staging)
    (staging / "manifest.json").write_text(json.dumps({
        "package": PACKAGE, "version": version,
        "tree_sha256": tree_sha256(hashes), "files": hashes,
    }, indent=1, sort_keys=True), encoding="utf-8")
    os.replace(staging, tree)
    _read_only(tree)
    return "ok (installed)"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", type=Path, default=Path(os.environ.get("OBENCH_PROVIDER_PIN_ROOT") or DEFAULT_ROOT))
    ap.add_argument("--bun", default=shutil.which("bun") or "")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("versions", nargs="*")
    args = ap.parse_args(argv)
    root = args.root.expanduser().resolve()
    versions = args.versions or referenced_pins()
    if not args.verify and not args.bun:
        print("bun not found; pass --bun", file=sys.stderr)
        return 2
    root.mkdir(parents=True, exist_ok=True)
    bad = 0
    for version in versions:
        if args.verify:
            reason = verify(root, version)
            status = "ok" if not reason else f"FAILED: {reason}"
        else:
            status = provision(root, version, args.bun)
        bad += status.startswith("FAILED")
        print(f"{PACKAGE}@{version}: {status}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
