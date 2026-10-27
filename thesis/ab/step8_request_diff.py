"""Diff the requests the harness sends to the stub, strace on vs off.

Compares captured ``*.requests.jsonl`` (from ``step8_stub_ready --capture``)
pairwise: JSON body, headers minus volatile ones, and the tool list. Also
reports wall time per run from each ``stub_ready.csv``. No model calls.
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics
from pathlib import Path

VOLATILE_HEADERS = {"content-length", "date", "host", "connection", "x-request-id",
                    "request-id", "traceparent", "x-stainless-retry-count",
                    "x-stainless-timeout", "user-agent"}


def _norm(req: dict) -> dict:
    headers = {k.lower(): v for k, v in req.get("headers", {}).items()
               if k.lower() not in VOLATILE_HEADERS}
    try:
        body = json.loads(req.get("body") or "{}")
    except ValueError:
        body = {"_raw": req.get("body")}
    tools = [t.get("name") for t in body.get("tools") or [] if isinstance(t, dict)]
    return {"method": req.get("method"), "path": req.get("path"), "headers": headers, "body": body, "tools": tools}


def _diff(a, b, path="") -> list[str]:
    if isinstance(a, dict) and isinstance(b, dict):
        out = []
        for k in sorted(set(a) | set(b)):
            out += _diff(a.get(k, "<absent>"), b.get(k, "<absent>"), f"{path}.{k}")
        return out
    if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        out = []
        for i, (x, y) in enumerate(zip(a, b)):
            out += _diff(x, y, f"{path}[{i}]")
        return out
    if a == b:
        return []
    if isinstance(a, str) and isinstance(b, str) and "\n" in a:
        import difflib
        changed = [l for l in difflib.unified_diff(a.splitlines(), b.splitlines(), lineterm="", n=0)
                   if l[:1] in "+-" and not l.startswith(("+++", "---"))]
        return [f"{path} line: {l[:200]}" for l in changed]
    return [f"{path}: {json.dumps(a)[:200]} != {json.dumps(b)[:200]}"]


_WORKDIR = "Working directory:"


def _shape(x):
    """Keys and value types only; tool lists keep their names."""
    if isinstance(x, dict):
        return {k: _shape(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_shape(v) for v in x]
    return type(x).__name__


def _drop_workdir(x):
    if isinstance(x, dict):
        return {k: _drop_workdir(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_drop_workdir(v) for v in x]
    if isinstance(x, str) and _WORKDIR in x:
        return "\n".join(l for l in x.splitlines() if _WORKDIR not in l)
    return x


def _key(r: dict) -> tuple:
    return (r.get("method"), r.get("path"), str(r["body"].get("model") or ""))


def compare_requests(a: list[dict], b: list[dict]) -> tuple[list[str], list[str]]:
    """Match two normalized request sets on endpoint path, method and body
    shape. Requests pair up by (method, path, model) since the title and main
    calls race. Returns (reasons they don't match, informational content diffs
    with the Working directory line ignored)."""
    ka, kb = sorted(map(_key, a)), sorted(map(_key, b))
    if ka != kb:
        return [f"request sets differ: {ka} != {kb}"], []
    reasons, notes = [], []
    for x, y in zip(sorted(a, key=_key), sorted(b, key=_key)):
        tag = "%s %s %s" % _key(x)
        shape = _diff(_shape(x["body"]), _shape(y["body"]))
        if x["tools"] != y["tools"]:
            shape.append(f"tools {x['tools']} != {y['tools']}")
        reasons += [f"{tag}: {d}" for d in shape]
        notes += [f"{tag}: {d}" for d in _diff(_drop_workdir(x["body"]), _drop_workdir(y["body"]))]
    return reasons, notes


def load(path: Path) -> list[dict]:
    return [_norm(json.loads(line)) for line in path.read_text().splitlines() if line.strip()]


def walls(csv_path: Path) -> list[float]:
    return [float(r["wall_s"]) for r in csv.DictReader(open(csv_path)) if r.get("wall_s")]


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--on", type=Path, required=True, help="stub_ready out dir, strace on")
    p.add_argument("--off", type=Path, required=True, help="stub_ready out dir, strace off")
    p.add_argument("--req", default="req", help="capture subdir name")
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args(argv)
    on = sorted((a.on / a.req).glob("*.requests.jsonl"))
    off = sorted((a.off / a.req).glob("*.requests.jsonl"))
    lines = []
    pairs = [("on-vs-off", on[0], off[0])]
    if len(on) > 1:
        pairs.append(("on-vs-on (baseline)", on[0], on[1]))
    if len(off) > 1:
        pairs.append(("off-vs-off (baseline)", off[0], off[1]))
    for name, x, y in pairs:
        ra, rb = load(x), load(y)
        lines.append(f"## {name}: {x.name} ({len(ra)} req) vs {y.name} ({len(rb)} req)")
        if len(ra) != len(rb):
            lines.append(f"request count differs: {len(ra)} != {len(rb)}")
        for i, (r1, r2) in enumerate(zip(ra, rb)):
            d = _diff(r1, r2, f"req{i}")
            lines.append(f"req{i} tools: {len(r1['tools'])} vs {len(r2['tools'])}; "
                         f"tool list {'identical' if r1['tools'] == r2['tools'] else 'DIFFERS'}")
            lines += [f"  {x}" for x in d] or ["  body+headers identical"]
    w_on, w_off = walls(a.on / "stub_ready.csv"), walls(a.off / "stub_ready.csv")
    m_on, m_off = statistics.median(w_on), statistics.median(w_off)
    lines.append("## wall time (s)")
    lines.append(f"strace on : {w_on} median {m_on:.3f}")
    lines.append(f"strace off: {w_off} median {m_off:.3f}")
    lines.append(f"on vs off (median): {100 * (m_on - m_off) / m_off:+.1f}%")
    a.out.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
