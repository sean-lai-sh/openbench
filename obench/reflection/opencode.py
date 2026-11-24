"""The pinned OpenCode snapshot for the reflection loop (``opencode_pin.json``).

Reproduce the pin::

    python3 -m thesis.ab.build_opencode ba54cee55e18b47fb70badc84ae2cbac7c83d258 --cache <cache>
    # prints <cache>/bin/<sha>/opencode; build-stamp.json sits beside it

``thesis/ab/build_opencode.py`` is reused unchanged: it clones the repo, checks
out the SHA in its own worktree, installs the toolchain the tree asks for and
builds the single-file binary. ``verify_binary`` checks a built binary against
the pin before any run.

Every run uses ``--format json --thinking``: at this SHA ``opencode run``
emits ``reasoning`` events only with ``--thinking``
(``packages/opencode/src/cli/cmd/run.ts``), and ``--format json`` is the
step event stream ``trace.py`` reads.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

PIN_PATH = Path(__file__).with_name("opencode_pin.json")


class PinError(Exception):
    pass


def load_pin(path: Path = PIN_PATH) -> dict:
    pin = json.loads(Path(path).read_text(encoding="utf-8"))
    for key in ("sha", "package_version", "repo", "install_source", "run_flags"):
        if not pin.get(key):
            raise PinError(f"opencode pin is missing {key!r}: {path}")
    return pin


def pinned_binary(cache: Path, pin: dict | None = None) -> Path:
    """Where ``build_opencode`` puts the pinned binary under ``cache``."""
    pin = pin or load_pin()
    return Path(cache) / "bin" / pin["sha"] / "opencode"


def verify_binary(binary: Path, pin: dict | None = None, runner=subprocess.run) -> dict:
    """Fail unless ``binary`` is the pinned build: it sits in the pin's
    ``bin/<sha>/`` directory beside the ``build-stamp.json`` that
    ``build_opencode`` writes, and it runs. ``--version`` is recorded, not
    compared: a source build reports a build-time string (``openbench`` or
    ``0.0.0-<channel>-<time>``), never the package version, so the SHA and the
    stamp are the identity. Returns what was checked, for the run record."""
    pin = pin or load_pin()
    binary = Path(binary)
    if binary.parent.name != pin["sha"]:
        raise PinError(f"{binary} is not under bin/{pin['sha']}/ (the pinned build)")
    if not binary.is_file():
        raise PinError(f"pinned opencode binary is missing: {binary}")
    stamp_path = binary.parent / "build-stamp.json"
    if not stamp_path.is_file():
        raise PinError(f"no build-stamp.json beside {binary}; rebuild with thesis/ab/build_opencode.py")
    proc = runner([str(binary), "--version"], capture_output=True, text=True, timeout=60,
                  stdin=subprocess.DEVNULL)
    if proc.returncode != 0:
        raise PinError(f"{binary} --version exited {proc.returncode}")
    reported = ((proc.stdout or "") + (proc.stderr or "")).strip().splitlines()
    return {
        "sha": pin["sha"],
        "package_version": pin["package_version"],
        "reported_version": reported[-1].strip() if reported else "",
        "build_stamp": json.loads(stamp_path.read_text(encoding="utf-8")),
    }


def run_command(binary: Path, instruction: str, model: str, *, variant: str | None = None,
                pin: dict | None = None) -> list[str]:
    """``opencode run --format json --thinking --model <model> [--variant v] <instruction>``.

    ``variant`` is OpenCode's provider reasoning-effort knob. The explicit
    thinking setting itself is whatever reaches the wire, and the trace records
    it from the request payload (TRACE_SCHEMA.md, ``request.thinking_setting``).
    """
    pin = pin or load_pin()
    cmd = [str(binary), *pin["run_flags"], "--model", model]
    if variant:
        cmd += ["--variant", variant]
    return cmd + [instruction]
