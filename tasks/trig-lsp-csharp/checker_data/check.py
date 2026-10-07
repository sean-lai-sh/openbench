"""Grade Program.cs by building it.

Roslyn does not report semantic errors for a loose file, so the fixture is
two syntax errors and the only pass is ``dotnet build`` exiting 0. A missing
SDK is not a wrong answer: the checker exits 2, which the runner records as
infra.
"""

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HOST_DOTNET = "/home/box/.dotnet/dotnet"
SDK_MISSING = "dotnet SDK was not found"


def host_dotnet(env: dict | None = None) -> str:
    """Box SDK path. ``OBENCH_HOST_DOTNET`` overrides the default."""
    base = os.environ if env is None else env
    override = (base.get("OBENCH_HOST_DOTNET") or "").strip()
    return override or HOST_DOTNET


def resolve_dotnet(env: dict | None = None) -> str | None:
    """PATH, then ``DOTNET_ROOT``, then the box SDK."""
    base = os.environ if env is None else env
    found = shutil.which("dotnet", path=base.get("PATH"))
    if found:
        return found
    root = (base.get("DOTNET_ROOT") or "").strip()
    if root:
        candidate = os.path.join(root, "dotnet")
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    host = host_dotnet(base)
    if host and os.path.isfile(host) and os.access(host, os.X_OK):
        return host
    return None


def prepare_dotnet_env(env: dict | None = None) -> tuple[dict, str | None]:
    base = dict(os.environ if env is None else env)
    binary = resolve_dotnet(base)
    if not binary:
        return base, None
    root = os.path.dirname(binary)
    if not (base.get("DOTNET_ROOT") or "").strip():
        base["DOTNET_ROOT"] = root
    path = base.get("PATH") or ""
    parts = path.split(os.pathsep) if path else []
    if root not in parts:
        base["PATH"] = os.pathsep.join([root, path]) if path else root
    home = (base.get("HOME") or "").strip()
    if not home or not os.path.isdir(home) or not os.access(home, os.W_OK):
        cli_home = (base.get("DOTNET_CLI_HOME") or "").strip()
        if not cli_home or not os.path.isdir(cli_home):
            base["DOTNET_CLI_HOME"] = tempfile.mkdtemp(prefix="obench-dotnet-home-")
    return base, binary


def main() -> int:
    env, binary = prepare_dotnet_env()
    if not binary:
        print(SDK_MISSING + "; the checker cannot run dotnet build", file=sys.stderr)
        return 2
    proc = subprocess.run(
        [binary, "build", "--nologo", "-v", "q"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
    )
    if proc.returncode == 0:
        print("dotnet build passed")
        print("OBENCH_VERDICT: pass")
        return 0
    sys.stdout.write(proc.stdout or "")
    print("OBENCH_VERDICT: fail")
    return 1


if __name__ == "__main__":
    import traceback
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        raise SystemExit(2)
