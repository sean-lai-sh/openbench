"""Post-monorepo OpenCode builds: layout, bundled provider, per-cell record.

From 2.0.2x the OpenCode tree has no ``packages/opencode``. The CLI builds
from ``packages/cli`` (``script/build.ts`` writes
``packages/cli/dist/cli-<os>-<arch>/bin/opencode``), and the Anthropic
provider is OpenCode's own code in ``packages/ai``
(``packages/ai/src/providers/anthropic.ts``, package ``@opencode/ai``).
``bun.lock`` has no ``@ai-sdk/anthropic``, so there is nothing to pin or
seed: the provider ships inside the binary.

Step-8 PRs 51062, 53166, and 55613 are on this layout. Their cells run
provider-free (no ``anthropic_sdk``, no ``provider_pins``) and record
``provider_loaded_source=bundled`` plus the bundled ``@opencode/ai`` version
and the git tree id of ``packages/ai/src``. Both sides of each of the three
PRs have the same ``packages/ai/src`` tree, so the provider is not part of
the with/without difference.

This module does not import the rest of ``thesis.ab`` so the build and the
runner can both use it.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

MONOREPO_PRS = ("51062", "53166", "55613")
CLI_DIR = "packages/cli"
CLI_BUILD = "packages/cli/script/build.ts"
LEGACY_DIR = "packages/opencode"
AI_PACKAGE_JSON = "packages/ai/package.json"
AI_SRC = "packages/ai/src"
ANTHROPIC_SOURCE = "packages/ai/src/providers/anthropic.ts"
BUNDLED_PACKAGE = "@opencode/ai"
LOADED_SOURCE = "bundled"
PIN_SOURCE = "bundled_monorepo"
SDK_PACKAGE = "@ai-sdk/anthropic"
# Cell fields this module adds. ``provider_versions`` is not written, so a
# bundled cell is never charged to an @ai-sdk/anthropic version.
CELL_FIELDS = (
    "provider_loaded_source",
    "provider_loaded_probe",
    "bundled_provider_package",
    "bundled_provider_version",
    "bundled_provider_tree",
)


def is_monorepo_tree(root: Path) -> bool:
    """True for a checkout on the post-monorepo layout.

    Needs ``packages/cli/script/build.ts`` and no ``packages/opencode``. A
    tree that still has ``packages/opencode`` keeps the historical path.
    """
    root = Path(root)
    return (root / CLI_BUILD).is_file() and not (root / LEGACY_DIR).exists()


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _git_has(repo: Path, sha: str, path: str) -> bool:
    return _git(repo, "cat-file", "-e", f"{sha}:{path}").returncode == 0


def _git_show(repo: Path, sha: str, path: str) -> str | None:
    proc = _git(repo, "show", f"{sha}:{path}")
    return proc.stdout if proc.returncode == 0 else None


def _git_tree(repo: Path, rev: str, path: str) -> str:
    proc = _git(repo, "rev-parse", "--verify", "--quiet", f"{rev}:{path}")
    return proc.stdout.strip() if proc.returncode == 0 else ""


def layout_at(mirror: Path, sha: str) -> str:
    """``monorepo``, ``legacy``, ``missing`` (sha not in mirror), or ``unknown``."""
    mirror = Path(mirror)
    if _git(mirror, "cat-file", "-e", f"{sha}^{{commit}}").returncode != 0:
        return "missing"
    if _git_has(mirror, sha, LEGACY_DIR):
        return "legacy"
    if _git_has(mirror, sha, CLI_BUILD):
        return "monorepo"
    return "unknown"


def layout_of_tree(root: Path) -> str:
    """Same labels as ``layout_at`` for a checked-out tree."""
    root = Path(root)
    if not (root / "package.json").is_file():
        return "missing"
    if (root / LEGACY_DIR).exists():
        return "legacy"
    if is_monorepo_tree(root):
        return "monorepo"
    return "unknown"


def _ai_version(text: str | None) -> str:
    if not text:
        return ""
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return ""
    if not isinstance(parsed, dict):
        return ""
    if str(parsed.get("name") or "") != BUNDLED_PACKAGE:
        return ""
    return str(parsed.get("version") or "")


def _sdk_in_lock(text: str | None) -> bool:
    return bool(text) and f'"{SDK_PACKAGE}' in text


def _bundled(version: str, has_source: bool, tree: str, lock_text: str | None) -> dict | None:
    if not version or not has_source:
        return None
    return {
        "package": BUNDLED_PACKAGE,
        "version": version,
        "source": ANTHROPIC_SOURCE,
        "tree": tree,
        "sdk_locked": _sdk_in_lock(lock_text),
    }


def bundled_provider_at(mirror: Path, sha: str) -> dict | None:
    """Bundled provider for ``sha`` read from a git mirror, or None."""
    mirror = Path(mirror)
    return _bundled(
        _ai_version(_git_show(mirror, sha, AI_PACKAGE_JSON)),
        _git_has(mirror, sha, ANTHROPIC_SOURCE),
        _git_tree(mirror, sha, AI_SRC),
        _git_show(mirror, sha, "bun.lock"),
    )


def bundled_provider_for_tree(root: Path) -> dict | None:
    """Bundled provider for a checked-out tree, or None.

    ``tree`` is the git tree id of ``packages/ai/src`` at ``HEAD`` when the
    checkout is a git worktree, otherwise ``""``.
    """
    root = Path(root)
    pkg = root / AI_PACKAGE_JSON
    lock = root / "bun.lock"
    try:
        pkg_text = pkg.read_text(encoding="utf-8") if pkg.is_file() else None
        lock_text = lock.read_text(encoding="utf-8") if lock.is_file() else None
    except OSError:
        return None
    tree = _git_tree(root, "HEAD", AI_SRC) if (root / ".git").exists() else ""
    return _bundled(_ai_version(pkg_text), (root / ANTHROPIC_SOURCE).is_file(), tree, lock_text)


def bundled_label(provider: dict | None) -> str:
    """``@opencode/ai@2.0.29`` plus the short tree id when there is one."""
    if not provider:
        return ""
    label = f"{provider['package']}@{provider['version']}"
    if provider.get("tree"):
        label += f" tree {provider['tree'][:12]}"
    return label


def bundled_reason(layout: str, provider: dict | None) -> str:
    """Empty when this side can run provider-free, else why not."""
    if layout == "missing":
        return "commit not found (no mirror or worktree has it)"
    if layout == "legacy":
        return "tree has packages/opencode; not a monorepo build"
    if layout != "monorepo":
        return f"layout {layout}: no {CLI_BUILD}"
    if provider is None:
        return f"no bundled provider ({ANTHROPIC_SOURCE} or {AI_PACKAGE_JSON} missing)"
    if provider.get("sdk_locked"):
        return f"bun.lock still lists {SDK_PACKAGE}; the provider is not only bundled"
    return ""


def bundled_proxy(proxy: dict, provider: dict) -> dict:
    """Copy ``proxy`` for a provider-free cell.

    Drops every key that makes the adapter install or check
    ``@ai-sdk/anthropic`` and records the bundled provider instead.
    """
    out = dict(proxy)
    for key in (
        "anthropic_sdk", "provider_pins", "provider_pin_sha256", "pin_store",
        "pin_from", "sdk_install_alias", "sdk_install_gate",
    ):
        out.pop(key, None)
    out["needs_sdk"] = False
    out["provider_bundled"] = True
    out["provider_loaded_source"] = LOADED_SOURCE
    out["pin_source"] = PIN_SOURCE
    out["bundled_provider_package"] = provider["package"]
    out["bundled_provider_version"] = provider["version"]
    out["bundled_provider_tree"] = provider.get("tree") or ""
    return out


def is_bundled(proxy) -> bool:
    return isinstance(proxy, dict) and bool(proxy.get("provider_bundled"))


def attach_bundled_provider(row: dict, proxy) -> None:
    """Per-cell record for a bundled-provider cell. No-op for other cells.

    The adapter's runtime probe (#156) sets ``provider_loaded_source`` to
    ``preload`` or ``strace`` with ``provider_loaded_version`` when the
    process loaded ``node_modules/@ai-sdk/anthropic``, else ``none``. That
    value is kept as ``provider_loaded_probe``. No load is ``bundled``. A
    load (or an ``@ai-sdk/anthropic`` version in ``provider_versions``) is
    ``separate_install`` and the cell is infra, the same rule #156 applies
    to a loaded version other than the pin.
    """
    if not isinstance(row, dict) or not is_bundled(proxy):
        return
    probe = str(row.get("provider_loaded_source") or "").strip()
    if probe:
        row["provider_loaded_probe"] = probe
    row["bundled_provider_package"] = str(proxy.get("bundled_provider_package") or "")
    row["bundled_provider_version"] = str(proxy.get("bundled_provider_version") or "")
    row["bundled_provider_tree"] = str(proxy.get("bundled_provider_tree") or "")
    row["pin_source"] = PIN_SOURCE
    loaded = str(row.get("provider_loaded_version") or "").strip()
    versions = row.get("provider_versions")
    if not loaded and isinstance(versions, dict):
        on_disk = str(versions.get(SDK_PACKAGE) or "").strip()
        if on_disk and on_disk != "missing":
            loaded = on_disk
    if not loaded:
        row["provider_loaded_source"] = str(proxy.get("provider_loaded_source") or LOADED_SOURCE)
        return
    row["provider_loaded_source"] = "separate_install"
    mismatch = f"provider_bundled_mismatch: loaded {SDK_PACKAGE}@{loaded}; expected bundled {BUNDLED_PACKAGE}"
    row["provider_loaded_mismatch"] = mismatch
    row["failure_class"] = "infra"
    row["completed"] = False
    error = str(row.get("error") or "")
    if mismatch not in error:
        row["error"] = f"{error}; {mismatch}" if error else mismatch


def dist_binaries(root: Path) -> list[Path]:
    """``packages/cli/dist/cli-*/bin/opencode`` under a monorepo checkout."""
    pkg = Path(root) / CLI_DIR
    return sorted(path for path in pkg.glob("dist/cli-*/bin/opencode") if path.is_file())
