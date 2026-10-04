from __future__ import annotations

import json
import os
import shlex
import subprocess
from pathlib import Path

from thesis.ab.durable import exclusive_lock
from thesis.ab.errors import BuildError


def version_tuple(text: str) -> tuple[int, ...]:
    nums = []
    for part in text.strip().lstrip("v").split("."):
        digits = ""
        for char in part:
            if char.isdigit():
                digits += char
            else:
                break
        if not digits:
            break
        nums.append(int(digits))
    return tuple(nums)


def node_requirement(root: Path) -> str:
    for name in (".nvmrc", ".node-version"):
        path = root / name
        if path.is_file():
            text = path.read_text(encoding="utf-8").strip().lstrip("v")
            if text:
                return text
    pkg_path = root / "package.json"
    if not pkg_path.is_file():
        raise BuildError("no package.json, .nvmrc, or .node-version")
    engines = json.loads(pkg_path.read_text(encoding="utf-8")).get("engines") or {}
    node = engines.get("node")
    if not node:
        raise BuildError("package.json has no engines.node")
    return str(node)


def nvm_install_arg(requirement: str) -> str:
    text = requirement.strip().lstrip("v")
    exact = text[:1].isdigit()
    for prefix in (">=", ">", "="):
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
            exact = False
            break
    parts = version_tuple(text)
    if not parts:
        raise BuildError(f"cannot read a Node version from {requirement!r}")
    if exact:
        return ".".join(str(part) for part in parts)
    return str(parts[0])


def version_satisfies(installed: str, requirement: str) -> bool:
    got = version_tuple(installed)
    text = requirement.strip().lstrip("v")
    if text.startswith(">="):
        return got >= version_tuple(text[2:])
    if text.startswith(">"):
        return got > version_tuple(text[1:])
    if text[:1].isdigit():
        want = version_tuple(text)
        return got[:len(want)] == want
    return False


def ensure_node(requirement: str, cache: Path) -> Path:
    arg = nvm_install_arg(requirement)
    with exclusive_lock(Path(cache) / "locks" / "node.lock"):
        script = (
            "set -euo pipefail\n"
            "export NVM_DIR=\"${NVM_DIR:-$HOME/.nvm}\"\n"
            ". \"$NVM_DIR/nvm.sh\"\n"
            f"nvm install {shlex.quote(arg)}\n"
            f"node_path=$(nvm which {shlex.quote(arg)})\n"
            "printf '%s\\n' \"$node_path\"\n"
            "\"$node_path\" -v\n"
        )
        proc = subprocess.run(["bash", "-lc", script], capture_output=True, text=True)
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "nvm install failed").strip()
            raise BuildError(detail)
        lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
        node_line = next((line for line in lines if line.startswith("/")), "")
        version_line = next((line for line in lines if line.startswith("v")), "")
        if not node_line:
            raise BuildError(f"nvm which returned no path: {proc.stdout!r}")
        if version_line and not version_satisfies(version_line, requirement):
            raise BuildError(f"node {version_line} does not satisfy {requirement}")
        node = Path(node_line)
        if not node.is_file():
            raise BuildError(f"nvm reported missing node {node}")
        return node


def bun_requirement(root: Path) -> str:
    pinned = root / ".bun-version"
    if pinned.is_file() and pinned.read_text(encoding="utf-8").strip():
        return pinned.read_text(encoding="utf-8").strip().lstrip("v")
    pkg_path = root / "package.json"
    if not pkg_path.is_file():
        raise BuildError("no package.json or .bun-version")
    raw = json.loads(pkg_path.read_text(encoding="utf-8")).get("packageManager") or ""
    if isinstance(raw, str) and raw.startswith("bun@"):
        return raw.split("@", 1)[1]
    raise BuildError("package.json packageManager is not bun@...")


def pick_bun(requirement: str, releases: list[str]) -> str:
    text = requirement.strip().lstrip("v")
    if text[:1].isdigit() and not any(mark in text for mark in (">", "<", "=")):
        return text
    if text.startswith(">="):
        minimum = version_tuple(text[2:])
        matches = [item for item in releases if version_tuple(item) >= minimum]
        if not matches:
            raise BuildError(f"no Bun release satisfies {requirement}")
        return max(matches, key=version_tuple)
    raise BuildError(f"unsupported Bun requirement {requirement!r}")


def bun_releases() -> list[str]:
    import urllib.request
    request = urllib.request.Request(
        "https://api.github.com/repos/oven-sh/bun/releases?per_page=100",
        headers={"Accept": "application/vnd.github+json", "User-Agent": "openbench"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        payload = json.load(response)
    found = []
    for item in payload:
        tag = str(item.get("tag_name") or "")
        if not tag.startswith("bun-v"):
            continue
        version = tag[len("bun-v"):]
        if version_tuple(version) and "-" not in version:
            found.append(version)
    if not found:
        raise BuildError("Bun release list was empty")
    return found


def rust_channel(root: Path) -> str | None:
    toml = root / "rust-toolchain.toml"
    if toml.is_file():
        for line in toml.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("channel") and "=" in line:
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    plain = root / "rust-toolchain"
    if plain.is_file():
        text = plain.read_text(encoding="utf-8").strip()
        if text and not text.startswith("["):
            return text.splitlines()[0].strip()
    return None


def ensure_rust(channel: str) -> Path:
    """Install ``channel`` and return the real toolchain bin, not the rustup shim. The shim installs every target in ``rust-toolchain.toml``, including cross targets, on this host."""
    proc = subprocess.run(
        ["rustup", "toolchain", "install", channel, "--profile", "minimal"],
        text=True,
    )
    if proc.returncode != 0:
        raise BuildError(f"rustup toolchain install {channel} failed")
    home = Path(os.environ.get("RUSTUP_HOME", Path.home() / ".rustup"))
    matches = sorted((home / "toolchains").glob(f"{channel}-*/bin"))
    if not matches:
        raise BuildError(f"cargo for {channel} not found under {home}")
    cargo = matches[0] / "cargo"
    if not cargo.is_file():
        raise BuildError(f"missing {cargo}")
    return matches[0]
