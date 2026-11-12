#!/usr/bin/env python3
"""Evaluate the D1 prompt-follow-up re-smoke gates from cell records + ledgers."""
from __future__ import annotations

import json
import sys
from pathlib import Path


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    if not path.is_file():
        return rows
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def thinking_tokens(rec: dict):
    usage = rec.get("usage") if isinstance(rec.get("usage"), dict) else {}
    details = usage.get("output_tokens_details")
    if isinstance(details, dict) and details.get("thinking_tokens") is not None:
        return details.get("thinking_tokens")
    return None


def cache_rw(rec: dict):
    usage = rec.get("usage") if isinstance(rec.get("usage"), dict) else {}
    read = rec.get("cache_read")
    write = rec.get("cache_write")
    if read is None:
        read = usage.get("cache_read_input_tokens")
    if write is None:
        write = usage.get("cache_creation_input_tokens")
    return read, write


def cmd_model(cmd):
    if isinstance(cmd, list) and "-m" in cmd:
        i = cmd.index("-m")
        if i + 1 < len(cmd):
            return cmd[i + 1]
    return None


def ledger_id_from_row(row: dict):
    for k in ("proxy_cell_id", "cell_id", "instance_id", "run_id"):
        v = row.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    proxy = row.get("proxy")
    if isinstance(proxy, dict):
        for k in ("cell_id", "ledger_id", "id"):
            v = proxy.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
    return None


def collect_written_configs(root: Path) -> list[dict]:
    found = []
    names = {"opencode.json", "config.json", "opencode.jsonc"}
    for p in root.rglob("*"):
        if p.is_file() and p.name in names:
            item = {"path": str(p.relative_to(root))}
            try:
                item["body"] = json.loads(p.read_text(encoding="utf-8", errors="replace"))
            except Exception as exc:
                item["error"] = str(exc)
            found.append(item)
    return found


def sonnet_contexts_from_config(body: dict) -> list[tuple[str, object]]:
    out = []
    providers = (body or {}).get("provider") or {}
    if not isinstance(providers, dict):
        return out
    for pname, provider in providers.items():
        if not isinstance(provider, dict):
            continue
        models = provider.get("models") or {}
        if not isinstance(models, dict):
            continue
        for mid, entry in models.items():
            if "claude-sonnet-5-5" in str(mid) and isinstance(entry, dict):
                limit = entry.get("limit") if isinstance(entry.get("limit"), dict) else {}
                out.append((f"{pname}/{mid}", limit.get("context")))
    return out


ROW_KEYS = [
    "task", "model", "protocol_model", "requested_model", "upstream_model",
    "success", "score", "functional_pass", "failure_class", "failure_reason",
    "error", "load_proof", "load_proof_basis", "load_proof_reason",
    "loaded_anthropic", "provider_loaded_version", "provider_loaded_source",
    "anthropic_pin", "pin_source", "pin_source_class", "embedded_version",
    "installed_anthropic", "thinking_mode", "thinking_sent",
    "model_context_window", "model_max_tokens",
    "proxy_cost_usd", "proxy_requests", "requests_count",
    "runner_commit", "binary_sha256", "missing_fields",
    "tokens_reasoning", "tokens_proxy_reasoning",
    "requests_cache_read", "requests_cache_write",
    "tokens_cache_read", "tokens_cache_write",
    "started_et", "ended_et", "host",
]


def summarize_ledger(path: Path) -> dict:
    recs = load_jsonl(path)
    calls = []
    for i, rec in enumerate(recs, 1):
        cr, cw = cache_rw(rec)
        calls.append({
            "i": i,
            "status": rec.get("status"),
            "upstream_model": rec.get("upstream_model"),
            "requested_model": rec.get("requested_model"),
            "thinking_sent": rec.get("thinking_sent"),
            "thinking_tokens": thinking_tokens(rec),
            "cache_read": cr,
            "cache_write": cw,
        })
    totals = None
    tp = path.with_name(path.name[: -len(".jsonl")] + ".totals.json") if path.name.endswith(".jsonl") else None
    # path.with_suffix is unsafe because of dots in the hash? suffix of .jsonl is fine
    totals_path = path.with_suffix(".totals.json") if path.suffix == ".jsonl" else None
    # files are name.jsonl and name.totals.json — with_suffix(".totals.json") would make name.totals.json? 
    # Path.with_suffix replaces last suffix: foo.jsonl -> foo.totals.json. Good.
    if totals_path and totals_path.is_file():
        totals = json.loads(totals_path.read_text())
    return {"n": len(recs), "calls": calls, "totals": totals}


