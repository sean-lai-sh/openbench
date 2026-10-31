"""Capture the real Pi harness's requests at a loopback stub (no model call).

The Pi counterpart of ``thesis.ab.step8_stub_ready --capture``, which drives
only the OpenCode adapter. This runs the pinned Pi binary through
``obench.adapters.pi_harness``, the adapter the #196 Pi cells used, with its
proxy URL pointed at ``build_check.CaptureStub``. The stub answers end_turn
"ok", so the run ends after one turn and nothing is billed.

    python -m thesis.base_agent.capture_pi --cache results/harness-src \\
        --model claude-sonnet-5-5 --out thesis/base_agent/captures/pi

    # or with a prebuilt Pi (e.g. the #196 binary on the thesis VM):
    python -m thesis.base_agent.capture_pi --binary ~/h1/harness-src/bin/pi/<pin>/pi \\
        --model claude-sonnet-5-5 --out thesis/base_agent/captures/pi

Writes ``real.requests.jsonl`` and ``capture.toml`` (see captures/README.md).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import tempfile
import time
from pathlib import Path

from thesis.base_agent.build_check import DEFAULT_INSTRUCTION, CaptureStub, write_requests

_ENV = ("OBENCH_PI_HARNESS", "OBENCH_VERTEX_PROXY_URL", "OBENCH_VERTEX_CELL_ID", "OBENCH_VERTEX_LEDGER_DIR",
        "OBENCH_PI_BIN", "OBENCH_PI_PIN_FILE", "OBENCH_PI_VERTEX", "OBENCH_PI_SETTINGS_PATH")


def capture(binary: Path, pin: str, model: str, instruction: str, timeout_s: int = 180) -> dict:
    from obench.adapters import pi_harness

    pin_file = Path(str(binary) + ".pin")
    pin_file.write_text(pin + "\n", encoding="utf-8")
    saved = {k: os.environ.get(k) for k in _ENV}
    stub = CaptureStub()
    try:
        with tempfile.TemporaryDirectory(prefix="pi-capture-") as work, \
                tempfile.TemporaryDirectory(prefix="pi-ledger-") as ledger:
            os.environ.pop("OBENCH_PI_VERTEX", None)
            os.environ.update({"OBENCH_PI_HARNESS": "1", "OBENCH_VERTEX_PROXY_URL": stub.url,
                               "OBENCH_VERTEX_CELL_ID": "ac3capture", "OBENCH_VERTEX_LEDGER_DIR": ledger,
                               "OBENCH_PI_BIN": str(binary), "OBENCH_PI_PIN_FILE": str(pin_file),
                               "OBENCH_PI_SETTINGS_PATH": str(Path(ledger) / "settings.json")})
            row = pi_harness.run(instruction, work, model, timeout_s)
            return {"requests": list(stub.requests), "workdir": work, "row": row}
    finally:
        stub.close()
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _system_text(requests: list[dict]) -> str:
    from thesis.base_agent.build_check import _body, _text_of, main_request
    return _text_of(_body(main_request(requests)).get("system"))


def main(argv=None) -> int:
    from obench.adapters.pi_harness import PIN
    from thesis.ab.build_pi import binary as build_binary

    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--cache", type=Path, help="thesis.ab.build_pi cache; builds the pinned Pi on a miss")
    src.add_argument("--binary", type=Path, help="an existing Pi binary built at the pin (skips the build)")
    p.add_argument("--model", default="claude-sonnet-5-5")
    p.add_argument("--instruction", default=DEFAULT_INSTRUCTION)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args(argv)
    binary = a.binary.expanduser().resolve() if a.binary else Path(build_binary(PIN, a.cache.resolve()))
    if not binary.is_file():
        raise SystemExit(f"no Pi binary at {binary}")
    got = capture(binary, PIN, a.model, a.instruction)
    if not got["requests"]:
        raise SystemExit(f"no request reached the stub: {json.dumps(got['row'], default=str)[:500]}")
    a.out.mkdir(parents=True, exist_ok=True)
    write_requests(a.out / "real.requests.jsonl", got["requests"])
    meta = {
        "harness": "pi", "harness_pin": PIN,
        "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
        "model": a.model, "instruction": a.instruction, "workdir": got["workdir"],
        "method": "thesis.base_agent.capture_pi (obench.adapters.pi_harness -> build_check.CaptureStub)",
        "captured_at": time.strftime("%Y-%m-%d"), "captured_on": f"{platform.system()} {platform.machine()}",
        "requests": len(got["requests"]),
    }
    env = {}
    system = _system_text(got["requests"])
    m = re.search(r"- Main documentation: (\S+)/README\.md", system)
    if m:  # Pi's docs paths depend on where it is installed; replayed like cwd
        env["pi_install_root"] = m.group(1)
    cwd = re.search(r"<cwd>\n(.+)\n</cwd>", system)
    if cwd:  # Pi reports the resolved path (/private/var/... on macOS)
        meta["workdir"] = cwd.group(1)
    toml = "".join(f"{k} = {json.dumps(v)}\n" for k, v in meta.items())
    toml += "\n[env]\n" + "".join(f"{k} = {json.dumps(v)}\n" for k, v in env.items())
    (a.out / "capture.toml").write_text(toml)
    print(json.dumps({k: v for k, v in meta.items()}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
