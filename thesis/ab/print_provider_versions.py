"""Print resolved ``@ai-sdk/*`` versions for one OpenCode build.

Usage:
    python3 -m thesis.ab.print_provider_versions BUILD [--side SIDE] [--cache DIR] [--root CHECKOUT]

BUILD is a full SHA or a unique prefix. The manifest pin is printed for
each matching side. When ``--root`` or a worktree under ``--cache`` has a
``bun.lock`` or ``node_modules``, the locked and installed versions are
printed beside it. Columns are tab-separated so a VM listing and a box
listing can be diffed.

``--cache`` is the OpenCode source cache (``.../worktrees/<sha>``).
``--root`` is an explicit checkout and wins over the cache worktree.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from thesis.ab.provider_pin import (
    PinLookupError,
    installed_packages,
    iter_sides,
    resolve_sha,
)
from thesis.ab.sdk_pin import _entry, load_jsonc


def locked_packages(root: Path) -> dict:
    """Exact ``@ai-sdk/*`` and ``@opencode-ai/plugin`` versions in ``bun.lock``."""
    path = Path(root) / "bun.lock"
    if not path.is_file():
        return {}
    try:
        data = load_jsonc(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return {}
    packages = data.get("packages") if isinstance(data, dict) else None
    if not isinstance(packages, dict):
        return {}
    found = {}
    for name in packages:
        if not (str(name).startswith("@ai-sdk/") or name == "@opencode-ai/plugin"):
            continue
        version, _provider = _entry(packages, name)
        if version:
            found[str(name)] = version
    return found


def _checkout(cache: Path | None, sha: str, root: Path | None) -> Path | None:
    if root is not None:
        return Path(root)
    if cache is None or not sha:
        return None
    cache = Path(cache)
    names = [sha]
    if len(sha) >= 7:
        try:
            matches = [path.name for path in (cache / "worktrees").iterdir() if path.name.startswith(sha)]
        except OSError:
            matches = []
        if len(matches) == 1:
            names = matches
    for name in names:
        for candidate in (
            cache / "worktrees" / name,
            cache / "worktrees" / "opencode" / name,
        ):
            if (candidate / "bun.lock").is_file() or (candidate / "package.json").is_file():
                return candidate
    if (cache / "node_modules").is_dir() or (cache / "bun.lock").is_file():
        return cache
    return None


def format_build(sha: str, side: str = "", cache: Path | None = None, root: Path | None = None) -> str:
    full = resolve_sha(sha)
    rows = iter_sides(full, side)
    if side and not rows:
        raise PinLookupError(f"no pin for {full} side {side}")
    checkout = _checkout(cache, full, root)
    locked = locked_packages(checkout) if checkout is not None else {}
    installed = installed_packages(checkout) if checkout is not None else {}
    if cache is not None and (Path(cache) / "node_modules").is_dir() and checkout != Path(cache):
        for name, version in installed_packages(cache).items():
            installed.setdefault(name, version)
    lines = [f"sha\t{full}"]
    if checkout is not None:
        lines.append(f"checkout\t{checkout}")
    for row in rows:
        entry = row["entry"] if isinstance(row["entry"], dict) else {}
        lines.append(
            "side\t{side}\tpr\t{pr}\tevidence\t{evidence}\tpin_source\t{pin_source}".format(
                side=row["side"],
                pr=entry.get("pr") or "",
                evidence=entry.get("evidence") or "",
                pin_source=entry.get("pin_source") or "",
            )
        )
        lines.append("package\tmanifest\tlocked\tinstalled")
        names = sorted(set(row["packages"]) | set(locked) | set(installed))
        for name in names:
            lines.append(
                "\t".join([
                    name,
                    str(row["packages"].get(name) or ""),
                    str(locked.get(name) or ""),
                    str(installed.get(name) or ""),
                ])
            )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Print manifest, lockfile, and installed @ai-sdk versions for one OpenCode build",
    )
    parser.add_argument("build", help="full build SHA or a unique prefix")
    parser.add_argument("--side", default="", help="with, without, aa-1, or aa-2")
    parser.add_argument("--cache", type=Path, default=None, help="OpenCode source cache")
    parser.add_argument("--root", type=Path, default=None, help="explicit checkout")
    args = parser.parse_args(argv)
    try:
        sys.stdout.write(format_build(args.build, args.side, args.cache, args.root))
    except PinLookupError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
