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

The harness model passed to the adapter is ``claude-opus-5-5``. That is the
adapter's proxy route. ``--vertex-model`` is what the proxy calls upstream.
This module does nothing on import.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
from pathlib import Path


HARNESS_MODEL = "claude-opus-5-5"
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


def main(argv: list[str] | None = None) -> int:
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
                        help="model the proxy calls; the adapter alias stays claude-opus-5-5")
    parser.add_argument("--node", type=Path, default=None,
                        help="Node prefix to mount (or OPENCODE_NODE_PREFIX)")
    parser.add_argument("--exec", choices=("local", "docker"), default="local",
                        help="docker runs one bridge-network cell; host-network is not used")
    parser.add_argument("--image", default=os.environ.get("OBENCH_CELL_IMAGE", ""),
                        help="cell image for --exec docker (or OBENCH_CELL_IMAGE)")
    args = parser.parse_args(argv)
    if args.exec == "docker" and not args.image:
        raise SystemExit("bridge smoke needs --image or OBENCH_CELL_IMAGE")

    repo = _repo_root()
    cache = (args.cache or _default_cache()).resolve()
    binary = _resolve_binary(cache, args.sha.strip().lower(), args.binary)
    node = args.node or os.environ.get("OPENCODE_NODE_PREFIX", "").strip()

    from thesis.ab.compat import (
        PROXY_API_KEY,
        PROXY_MODEL_REF,
        anthropic_proxy_config,
        sdk_base_url,
    )
    from thesis.ab.proxy_bridge import bridge_egress_probe, cell_network, read_proxy_observed
    from thesis.ab.summarize import row_cost
    from thesis.ab.vertex_anthropic_proxy import cell_proxy_base, start_from_env
    from obench.run import run_cell

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
    config = anthropic_proxy_config(sdk, include_endpoint=True)
    os.environ["OBENCH_OPENCODE_CONFIG_JSON"] = json.dumps(config)
    os.environ.pop("OBENCH_OPENCODE_PERMISSION_CONFIG", None)
    os.environ["OBENCH_OPENCODE_PROXY"] = json.dumps({
        "model_ref": PROXY_MODEL_REF,
        "base_url": sdk,
        "api_key": PROXY_API_KEY,
    })

    tasks_dir = args.tasks_dir or (repo / "data" / "packs" / "openbench-tb-hard")
    adapters = repo / "obench" / "adapters"
    try:
        print(f"cell {args.vertex_model} {cell_id} network_mode={network_mode}", flush=True)
        row = run_cell(
            "opencode", args.task, HARNESS_MODEL, 1, TIMEOUT_S,
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
        cost = row_cost({
            "upstream_model": args.vertex_model,
            "tokens_input_uncached": row.get("tokens_proxy_input_uncached") or 0,
            "tokens_output": row.get("tokens_proxy_output") or 0,
            "tokens_cache_read": row.get("tokens_proxy_cache_read") or 0,
            "tokens_cache_write": row.get("tokens_proxy_cache_write") or 0,
        }) if calls else None
        record = {
            "cell_id": cell_id,
            "harness_model": HARNESS_MODEL,
            "vertex_model": args.vertex_model,
            "sha": args.sha.strip().lower(),
            "binary": str(binary),
            "task": args.task,
            "network_mode": network_mode,
            "proxy_observed": observed,
            "row": row,
            "requests_cost_usd": cost,
        }
        _write(out / f"{args.vertex_model}.json", record)
        _write(out / "summary.json", {
            "network_mode": network_mode,
            "cells": [{
                "cell_id": cell_id,
                "vertex_model": args.vertex_model,
                "network_mode": network_mode,
                "completed": row.get("completed"),
                "failure_class": row.get("failure_class"),
                "checker_exit": row.get("checker_exit"),
                "proxy_observed": observed,
                "requests_cost_usd": cost,
            }],
        })
        print(json.dumps({
            "cell_id": cell_id,
            "network_mode": network_mode,
            "completed": row.get("completed"),
            "failure_class": row.get("failure_class"),
            "proxy_observed": observed,
        }), flush=True)
    finally:
        proxy.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
