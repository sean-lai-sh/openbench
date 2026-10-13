from __future__ import annotations

import argparse
import json
import os
import platform
import shlex
import subprocess
import sys
from pathlib import Path

from thesis.ab.build_opencode import ensure_bun
from thesis.ab.checkout import checkout
from thesis.ab.durable import exclusive_lock
from thesis.ab.errors import BuildError, Incompatible
from thesis.ab.models_config import supports_custom_models
from thesis.ab.toolchain import (
    bun_releases,
    bun_requirement,
    ensure_rust,
    pick_bun,
    rust_channel,
)

_ENTRIES = (
    "packages/coding-agent/dist/cli.js",
    "packages/coding-agent/dist/bundle/cli.js",
    "packages/coding-agent/src/cli.ts",
)


def _run(cmd: list[str], cwd: Path, env: dict) -> None:
    proc = subprocess.run(cmd, cwd=cwd, env=env, text=True)
    if proc.returncode != 0:
        raise BuildError(f"command failed ({proc.returncode}): {' '.join(cmd)}")


def _publish(dest: Path, script: str) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".tmp")
    tmp.write_text(script, encoding="utf-8")
    tmp.chmod(0o755)
    os.replace(tmp, dest)
    return dest


def _scripts(root: Path) -> dict:
    path = root / "package.json"
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8")).get("scripts") or {}


def _rewrite_script(path: Path, key: str, command: str) -> None:
    if not path.is_file():
        return
    try:
        package = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    scripts = package.get("scripts")
    if not isinstance(scripts, dict) or key not in scripts:
        return
    scripts[key] = command
    path.write_text(json.dumps(package, indent=2) + "\n", encoding="utf-8")


def disarm_native_cargo(root: Path) -> None:
    """Stop a later bun/turbo build from compiling pi-natives with cargo.

    The prebuilt ``.node`` is already in ``packages/natives/native``. The
    package ``build`` script and the repo ``build:native`` script are the
    paths that invoke cargo.
    """
    _rewrite_script(root / "packages" / "natives" / "package.json", "build", "true")
    _rewrite_script(root / "package.json", "build:native", "true")


def natives_version(root: Path) -> str:
    path = root / "packages" / "natives" / "package.json"
    if not path.is_file():
        return ""
    version = json.loads(path.read_text(encoding="utf-8")).get("version")
    return version.strip() if isinstance(version, str) else ""


