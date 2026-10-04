"""Build one OpenCode git SHA into a cached binary.

The shared clone is locked. Each SHA gets its own worktree and its own
output path, so two SHAs can compile at the same time. A crash before
``os.replace`` leaves no binary for that SHA.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import stat
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

from thesis.ab.durable import exclusive_lock
from thesis.ab.errors import BuildError

UPSTREAM = "https://github.com/anomalyco/opencode.git"
FALLBACK_UPSTREAM = "https://github.com/sst/opencode.git"


def _run(cmd: list[str], cwd: Path, env: dict | None = None) -> None:
    proc = subprocess.run(cmd, cwd=cwd, env=env, text=True)
    if proc.returncode != 0:
        raise BuildError(f"command failed ({proc.returncode}): {' '.join(cmd)}")


def bun_version(root: Path) -> str | None:
    path = root / "package.json"
    if not path.is_file():
        return None
    raw = json.loads(path.read_text(encoding="utf-8")).get("packageManager") or ""
    if isinstance(raw, str) and raw.startswith("bun@"):
        return raw.split("@", 1)[1]
    return None


def go_version(root: Path) -> str | None:
    for relative in ("packages/tui/go.mod", "go.mod"):
        path = root / relative
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("go "):
                return line.split()[1]
    return None


def build_plan(root: Path) -> dict:
    """Describe the compile for this checkout. Does not run it."""
    script = root / "packages" / "opencode" / "script"
    build_ts = script / "build.ts"
    publish_ts = script / "publish.ts"
    bun = bun_version(root)
    if build_ts.is_file():
        text = build_ts.read_text(encoding="utf-8", errors="replace")
        args = ["bun", "script/build.ts"]
        if "--single" in text:
            args.append("--single")
        if "--skip-embed-web-ui" in text:
            args.append("--skip-embed-web-ui")
        return {
            "kind": "build.ts",
            "bun": bun,
            "go": None,
            "cwd": "packages/opencode",
            "args": args,
        }
    if publish_ts.is_file() and "bun build" in publish_ts.read_text(
        encoding="utf-8", errors="replace"
    ):
        return {
            "kind": "compile",
            "bun": bun,
            "go": go_version(root),
            "cwd": "packages/opencode",
            "args": [],
        }
    return {
        "kind": "bun-run",
        "bun": bun,
        "go": None,
        "cwd": "packages/opencode",
        "args": ["bun", "run", "./src/index.ts"],
    }


def _host() -> tuple[str, str, str]:
    system = {"Linux": "linux", "Darwin": "darwin"}.get(platform.system())
    machine = {"x86_64": "x64", "amd64": "x64", "aarch64": "arm64", "arm64": "arm64"}.get(
        platform.machine()
    )
    goarch = {"x64": "amd64", "arm64": "arm64"}.get(machine or "")
    if not system or not machine or not goarch:
        raise BuildError(f"unsupported host {platform.system()} {platform.machine()}")
    return system, machine, goarch


def _bun_asset(version: str) -> tuple[str, str]:
    system, machine, _goarch = _host()
    name = f"bun-{system}-{machine}"
    return (
        f"https://github.com/oven-sh/bun/releases/download/bun-v{version}/{name}.zip",
        f"{name}/bun",
    )


def ensure_bun(version: str, cache: Path) -> Path:
    dest = cache / "bun" / version / "bun"
    if dest.is_file() and os.access(dest, os.X_OK):
        return dest
    url, member = _bun_asset(version)
    dest.parent.mkdir(parents=True, exist_ok=True)
    blob = dest.parent / "bun.zip"
    urllib.request.urlretrieve(url, blob)
    with zipfile.ZipFile(blob) as zf:
        zf.extract(member, dest.parent)
    extracted = dest.parent / member
    os.replace(extracted, dest)
    dest.chmod(dest.stat().st_mode | stat.S_IEXEC)
    return dest


def _go_ok(version: str) -> bool:
    try:
        proc = subprocess.run(["go", "version"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return False
    text = (proc.stdout or "") + (proc.stderr or "")
    want = tuple(int(part) for part in version.split(".")[:2])
    for token in text.split():
        if token.startswith("go") and token[2:3].isdigit():
            nums = token[2:].split(".")
            try:
                got = (int(nums[0]), int(nums[1]))
            except (ValueError, IndexError):
                continue
            return got >= want
    return False


def ensure_go(version: str, cache: Path) -> str | None:
    """Return a PATH prefix that contains a new enough ``go``, or None to use the host."""
    if _go_ok(version):
        return None
    parts = version.split(".")
    patch = version if len(parts) >= 3 and parts[2] != "0" else f"{parts[0]}.{parts[1]}.6"
    system, _machine, goarch = _host()
    dest = cache / "go" / patch
    go_bin = dest / "bin" / "go"
    if not go_bin.is_file():
        url = f"https://go.dev/dl/go{patch}.{system}-{goarch}.tar.gz"
        blob = cache / "go" / f"go{patch}.tar.gz"
        blob.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(url, blob)
        import tarfile
        with tarfile.open(blob) as tf:
            tf.extractall(cache / "go" / f"src-{patch}")
        extracted = cache / "go" / f"src-{patch}" / "go"
        if dest.exists():
            shutil.rmtree(dest)
        os.replace(extracted, dest)
    return str(dest / "bin")


def _env_with(bun: Path | None, go_prefix: str | None) -> dict:
    env = dict(os.environ)
    prefixes = []
    if bun is not None:
        prefixes.append(str(bun.parent))
    if go_prefix:
        prefixes.append(go_prefix)
    if prefixes:
        env["PATH"] = os.pathsep.join(prefixes + [env.get("PATH", "")])
    return env


def _compile_old(root: Path, env: dict) -> Path:
    system, machine, goarch = _host()
    pkg = root / "packages" / "opencode"
    dist = pkg / "dist" / f"opencode-{system}-{machine}" / "bin"
    dist.mkdir(parents=True, exist_ok=True)
    tui_main = root / "packages" / "tui" / "cmd" / "opencode" / "main.go"
    tui_out = dist / "tui"
    if tui_main.is_file():
        _run(
            [
                "go", "build",
                "-ldflags=-s -w -X main.Version=openbench",
                "-o", str(tui_out),
                "./cmd/opencode/main.go",
            ],
            cwd=root / "packages" / "tui",
            env={**env, "CGO_ENABLED": "0", "GOOS": system, "GOARCH": goarch},
        )
    outfile = dist / "opencode"
    cmd = [
        "bun", "build",
        "--define", "OPENCODE_VERSION='openbench'",
        "--compile", "--minify",
        f"--target=bun-{system}-{machine}",
        f"--outfile={outfile}",
        "./src/index.ts",
    ]
    if tui_out.is_file():
        cmd.append(str(tui_out))
    _run(cmd, cwd=pkg, env=env)
    if not outfile.is_file():
        raise BuildError(f"compile did not produce {outfile}")
    return outfile


def _find_binary(root: Path) -> Path:
    pkg = root / "packages" / "opencode"
    found = sorted(pkg.glob("dist/**/bin/opencode"))
    executables = [path for path in found if path.is_file() and os.access(path, os.X_OK)]
    if not executables:
        wrapper = pkg / "bin" / "opencode"
        if wrapper.is_file():
            return wrapper
        raise BuildError(f"no opencode binary under {pkg / 'dist'}")
    return executables[-1]


def _execute_plan(root: Path, plan: dict, cache: Path) -> Path:
    bun_path = ensure_bun(plan["bun"], cache) if plan.get("bun") else None
    go_prefix = ensure_go(plan["go"], cache) if plan.get("go") else None
    env = _env_with(bun_path, go_prefix)
    _run(["bun", "install"], cwd=root, env=env)
    if plan["kind"] == "compile":
        return _compile_old(root, env)
    if plan["kind"] == "bun-run":
        # No compile script. A wrapper keeps ``binary()`` a single executable path.
        pkg = root / "packages" / "opencode"
        wrapper = cache / "wrappers" / "opencode"
        wrapper.parent.mkdir(parents=True, exist_ok=True)
        bun = str(bun_path or "bun")
        wrapper.write_text(
            "#!/bin/sh\n"
            f"exec {bun} run {pkg / 'src' / 'index.ts'} \"$@\"\n",
            encoding="utf-8",
        )
        wrapper.chmod(0o755)
        return wrapper
    _run(plan["args"], cwd=root / plan["cwd"], env=env)
    return _find_binary(root)


def _ensure_mirror(cache: Path) -> Path:
    mirror = cache / "mirror"
    if (mirror / ".git").exists() or (mirror / "HEAD").exists():
        _run(["git", "-C", str(mirror), "fetch", "--all", "--tags", "--prune"], cwd=cache)
        return mirror
    cache.mkdir(parents=True, exist_ok=True)
    try:
        _run(["git", "clone", "--filter=blob:none", UPSTREAM, str(mirror)], cwd=cache)
    except BuildError:
        if mirror.exists():
            shutil.rmtree(mirror)
        _run(["git", "clone", "--filter=blob:none", FALLBACK_UPSTREAM, str(mirror)], cwd=cache)
    return mirror


def _ensure_worktree(mirror: Path, sha: str, dest: Path) -> None:
    if (dest / ".git").exists():
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    _run(
        ["git", "-C", str(mirror), "worktree", "add", "--detach", str(dest), sha],
        cwd=mirror.parent,
    )


def binary(sha: str, cache: Path) -> Path:
    """Return a runnable ``opencode`` for ``sha``, building it on a cache miss."""
    sha = sha.strip().lower()
    if len(sha) != 40:
        raise BuildError(f"expected a 40-character SHA, got {sha!r}")
    # Git resolves a relative dest against ``cwd``. Callers pass ``results/...``.
    cache = Path(cache).resolve()
    published = cache / "bin" / sha / "opencode"
    if published.is_file() and os.access(published, os.X_OK):
        return published
    with exclusive_lock(cache / "locks" / f"{sha}.lock"):
        if published.is_file() and os.access(published, os.X_OK):
            return published
        with exclusive_lock(cache / "mirror.lock"):
            mirror = _ensure_mirror(cache)
            worktree = cache / "worktrees" / sha
            _ensure_worktree(mirror, sha, worktree)
        plan = build_plan(worktree)
        built = _execute_plan(worktree, plan, cache)
        published.parent.mkdir(parents=True, exist_ok=True)
        tmp = published.with_name("opencode.tmp")
        shutil.copy2(built, tmp)
        tmp.chmod(0o755)
        os.replace(tmp, published)
    return published


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build one OpenCode SHA")
    parser.add_argument("sha")
    parser.add_argument("--cache", type=Path, default=Path("results/opencode-src"))
    args = parser.parse_args(argv)
    try:
        print(binary(args.sha, args.cache))
    except BuildError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
