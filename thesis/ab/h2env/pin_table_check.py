#!/usr/bin/env python3
"""Pre-launch pin check against the rev2 pin table.

usage: pin_table_check.py --pr PR --model MODEL --pin PIN [--table CSV] [--study H2]

Exit 0 only when every rev2 row for (study, pr, model) has rerun_pin_rev2 == PIN.
Exit 9 on a mismatch, on no rows, or on rows that disagree (refuse to launch).
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

DEFAULT_TABLE = Path(__file__).resolve().parents[3] / "results" / "pin-table-1030" / "rev2" / "pin-table.csv"


def table_pins(table, study: str, pr: str, model: str) -> set[str]:
    with open(table, newline="", encoding="utf-8") as f:
        return {(r.get("rerun_pin_rev2") or "").strip() for r in csv.DictReader(f)
                if r.get("study") == study and r.get("pr") == str(pr) and r.get("model") == model}


def check(table, study: str, pr: str, model: str, pin: str) -> tuple[bool, str]:
    pins = table_pins(table, study, pr, model)
    if not pins:
        return False, f"REFUSE pin: no rev2 rows for {study} pr={pr} model={model}"
    if len(pins) != 1:
        return False, f"REFUSE pin: rev2 rows disagree for pr={pr} model={model}: {sorted(pins)}"
    want = next(iter(pins))
    if want != pin:
        return False, f"REFUSE pin: pr={pr} model={model} driver pin {pin} != rev2 {want}"
    return True, f"pin ok: pr={pr} model={model} pin={pin} (rev2)"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pr", required=True); ap.add_argument("--model", required=True)
    ap.add_argument("--pin", required=True); ap.add_argument("--study", default="H2")
    ap.add_argument("--table", type=Path, default=DEFAULT_TABLE)
    a = ap.parse_args(argv)
    ok, msg = check(a.table, a.study, a.pr, a.model, a.pin)
    print(msg)
    return 0 if ok else 9


if __name__ == "__main__":
    sys.exit(main())
