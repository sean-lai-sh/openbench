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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pi harness-comparison smoke, one cell per model")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--cache", type=Path, default=Path(os.environ.get("PI_HARNESS_CACHE", "/h1/pi-src")))
    parser.add_argument("--tasks-dir", type=Path, default=None)
    args = parser.parse_args(argv)

    repo = _repo_root()
    os.environ.pop("OBENCH_PI_VERTEX", None)
    os.environ["OBENCH_PI_HARNESS"] = "1"
    os.environ["OBENCH_VERTEX_ROUTE_BY_REQUEST"] = "1"

    from obench.adapters.pi_harness import PIN, load_proxy_totals, settings_destination
    from thesis.ab.build_pi import binary
    from thesis.ab.vertex_anthropic_proxy import start_from_env
    from obench.run import run_cell

    if PIN_MODELS != ("claude-opus-5-5", "claude-sonnet-5-5"):
        raise RuntimeError("smoke models drifted")

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
    proxy = start_from_env(ledger_dir=ledger, thinking_mode="default", model=PIN_MODELS[0])
    os.environ["OBENCH_VERTEX_PROXY_URL"] = proxy.base_url
    print(f"proxy {proxy.base_url} pin {PIN}", flush=True)

    tasks_dir = args.tasks_dir or (repo / "data" / "packs" / "openbench-tb-hard")
    adapters = repo / "obench" / "adapters"
    records = []
    try:
        for model in PIN_MODELS:
            cell_id = secrets.token_hex(8)
            os.environ["OBENCH_VERTEX_CELL_ID"] = cell_id
            os.environ.pop("OBENCH_PI_SETTINGS_PATH", None)
            print(f"cell {model} {cell_id}", flush=True)
            row = run_cell(
                "pi", TASK, model, 1, TIMEOUT_S,
                str(tasks_dir), str(adapters), CHECKER_TIMEOUT_S,
                exec_mode="local",
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
            record = {
                "cell_id": cell_id,
                "model": model,
                "pin": PIN,
                "task": TASK,
                "wire": "anthropic-messages",
                "openai_chat_completions": False,
                "row": row,
                "settings": settings,
                "totals": totals,
                "totals_error": totals_error,
                "requests_cost_usd": None if totals is None else _cost(model, totals["all"]),
                "requests_cost_main_usd": None if totals is None else _cost(model, totals["main"]),
            }
            _write(out / f"{model}.json", record)
            records.append({
                "model": model,
                "cell_id": cell_id,
                "completed": row.get("completed"),
                "failure_class": row.get("failure_class"),
                "checker_exit": row.get("checker_exit"),
                "tokens": row.get("tokens"),
                "requests_cost_usd": record["requests_cost_usd"],
                "totals_calls_all": None if totals is None else totals["all"]["calls"],
                "totals_calls_main": None if totals is None else totals["main"]["calls"],
            })
            print(json.dumps(records[-1]), flush=True)
    finally:
        proxy.close()
    _write(out / "summary.json", {"pin": PIN, "cells": records})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
