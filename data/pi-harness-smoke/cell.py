#!/usr/bin/env python3
"""One Pi smoke cell per comparison model. Not a scored run.

Builds the pinned Pi commit, starts the Vertex proxy from #128, and calls
``obench.run.run_cell`` for polyglot-rust-c. Pi is wired to Anthropic
``/v1/messages`` (cell base URL without ``/v1``). Do not set ``OBENCH_PI_VERTEX``;
that selects the A/B adapter path.

Requires ``GOOGLE_CLOUD_PROJECT`` (or ``GCLOUD_PROJECT``) and Application
Default Credentials. This module does nothing on import.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
from pathlib import Path


PIN_MODELS = ("claude-opus-5-5", "claude-sonnet-5-5")
TASK = "polyglot-rust-c"
TIMEOUT_S = 2400
CHECKER_TIMEOUT_S = 120


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _log(out: Path, line: str) -> None:
    print(line, flush=True)
    with (out / "smoke.log").open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _cost(model: str, bucket: dict):
    from thesis.ab.summarize import row_cost

    return row_cost({
        "upstream_model": model,
        "tokens_input_uncached": bucket["input_uncached"],
        "tokens_output": bucket["output"],
        "tokens_cache_read": bucket["cache_read"],
        "tokens_cache_write": bucket["cache_write"],
    })


def argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Pi harness-comparison smoke, one cell per model")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--cache", type=Path, default=Path(os.environ.get("PI_HARNESS_CACHE", "/h1/pi-src")))
    parser.add_argument("--tasks-dir", type=Path, default=None)
    parser.add_argument("--models", default=",".join(PIN_MODELS),
                        help="comma-separated subset of the pinned smoke models")
    parser.add_argument(
        "--require-model-match",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Halt when the request model id differs from the Vertex model. "
            "On for this Pi vs OpenCode smoke."
        ),
    )
    parser.add_argument("--exec", choices=("local", "docker"), default="local",
                        help="docker runs one bridge-network cell; host-network is not used")
    parser.add_argument("--image", default=os.environ.get("OBENCH_CELL_IMAGE", ""),
                        help="cell image for --exec docker (or OBENCH_CELL_IMAGE)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = argument_parser().parse_args(argv)
    if args.exec == "docker" and not args.image:
        raise SystemExit("bridge smoke needs --image or OBENCH_CELL_IMAGE")

    repo = _repo_root()
    os.environ.pop("OBENCH_PI_VERTEX", None)
    os.environ["OBENCH_PI_HARNESS"] = "1"
    os.environ["OBENCH_VERTEX_ROUTE_BY_REQUEST"] = "1"

    from obench.adapters.pi_harness import PIN, load_proxy_totals, settings_destination
    from thesis.ab.build_pi import binary
    from thesis.ab.proxy_bridge import cell_network, read_proxy_observed
    from thesis.ab.run_ab import PROTOCOL_LOCATION, attach_proxy_trace, proxy_trace_public
    from thesis.ab.vertex_anthropic_proxy import cell_ledger_path, start_from_env
    from obench.run import read_proxy_ledger, run_cell

    if PIN_MODELS != ("claude-opus-5-5", "claude-sonnet-5-5"):
        raise RuntimeError("smoke models drifted")

    models = tuple(m for m in args.models.split(",") if m)
    if not models or any(m not in PIN_MODELS for m in models):
        raise SystemExit(f"--models must be a subset of {PIN_MODELS}")

    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    wrapper = binary(PIN, args.cache.resolve())
    pin_file = Path(str(wrapper) + ".pin")
    pin_file.write_text(PIN + "\n", encoding="utf-8")
    os.environ["OBENCH_PI_BIN"] = str(wrapper)
    os.environ["OBENCH_PI_PIN_FILE"] = str(pin_file)
    os.environ["OBENCH_PI_MOUNT"] = str(args.cache.resolve())

    ledger = out / "proxy-ledger"
    ledger.mkdir(parents=True, exist_ok=True)
    os.environ["OBENCH_VERTEX_LEDGER_DIR"] = str(ledger)
    proxy = start_from_env(ledger_dir=ledger, thinking_mode="default", model=models[0])
    os.environ["OBENCH_VERTEX_PROXY_URL"] = proxy.base_url
    print(f"proxy {proxy.base_url} pin {PIN}", flush=True)
    if args.exec == "docker":
        bridge = proxy.publish_on_docker_bridge()
        listen = bridge.listen_address
        if listen is not None:
            print(f"proxy-bridge {listen[0]}:{listen[1]}", flush=True)
        from thesis.ab.proxy_bridge import bridge_egress_probe
        egress = bridge_egress_probe(args.image)
        _log(out, egress)
        if "REACHABLE" in egress:
            proxy.close()
            return 1

    tasks_dir = args.tasks_dir or (repo / "data" / "packs" / "openbench-tb-hard")
    adapters = repo / "obench" / "adapters"
    network_mode = cell_network(args.exec, [])
    records = []
    halted = False
    try:
        for model in models:
            cell_id = secrets.token_hex(8)
            os.environ["OBENCH_VERTEX_CELL_ID"] = cell_id
            os.environ.pop("OBENCH_PI_SETTINGS_PATH", None)
            print(f"cell {model} {cell_id}", flush=True)
            row = run_cell(
                "pi", TASK, model, 1, TIMEOUT_S,
                str(tasks_dir), str(adapters), CHECKER_TIMEOUT_S,
                exec_mode=args.exec,
                docker_image=args.image or None,
                transcripts_dir=str(out / "transcripts"),
                results_stem=model,
            )
            settings_path = Path(settings_destination(cell_id, str(ledger)))
            settings = None
            if settings_path.is_file():
                settings = json.loads(settings_path.read_text(encoding="utf-8"))
            totals = None
            totals_error = None
            try:
                totals = load_proxy_totals(str(ledger), cell_id)
            except (OSError, json.JSONDecodeError, ValueError) as exc:
                totals_error = str(exc)
            ledger_rows = read_proxy_ledger(str(ledger), cell_id)
            attach_proxy_trace(
                row, ledger_rows, model,
                ledger_present=cell_ledger_path(ledger, cell_id).is_file(),
                protocol_location=PROTOCOL_LOCATION,
                require_model_match=args.require_model_match,
            )
            trace = proxy_trace_public(row)
            record = {
                "cell_id": cell_id,
                "model": model,
                "pin": PIN,
                "task": TASK,
                "wire": "anthropic-messages",
                "openai_chat_completions": False,
                "network_mode": network_mode,
                "proxy_observed": read_proxy_observed(ledger, cell_id),
                "row": row,
                "settings": settings,
                "totals": totals,
                "totals_error": totals_error,
                "requests_cost_usd": None if totals is None else _cost(model, totals["all"]),
                "requests_cost_main_usd": None if totals is None else _cost(model, totals["main"]),
                "proxy_cost_usd": None if totals is None else _cost(model, totals["all"]),
                **trace,
            }
            calls = 0 if totals is None else totals["all"]["calls"]
            reached = "yes" if proxy.reached(cell_id) or calls else "no"
            _log(out, f"proxy-reached cell={cell_id} reached={reached} calls={calls}")
            _write(out / f"{model}.json", record)
            records.append({
                "model": model,
                "cell_id": cell_id,
                "network_mode": network_mode,
                "completed": row.get("completed"),
                "failure_class": row.get("failure_class"),
                "checker_exit": row.get("checker_exit"),
                "tokens": row.get("tokens"),
                "requests_cost_usd": record["requests_cost_usd"],
                "proxy_cost_usd": record["proxy_cost_usd"],
                "totals_calls_all": None if totals is None else totals["all"]["calls"],
                "totals_calls_main": None if totals is None else totals["main"]["calls"],
                "proxy_observed": record["proxy_observed"],
                **trace,
            })
            print(json.dumps(records[-1]), flush=True)
            if row.get("off_protocol") is True:
                halted = True
                _log(
                    out,
                    "off-protocol halt "
                    f"model={model} upstream_model={row.get('upstream_model')} "
                    f"endpoint_location={row.get('endpoint_location')} "
                    f"requested_model={row.get('requested_model')}",
                )
                break
    finally:
        proxy.close()
    _write(out / "summary.json", {"pin": PIN, "cells": records})
    return 1 if halted else 0


if __name__ == "__main__":
    raise SystemExit(main())
