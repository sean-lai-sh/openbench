"""Install language servers into one cell's isolated home.

OpenCode looks up pyright with ``bun install`` under
``$XDG_DATA_HOME/opencode/bin`` and starts the TypeScript server only when
``typescript/lib/tsserver.js`` resolves from the workspace. The C# server is
``roslyn-language-server``, which current NuGet builds install only on the
.NET 10 SDK. OpenCode's own installer uses ``dotnet tool install --global``
and then looks in the data bin, so this helper installs with ``--tool-path``
into that bin and puts it on ``PATH``. A cell whose PATH has no .NET 10 SDK,
and no ``DOTNET_ROOT`` pointing at one, cannot start this server: the helper
raises and the adapter returns ``completed: false``. SDK 8 and 9 fail the
tool's package format.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess

TYPESCRIPT_SPEC = "typescript@5.8.3"
_KNOWN = frozenset({"pyright", "typescript", "dotnet"})
# The runner box keeps the .NET 10 SDK here. OpenCode's C# server is a
# `dotnet tool` and will not start from an older SDK on PATH.
_HOST_DOTNET_ROOT = "/home/box/.dotnet"


class LspProvisionError(RuntimeError):
    def __init__(self, message, *, infra=False):
        super().__init__(message)
        self.infra = bool(infra)


def _which(name: str, env: dict) -> str | None:
    return shutil.which(name, path=env.get("PATH"))


def _run(cmd: list[str], cwd: str, env: dict) -> None:
    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=180,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise LspProvisionError(f"{cmd[0]} failed: {exc}") from exc
    if proc.returncode != 0:
        tail = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
        detail = tail[-400:] if tail else f"exit {proc.returncode}"
        raise LspProvisionError(f"{' '.join(cmd)} failed: {detail}")


def _bun(env: dict, bun: str | None) -> str:
    if bun and os.path.isfile(bun):
        return bun
    found = _which("bun", env)
    if found:
        return found
    raise LspProvisionError("bun is not available to install a language server")


def _prepend(env: dict, directory: str) -> None:
    current = env.get("PATH") or ""
    env["PATH"] = directory + (os.pathsep + current if current else "")


def _pyright(env: dict, bun: str | None) -> str:
    if _which("pyright-langserver", env):
        return "pyright already on PATH"
    data = env.get("XDG_DATA_HOME") or ""
    if not data:
        raise LspProvisionError("XDG_DATA_HOME is not set")
    bindir = os.path.join(data, "opencode", "bin")
    os.makedirs(bindir, exist_ok=True)
    binary = _bun(env, bun)
    child = dict(env)
    child["BUN_BE_BUN"] = "1"
    _run([binary, "install", "pyright"], bindir, child)
    link = os.path.join(bindir, "node_modules", ".bin")
    if not os.path.isdir(link):
        raise LspProvisionError(f"pyright install did not create {link}")
    _prepend(env, link)
    return "installed pyright into the cell data dir"


def _typescript(env: dict, workdir: str, bun: str | None) -> str:
    tsserver = os.path.join(workdir, "node_modules", "typescript", "lib", "tsserver.js")
    if os.path.isfile(tsserver):
        return "typescript already in the workspace"
    binary = _bun(env, bun)
    child = dict(env)
    child["BUN_BE_BUN"] = "1"
    _run([binary, "add", "--exact", TYPESCRIPT_SPEC], workdir, child)
    if not os.path.isfile(tsserver):
        raise LspProvisionError(f"typescript install did not write {tsserver}")
    return f"installed {TYPESCRIPT_SPEC} into the workspace"


def _dotnet_major(dotnet: str, env: dict) -> int:
    home = env.get("HOME") or ""
    cwd = home if home and os.path.isdir(home) else None
    try:
        proc = subprocess.run(
            [dotnet, "--version"],
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise LspProvisionError(f"dotnet --version failed: {exc}") from exc
    text = (proc.stdout or proc.stderr or "").strip()
    if proc.returncode != 0 or not text:
        raise LspProvisionError(f"dotnet --version failed: {text or proc.returncode}")
    head = text.split(".", 1)[0]
    try:
        return int(head)
    except ValueError as exc:
        raise LspProvisionError(f"dotnet version {text!r} is not numeric") from exc


def _dotnet_binary(env: dict, explicit: str | None) -> str | None:
    if explicit and os.path.isfile(explicit):
        return explicit
    found = _which("dotnet", env)
    if found:
        return found
    root = (env.get("DOTNET_ROOT") or "").strip()
    if root:
        candidate = os.path.join(root, "dotnet")
        if os.path.isfile(candidate):
            return candidate
    return None


def _apply_host_dotnet(env: dict) -> None:
    """Put the runner's .NET 10 SDK on PATH when that directory exists."""
    root = _HOST_DOTNET_ROOT
    if not root or not os.path.isdir(root):
        return
    binary = os.path.join(root, "dotnet")
    if not os.path.isfile(binary):
        return
    env["DOTNET_ROOT"] = root
    _prepend(env, root)


