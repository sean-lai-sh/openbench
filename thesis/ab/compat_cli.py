from __future__ import annotations

import re
import subprocess
from pathlib import Path

from thesis.ab.compat import Assessment
from thesis.ab.harness import agent_layout
from thesis.ab.models_config import MODEL_ID, PROVIDER, model_document


def _flag_present(help_text: str, flag: str) -> bool:
    return re.search(rf"(?:^|\s){re.escape(flag)}(?:,|\s|\[|$)", help_text, re.M) is not None


def help_text(binary: str, timeout_s: int = 20) -> str:
    for flag in ("--help", "-h"):
        try:
            proc = subprocess.run(
                [binary, flag],
                capture_output=True,
                text=True,
                timeout=timeout_s,
                stdin=subprocess.DEVNULL,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        text = (proc.stdout or "") + (proc.stderr or "")
        if text.strip():
            return text
    return ""


def extra_args(text: str, name: str) -> list[str]:
    args = []
    if _flag_present(text, "--no-session"):
        args.append("--no-session")
    if name == "pi" and _flag_present(text, "--approve"):
        args.append("--approve")
    if name == "omp":
        args.append("--yolo")
    return args


def assess_cli(binary: str, root: Path, name: str, proxy_base: str) -> Assessment:
    text = help_text(binary)
    if not text.strip():
        return Assessment(
            "incompatible", "could not read --help", {}, False, None, name,
        )
    layout = agent_layout(name)
    body = model_document(root, proxy_base, layout["models_filename"])
    vertex = {
        "bin": binary,
        "proxy_url": proxy_base,
        "agent_env": layout["agent_env"],
        "home_dir": layout["home_dir"],
        "models_filename": layout["models_filename"],
        "models_body": body,
        "extra_args": extra_args(text, name),
        "provider": PROVIDER,
        "model_id": MODEL_ID,
    }
    return Assessment(
        "configured",
        "custom model via the shared proxy",
        {},
        False,
        vertex,
        name,
    )
