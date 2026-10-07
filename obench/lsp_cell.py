"""Install language servers into one cell's isolated home.

OpenCode looks up pyright with ``bun install`` under
``$XDG_DATA_HOME/opencode/bin`` and starts the TypeScript server only when
``typescript/lib/tsserver.js`` resolves from the workspace. The C# server is
``roslyn-language-server``, which current NuGet builds install only on the
.NET 10 SDK. OpenCode's own installer uses ``dotnet tool install --global``
and then looks in the data bin, so this helper installs with ``--tool-path``
into that bin and puts it on ``PATH``.
"""

from __future__ import annotations

import os
import shutil
import subprocess

TYPESCRIPT_SPEC = "typescript@5.8.3"
_KNOWN = frozenset({"pyright", "typescript", "dotnet"})


class LspProvisionError(RuntimeError):
    pass


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


def _dotnet(env: dict, dotnet: str | None) -> str:
    binary = dotnet if dotnet and os.path.isfile(dotnet) else _which("dotnet", env)
    if not binary:
        raise LspProvisionError("dotnet SDK 10 is not on PATH")
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
