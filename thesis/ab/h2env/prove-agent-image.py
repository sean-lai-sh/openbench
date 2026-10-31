#!/usr/bin/env python3
"""Prove the agent phase matches unmodified h1-env:1022.

Captures, for every Python on PATH, ``pip list --format=freeze`` and a fixed
set of import checks (torch, numpy, and the other hard-suite checker deps).
Diffs that capture against the same capture inside a fresh ``h1-env:1022``
container. The agent phase must not have ``/opt/h2-checker-venvs`` mounted.

Exit 0 and write an empty unified diff when the two captures are identical.
"""

from __future__ import annotations

import argparse
import difflib
import os
import shutil
import subprocess
import sys
from pathlib import Path

AGENT_IMAGE = "h1-env:1022"
VENV_PATH = "/opt/h2-checker-venvs"
IMPORTS = (
    "torch",
    "torchvision",
    "numpy",
    "pandas",
    "timm",
    "cv2",
    "transformers",
    "pytest",
    "chess",
    "shapely",
    "selenium",
    "bs4",
)


def pythons_on_path(path_value: str | None = None) -> list[str]:
    """Absolute paths of Python interpreters on PATH, in stable order."""
    raw = os.environ.get("PATH", "") if path_value is None else path_value
    found = []
    seen = set()
    for directory in raw.split(os.pathsep):
        if not directory:
            continue
        try:
            names = sorted(os.listdir(directory))
        except OSError:
            continue
        for name in names:
            if name != "python" and not name.startswith("python"):
                continue
            if name.endswith("-config") or name.endswith(".exe"):
                continue
            candidate = os.path.join(directory, name)
            if not os.path.isfile(candidate) or not os.access(candidate, os.X_OK):
                continue
            real = os.path.realpath(candidate)
            if real in seen:
                continue
            # Skip the interpreter if it is not actually Python.
            if "python" not in os.path.basename(real):
                continue
            seen.add(real)
            found.append(real)
    return found


def _run(argv, timeout=120) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(
            argv, capture_output=True, text=True, timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, "", f"{exc.__class__.__name__}: {exc}"
    return proc.returncode, proc.stdout or "", proc.stderr or ""


def _import_line(python: str, module: str) -> str:
    code = (
        "import importlib,sys\n"
        f"name={module!r}\n"
        "try:\n"
        "    importlib.import_module(name)\n"
        "    print('imported')\n"
        "except Exception as exc:\n"
        "    print(type(exc).__name__)\n"
    )
    code_rc, out, err = _run([python, "-c", code], timeout=60)
    kind = (out.strip().splitlines() or [""])[-1].strip()
    if not kind:
        kind = (err.strip().splitlines() or ["error"])[-1].strip()
    return f"import {module}: exit={code_rc} {kind}"


def capture_text() -> str:
    """Fingerprint the process environment the agent can see."""
    if os.path.lexists(VENV_PATH):
        raise SystemExit(
            f"not the agent phase: {VENV_PATH} exists "
            "(checker venvs must be attached only after the agent finishes)"
        )
    lines = ["# agent-phase package capture", f"# venv_path_exists={os.path.lexists(VENV_PATH)}"]
    interpreters = pythons_on_path()
    if not interpreters:
        lines.append("# python: none")
    for python in interpreters:
        lines.append(f"# python {python}")
        rc, out, err = _run([python, "--version"])
        version = (out or err).strip().replace("\n", " ")
        lines.append(f"# version exit={rc} {version}")
        pip_rc, pip_out, pip_err = _run([python, "-m", "pip", "list", "--format=freeze"])
        lines.append(f"# pip exit={pip_rc}")
        if pip_rc == 0:
            packages = sorted(
                line.strip() for line in pip_out.splitlines() if line.strip() and not line.startswith("#")
            )
            lines.extend(packages or ["# pip: empty"])
        else:
            detail = (pip_err or pip_out).strip().splitlines()
            lines.append("# pip: absent" if not detail else f"# pip: absent {detail[-1]}")
        for module in IMPORTS:
            lines.append(_import_line(python, module))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def unified_diff(agent: str, baseline: str) -> str:
    """Unified diff of the two captures. Empty string when they match."""
    return "".join(difflib.unified_diff(
        agent.splitlines(keepends=True),
        baseline.splitlines(keepends=True),
        fromfile="agent-phase",
        tofile="h1-env:1022",
    ))


def baseline_from_docker(image: str, script: Path) -> str:
    """Run this script's capture inside a fresh container of ``image``."""
    if not shutil.which("docker"):
        raise SystemExit(f"docker is not available; cannot capture {image}")
    sudo = ["sudo"] if os.environ.get("PROVE_DOCKER_SUDO") else []
    proc = subprocess.run(
        sudo + [
            "docker", "run", "--rm", "--network", "none",
            "-v", f"{script.resolve()}:/prove-agent-image.py:ro",
            "--entrypoint", "python3", image,
            "/prove-agent-image.py", "--capture",
        ],
        capture_output=True, text=True, timeout=300,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise SystemExit(f"baseline capture in {image} failed: {detail}")
    return proc.stdout


def agent_from_runner(harness: str, image: str, script: Path) -> tuple[str, list[str]]:
    """Capture inside the exact ``docker run`` argv the cell runner builds.

    Uses ``obench.docker_exec.build_docker_cmd`` for ``harness`` on ``image``
    (same mounts, env, PATH and proxy-bridge args as a real cell), swapping
    only the trailing ``entry.py`` command for this script's ``--capture``.
    No model is called.
    """
    import tempfile
    repo = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(repo))
    from obench import docker_exec

    with tempfile.TemporaryDirectory(prefix="prove-agent-", dir=str(Path.home())) as tmp:
        work = Path(tmp) / "work"
        work.mkdir()
        instr = Path(tmp) / "instruction.txt"
        instr.write_text("capture only\n", encoding="utf-8")
        cmd = docker_exec.build_docker_cmd(
            harness, str(work), "capture-only", 60,
            str(repo / "obench" / "adapters"), image, str(instr),
        )
        idx = len(cmd) - 1 - cmd[::-1].index(image)
        argv = cmd[:idx] + [
            "-v", f"{script.resolve()}:/prove-agent-image.py:ro",
            "--entrypoint", "python3", image, "/prove-agent-image.py", "--capture",
        ]
        if os.environ.get("PROVE_DOCKER_SUDO"):
            argv = ["sudo", "-E"] + argv
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=300)
    if proc.returncode != 0:
        raise SystemExit(f"agent capture via runner argv failed: {(proc.stderr or proc.stdout).strip()}")
    return proc.stdout, argv


