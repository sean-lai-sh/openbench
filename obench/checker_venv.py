"""Checker virtualenvs are a separate artifact from the agent image.

The agent runs in unmodified ``h1-env:1022``. ``/opt/h2-checker-venvs`` is not
part of that image. A separate image, ``h2-checker-venvs``, is extracted to a
stage directory and copied into a cell-private directory only after the agent
phase, for the checker process. During the agent phase the mount path is
absent and ``python -c 'import torch'`` matches a probe of ``h1-env:1022``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

AGENT_IMAGE = "h1-env:1022"
CHECKER_VENV_IMAGE = "h2-checker-venvs"
# Visible path the agent must not have. Baking the venvs into the agent image
# puts this directory on disk for the whole cell.
AGENT_VENV_PATH = "/opt/h2-checker-venvs"
STAGE_ENV = "OBENCH_CHECKER_VENV_STAGE"
AGENT_IMAGE_ENV = "OBENCH_AGENT_IMAGE"
AGENT_DIGEST_ENV = "OBENCH_AGENT_IMAGE_DIGEST"
H1_TORCH_PROBE_ENV = "OBENCH_H1_TORCH_PROBE"
CHECKER_ROOT_ENV = "H2_CHECKER_VENV_ROOT"
ENV_CAUSE_AGENT_IMAGE = "agent_image_drift"
TORCH_CODE = "import torch"


class AgentEnvironmentError(RuntimeError):
    """The agent process can see a different environment than h1-env:1022."""


def checker_split_enabled() -> bool:
    """True when a separate checker-venv stage is configured for this process."""
    return bool(os.environ.get(STAGE_ENV, "").strip())


def agent_image_name() -> str:
    """Tag of the image the agent runs in. Never the checker-venv artifact."""
    name = os.environ.get(AGENT_IMAGE_ENV, "").strip() or AGENT_IMAGE
    if name == CHECKER_VENV_IMAGE or name.startswith(CHECKER_VENV_IMAGE + ":"):
        raise AgentEnvironmentError(
            f"agent image {name} is the checker venv artifact"
        )
    return name


def normalize_torch_probe(returncode, stderr) -> str:
    """Identity of ``python -c 'import torch'`` independent of install paths."""
    text = stderr or ""
    if isinstance(text, bytes):
        text = text.decode("utf-8", errors="replace")
    if "ModuleNotFoundError" in text and "torch" in text:
        return "ModuleNotFoundError:torch"
    if returncode == 0 and "ModuleNotFoundError" not in text:
        return "imported"
    line = next((item.strip() for item in str(text).splitlines() if item.strip()), "")
    return f"exit={returncode}:{line}"


def torch_probe_argv(python="python3"):
    return [python, "-c", TORCH_CODE]


def run_torch_probe(runner=None, python="python3"):
    """Run the torch import. ``runner`` is ``subprocess.run``-shaped."""
    if runner is None:
        runner = subprocess.run
    try:
        proc = runner(
            torch_probe_argv(python),
            capture_output=True, text=True, timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, f"{exc.__class__.__name__}: {exc}"
    stderr = getattr(proc, "stderr", "") or ""
    code = getattr(proc, "returncode", 1)
    return code, stderr


def h1_torch_probe(image=None, runner=None):
    """Probe torch inside a fresh ``h1-env:1022`` container.

    ``OBENCH_H1_TORCH_PROBE`` is the normalized result captured on the host
    when this process cannot start containers. Without either, the check
    cannot show the agent matches the original image.
    """
    pinned = os.environ.get(H1_TORCH_PROBE_ENV, "").strip()
    if pinned:
        return pinned
    image = image or AGENT_IMAGE
    if runner is None:
        runner = subprocess.run
    try:
        proc = runner(
            [
                "docker", "run", "--rm", "--network", "none",
                "--entrypoint", "python3", image, "-c", TORCH_CODE,
            ],
            capture_output=True, text=True, timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AgentEnvironmentError(
            f"cannot probe torch in {image}: {exc}"
        ) from exc
    return normalize_torch_probe(getattr(proc, "returncode", 1), getattr(proc, "stderr", "") or "")


def assert_agent_phase(venv_path, live_probe, h1_probe) -> None:
    """Fail if the agent can see checker venvs or a different torch than h1.

    ``live_probe`` and ``h1_probe`` are either normalized strings or
    ``(returncode, stderr)`` pairs from ``python -c 'import torch'``.
    """
    path = Path(venv_path)
    if os.path.lexists(path):
        raise AgentEnvironmentError(
            f"{path} exists during the agent phase; "
            f"checker venvs are not part of {AGENT_IMAGE}"
        )
    live = live_probe if isinstance(live_probe, str) else normalize_torch_probe(*live_probe)
    baseline = h1_probe if isinstance(h1_probe, str) else normalize_torch_probe(*h1_probe)
    if live != baseline:
        raise AgentEnvironmentError(
            "python -c 'import torch' during the agent phase "
            f"does not match {AGENT_IMAGE} ({live} != {baseline})"
        )


def agent_image_digest(inspect=None) -> str | None:
    """Immutable id of the agent image, for pairing cells.

    ``OBENCH_AGENT_IMAGE_DIGEST`` wins so a cell inside the container can
    record the digest the host inspected. Otherwise inspect the agent tag.
    """
    pinned = os.environ.get(AGENT_DIGEST_ENV, "").strip()
    if pinned:
        return pinned
    if inspect is None:
        from .run import docker_image_digest
        inspect = docker_image_digest
    try:
        return inspect(agent_image_name())
    except AgentEnvironmentError:
        raise
    except Exception:
        return None


def note_agent_image(row: dict) -> dict:
    """Record the agent image when this process is an H2 cell.

    Unrelated local runs leave the columns null. A configured digest is used
    as-is so the cell does not have to inspect Docker itself.
    """
    if not (
        checker_split_enabled()
        or os.environ.get(AGENT_IMAGE_ENV, "").strip()
        or os.environ.get(AGENT_DIGEST_ENV, "").strip()
    ):
        return row
    digest = os.environ.get(AGENT_DIGEST_ENV, "").strip() or None
    if digest is None:
        digest = agent_image_digest()
    return stamp_agent_image(row, digest)


def stamp_agent_image(row: dict, digest: str | None = None) -> dict:
    """Record the agent image tag and digest on a cell. Does not touch the checker image."""
    if not isinstance(row, dict):
        return row
    row["agent_image"] = agent_image_name()
    if digest is None and AGENT_DIGEST_ENV in os.environ:
        digest = os.environ.get(AGENT_DIGEST_ENV, "").strip() or None
    if "agent_image_digest" not in row or digest is not None:
        row["agent_image_digest"] = digest
    return row


def guard_agent_phase(venv_path=None, live_probe=None, h1_probe=None) -> None:
    """Runtime check used immediately before the adapter starts."""
    path = venv_path if venv_path is not None else AGENT_VENV_PATH
    if live_probe is None:
        live_probe = run_torch_probe()
    if h1_probe is None:
        h1_probe = h1_torch_probe()
    assert_agent_phase(path, live_probe, h1_probe)


def attach_checker_venvs(stage, dest) -> Path:
    """Copy the staged checker artifact into ``dest`` for this checker only.

    ``dest`` is cell-private. This does not create ``/opt/h2-checker-venvs``,
    so a concurrent agent still sees that path absent.
    """
    stage = Path(stage)
    dest = Path(dest)
    if not stage.is_dir():
        raise AgentEnvironmentError(f"checker venv stage is missing: {stage}")
    if dest.exists():
        raise AgentEnvironmentError(f"checker venv destination already exists: {dest}")
    if Path(AGENT_VENV_PATH) in dest.resolve().parents or dest.resolve() == Path(AGENT_VENV_PATH):
        raise AgentEnvironmentError(
            f"refusing to attach checker venvs at {AGENT_VENV_PATH} on the agent image"
        )
    shutil.copytree(stage, dest, symlinks=True)
    relocate_venvs(dest)
    return dest


def relocate_venvs(dest) -> None:
    """Point the copied venvs at the interpreter copied alongside them.

    The artifact is built at ``/opt/h2-checker-venvs`` with its uv-managed
    interpreter under ``.uv-python``. Venv ``bin/python`` symlinks and
    ``pyvenv.cfg`` ``home`` are absolute, so rewrite every one that points
    under the build path to the same place under ``dest``. Links pointing
    anywhere else are left alone; ``verify_checker_venv`` rejects them if
    they do not resolve.
    """
    dest = Path(dest)
    prefix = AGENT_VENV_PATH.rstrip("/") + "/"
    for path in sorted(dest.rglob("*")):
        if path.is_symlink():
            target = os.readlink(path)
            if target.startswith(prefix):
                path.unlink()
                os.symlink(str(dest / target[len(prefix):]), path)
        elif path.name == "pyvenv.cfg" and path.is_file():
            text = path.read_text(encoding="utf-8")
            if prefix in text:
                path.write_text(text.replace(prefix, str(dest) + "/"), encoding="utf-8")


def stage_dir() -> Path | None:
    raw = os.environ.get(STAGE_ENV, "").strip()
    return Path(raw) if raw else None


def prepare_checker_root(parent: Path) -> Path | None:
    """Attach venvs after the agent phase. Returns the checker root, or None."""
    stage = stage_dir()
    if stage is None:
        return None
    dest = Path(parent) / "h2-checker-venvs"
    return attach_checker_venvs(stage, dest)
