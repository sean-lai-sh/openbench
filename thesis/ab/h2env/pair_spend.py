#!/usr/bin/env python3
"""usage: pair_spend.py ROOT... -> "total=X cells=N maxpair=Y", then "OVER <model> <key> <usd>" per pair >= $1.00 (pair = model/pr|task|trial, both arms)."""
import json, sys
from pathlib import Path
tot = 0.0; n = 0; pairs = {}
for root in map(Path, sys.argv[1:]):
    for p in root.rglob("*.json"):
        parts = p.relative_to(root).parts
        if "cells" not in parts[:-1]: continue
        try: d = json.loads(p.read_text())
        except Exception: continue
        if not isinstance(d, dict): continue
        c = float(d.get("requests_cost_usd") or 0); tot += c; n += 1
        i = parts.index("cells")
        key = "/".join(parts[:i]) + "|" + parts[i+2] + "|" + p.stem  # model/pr|task|trial
        pairs[key] = pairs.get(key, 0) + c
print(f"total={tot:.4f} cells={n} maxpair={max(pairs.values(), default=0):.4f}")
for k, v in pairs.items():
    if v >= 1.0: print(f"OVER {k.split('/')[0]} {k} {v:.4f}")
