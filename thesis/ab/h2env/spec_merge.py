"""Merge an env-rerun spec into one launch line per model.

The driver starts one container per spec line, named ``$PFX-<model>``, and
the container's run_ab writes to ``<outdir>/<model>``. A spec written one
cell per line therefore has to collapse to one line per model with the
cells comma-joined for ``--cells``. Lines that would share a container name
or an output dir under different settings are refused.

SPEC line: ``<model> <pr> <pin> <rerun-from> [cells, comma-separated]``.
Blank lines and lines starting with ``#`` are skipped.
"""
import sys


class SpecError(ValueError):
    pass


def merge(lines):
    groups = {}
    for number, raw in enumerate(lines, 1):
        text = raw.strip()
        if not text or text.startswith("#"):
            continue
        fields = text.split()
        if len(fields) not in (4, 5):
            raise SpecError(f"line {number}: want 4 or 5 fields, got {len(fields)}")
        model, pr, pin, src = fields[:4]
        cells = [c for c in fields[4].split(",") if c] if len(fields) == 5 else None
        key = (pr, pin, src)
        if model in groups and groups[model]["key"] != key:
            raise SpecError(
                f"line {number}: model {model} already set to pr/pin/src "
                f"{' '.join(groups[model]['key'])}; one container per model")
        group = groups.setdefault(model, {"key": key, "cells": [], "full": False})
        if cells is None:
            group["full"] = True
        else:
            for cell in cells:
                if cell not in group["cells"]:
                    group["cells"].append(cell)
        if group["full"] and group["cells"]:
            raise SpecError(f"line {number}: model {model} mixes a full run with --cells lines")
    out = []
    for model, group in groups.items():
        pr, pin, src = group["key"]
        line = f"{model} {pr} {pin} {src}"
        if group["cells"]:
            line += " " + ",".join(group["cells"])
        out.append(line)
    return out


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2:
        print("usage: spec_merge.py SPEC OUT", file=sys.stderr)
        return 2
    try:
        with open(argv[0]) as handle:
            merged = merge(handle.readlines())
    except SpecError as exc:
        print(f"REFUSE spec: {exc}")
        return 9
    if not merged:
        print("REFUSE spec: no lines")
        return 9
    with open(argv[1], "w") as handle:
        handle.write("\n".join(merged) + "\n")
    print(f"spec merged: {len(merged)} launch line(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
