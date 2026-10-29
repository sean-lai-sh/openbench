#!/usr/bin/env python3
"""One OpenCode bridge cell. Not a scored run.

Same publication as ``data/pi-harness-smoke/cell.py``: the Vertex proxy stays
on ``127.0.0.1``, one forwarder listens on the docker bridge gateway, and the
cell uses bridge networking. The egress probe re-resolves ``api.anthropic.com``
inside that network (it does not reuse a host DNS answer) and logs the
sinkhole line. A request that arrives at the proxy logs ``proxy-reached``.

``h1-env:1027-strace`` has no ``opencode`` and no Node. The cache is mounted
at ``/h1/opencode-src`` (or the ``/h1/...`` path the host directory already
uses) and ``OPENCODE_NODE_PREFIX`` at its ``/h1/...`` path, which is what the
cached wrappers exec.

The Pi vs OpenCode batch launches this cell as ``anthropic/claude-sonnet-5-5``.
The adapter still enters its proxy route through ``claude-opus-5-5``; the
``-m`` value is the Sonnet ref. ``--require-model-match`` defaults on, so a
request whose model id is not the Vertex model stops the smoke.
``--vertex-model`` is what the proxy calls upstream.
This module does nothing on import.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
from pathlib import Path


# Adapter key that selects the proxy route. The launched ``-m`` value is MODEL_REF.
ADAPTER_MODEL = "claude-opus-5-5"
MODEL_REF = "anthropic/claude-sonnet-5-5"
MODEL_ID = "claude-sonnet-5-5"
TASK = "polyglot-rust-c"
TIMEOUT_S = 2400
CHECKER_TIMEOUT_S = 120


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _default_cache() -> Path:
    chosen = os.environ.get("OPENCODE_HARNESS_CACHE", "").strip()
    if chosen:
        return Path(chosen)
    home = Path.home() / "h1" / "opencode-src"
    if home.is_dir():
        return home
    return Path("/h1/opencode-src")


def _log(out: Path, line: str) -> None:
    print(line, flush=True)
    with (out / "smoke.log").open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def requests_cost_usd(model: str, ledger: Path, cell_id: str):
    """Price the proxy ledger. Do not bill empty ``tokens_proxy_*`` as zero.

    OpenCode's run_cell row leaves ``tokens_proxy_*`` unset. ``or 0`` made
    ``row_cost`` see a complete zero split and report ``0.0`` while the ledger
    held the real input, output, and cache-write tokens.
    """
    from obench.adapters.pi_harness import load_proxy_totals
    from thesis.ab.summarize import proxy_cost_usd

    try:
        totals = load_proxy_totals(str(ledger), cell_id)
    except (OSError, json.JSONDecodeError, ValueError):
        return None
    bucket = totals["all"]
    return proxy_cost_usd(
        model,
        input_uncached=bucket["input_uncached"],
        output=bucket["output"],
        cache_read=bucket["cache_read"],
        cache_write=bucket["cache_write"],
    )


def comparison_config(base_url: str) -> dict:
    """OpenCode config for the Pi vs OpenCode smoke.

    ``model`` and ``small_model`` are both ``anthropic/claude-sonnet-5-5``.
    The pre-loop title call stays enabled; this only changes the model id
    that call sends. OpenCode's default small model is Haiku, which the
    proxy then serves as Sonnet and ``--require-model-match`` rejects.
    """
    from thesis.ab.compat import anthropic_proxy_config

    config = anthropic_proxy_config(
        base_url, include_endpoint=True, model_id=MODEL_ID, model_name="Claude Sonnet 5.5",
    )
    config["model"] = MODEL_REF
    config["small_model"] = MODEL_REF
    return config


def _resolve_binary(cache: Path, sha: str, explicit: Path | None) -> Path:
    if explicit is not None:
        path = explicit.expanduser().resolve()
        if not path.is_file():
            raise SystemExit(f"opencode binary is missing: {path}")
        return path
    if not sha:
        raise SystemExit("pass --sha or --binary (or set OPENCODE_SHA)")
    published = (cache / "bin" / sha / "opencode").resolve()
    if published.is_file():
        return published
    from thesis.ab.build_opencode import binary

    return Path(binary(sha, cache)).resolve()


def argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="OpenCode bridge smoke, one cell")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--cache", type=Path, default=None)
    parser.add_argument("--sha", default=os.environ.get("OPENCODE_SHA", ""),
                        help="OpenCode commit under <cache>/bin/<sha>/opencode")
    parser.add_argument("--binary", type=Path, default=None,
                        help="opencode executable; skips --sha")
    parser.add_argument("--tasks-dir", type=Path, default=None)
    parser.add_argument("--task", default=TASK)
    parser.add_argument("--vertex-model", default="claude-sonnet-5-5",
                        help="model the proxy calls upstream")
    parser.add_argument("--node", type=Path, default=None,
                        help="Node prefix to mount (or OPENCODE_NODE_PREFIX)")
    parser.add_argument("--exec", choices=("local", "docker"), default="local",
                        help="docker runs one bridge-network cell; host-network is not used")
    parser.add_argument("--image", default=os.environ.get("OBENCH_CELL_IMAGE", ""),
                        help="cell image for --exec docker (or OBENCH_CELL_IMAGE)")
    parser.add_argument(
        "--require-model-match",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Halt when the request model id differs from the Vertex model. "
            "On for this Pi vs OpenCode smoke. --no-require-model-match leaves "
            "an Opus request served as Sonnet alone."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = argument_parser().parse_args(argv)
    if args.exec == "docker" and not args.image:
        raise SystemExit("bridge smoke needs --image or OBENCH_CELL_IMAGE")

    repo = _repo_root()
    cache = (args.cache or _default_cache()).resolve()
    binary = _resolve_binary(cache, args.sha.strip().lower(), args.binary)
    node = args.node or os.environ.get("OPENCODE_NODE_PREFIX", "").strip()

    from thesis.ab.compat import (
        PROXY_API_KEY,
        sdk_base_url,
    )
    from thesis.ab.proxy_bridge import bridge_egress_probe, cell_network, read_proxy_observed
    from thesis.ab.run_ab import PROTOCOL_LOCATION, attach_proxy_trace, proxy_trace_public
    from thesis.ab.vertex_anthropic_proxy import cell_ledger_path, cell_proxy_base, start_from_env
    from obench.run import read_proxy_ledger, run_cell

    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    os.environ["OBENCH_OPENCODE_BIN"] = str(binary)
    os.environ["OBENCH_OPENCODE_MOUNT"] = str(cache)
    if node:
        os.environ["OPENCODE_NODE_PREFIX"] = str(Path(node).expanduser().resolve())
    else:
        os.environ.pop("OPENCODE_NODE_PREFIX", None)

    ledger = out / "proxy-ledger"
    ledger.mkdir(parents=True, exist_ok=True)
    proxy = start_from_env(ledger_dir=ledger, thinking_mode="default", model=args.vertex_model)
    print(f"proxy {proxy.base_url} binary {binary}", flush=True)
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
    sdk = sdk_base_url(cell_proxy_base(proxy.base_url, cell_id))
    # Permission flags are read from `opencode run --help` inside the cell,
    # where the mounted Node and /h1 tree exist. Do not probe the binary on
    # the host: the cached wrapper's interpreter path is the container path.
    config = comparison_config(sdk)
    os.environ["OBENCH_OPENCODE_CONFIG_JSON"] = json.dumps(config)
    os.environ.pop("OBENCH_OPENCODE_PERMISSION_CONFIG", None)
    os.environ["OBENCH_OPENCODE_PROXY"] = json.dumps({
        "model_ref": MODEL_REF,
        "base_url": sdk,
        "api_key": PROXY_API_KEY,
    })

    tasks_dir = args.tasks_dir or (repo / "data" / "packs" / "openbench-tb-hard")
    adapters = repo / "obench" / "adapters"
    try:
        print(f"cell {args.vertex_model} {cell_id} network_mode={network_mode}", flush=True)
        row = run_cell(
            "opencode", args.task, ADAPTER_MODEL, 1, TIMEOUT_S,
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
        cost = requests_cost_usd(args.vertex_model, ledger, cell_id)
        record = {
            "cell_id": cell_id,
            "harness_model": MODEL_REF,
            "adapter_model": ADAPTER_MODEL,
            "vertex_model": args.vertex_model,
            "sha": args.sha.strip().lower(),
            "binary": str(binary),
            "task": args.task,
            "network_mode": network_mode,
            "proxy_observed": observed,
            "row": row,
            "requests_cost_usd": cost,
            "proxy_cost_usd": cost,
            **trace,
        }
        _write(out / f"{args.vertex_model}.json", record)
        summary_cell = {
            "cell_id": cell_id,
            "vertex_model": args.vertex_model,
            "network_mode": network_mode,
            "completed": row.get("completed"),
            "failure_class": row.get("failure_class"),
            "checker_exit": row.get("checker_exit"),
            "proxy_observed": observed,
            "requests_cost_usd": cost,
            "proxy_cost_usd": cost,
            **trace,
        }
        _write(out / "summary.json", {
            "network_mode": network_mode,
            "cells": [summary_cell],
        })
        print(json.dumps({
            "cell_id": cell_id,
            "network_mode": network_mode,
            "completed": row.get("completed"),
            "failure_class": row.get("failure_class"),
            "proxy_observed": observed,
            **trace,
        }), flush=True)
        if row.get("off_protocol") is True:
            _log(
                out,
                "off-protocol halt "
                f"upstream_model={row.get('upstream_model')} "
                f"protocol_model={row.get('protocol_model')} "
                f"endpoint_location={row.get('endpoint_location')} "
                f"requested_model={row.get('requested_model')} "
                f"model_match_reason={row.get('model_match_reason')}",
            )
            return 1
    finally:
        proxy.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
