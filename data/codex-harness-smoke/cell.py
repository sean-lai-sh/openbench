#!/usr/bin/env python3
"""One Codex hard-suite cell through the shared Vertex proxy. Not a scored run.

The Codex arm of the harness comparison, launched the same way as
``data/pi-harness-smoke/cell.py`` and ``data/opencode-harness-smoke/cell.py``:
the Vertex proxy runs on ``127.0.0.1`` with a per-cell ledger, the cell runs
through ``obench.run.run_cell``, and the row gets the proxy trace and the
ledger-priced cost. Codex reaches the proxy on ``POST /v1/responses``
(``thesis/ab/responses_api.py``); the adapter is
``obench/adapters/codex_harness.py`` (Codex pinned to 0.144.5, AD1-codex-ctx
``model_context_window=200000``).

``--out`` must not be inside any ``results/`` or ``data/`` directory: smoke
output is local evidence, not a dataset.

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
# Same-model reference arms (#196, Sonnet 5.5): committed proxy ledgers.
REFERENCE_LEDGERS = "results/pi-vs-oc-180-1029/cells/*/{arm}/proxy-ledger/*.jsonl"
REFERENCE_ARMS = ("pi", "opencode")
BYTE_TOLERANCE = 0.05


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
            "stay out of results/ and data/ (use e.g. ~/codex-harness-smoke)"
        )
    return resolved


def requests_cost_usd(model: str, ledger: Path, cell_id: str):
    """List-price cost of the cell's proxy ledger (same pricing as Pi/OpenCode)."""
    from obench.adapters.codex_harness import load_proxy_totals
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


def reference_thinking(repo: Path, model: str, pattern: str = REFERENCE_LEDGERS) -> dict:
    """``thinking_sent`` values each reference arm recorded for ``model``."""
    found: dict = {}
    for arm in REFERENCE_ARMS:
        values: set = set()
        for path in sorted(repo.glob(pattern.format(arm=arm))):
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if row.get("upstream_model") == model and row.get("thinking_sent"):
                    values.add(row["thinking_sent"])
        found[arm] = sorted(values)
    return found


def _delta(captured, real):
    if not isinstance(captured, int) or not isinstance(real, int) or real <= 0:
        return None
    return round((captured - real) / real, 4)


def smoke_evidence(row: dict, ledger_rows: list, reference: dict | None = None) -> dict:
    """The four re-smoke criteria, computed from the cell row and its ledger.

    1. every request traced (``trace_requests`` == ledger requests, 0 untraced);
    2. ``cache_read`` > 0 on every call from call 2 on;
    3. ``thinking_sent`` equals what each reference arm sends for the model;
    4. system and tool bytes the proxy forwards are within 5% of what
       Codex 0.144.5 itself sent (``responses_raw_*``; raw bodies are under
       ``proxy-ledger/<cell>.responses/``).
    """
    rows = [r for r in ledger_rows if isinstance(r, dict) and isinstance(r.get("usage"), dict)]
    calls = len(rows)
    traced = row.get("trace_requests")
    untraced = row.get("untraced_requests")
    cache_reads = [r.get("cache_read") for r in rows]
    sent = sorted({str(r.get("thinking_sent")) for r in rows})
    reference = reference or {}
    byte_rows = []
    for r in rows:
        rec = ((r.get("cc_identity_stripped") or {}).get("responses") or {})
        if "responses_raw_system_bytes" not in rec:
            continue
        sys_delta = _delta(rec.get("responses_system_bytes"), rec.get("responses_raw_system_bytes"))
        tools_delta = _delta(rec.get("responses_tools_bytes"), rec.get("responses_raw_tools_bytes"))
        byte_rows.append({
            "raw_request_file": rec.get("responses_raw_request_file"),
            "system_bytes": rec.get("responses_system_bytes"),
            "raw_system_bytes": rec.get("responses_raw_system_bytes"),
            "system_delta": sys_delta,
            "tools_bytes": rec.get("responses_tools_bytes"),
            "raw_tools_bytes": rec.get("responses_raw_tools_bytes"),
            "tools_delta": tools_delta,
        })
    within = bool(byte_rows) and all(
        b["system_delta"] is not None and abs(b["system_delta"]) <= BYTE_TOLERANCE
        and b["tools_delta"] is not None and abs(b["tools_delta"]) <= BYTE_TOLERANCE
        for b in byte_rows
    )
    matches = {arm: sent == values for arm, values in reference.items()}
    return {
        "1_traced": {
            "proxy_requests": calls, "trace_requests": traced, "untraced_requests": untraced,
            "pass": calls > 0 and traced == calls and untraced == 0,
        },
        "2_cache_read": {
            "per_call": cache_reads,
            "pass": calls >= 2 and all(isinstance(v, int) and v > 0 for v in cache_reads[1:]),
        },
        "3_thinking_sent": {
            "codex": sent, "reference": reference,
            "matches": matches,
            "pass": bool(matches) and all(matches.values()),
        },
        "4_prompt_bytes": {
            "tolerance": BYTE_TOLERANCE, "per_call": byte_rows, "pass": within,
        },
    }


