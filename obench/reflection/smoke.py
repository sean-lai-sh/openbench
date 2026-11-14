"""One-cell smoke per reflection-loop model (SEA-105). Paid: run on the VM only.

    python3 -m obench.reflection.smoke --model gemini-4-carbon \\
        --opencode "$HOME/h1/opencode-src/bin/<sha>/opencode" --out "$HOME/reflection-smoke/carbon"

Starts the recording proxy, runs the pinned OpenCode once on one task with
only this model's provider enabled, builds the per-step trace
(``trace.py``) and writes ``summary.json`` with the checks the ticket
requires:

1. ``model``: the command's ``--model`` names the model, and every wire
   record's served model is it (``upstream_model``);
2. ``traced``: every main call became a trace step, and the call and step
   counts match;
3. ``thinking_explicit``: every request carried the explicit setting;
4. ``usage_thinking``: every main call's usage reported a thinking-token
   count (Carbon: thinking is a summary/omitted/none kind, tokens still
   from usage). gpt-oss passes on "reported 0, text present" (flagged
   ``reported_zero_text_present``, or ``reported_absent_text_present`` when usage has
   no reasoning field) and fails only on missing/empty reasoning
   text; its counts are not comparable with Carbon's and Opus's;
5. ``cost``: every call has a cost (``cost_usd``) and the run total is
   logged;
6. ``pin``: the binary is the pinned OpenCode build.

``--out`` must be outside any ``results/`` or ``data/`` directory. The task
workspace is copied, so the repo is never edited. Exits 1 if a check fails.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from obench.reflection import opencode as oc
from obench.reflection import trace as tr
from obench.reflection import vertex_models as vm
from obench.reflection.wire_proxy import WireProxy

REPO = Path(__file__).resolve().parents[2]
DEFAULT_TASK = REPO / "tasks" / "fix-failing-test"
FORBIDDEN_OUT_PARTS = ("results", "data")
# Provider credentials OpenCode must not see: only the proxy route may be used.
STRIPPED_ENV = ("ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL", "OPENAI_API_KEY", "OPENAI_BASE_URL",
                "GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_GENERATIVE_AI_API_KEY", "OPENROUTER_API_KEY",
                "OPENCODE_CONFIG", "OPENCODE_CONFIG_DIR", "GOOGLE_APPLICATION_CREDENTIALS")


def check_out_dir(out: Path) -> Path:
    resolved = Path(out).expanduser().resolve()
    bad = [p for p in resolved.parts if p in FORBIDDEN_OUT_PARTS]
    if bad:
        raise SystemExit(f"--out {resolved} is inside a {bad[0]!r} directory; smoke output stays out of results/ and data/")
    return resolved


def child_env(model: vm.VertexModel, proxy_base: str, home: Path) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in STRIPPED_ENV}
    env.update({
        "OPENCODE_CONFIG_CONTENT": vm.opencode_config_env(model, proxy_base),
        "HOME": str(home), "XDG_CONFIG_HOME": str(home / ".config"), "XDG_DATA_HOME": str(home / ".local/share"),
        "XDG_CACHE_HOME": str(home / ".cache"), "XDG_STATE_HOME": str(home / ".local/state"),
        "OPENCODE_DISABLE_AUTOUPDATE": "1",
    })
    return env


def checks(model: vm.VertexModel, cmd: list[str], wires: list[dict], records: list[dict] | None,
           trace_error: str | None, pin_check: dict | None) -> dict:
    main = [w for w in wires if w.get("call_role") != "side"]
    served = sorted({str(w.get("upstream_model")) for w in wires})
    arg = cmd[cmd.index("--model") + 1] if "--model" in cmd else None
    thinking = [tr.thinking_setting(w["provider_wire"], w["request"])["explicit"] for w in wires
                if isinstance(w.get("request"), dict)]
    costs = [w.get("cost_usd") for w in wires]
    return {
        "model": {"command_model": arg, "served": served,
                  "pass": arg == vm.opencode_model_arg(model) and bool(wires)
                  and all(vm.served_matches(model, w.get("upstream_model")) for w in wires)},
        "traced": {"wire_calls": len(wires), "main_calls": len(main), "steps": len(records or []),
                   "trace_error": trace_error,
                   "pass": records is not None and len(records) == len(main) > 0},
        "thinking_explicit": {"requests": len(thinking), "explicit": sum(thinking),
                              "setting": model.thinking, "pass": bool(thinking) and all(thinking)},
        "usage_thinking": usage_thinking(model, records),
        "cost": {"per_call": costs, "total_usd": round(sum(c for c in costs if c is not None), 6) if costs else None,
                 "price_verified": model.price_verified, "price_source": model.price_source,
                 "pass": bool(costs) and all(isinstance(c, (int, float)) for c in costs)},
        "pin": {"check": pin_check, "pass": pin_check is not None},
    }


def usage_thinking(model: vm.VertexModel, records: list[dict] | None) -> dict:
    """Check 4. Every step's usage must report a thinking-token count (the
    usage value is always the one recorded). For gpt-oss, whose usage
    reports 0 alongside real reasoning text, a step instead passes on
    non-empty reasoning text: "reported 0, text present", flagged
    ``reported_zero_text_present``. Missing or empty text is the only failure
    there. Carbon and Opus pass on any reported count; Carbon's thinking is
    summaries by design."""
    from_text = model.key in vm.THINKING_TOKENS_FROM_TEXT
    steps = []
    for r in records or []:
        thinking, tokens = r.get("thinking") or {}, (r.get("usage") or {}).get("thinking_tokens")
        reported = isinstance(tokens, int) and not isinstance(tokens, bool)
        # gpt-oss: Vertex reports 0 or omits the reasoning field entirely; the text is the evidence.
        ok = bool((thinking.get("text") or "").strip()) if from_text else reported
        steps.append({"step": r.get("step"), "thinking_tokens": tokens, "kind": thinking.get("kind"),
                      "chars": thinking.get("chars"), "flag": thinking.get("flag"),
                      "tokens_counted": thinking.get("tokens_counted"),
                      "tokens_counted_by": thinking.get("tokens_counted_by"), "pass": ok})
    return {"per_step": steps,
            "rule": ("non-empty reasoning text; usage thinking tokens recorded as reported (0 or absent on Vertex)" if from_text
                     else "reported count from response usage"),
            "comparable_with_other_models": not from_text,
            "flags": sorted({s["flag"] for s in steps if s["flag"]}),
            "pass": bool(steps) and all(s["pass"] for s in steps)}


def run(args) -> int:
    model = vm.resolve(args.model)
    out = check_out_dir(args.out)
    out.mkdir(parents=True, exist_ok=True)
    project = os.environ.get("GOOGLE_CLOUD_PROJECT", "").strip()
    if not project:
        raise SystemExit("GOOGLE_CLOUD_PROJECT is not set")
    try:
        pin_check = oc.verify_binary(Path(args.opencode))
    except oc.PinError as exc:
        raise SystemExit(str(exc)) from exc
    from thesis.ab.vertex_anthropic_proxy import AdcToken  # stdlib-only ADC token source, reused unchanged

    token = AdcToken()
    token()  # fail before any model call if credentials are missing
    task = Path(args.task).resolve()
    instruction = (task / "instruction.md").read_text(encoding="utf-8")
    work = out / "work"
    shutil.rmtree(work, ignore_errors=True)
    shutil.copytree(task / "workspace", work)
    wire_path, events_path = out / "wire.jsonl", out / "opencode-events.jsonl"
    wire_path.unlink(missing_ok=True)
    proxy = WireProxy(project, wire_path, token)
    cmd = oc.run_command(Path(args.opencode), instruction, vm.opencode_model_arg(model))
    try:
        with tempfile.TemporaryDirectory(prefix="reflection-home-") as home:
            with events_path.open("w", encoding="utf-8") as events:
                proc = subprocess.run(cmd, cwd=work, env=child_env(model, proxy.base_url, Path(home)),
                                      stdout=events, stderr=subprocess.PIPE, text=True, timeout=args.timeout,
                                      stdin=subprocess.DEVNULL)
    finally:
        proxy.close()
    (out / "opencode-stderr.txt").write_text(proc.stderr or "", encoding="utf-8")
    wires = [json.loads(l) for l in wire_path.read_text(encoding="utf-8").splitlines() if l.strip()] \
        if wire_path.exists() else []
    records, trace_error = None, None
    try:
        events = tr.parse_events(events_path.read_text(encoding="utf-8").splitlines())
        records = tr.build_trace(events, wires, run={"model": model.key, "task": task.name, "kind": "smoke"},
                                 cost_fn=lambda rec: (vm.cost_usd(model, rec["usage"]), "reflection.vertex_models"),
                                 count_thinking_tokens=vm.THINKING_TOKENS_FROM_TEXT.get(model.key))
        tr.write_trace(out / "trace.jsonl", records)
    except tr.TraceError as exc:
        trace_error = str(exc)
    result = checks(model, cmd, wires, records, trace_error, pin_check)
    summary = {"model": model.key, "vertex_id": model.vertex_id, "location": model.location, "task": task.name,
               "opencode_exit": proc.returncode, "command": [cmd[0], *cmd[1:-1], "<instruction>"],
               "checks": result, "pass": all(c["pass"] for c in result.values())}
    (out / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({k: v["pass"] for k, v in result.items()}, sort_keys=True))
    return 0 if summary["pass"] else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="One-cell reflection-loop smoke for one Vertex model (paid)")
    parser.add_argument("--model", required=True, choices=sorted(vm.MODELS))
    parser.add_argument("--opencode", required=True, help="the pinned OpenCode binary (bin/<sha>/opencode)")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--task", default=str(DEFAULT_TASK))
    parser.add_argument("--timeout", type=int, default=1800)
    return run(parser.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
