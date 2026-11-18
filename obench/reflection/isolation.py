"""Block the GCE metadata server from trial containers, keep the host proxy reachable, and check it.

The 2026-11-17 smoke found that every agent container (on Docker's default bridge, with no firewall rule) could
open a TCP connection to 169.254.169.254:80, so an agent could mint the VM service account's token. Trials now
run on the dedicated bridge ``openbench-agent`` (interface ``obench-agent0``; ``cell_executor.AGENT_NETWORK``),
and one DOCKER-USER rule drops forwarded traffic from that interface to the metadata server:

    iptables -I DOCKER-USER -i obench-agent0 -d 169.254.169.254/32 -j DROP

DOCKER-USER only sees forwarded (container) traffic, so the host's own metadata access, which the proxy's ADC
token uses, keeps working. The internal ``openbench-agent-offline`` network has no route out at all.

    python3 -m obench.reflection.isolation            # create the network, show the rule, probe
    python3 -m obench.reflection.isolation --apply    # also add the rule (sudo -n iptables), then probe

The rule does not survive a reboot or a Docker restart. That is fine: every ``runner --cell`` run probes first
and refuses to start (exit 5) if a container can reach the metadata server or can't reach the proxy, and every
trial's ``cell.json`` records the probe (``isolation``).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys

from obench.reflection.cell_executor import (AGENT_BRIDGE_IF, METADATA_RULE, CellError, CellExecutor, TrialDocker)


def rule_present(runner=subprocess.run) -> bool:
    return runner(["sudo", "-n", "iptables", "-C", *METADATA_RULE], capture_output=True, timeout=30).returncode == 0


def apply_rule(runner=subprocess.run) -> str:
    if rule_present(runner):
        return "present"
    out = runner(["sudo", "-n", "iptables", "-I", *METADATA_RULE], capture_output=True, text=True, timeout=30)
    if out.returncode != 0:
        raise SystemExit(f"could not add the rule (needs passwordless sudo): {out.stderr.strip()}")
    return "added"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--apply", action="store_true", help="add the DOCKER-USER rule with sudo -n iptables")
    parser.add_argument("--opencode", required=True, help="the pinned OpenCode binary (the executor checks the pin)")
    parser.add_argument("--probe-image", default=None, help="image with bash for the probe (default: h1-env)")
    args = parser.parse_args(argv)
    docker = TrialDocker()
    docker.agent_gateway()  # create the network so its interface exists for the rule
    report = {"interface": AGENT_BRIDGE_IF, "rule": "iptables -I " + " ".join(METADATA_RULE)}
    if args.apply:
        report["rule_status"] = apply_rule()
    executor = CellExecutor(args.opencode, "isolation-check", lambda: "", docker=docker, probe_image=args.probe_image)
    try:
        report["probe"] = executor.isolation_preflight()
        ok = True
    except CellError as exc:
        report["probe_error"] = str(exc)
        ok = False
    print(json.dumps(report, indent=2))
    return 0 if ok else 5


if __name__ == "__main__":
    sys.exit(main())
