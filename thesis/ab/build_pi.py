from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import tarfile
import tempfile
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


def _extract_packed(tarball: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tarball) as archive:
        for member in archive.getmembers():
            if not member.name.startswith("package/") or member.issym() or member.islnk():
                continue
            relative = member.name[len("package/"):]
            if not relative or Path(relative).is_absolute() or ".." in Path(relative).parts:
                continue
            target = dest / relative
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            extracted = archive.extractfile(member)
            if extracted is None:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(extracted.read())
            target.chmod(member.mode & 0o777)


def _linux_x64(name: str) -> bool:
    lowered = name.lower()
    if "linux" not in lowered or "x64" not in lowered:
        return False
    if "musl" in lowered:
        return False
    return True


def _optional_dest(root: Path, name: str) -> Path:
    if name.startswith("@"):
        scope, pkg = name.split("/", 1)
        return root / "node_modules" / scope / pkg
    return root / "node_modules" / name


def _pack_into(root: Path, env: dict, name: str, version: str, dest: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="npm-pack-") as tmp:
        _run(["npm", "pack", f"{name}@{version}", "--pack-destination", tmp], root, env)
        balls = list(Path(tmp).glob("*.tgz"))
        if len(balls) != 1:
            raise BuildError(f"npm pack {name}@{version} produced {len(balls)} tarballs")
        _extract_packed(balls[0], dest)


def _install_missing_optionals(root: Path, env: dict) -> None:
    node_modules = root / "node_modules"
    manifests = list(node_modules.glob("*/package.json"))
    manifests.extend(node_modules.glob("@*/*/package.json"))
    wanted: list[tuple[str, str]] = []
    for manifest in manifests:
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for name, version in (data.get("optionalDependencies") or {}).items():
            if not isinstance(name, str) or not isinstance(version, str):
                continue
            if not _linux_x64(name):
                continue
            dest = _optional_dest(root, name)
            if (dest / "package.json").is_file():
                continue
            wanted.append((name, version))
    for name, version in wanted:
        _pack_into(root, env, name, version, _optional_dest(root, name))


def compile_tree(root: Path, node: Path) -> Path:
    env = dict(os.environ)
    env["PATH"] = str(node.parent) + os.pathsep + env.get("PATH", "")
    env["CI"] = "1"
    _run(["git", "-C", str(root), "checkout", "--", "."], root, env)
    _run(["npm", "ci"], root, env)
    _install_missing_optionals(root, env)
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