def pair_ledger(row: dict, ledgers: dict[str, dict]) -> str | None:
    wanted = ledger_id_from_row(row)
    if wanted:
        for name in ledgers:
            if name.startswith(wanted) or wanted in name:
                return name
    n = row.get("proxy_requests") or row.get("requests_count")
    cost = row.get("proxy_cost_usd")
    matches = []
    for name, led in ledgers.items():
        if n is not None and led.get("n") == n:
            matches.append(name)
    if len(matches) == 1:
        return matches[0]
    return matches[0] if len(matches) == 1 else (wanted if wanted else None)


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else "/o")
    report = {"root": str(root), "arms": {}, "gates": {}}
    cfg_path = root / "config-check.json"
    offline = json.loads(cfg_path.read_text()) if cfg_path.is_file() else {}
    report["offline_config"] = {
        side: {
            "context_ok": sec.get("context_ok"),
            "sonnet_contexts": sec.get("sonnet_contexts"),
            "pin_source": sec.get("pin_source"),
            "anthropic_sdk": sec.get("anthropic_sdk"),
            "bundled": sec.get("bundled"),
            "bundled_anthropic_pin": sec.get("bundled_anthropic_pin"),
        }
        for side, sec in (offline or {}).items()
        if isinstance(sec, dict)
    }

    written = collect_written_configs(root)
    report["written_configs"] = []
    for item in written:
        entry = {"path": item["path"]}
        if "error" in item:
            entry["error"] = item["error"]
        else:
            entry["sonnet_contexts"] = sonnet_contexts_from_config(item.get("body") or {})
        report["written_configs"].append(entry)

    ledger_dir = root / "proxy-ledger"
    all_ledgers = {}
    if ledger_dir.is_dir():
        for lp in sorted(ledger_dir.glob("*.jsonl")):
            if "cache-miss" in lp.name:
                continue
            all_ledgers[lp.name] = summarize_ledger(lp)

    used_ledgers = set()
    for side in ("without", "with"):
        path = root / "725226" / f"{side}.jsonl"
        rows = load_jsonl(path)
        arm = {"path": str(path), "n_rows": len(rows)}
        if not rows:
            report["arms"][side] = arm
            continue
        row = rows[0]
        useful = {k: row.get(k) for k in ROW_KEYS}
        useful["cmd_model"] = cmd_model(row.get("cmd"))
        useful["_extra_id_fields"] = {
            k: row.get(k)
            for k in row.keys()
            if any(s in k.lower() for s in ("ledger", "cell_id", "proxy_id", "run_id", "instance"))
        }
        name = pair_ledger(row, all_ledgers)
        # fallback: unused ledger with same request count
        if name not in all_ledgers:
            n = row.get("proxy_requests") or row.get("requests_count")
            unused = [k for k, v in all_ledgers.items() if k not in used_ledgers and v.get("n") == n]
            if len(unused) == 1:
                name = unused[0]
            elif len(all_ledgers) - len(used_ledgers) == 1:
                name = next(k for k in all_ledgers if k not in used_ledgers)
        if name in all_ledgers:
            used_ledgers.add(name)
            arm["ledger"] = name
            arm["calls"] = all_ledgers[name]["calls"]
            arm["ledger_totals"] = all_ledgers[name]["totals"]
        else:
            arm["ledger"] = name
            arm["calls"] = []
        arm["row"] = useful
        report["arms"][side] = arm

    report["unpaired_ledgers"] = {
        k: v for k, v in all_ledgers.items() if k not in used_ledgers
    }

    problems = []
    load_ok = True
    trace_ok = True
    context_ok = True
    thinking_ok = True

    for side in ("without", "with"):
        arm = report["arms"].get(side) or {}
        if arm.get("n_rows", 0) < 1:
            problems.append(f"{side}: missing cell row")
            load_ok = trace_ok = context_ok = thinking_ok = False
            continue
        row = arm["row"]
        pin_src = row.get("pin_source")
        loaded = row.get("provider_loaded_version") or row.get("loaded_anthropic")
        pin = row.get("anthropic_pin")
        proof = row.get("load_proof")
        if proof not in {"pass", "ok", True}:
            load_ok = False
            problems.append(f"{side}: load_proof={proof!r} reason={row.get('load_proof_reason')}")
        if pin_src != "bundled_package_json":
            load_ok = False
            problems.append(f"{side}: pin_source={pin_src!r} (want bundled_package_json)")
        if not loaded or not pin or str(loaded) != str(pin):
            load_ok = False
            problems.append(f"{side}: loaded {loaded!r} != pin {pin!r}")

        sent = row.get("thinking_sent")
        values = sent if isinstance(sent, list) else [sent]
        if not values or any(v not in {"none"} for v in values):
            thinking_ok = False
            problems.append(f"{side}: thinking_sent={sent!r} (want none on every request)")

        if row.get("upstream_model") != "claude-sonnet-5-5":
            trace_ok = False
            problems.append(f"{side}: upstream_model={row.get('upstream_model')!r}")
        if row.get("model") != "claude-sonnet-5-5":
            trace_ok = False
            problems.append(f"{side}: model={row.get('model')!r}")
        if row.get("cmd_model") and "claude-sonnet-5-5" not in str(row.get("cmd_model")):
            trace_ok = False
            problems.append(f"{side}: cmd_model={row.get('cmd_model')!r}")

        calls = arm.get("calls") or []
        reqs = row.get("proxy_requests") or row.get("requests_count") or 0
        if not reqs:
            trace_ok = False
            problems.append(f"{side}: no proxy requests")
        if len(calls) != reqs:
            trace_ok = False
            problems.append(f"{side}: traced {len(calls)} != requests {reqs}")
        for call in calls:
            if call.get("upstream_model") != "claude-sonnet-5-5":
                trace_ok = False
                problems.append(f"{side} call {call.get('i')}: upstream={call.get('upstream_model')!r}")
            if call.get("requested_model") != "claude-sonnet-5-5":
                trace_ok = False
                problems.append(f"{side} call {call.get('i')}: requested={call.get('requested_model')!r}")
            if call.get("thinking_sent") != "none":
                thinking_ok = False
                problems.append(f"{side} call {call.get('i')}: thinking_sent={call.get('thinking_sent')!r}")
            if call.get("status") not in (200, "200", None):
                # None shouldn't happen; non-200 is still traced but worth noting
                problems.append(f"{side} call {call.get('i')}: status={call.get('status')!r}")

    offline_ok = bool(report["offline_config"])
    if not offline_ok:
        problems.append("no config-check.json")
    for side, section in report["offline_config"].items():
        if not section.get("context_ok"):
            offline_ok = False
            problems.append(
                f"{side}: offline bound sonnet context not 200000: {section.get('sonnet_contexts')}"
            )
    live_context_ok = True
    if report["written_configs"]:
        any_sonnet = False
        for item in report["written_configs"]:
            ctxs = item.get("sonnet_contexts") or []
            if ctxs:
                any_sonnet = True
            for mid, ctx in ctxs:
                if ctx != 200000:
                    live_context_ok = False
                    problems.append(f"written {item['path']} {mid} context={ctx}")
        if not any_sonnet:
            live_context_ok = False
            problems.append("written config files present but no claude-sonnet-5-5 limit.context")
        context_ok = live_context_ok and offline_ok
    else:
        # Live config is not saved in the cell tree (same as #247). Offline bind is the written-config check.
        context_ok = offline_ok
        report["written_config_note"] = (
            "no opencode.json saved under the run dir; using assessed+bound config from config-check.py"
        )

    report["gates"] = {
        "load_proof": load_ok,
        "traced_upstream_sonnet": trace_ok,
        "written_context_200000": context_ok,
        "thinking_unset": thinking_ok,
        "all_pass": load_ok and trace_ok and context_ok and thinking_ok,
        "problems": problems,
    }
    text = json.dumps(report, indent=2, sort_keys=True, default=str)
    print(text)
    (root / "gate-check.json").write_text(text + "\n")
    return 0 if report["gates"]["all_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
