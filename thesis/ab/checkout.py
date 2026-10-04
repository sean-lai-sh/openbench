from __future__ import annotations

import subprocess
from pathlib import Path

from thesis.ab.durable import exclusive_lock
from thesis.ab.errors import BuildError
from thesis.ab.harness import clone_urls


def _run(cmd: list[str], cwd: Path) -> None:
    proc = subprocess.run(cmd, cwd=cwd, text=True)
    if proc.returncode != 0:
        raise BuildError(f"command failed ({proc.returncode}): {' '.join(cmd)}")


def _ensure_mirror(mirror: Path, urls: tuple[str, ...]) -> None:
    if (mirror / ".git").exists() or (mirror / "HEAD").exists():
        _run(["git", "-C", str(mirror), "fetch", "--all", "--tags", "--prune"], cwd=mirror.parent)
        return
    mirror.parent.mkdir(parents=True, exist_ok=True)
    errors = []
    for url in urls:
        if mirror.exists():
            import shutil
            shutil.rmtree(mirror)
        try:
            _run(["git", "clone", "--filter=blob:none", url, str(mirror)], cwd=mirror.parent)
            return
        except BuildError as exc:
            errors.append(str(exc))
    raise BuildError("clone failed: " + "; ".join(errors))


def _ensure_worktree(mirror: Path, sha: str, dest: Path) -> None:
    if (dest / ".git").exists():
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    _run(
        ["git", "-C", str(mirror), "worktree", "add", "--detach", str(dest), sha],
        cwd=mirror.parent,
    )


def checkout(cache: Path, name: str, sha: str) -> Path:
    sha = sha.strip().lower()
    if len(sha) != 40:
        raise BuildError(f"expected a 40-character SHA, got {sha!r}")
    # Git resolves a relative dest against ``cwd``. Callers pass ``results/...``.
    cache = Path(cache).resolve()
    dest = cache / "worktrees" / name / sha
    mirror = cache / "mirrors" / name
    with exclusive_lock(cache / "locks" / f"{name}.mirror.lock"):
        _ensure_mirror(mirror, clone_urls(name))
        _ensure_worktree(mirror, sha, dest)
    return dest
