#!/usr/bin/env python3
"""usage: pair_spend.py ROOT... -> "total=X cells=N" (plain spend sum; used by the central stop)."""
import json, sys
from pathlib import Path
tot = 0.0; n = 0
for root in map(Path, sys.argv[1:]):
    for p in root.rglob("*.json"):
        parts = p.relative_to(root).parts
        if "cells" not in parts[:-1]: continue
        try: d = json.loads(p.read_text())
        except Exception: continue
        if not isinstance(d, dict): continue
        c = float(d.get("requests_cost_usd") or 0); tot += c; n += 1
print(f"total={tot:.4f} cells={n}")
