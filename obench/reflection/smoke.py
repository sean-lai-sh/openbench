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
   from usage; gpt-oss: 0 is recorded as reported);
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
    thinking_tokens = [((r.get("usage") or {}).get("thinking_tokens")) for r in records or []]
    return {
        "model": {"command_model": arg, "served": served,
                  "pass": arg == vm.opencode_model_arg(model) and bool(wires)
                  and all(str(w.get("upstream_model") or "").startswith(model.vertex_id) for w in wires)},
        "traced": {"wire_calls": len(wires), "main_calls": len(main), "steps": len(records or []),
                   "trace_error": trace_error,
                   "pass": records is not None and len(records) == len(main) > 0},
        "thinking_explicit": {"requests": len(thinking), "explicit": sum(thinking),
                              "setting": model.thinking, "pass": bool(thinking) and all(thinking)},
        "usage_thinking": {"per_step": thinking_tokens,
                           "kinds": [((r.get("thinking") or {}).get("kind")) for r in records or []],
                           "pass": bool(records) and all(isinstance(t, int) for t in thinking_tokens)},
        "cost": {"per_call": costs, "total_usd": round(sum(c for c in costs if c is not None), 6) if costs else None,
                 "price_verified": model.price_verified, "price_source": model.price_source,
                 "pass": bool(costs) and all(isinstance(c, (int, float)) for c in costs)},
        "pin": {"check": pin_check, "pass": pin_check is not None},
    }


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
                                 cost_fn=lambda rec: (vm.cost_usd(model, rec["usage"]), "reflection.vertex_models"))
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
