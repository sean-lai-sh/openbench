from __future__ import annotations

import argparse
import json
import os
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


def compile_tree(root: Path, bun: Path, cargo_bin: Path | None) -> Path:
    env = dict(os.environ)
    prefixes = [str(bun.parent)]
    if cargo_bin is not None:
        prefixes.insert(0, str(cargo_bin))
    env["PATH"] = os.pathsep.join(prefixes + [env.get("PATH", "")])
    env["CI"] = "1"
    _run(["bun", "install"], root, env)
    scripts = _scripts(root)
    if "build:native" in scripts:
        _run(["bun", "run", "build:native"], root, env)
    if "build" in scripts:
        _run(["bun", "run", "build"], root, env)
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
        requirement = bun_requirement(root)
        version = requirement if requirement[:1].isdigit() and ">=" not in requirement else pick_bun(
            requirement, bun_releases()
        )
        with exclusive_lock(cache / "locks" / f"bun-{version}.lock"):
            bun = ensure_bun(version, cache)
        channel = rust_channel(root)
        cargo_bin = ensure_rust(channel) if channel else None
        entry = compile_tree(root, bun, cargo_bin)
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
