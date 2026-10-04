from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shlex
import subprocess
import sys
from pathlib import Path

from thesis.ab.checkout import checkout
from thesis.ab.durable import exclusive_lock
from thesis.ab.errors import BuildError, Incompatible
from thesis.ab.models_config import supports_custom_models
from thesis.ab.toolchain import ensure_node, node_requirement

_ENTRIES = (
    "packages/coding-agent/dist/cli.js",
    "packages/coding-agent/dist/bundle/cli.js",
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


def _build_script(root: Path) -> str:
    scripts = json.loads((root / "package.json").read_text(encoding="utf-8")).get("scripts") or {}
    if "build:offline" in scripts:
        return "build:offline"
    return "build"


def _without_live_catalog(package_text: str) -> str | None:
    data = json.loads(package_text)
    scripts = data.get("scripts") or {}
    changed = False
    for key, script in list(scripts.items()):
        if not isinstance(script, str):
            continue
        if "generate-models" not in script and "check:model-data" not in script and "check-model-data" not in script:
            continue
        kept = [
            part.strip()
            for part in script.split("&&")
            if "generate-models" not in part and "check:model-data" not in part and "check-model-data" not in part
        ]
        scripts[key] = " && ".join(kept) if kept else "tsgo -p tsconfig.build.json"
        changed = True
    if not changed:
        return None
    data["scripts"] = scripts
    return json.dumps(data, indent="\t") + "\n"


def _fill_missing_catalogs(root: Path) -> None:
    providers = root / "packages" / "ai" / "src" / "providers"
    if not providers.is_dir():
        return
    data_dir = providers / "data"
    for path in providers.glob("*.models.ts"):
        text = path.read_text(encoding="utf-8", errors="replace")
        for name in re.findall(r"\./data/([A-Za-z0-9._-]+\.json)", text):
            dest = data_dir / name
            if dest.is_file():
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text("{}\n", encoding="utf-8")


def _ensure_tsgo_platform(root: Path, env: dict) -> None:
    pkg_path = root / "node_modules" / "@typescript" / "native-preview" / "package.json"
    if not pkg_path.is_file():
        return
    optional = json.loads(pkg_path.read_text(encoding="utf-8")).get("optionalDependencies") or {}
    machine = platform.machine()
    arch = {"x86_64": "x64", "amd64": "x64", "aarch64": "arm64"}.get(machine, machine)
    name = f"@typescript/native-preview-{sys.platform}-{arch}"
    version = optional.get(name)
    if not version:
        return
    if (root / "node_modules" / "@typescript" / name.split("/", 1)[1]).is_dir():
        return
    _run(["npm", "install", "--no-save", "--no-package-lock", f"{name}@{version}"], root, env)


def compile_tree(root: Path, node: Path) -> Path:
    env = dict(os.environ)
    env["PATH"] = str(node.parent) + os.pathsep + env.get("PATH", "")
    env["CI"] = "1"
    _run(["git", "-C", str(root), "checkout", "--", "."], root, env)
    _run(["npm", "ci"], root, env)
    _ensure_tsgo_platform(root, env)
    _fill_missing_catalogs(root)
    ai_package = root / "packages" / "ai" / "package.json"
    if ai_package.is_file():
        rewritten = _without_live_catalog(ai_package.read_text(encoding="utf-8"))
        if rewritten is not None:
            ai_package.write_text(rewritten, encoding="utf-8")
    _run(["npm", "run", _build_script(root)], root, env)
    for relative in _ENTRIES:
        path = root / relative
        if path.is_file():
            return path
    raise BuildError("npm run build did not produce packages/coding-agent/dist/cli.js")


def binary(sha: str, cache: Path) -> Path:
    cache = Path(cache).resolve()
    sha = sha.strip().lower()
    published = cache / "bin" / "pi" / sha / "pi"
    if published.is_file() and os.access(published, os.X_OK):
        return published
    with exclusive_lock(cache / "locks" / f"pi-{sha}.lock"):
        if published.is_file() and os.access(published, os.X_OK):
            return published
        root = checkout(cache, "pi", sha)
        if not supports_custom_models(root):
            raise Incompatible("no custom-model support")
        node = ensure_node(node_requirement(root), cache)
        cli = compile_tree(root, node)
        script = (
            "#!/bin/sh\n"
            f"exec {shlex.quote(str(node))} {shlex.quote(str(cli))} \"$@\"\n"
        )
        return _publish(published, script)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build one Pi SHA")
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