def _git_rev(root: Path, rev: str) -> str:
    proc = subprocess.run(
        ["git", "rev-parse", rev],
        cwd=root,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return ""
    return proc.stdout.strip()


def crates_match_release(root: Path, version: str) -> bool:
    """True when ``crates/`` is the same tree as the published ``v{version}`` tag.

    GitHub's compare API reports a diverged history even when the tree hash
    matches, so the build compares ``HEAD:crates`` with the tag commit's tree.
    """
    if not version:
        return False
    head = _git_rev(root, "HEAD:crates")
    if not head:
        return False
    commit = _git_rev(root, f"v{version}^{{commit}}")
    if not commit:
        return False
    tagged = _git_rev(root, f"{commit}:crates")
    return bool(tagged) and tagged == head


PINNED_BUN = "1.4.3"


def bun_version_for_build(root: Path) -> str:
    """Bun for this checkout. Commits with no pin use ``PINNED_BUN``.

    d8782684 and e4fa6aff list neither ``packageManager`` nor ``engines.bun``.
    """
    try:
        return bun_requirement(root)
    except BuildError:
        return PINNED_BUN


def native_asset_name() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    if system == "linux":
        os_name = "linux"
    elif system == "darwin":
        os_name = "darwin"
    elif system == "windows":
        os_name = "win32"
    else:
        raise BuildError(f"unsupported platform {system}")
    if machine in {"x86_64", "amd64"}:
        arch = "x64"
    elif machine in {"aarch64", "arm64"}:
        arch = "arm64"
    else:
        raise BuildError(f"unsupported architecture {machine}")
    return f"pi_natives.{os_name}-{arch}.node"


def native_asset_candidates() -> list[str]:
    """Release asset names, legacy first, then the renamed modern/baseline pair."""
    legacy = native_asset_name()
    stem = legacy[: -len(".node")]
    return [legacy, f"{stem}-modern.node", f"{stem}-baseline.node"]


def _platform_token() -> str:
    legacy = native_asset_name()
    return legacy[len("pi_natives."): -len(".node")]


def npm_native_specs(version: str) -> tuple[str, str]:
    """Generic package, then the platform package that ships the ``.node`` files."""
    token = _platform_token()
    return (
        f"@oh-my-pi/pi-natives@{version}",
        f"@oh-my-pi/pi-natives-{token}@{version}",
    )


def _default_opener(target: str) -> bytes:
    import urllib.request

    request = urllib.request.Request(target, headers={"User-Agent": "openbench"})
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def _github_native_files(version: str, opener) -> tuple[dict[str, bytes], bool]:
    """Download release assets. The bool is true when a response body was empty."""
    files: dict[str, bytes] = {}
    saw_empty = False
    base = f"https://github.com/can1357/oh-my-pi/releases/download/v{version}/"
    for name in native_asset_candidates():
        try:
            body = opener(base + name)
        except Exception:
            continue
        if not body:
            saw_empty = True
            continue
        files[name] = body
        if name == native_asset_name():
            return files, saw_empty
    return files, saw_empty


def _npm_pack_natives(spec: str) -> dict[str, bytes]:
    """``npm pack`` one natives package and return its platform ``.node`` files."""
    import tarfile
    import tempfile

    token = _platform_token()
    with tempfile.TemporaryDirectory() as tmp:
        proc = subprocess.run(
            ["npm", "pack", spec, "--silent"],
            cwd=tmp,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if proc.returncode != 0:
            return {}
        tarballs = list(Path(tmp).glob("*.tgz"))
        if not tarballs:
            return {}
        found: dict[str, bytes] = {}
        with tarfile.open(tarballs[0], "r:gz") as archive:
            for member in archive.getmembers():
                if not member.isfile():
                    continue
                base = Path(member.name).name
                if not base.endswith(".node") or token not in base:
                    continue
                extracted = archive.extractfile(member)
                if extracted is None:
                    continue
                body = extracted.read()
                if body:
                    found[base] = body
        return found


def _npm_native_files(version: str, fetch) -> dict[str, bytes]:
    if fetch is None:
        fetch = _npm_pack_natives
    found: dict[str, bytes] = {}
    for spec in npm_native_specs(version):
        try:
            files = fetch(spec)
        except Exception:
            continue
        if not isinstance(files, dict):
            continue
        for name, body in files.items():
            base = Path(str(name)).name
            if body and base.endswith(".node") and _platform_token() in base:
                found[base] = body
    return found


def _alias_bytes(files: dict[str, bytes]) -> bytes:
    token = _platform_token()
    for name, body in files.items():
        if name.endswith(f"{token}-modern.node"):
            return body
    legacy = native_asset_name()
    if legacy in files:
        return files[legacy]
    for name, body in files.items():
        if token in name and name.endswith(".node"):
            return body
    raise BuildError("no platform pi-natives binary")


def install_native_files(root: Path, files: dict[str, bytes]) -> None:
    """Copy ``.node`` files where the natives loader looks, and alias one."""
    if not files:
        raise BuildError("empty pi-natives asset")
    dest_dir = root / "packages" / "natives" / "native"
    dest_dir.mkdir(parents=True, exist_ok=True)
    for name, body in files.items():
        (dest_dir / Path(name).name).write_bytes(body)
    (dest_dir / "pi_natives.node").write_bytes(_alias_bytes(files))


def install_published_natives(root: Path, version: str, opener=None) -> None:
    """Drop the GitHub release ``.node`` where the natives loader looks."""
    if opener is None:
        opener = _default_opener
    files, saw_empty = _github_native_files(version, opener)
    if not files:
        if saw_empty:
            raise BuildError(f"empty pi-natives asset {native_asset_name()}")
        raise BuildError(f"missing pi-natives asset for {version}")
    install_native_files(root, files)


def prepare_natives(root: Path, opener=None, npm_fetch=None) -> str:
    """``published`` when a prebuilt binary can be reused, else ``cargo`` or ``skip``.

    GitHub renamed the asset to ``pi_natives.<os>-<arch>-{modern,baseline}.node``
    and later tags publish no asset. Those builds take
    ``@oh-my-pi/pi-natives`` and then ``@oh-my-pi/pi-natives-<platform>``, which
    ships the modern and baseline ``.node`` files. A prebuilt binary skips
    rustup, including checkouts whose ``crates/`` tree has moved on
    (27517f25, 1b5c7b53). ``cargo`` remains when no prebuilt file is available.
    """
    if "build:native" not in _scripts(root):
        return "skip"
    version = natives_version(root)
    if not version:
        return "cargo"
    if opener is None:
        opener = _default_opener
    files: dict[str, bytes] = {}
    saw_empty = False
    if crates_match_release(root, version):
        files, saw_empty = _github_native_files(version, opener)
    if not files:
        files = _npm_native_files(version, npm_fetch)
    if files:
        install_native_files(root, files)
        return "published"
    if saw_empty and crates_match_release(root, version):
        raise BuildError(f"empty pi-natives asset {native_asset_name()}")
    return "cargo"


def read_host_rustc() -> str:
    """Version token from ``rustc --version``, such as ``1.85.1``."""
    try:
        proc = subprocess.run(
            ["rustc", "--version"], capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if proc.returncode != 0:
        return ""
    parts = (proc.stdout or "").split()
    if len(parts) >= 2 and parts[0] == "rustc":
        return parts[1]
    return (proc.stdout or "").strip()


def active_rust_toolchain() -> str:
    """Active rustup toolchain name, or ``""`` when rustup is not available."""
    try:
        proc = subprocess.run(
            ["rustup", "show", "active-toolchain"],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if proc.returncode != 0:
        return ""
    lines = [line.strip() for line in (proc.stdout or "").splitlines() if line.strip()]
    if not lines:
        return ""
    return lines[0].split()[0]


def _toolchain_matches(channel: str, active: str) -> bool:
    if not channel or not active:
        return False
    return active == channel or active.startswith(channel + "-")


def resolve_source_toolchain(root: Path, *, host_rustc: str | None = None,
                             active: str | None = None, installer=None) -> Path | None:
    """Return a cargo bin directory, or None when the host toolchain already matches.

    Source builds are the fallback when no prebuilt ``.node`` exists. A host
    whose rustc is not the checkout's channel (rustc 1.85.1 against
    ``nightly-2026-03-27``) does not get a cargo invocation: the error names
    the toolchain the checkout needs.
    """
    channel = rust_channel(root) or ""
    host = read_host_rustc() if host_rustc is None else host_rustc
    if not channel:
        raise BuildError(
            "pi-natives source build needs a rust-toolchain channel; "
            f"host rustc is {host or 'not found'}"
        )
    current = active_rust_toolchain() if active is None else active
    if _toolchain_matches(channel, current):
        return None
    install = installer or ensure_rust
    try:
        return install(channel)
    except BuildError as exc:
        raise BuildError(
            f"pi-natives source build needs rust toolchain {channel}; "
            f"host rustc is {host or 'not found'}"
        ) from exc


def plan_natives(root: Path, opener=None, npm_fetch=None, *,
                 host_rustc: str | None = None, active: str | None = None,
                 installer=None) -> tuple[str, Path | None]:
    """``(published|cargo|skip, cargo_bin)``.

    A published npm binary disarms the cargo build scripts and returns no
    cargo bin, so the compile never invokes cargo. ``cargo`` is only returned
    when no prebuilt exists and the checkout's toolchain can be used.
    """
    mode = prepare_natives(root, opener=opener, npm_fetch=npm_fetch)
    if mode == "published":
        disarm_native_cargo(root)
        return "published", None
    if mode != "cargo":
        return mode, None
    cargo_bin = resolve_source_toolchain(
        root, host_rustc=host_rustc, active=active, installer=installer,
    )
    return "cargo", cargo_bin


def compile_tree(root: Path, bun: Path, cargo_bin: Path | None, *,
                 natives: str = "cargo", runner=None) -> Path:
    run = runner or _run
    env = dict(os.environ)
    prefixes = [str(bun.parent)]
    if cargo_bin is not None:
        prefixes.insert(0, str(cargo_bin))
    env["PATH"] = os.pathsep.join(prefixes + [env.get("PATH", "")])
    env["CI"] = "1"
    run(["bun", "install"], root, env)
    scripts = _scripts(root)
    if "build:native" in scripts and natives != "published":
        run(["bun", "run", "build:native"], root, env)
    if "build" in scripts:
        run(["bun", "run", "build"], root, env)
    for relative in _ENTRIES:
        path = root / relative
        if path.is_file():
            return path
    raise BuildError("Oh My Pi build did not produce a coding-agent entrypoint")


def binary(sha: str, cache: Path) -> Path:
    cache = Path(cache).resolve()
    sha = sha.strip().lower()
    published = cache / "bin" / "omp" / sha / "omp"
    if published.is_file() and os.access(published, os.X_OK):
        return published
    with exclusive_lock(cache / "locks" / f"omp-{sha}.lock"):
        if published.is_file() and os.access(published, os.X_OK):
            return published
        root = checkout(cache, "omp", sha)
        if not supports_custom_models(root):
            raise Incompatible("no custom-model support")
        requirement = bun_version_for_build(root)
        version = requirement if requirement[:1].isdigit() and ">=" not in requirement else pick_bun(
            requirement, bun_releases()
        )
        with exclusive_lock(cache / "locks" / f"bun-{version}.lock"):
            bun = ensure_bun(version, cache)
        natives, cargo_bin = plan_natives(root)
        entry = compile_tree(root, bun, cargo_bin, natives=natives)
        path_prefix = shlex.quote(str(bun.parent))
        script = "#!/bin/sh\n" f"export PATH={path_prefix}:\"$PATH\"\n"
        if cargo_bin is not None:
            script += f"export PATH={shlex.quote(str(cargo_bin))}:\"$PATH\"\n"
        script += f"exec {shlex.quote(str(bun))} {shlex.quote(str(entry))} \"$@\"\n"
        return _publish(published, script)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build one Oh My Pi SHA")
    parser.add_argument("sha")
    parser.add_argument("--cache", type=Path, default=Path("results/harness-src"))
    args = parser.parse_args(argv)
    try:
        print(binary(args.sha, args.cache))
    except Incompatible as exc:
        print(f"incompatible: {exc}", file=sys.stderr)
        return 2
    except BuildError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