def baseline_from_python(python: str) -> str:
    """Re-run the capture under another interpreter in this environment."""
    script = Path(__file__).resolve()
    proc = subprocess.run(
        [python, str(script), "--capture"],
        capture_output=True, text=True, timeout=300,
        env={key: value for key, value in os.environ.items()
             if key not in {"H2_CHECKER_VENV_ROOT", "OBENCH_CHECKER_VENV_STAGE"}},
    )
    if proc.returncode != 0:
        raise SystemExit(proc.stderr or proc.stdout)
    return proc.stdout


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", action="store_true", help="print the agent-phase capture")
    parser.add_argument(
        "--agent-image",
        default="",
        help="capture the agent phase from this image (a fresh container, no checker venvs)",
    )
    parser.add_argument(
        "--agent-harness",
        default="",
        help="capture the agent phase from the runner's own docker argv for this harness (e.g. pi, opencode)",
    )
    parser.add_argument("--baseline-image", default=AGENT_IMAGE)
    parser.add_argument("--baseline-python", default="", help="compare against this interpreter instead of docker")
    parser.add_argument("--baseline-file", default="", help="compare against a saved capture")
    parser.add_argument(
        "--out",
        default=str(Path(__file__).resolve().parent / "agent-phase-vs-h1.diff"),
    )
    args = parser.parse_args(argv)
    if args.capture:
        sys.stdout.write(capture_text())
        return 0
    if args.agent_harness:
        agent, argv = agent_from_runner(args.agent_harness, args.agent_image or AGENT_IMAGE, Path(__file__).resolve())
        print("agent argv: " + " ".join(argv), file=sys.stderr)
    elif args.agent_image:
        agent = baseline_from_docker(args.agent_image, Path(__file__).resolve())
    else:
        agent = capture_text()
    if args.baseline_file:
        baseline = Path(args.baseline_file).read_text(encoding="utf-8")
        source = args.baseline_file
    elif args.baseline_python:
        baseline = baseline_from_python(args.baseline_python)
        source = args.baseline_python
    else:
        baseline = baseline_from_docker(args.baseline_image, Path(__file__).resolve())
        source = args.baseline_image
    diff = unified_diff(agent, baseline)
    out = Path(args.out)
    if diff:
        out.write_text(diff, encoding="utf-8")
        sys.stderr.write(diff)
        print(f"differs from {source}; wrote {out}", file=sys.stderr)
        return 1
    report = (
        "identical\n"
        f"baseline_image: {AGENT_IMAGE}\n"
        f"baseline_source: {source}\n"
        f"venv_path {VENV_PATH} absent during capture\n"
    )
    out.write_text(report, encoding="utf-8")
    sys.stdout.write(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
