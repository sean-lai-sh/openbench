#!/usr/bin/env python3
"""One Hermes hard-suite cell through the shared Vertex proxy. Not a scored run.

The Hermes arm of the harness comparison, launched like the Codex, Pi and
OpenCode cells: the Vertex proxy runs on ``127.0.0.1`` with a per-cell
ledger, the cell runs through ``obench.run.run_cell``, and the row gets the
proxy trace, the ledger-priced cost and the four-check evidence
(``thesis/ab/smoke_evidence.py``). Hermes speaks Anthropic Messages natively
(``POST /v1/messages``); the adapter is ``obench/adapters/hermes_harness.py``
(Hermes pinned to 4dcef215, MIT). Raw request bodies are captured
(``OBENCH_VERTEX_CAPTURE_REQUESTS=1``) for the prompt-byte check.

Run ``data/hermes-harness-smoke/prep.sh`` once on the VM first.
``--out`` must not be inside any ``results/`` or ``data/`` directory.
This module does nothing on import.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
from pathlib import Path


MODEL_ID = "claude-sonnet-5-5"
TASK = "polyglot-rust-c"
TIMEOUT_S = 2400
CHECKER_TIMEOUT_S = 120
FORBIDDEN_OUT_PARTS = ("results", "data")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _log(out: Path, line: str) -> None:
    print(line, flush=True)
    with (out / "smoke.log").open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def check_out_dir(out: Path) -> Path:
    """Refuse an output directory inside any ``results/`` or ``data/`` folder."""
    resolved = out.expanduser().resolve()
    bad = [part for part in resolved.parts if part in FORBIDDEN_OUT_PARTS]
    if bad:
        raise SystemExit(
            f"--out {resolved} is inside a {bad[0]!r} directory; smoke output must "
            "stay out of results/ and data/ (use e.g. ~/hermes-harness-smoke)"
        )
    return resolved


def requests_cost_usd(model: str, ledger: Path, cell_id: str):
    from obench.adapters.hermes_harness import load_proxy_totals
    from thesis.ab.summarize import proxy_cost_usd

    try:
        totals = load_proxy_totals(str(ledger), cell_id)
    except (OSError, json.JSONDecodeError, ValueError):
        return None, None
    bucket = totals["all"]
    cost = proxy_cost_usd(
        model,
        input_uncached=bucket["input_uncached"],
        output=bucket["output"],
        cache_read=bucket["cache_read"],
        cache_write=bucket["cache_write"],
    )
    return cost, totals


def _resolve(explicit: Path | None, env: str, what: str) -> Path:
    raw = explicit or (Path(os.environ[env]) if os.environ.get(env) else None)
    if raw is None:
        raise SystemExit(f"pass {what} (or set {env}); run data/hermes-harness-smoke/prep.sh first")
    path = raw.expanduser().resolve()
    if not path.exists():
        raise SystemExit(f"{what} is missing: {path}")
    return path


def argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Hermes hard-suite cell, one cell")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--root", type=Path, default=None, help="Hermes install root from prep.sh (or OBENCH_HERMES_ROOT)")
    parser.add_argument("--binary", type=Path, default=None, help="hermes launcher from prep.sh (or OBENCH_HERMES_BIN)")
    parser.add_argument("--tasks-dir", type=Path, default=None)
    parser.add_argument("--task", default=TASK)
    parser.add_argument("--vertex-model", default=MODEL_ID, help="model the proxy calls upstream")
    parser.add_argument("--exec", choices=("local", "docker"), default="local")
    parser.add_argument("--image", default=os.environ.get("OBENCH_CELL_IMAGE", ""),
                        help="cell image for --exec docker (or OBENCH_CELL_IMAGE)")
    parser.add_argument("--require-model-match", action=argparse.BooleanOptionalAction, default=True,
                        help="halt when a request's model id differs from the Vertex model")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = argument_parser().parse_args(argv)
    if args.exec == "docker" and not args.image:
        raise SystemExit("docker cell needs --image or OBENCH_CELL_IMAGE")
    out = check_out_dir(args.out)
    root = _resolve(args.root, "OBENCH_HERMES_ROOT", "--root")
    binary = _resolve(args.binary, "OBENCH_HERMES_BIN", "--binary")
    os.environ["OBENCH_HERMES_ROOT"] = str(root)
    os.environ["OBENCH_HERMES_BIN"] = str(binary)

    from obench.adapters.hermes_harness import (CONTEXT_LENGTH, PIN, LaunchError, PinError, require_pin,
                                                resolve_launch)
    from thesis.ab.proxy_bridge import bridge_egress_probe, cell_network, read_proxy_observed
    from thesis.ab.run_ab import PROTOCOL_LOCATION, attach_proxy_trace, proxy_trace_public
    from thesis.ab.smoke_evidence import reference_thinking, smoke_evidence
    from thesis.ab.vertex_anthropic_proxy import cell_ledger_path, start_from_env
    from obench.run import read_proxy_ledger, run_cell

    try:
        require_pin(str(binary))
        launch = resolve_launch(str(root), str(binary))
    except (PinError, LaunchError) as exc:
        raise SystemExit(str(exc)) from exc

    repo = _repo_root()
    out.mkdir(parents=True, exist_ok=True)
    os.environ.pop("OBENCH_PI_HARNESS", None)
    os.environ.pop("OBENCH_CODEX_HARNESS", None)
    os.environ["OBENCH_HERMES_HARNESS"] = "1"
    os.environ["OBENCH_VERTEX_ROUTE_BY_REQUEST"] = "1"
    os.environ["OBENCH_VERTEX_CAPTURE_REQUESTS"] = "1"

    ledger = out / "proxy-ledger"
    ledger.mkdir(parents=True, exist_ok=True)
    os.environ["OBENCH_VERTEX_LEDGER_DIR"] = str(ledger)
    proxy = start_from_env(ledger_dir=ledger, thinking_mode="default", model=args.vertex_model)
    os.environ["OBENCH_VERTEX_PROXY_URL"] = proxy.base_url
    print(f"proxy {proxy.base_url} hermes {PIN} python {launch['python']} entry {launch['entry']}", flush=True)
    network_mode = cell_network(args.exec, [])
    if args.exec == "docker":
        bridge = proxy.publish_on_docker_bridge()
        listen = bridge.listen_address
        if listen is not None:
            print(f"proxy-bridge {listen[0]}:{listen[1]}", flush=True)
        egress = bridge_egress_probe(args.image)
        _log(out, egress)
        if "REACHABLE" in egress:
            proxy.close()
            return 1

    cell_id = secrets.token_hex(8)
    os.environ["OBENCH_VERTEX_CELL_ID"] = cell_id
    tasks_dir = args.tasks_dir or (repo / "data" / "packs" / "openbench-tb-hard")
    adapters = repo / "obench" / "adapters"
    try:
        print(f"cell {args.vertex_model} {cell_id} network_mode={network_mode}", flush=True)
        row = run_cell(
            "hermes", args.task, args.vertex_model, 1, TIMEOUT_S,
            str(tasks_dir), str(adapters), CHECKER_TIMEOUT_S,
            exec_mode=args.exec,
            docker_image=args.image or None,
            transcripts_dir=str(out / "transcripts"),
            results_stem=args.vertex_model,
        )
        observed = read_proxy_observed(ledger, cell_id)
        calls = len(observed)
        reached = "yes" if proxy.reached(cell_id) or calls else "no"
        _log(out, f"proxy-reached cell={cell_id} reached={reached} calls={calls}")
        ledger_rows = read_proxy_ledger(str(ledger), cell_id)
        attach_proxy_trace(
            row, ledger_rows, args.vertex_model,
            ledger_present=cell_ledger_path(ledger, cell_id).is_file(),
            protocol_location=PROTOCOL_LOCATION,
            require_model_match=args.require_model_match,
        )
        trace = proxy_trace_public(row)
        evidence = smoke_evidence(row, ledger_rows, reference_thinking(repo, args.vertex_model))
        cost, totals = requests_cost_usd(args.vertex_model, ledger, cell_id)
        tokens = (totals or {}).get("all") or {}
        settings = row.get("harness_settings") or {}
        record = {
            "cell_id": cell_id,
            "harness": "hermes",
            "hermes_pin": PIN,
            "context_length": CONTEXT_LENGTH,
            "vertex_model": args.vertex_model,
            "binary": str(binary),
            "install_root": str(root),
            "launch": {"python": launch["python"], "entry": launch["entry"]},
            "task": args.task,
            "network_mode": network_mode,
            "proxy_observed": observed,
            "proxy_totals": totals,
            "row": row,
            "requests_cost_usd": cost,
            "proxy_cost_usd": cost,
            "evidence": evidence,
            **trace,
        }
        _write(out / f"{args.vertex_model}.json", record)
        summary = {
            "cell_id": cell_id,
            "hermes_pin": PIN,
            "context_length": CONTEXT_LENGTH,
            "vertex_model": args.vertex_model,
            "completed": row.get("completed"),
            "failure_class": row.get("failure_class"),
            "checker_exit": row.get("checker_exit"),
            "calls": tokens.get("calls"),
            "input_uncached": tokens.get("input_uncached"),
            "output": tokens.get("output"),
            "cache_read": tokens.get("cache_read"),
            "cache_write": tokens.get("cache_write"),
            "proxy_cost_usd": cost,
            "main_calls": settings.get("main_calls"),
            "aux_calls": settings.get("aux_calls"),
            "gateway_stop": settings.get("gateway_stop"),
            "evidence": evidence,
            "evidence_pass": {k: v.get("pass") for k, v in evidence.items()},
            "server_thinking_tokens_per_call": evidence["3_thinking_sent"]["server_thinking_tokens_per_call"],
            "raw_requests_dir": str(ledger / f"{cell_id}.requests"),
            "cache_miss_headers": str(ledger / f"{cell_id}.cache-miss-headers.jsonl"),
            **trace,
        }
        _write(out / "summary.json", {"network_mode": network_mode, "cells": [summary]})
        print(json.dumps(summary), flush=True)
        _log(out, "evidence " + json.dumps(summary["evidence_pass"], sort_keys=True))
        if row.get("off_protocol") is True:
            _log(out, f"off-protocol halt upstream_model={row.get('upstream_model')} "
                      f"requested_model={row.get('requested_model')} "
                      f"model_match_reason={row.get('model_match_reason')}")
            return 1
    finally:
        proxy.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
