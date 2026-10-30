"""Run the base agent once, headless.

    python -m thesis.base_agent.run --config base --arm swap \\
        --model claude-sonnet-5-5 --base-url http://127.0.0.1:PORT \\
        --workdir /work --instruction-file instruction.md --out result.json

Prints the version record. The result JSON carries it too, so every row a
runner writes from it can log ``base_agent_version``. Wiring this into the
cell runner is a separate change.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from thesis.base_agent import config as C
from thesis.base_agent.agent import Agent, HttpModelClient


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", required=True, help="config name under configs/ or a path")
    p.add_argument("--arm", choices=C.ARMS, required=True)
    p.add_argument("--model")
    p.add_argument("--base-url", help="counting proxy base URL")
    p.add_argument("--workdir")
    p.add_argument("--instruction-file", type=Path)
    p.add_argument("--out", type=Path)
    p.add_argument("--print-version", action="store_true", help="resolve and print the version record only")
    a = p.parse_args(argv)
    if a.print_version:
        cfg, fixed = C.load_config(a.config), C.load_fixed()
        print(json.dumps(C.version_record(cfg, fixed, C.resolve(cfg, fixed, a.arm)), indent=2))
        return 0
    missing = [f for f in ("model", "base_url", "workdir", "instruction_file") if getattr(a, f) is None]
    if missing:
        p.error("required: " + ", ".join("--" + f.replace("_", "-") for f in missing))
    agent = Agent.from_config(a.config, a.arm, HttpModelClient(a.base_url), a.model,
                              a.workdir, a.instruction_file.read_text())
    result = agent.run()
    if a.out:
        a.out.write_text(json.dumps(result, indent=1, default=str))
    print(json.dumps({"stop": result["stop"], "steps": result["steps"], **result["version"]}, indent=2))
    return 0 if result["stop"] == "end_turn" else 1


if __name__ == "__main__":
    raise SystemExit(main())
