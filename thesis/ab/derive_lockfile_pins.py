#!/usr/bin/env python3
"""Derive ``@ai-sdk/anthropic`` pins from each OpenCode build's own lockfile (D3).

Step-8 deviation D3 (briefs/step8-amendment-M1-deviation-D3-lockfile-pins-2026-10-26.md).
The lockfile is read with ``git show <sha>:bun.lock`` from an OpenCode mirror,
so no worktree is needed. The version is the one bun resolved for the
provider package's own dependency: the ``packages/opencode`` workspace must
declare ``@ai-sdk/anthropic``, and its entry is ``opencode/@ai-sdk/anthropic``
when bun nested it, else the top-level ``@ai-sdk/anthropic``. Exactly one
exact version is a pin. Zero entries, more than one distinct version, or no
readable ``bun.lock`` is ``unpinnable``: no guess is made and no entry is
written, so the queue preflight holds that side.

  derive_lockfile_pins.py validate --mirror DIR [--out-dir DIR]
      compare the lockfile version with every pin_source=box_cache side.
      Exit 1 if any side disagrees.
  derive_lockfile_pins.py derive --mirror DIR --subs SUBS.txt --prs prs.csv
      --from-batch F03-2 [--write] [--out-dir DIR]
      add pin_source=lockfile entries for every side of the batches from
      --from-batch on that has no pin. Refuses unless the gate passed.
      Rerunning on the written file adds nothing and recomputes the same set.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
from pathlib import Path

PACKAGE = "@ai-sdk/anthropic"
PIN_SOURCE = "lockfile"
PROVIDER_WORKSPACE = "packages/opencode"
EVIDENCE = "lockfile-d3"
_EXACT = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
_TRAILING_COMMA = re.compile(r",(\s*[}\]])")
PINS = Path(__file__).with_name("provider_pins.json")


def load_jsonc(text: str) -> dict:
    prev = None
    while prev != text:
        prev, text = text, _TRAILING_COMMA.sub(r"\1", text)
    return json.loads(text)


def lockfile_versions(mirror: Path, sha: str) -> tuple[list[str], str]:
    """Distinct locked versions of PACKAGE at ``sha`` and a note."""
    run = subprocess.run(["git", "-C", str(mirror), "show", f"{sha}:bun.lock"],
                         capture_output=True, text=True)
    if run.returncode != 0:
        return [], "no bun.lock at sha"
    try:
        lock = load_jsonc(run.stdout)
    except json.JSONDecodeError as exc:
        return [], f"bun.lock unparsable: {exc.msg}"
    packages = lock.get("packages") if isinstance(lock, dict) else None
    packages = packages if isinstance(packages, dict) else {}
    workspaces = lock.get("workspaces") if isinstance(lock, dict) else None
    ws = (workspaces or {}).get(PROVIDER_WORKSPACE)
    if not isinstance(ws, dict):
        return [], f"no {PROVIDER_WORKSPACE} workspace in bun.lock"
    declared = any(PACKAGE in (ws.get(k) or {}) for k in
                   ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies"))
    if not declared:
        return [], f"{PROVIDER_WORKSPACE} does not declare {PACKAGE}"
    # bun resolves a workspace dependency to "<workspace name>/<pkg>" when it
    # is hoisted apart, else to the top-level "<pkg>" entry.
    found = set()
    for key in (f"{ws.get('name') or ''}/{PACKAGE}", PACKAGE):
        entry = packages.get(key)
        if entry is None:
            continue
        if isinstance(entry, list) and entry and isinstance(entry[0], str) and "@" in entry[0]:
            found.add(entry[0].rsplit("@", 1)[1])
        else:
            found.add("?")
        break
    return sorted(found), ""


def any_workspace_versions(mirror: Path, sha: str) -> str:
    """Every locked PACKAGE version anywhere in bun.lock (diagnostic only, never a pin)."""
    run = subprocess.run(["git", "-C", str(mirror), "show", f"{sha}:bun.lock"],
                         capture_output=True, text=True)
    if run.returncode != 0:
        return ""
    try:
        packages = load_jsonc(run.stdout).get("packages") or {}
    except (json.JSONDecodeError, AttributeError):
        return ""
    found = {e[0].rsplit("@", 1)[1] for k, e in packages.items()
             if (k == PACKAGE or k.endswith("/" + PACKAGE)) and isinstance(e, list) and e
             and isinstance(e[0], str) and "@" in e[0]}
    return "|".join(sorted(found))


def derive(mirror: Path, sha: str) -> tuple[str | None, str]:
    """(version, reason). version is None when the side is unpinnable."""
    versions, note = lockfile_versions(mirror, sha)
    if note:
        return None, note
    if not versions:
        return None, f"no {PACKAGE} entry in bun.lock"
    if len(versions) > 1:
        return None, "more than one version: " + "|".join(versions)
    if not _EXACT.match(versions[0]):
        return None, f"not an exact version: {versions[0]}"
    return versions[0], ""


def box_cache_sides(manifest: dict) -> list[tuple[str, str, str, str]]:
    rows = []
    for sha, sides in sorted(manifest["builds"].items()):
        for side, entry in sorted(sides.items()):
            if entry.get("pin_source") == "box_cache":
                rows.append((sha, side, str(entry.get("pr") or ""),
                             entry["packages"].get(PACKAGE, "")))
    return rows


def validate(mirror: Path) -> list[dict]:
    manifest = json.loads(PINS.read_text())
    out = []
    for sha, side, pr, box in box_cache_sides(manifest):
        lock, reason = derive(mirror, sha)
        out.append({"sha": sha, "side": side, "pr": pr, "box_cache": box,
                    "lockfile": lock or "unpinnable", "match": "yes" if lock == box else "no",
                    "note": reason, "any_workspace_versions": any_workspace_versions(mirror, sha)})
    return out


def batch_sides(subs: Path, prs: Path, from_batch: str) -> list[tuple[str, str, str, str]]:
    rows = {r["PR"].strip(): r for r in csv.DictReader(open(prs))}
    out, on = [], False
    for line in open(subs):
        parts = line.split()
        if len(parts) < 2:
            continue
        on = on or parts[0] == from_batch
        if not on:
            continue
        for pr in parts[1].split(","):
            r = rows[pr]
            out.append((parts[0], pr, "with", r["Merge commit SHA"].strip().lower()))
            out.append((parts[0], pr, "without", r["Parent/base SHA"].strip().lower()))
    return out


def lockfile_entries(mirror: Path, sides, manifest: dict) -> tuple[dict, list[dict]]:
    """Entries to add (sha -> side -> entry) and the unpinnable list."""
    builds = manifest["builds"]
    added: dict = {}
    unpinnable = []
    for batch, pr, side, sha in sides:
        existing = builds.get(sha, {}).get(side)
        if existing is not None and existing.get("pin_source") != PIN_SOURCE:
            continue
        version, reason = derive(mirror, sha)
        if version is None:
            unpinnable.append({"batch": batch, "pr": pr, "side": side, "sha": sha, "reason": reason})
            continue
        added.setdefault(sha, {})[side] = {"evidence": EVIDENCE, "packages": {PACKAGE: version},
                                           "pin_source": PIN_SOURCE, "pr": pr}
    return added, unpinnable


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]) if rows else ["none"], lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["validate", "derive"])
    ap.add_argument("--mirror", required=True, type=Path)
    ap.add_argument("--subs", type=Path)
    ap.add_argument("--prs", type=Path)
    ap.add_argument("--from-batch", default="F03-2")
    ap.add_argument("--out-dir", type=Path)
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args(argv)
    gate = validate(a.mirror)
    bad = [r for r in gate if r["match"] != "yes"]
    if a.mode == "validate":
        if a.out_dir:
            write_csv(a.out_dir / "comparison.csv", gate)
        print(f"gate: {len(gate) - len(bad)} of {len(gate)} box_cache sides match")
        for r in bad:
            print("MISMATCH", r["sha"], r["side"], r["pr"], r["box_cache"], r["lockfile"], r["note"])
        return 1 if bad else 0
    if bad:
        print(f"refusing: gate has {len(bad)} mismatches", file=sys.stderr)
        return 1
    manifest = json.loads(PINS.read_text())
    added, unpinnable = lockfile_entries(a.mirror, batch_sides(a.subs, a.prs, a.from_batch), manifest)
    n = sum(len(v) for v in added.values())
    if a.out_dir:
        write_csv(a.out_dir / "unpinnable.csv", unpinnable)
    print(f"lockfile pins: {n}; unpinnable: {len(unpinnable)}")
    if a.write:
        for sha, sides in added.items():
            manifest["builds"].setdefault(sha, {}).update(sides)
        manifest["builds"] = dict(sorted(manifest["builds"].items()))
        PINS.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