_SHA = re.compile(r"^[0-9a-f]{40}$")


def _checkout_root(path: str) -> str | None:
    marker = os.path.join(path, "packages", "opencode", "src", "config", "lsp.ts")
    runtime = os.path.join(path, "packages", "opencode", "src", "lsp", "lsp.ts")
    if os.path.isfile(marker) or os.path.isfile(runtime):
        return path
    return None


def _cached_bin_worktree(binary: str) -> str | None:
    """Map ``cache/bin/<sha>/opencode`` to ``cache/worktrees/<sha>``."""
    parent = os.path.dirname(binary)
    sha = os.path.basename(parent)
    if not _SHA.match(sha):
        return None
    if os.path.basename(os.path.dirname(parent)) != "bin":
        return None
    cache = os.path.dirname(os.path.dirname(parent))
    return _checkout_root(os.path.join(cache, "worktrees", sha))


def worktree_root(binary: str) -> str | None:
    """Return the OpenCode checkout that produced ``binary``, if it is on disk."""
    if not binary:
        return None
    cur = os.path.abspath(binary)
    for _ in range(12):
        found = _checkout_root(cur)
        if found:
            return found
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    cached = _cached_bin_worktree(os.path.abspath(binary))
    if cached:
        return cached
    try:
        with open(binary, encoding="utf-8", errors="replace") as handle:
            text = handle.read(2000)
    except OSError:
        return None
    match = re.search(r"(/\S+)/packages/opencode/src/index\.ts", text)
    if not match:
        return None
    return _checkout_root(match.group(1))


def lsp_boolean_enables_all(root: str) -> bool:
    """True when this tree disables every LSP unless config ``lsp`` is true.

    PR 23771's schema is ``boolean | record`` and the runtime logs
    "all LSPs are disabled" when ``cfg.lsp`` is missing. Earlier trees accept
    ``false | record`` and start builtin servers by default, so writing
    ``lsp: true`` there is rejected by the strict schema.
    """
    schema = os.path.join(root, "packages", "opencode", "src", "config", "lsp.ts")
    runtime = os.path.join(root, "packages", "opencode", "src", "lsp", "lsp.ts")
    try:
        schema_text = open(schema, encoding="utf-8").read()
        runtime_text = open(runtime, encoding="utf-8").read()
    except OSError:
        return False
    if "Schema.Boolean" not in schema_text:
        return False
    return "all LSPs are disabled" in runtime_text


def _dotnet(env: dict, dotnet: str | None) -> str:
    _apply_host_dotnet(env)
    # OpenCode's C# spawn uses which("roslyn-language-server") first. A hit
    # skips its own `dotnet tool install --global`, which writes somewhere
    # other than the data bin it then searches.
    if _which("roslyn-language-server", env):
        return "roslyn-language-server already on PATH"
    binary = _dotnet_binary(env, dotnet)
    if not binary:
        raise LspProvisionError(
            "dotnet SDK 10 is not on PATH; this cell cannot install "
            "roslyn-language-server with --tool-path into "
            "$XDG_DATA_HOME/opencode/bin. OpenCode's own installer uses "
            "`dotnet tool install --global` and then looks in that bin, "
            "which is not where --global writes. "
            "SDK 8 and 9 cannot install the current tool."
        )
    major = _dotnet_major(binary, env)
    if major < 10:
        raise LspProvisionError(
            f"dotnet SDK {major} cannot install roslyn-language-server; SDK 10 or newer is required"
        )
    data = env.get("XDG_DATA_HOME") or ""
    if not data:
        raise LspProvisionError("XDG_DATA_HOME is not set")
    bindir = os.path.join(data, "opencode", "bin")
    os.makedirs(bindir, exist_ok=True)
    _run(
        [binary, "tool", "install", "roslyn-language-server", "--tool-path", bindir, "--prerelease"],
        bindir,
        env,
    )
    installed = os.path.join(bindir, "roslyn-language-server")
    if not os.path.isfile(installed):
        raise LspProvisionError(f"roslyn install did not write {installed}")
    _prepend(env, bindir)
    return "installed roslyn-language-server onto the cell PATH"


def provision_language_servers(env: dict, workdir: str, tools, bun: str | None = None, dotnet: str | None = None) -> list[str]:
    """Install ``tools`` into ``env`` / ``workdir``. Mutates ``env['PATH']``."""
    notes = []
    for name in tools:
        if name not in _KNOWN:
            raise LspProvisionError(f"unknown language server {name!r}")
        if name == "pyright":
            notes.append(_pyright(env, bun))
        elif name == "typescript":
            notes.append(_typescript(env, workdir, bun))
        else:
            notes.append(_dotnet(env, dotnet))
    return notes