def _resolve_binary(explicit: Path | None) -> Path:
    raw = explicit or (Path(os.environ["OBENCH_CODEX_BIN"]) if os.environ.get("OBENCH_CODEX_BIN") else None)
    if raw is None:
        raise SystemExit("pass --binary (or set OBENCH_CODEX_BIN) to the pinned codex 0.144.5 binary")
    path = raw.expanduser().resolve()
    if not path.is_file():
        raise SystemExit(f"codex binary is missing: {path}")
    return path


def argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Codex hard-suite cell, one cell")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--binary", type=Path, default=None,
                        help="pinned codex 0.144.5 executable (or OBENCH_CODEX_BIN)")
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
    binary = _resolve_binary(args.binary)

    from obench.adapters.codex_harness import PinError, require_pin
    from thesis.ab.proxy_bridge import bridge_egress_probe, cell_network, read_proxy_observed
    from thesis.ab.run_ab import PROTOCOL_LOCATION, attach_proxy_trace, proxy_trace_public
    from thesis.ab.vertex_anthropic_proxy import cell_ledger_path, start_from_env
    from obench.run import read_proxy_ledger, run_cell

    try:
        version = require_pin(str(binary))
    except PinError as exc:
        raise SystemExit(str(exc)) from exc

    repo = _repo_root()
    out.mkdir(parents=True, exist_ok=True)
    os.environ.pop("OBENCH_PI_HARNESS", None)
    os.environ["OBENCH_CODEX_HARNESS"] = "1"
    os.environ["OBENCH_CODEX_BIN"] = str(binary)
    os.environ["OBENCH_VERTEX_ROUTE_BY_REQUEST"] = "1"

    ledger = out / "proxy-ledger"
    ledger.mkdir(parents=True, exist_ok=True)
    os.environ["OBENCH_VERTEX_LEDGER_DIR"] = str(ledger)
    proxy = start_from_env(ledger_dir=ledger, thinking_mode="default", model=args.vertex_model)
    os.environ["OBENCH_VERTEX_PROXY_URL"] = proxy.base_url
    print(f"proxy {proxy.base_url} codex {version} binary {binary}", flush=True)
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
            "codex", args.task, args.vertex_model, 1, TIMEOUT_S,
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
        attach_proxy_trace(
            row, read_proxy_ledger(str(ledger), cell_id), args.vertex_model,
            ledger_present=cell_ledger_path(ledger, cell_id).is_file(),
            protocol_location=PROTOCOL_LOCATION,
            require_model_match=args.require_model_match,
        )
        trace = proxy_trace_public(row)
        ledger_rows = read_proxy_ledger(str(ledger), cell_id)
        evidence = smoke_evidence(row, ledger_rows, reference_thinking(repo, args.vertex_model))
        cost, totals = requests_cost_usd(args.vertex_model, ledger, cell_id)
        tokens = (totals or {}).get("all") or {}
        record = {
            "cell_id": cell_id,
            "harness": "codex",
            "codex_version": version,
            "vertex_model": args.vertex_model,
            "binary": str(binary),
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
            "codex_version": version,
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
            "evidence": evidence,
            "evidence_pass": {k: v.get("pass") for k, v in evidence.items()},
            "cache_miss_headers": str(ledger / f"{cell_id}.cache-miss-headers.jsonl"),
            "raw_responses_dir": str(ledger / f"{cell_id}.responses"),
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
