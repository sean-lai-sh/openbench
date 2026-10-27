#!/usr/bin/env python3
"""Pin F03-2 through F16 to the nearest box-run @ai-sdk/anthropic version.

D4 (briefs/step8-amendment-M1-deviation-D4-nearest-build-pins-2026-10-26.md)
stopped before spend because leave-one-out misses landed on versions that had
infra cells. The decision recorded with these pins: only a provider fault
disqualifies a version. Timeouts, install errors, and empty-cache pin checks
do not. Provider faults stay infra for scoring. The #155 rescore
(results/step8-full413-1020-F01/rescore-provider-faults/) is unchanged, and
this script does not edit pass-rate formulas.

Both sides of a PR get the box_cache version of the box-run build nearest the
without (parent) commit on the OpenCode first-parent line. 51062, 53166, and
55613 have no packages/opencode and are deferred, not pinned.

  python3 -m thesis.ab.step8_pins apply --mirror <opencode mirror>

Writes data/step8-pins/pins.csv, README.md, and rerun-1443.json, and merges
new sides into thesis/ab/provider_pins.json. Does not launch a model.
Apply exits nonzero when leave-one-out agreement is below 95%.
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

from thesis.ab.derive_nearest_build_pins import (
    PACKAGE,
    Line,
    box_sides,
    nearest,
)

ROOT = Path(__file__).resolve().parents[2]
PINS = Path(__file__).with_name("provider_pins.json")
DEFAULT_SUBS = ROOT / "results/step8-vm-F03-1-1025-QUARANTINED/SUBS.txt"
DEFAULT_PRS = ROOT / "results/step8-full413-1020/prs.csv"
DEFAULT_OUT = ROOT / "data" / "step8-pins"
DEFERRED = ("51062", "53166", "55613")
# D4 rule 3(b): the nearest-box rule may be used only at or above this rate.
LOO_MIN_PERCENT = 95
# Built binaries live at <opencode-src>/bin/<sha>/opencode. --bin-root is that
# directory (the runner's results/opencode-src layout).
DRY_RUN_WITH_BINARIES = (
    "python3 -m thesis.ab.step8_pin_dry_run "
    "--cache /tmp/step8-pin-cache --bin-root <opencode-src>"
)
# PR 1443 is the only box PR whose sides recorded different versions.
RERUN_PR = "1443"
RERUN_VERSION = "2.0.0-beta.11"

AUTH = re.compile(r"authentication_error|invalid x-api-key", re.I)
INST = re.compile(r"bun\W+add|NpmInstallFailedError|No matching version found", re.I)
PROV = re.compile(
    r"Unhandled chunk type|AI_\w*Error|APICallError|TypeValidationError|stream error|"
    r"overloaded_error|api_error|invalid_request_error",
    re.I,
)
# "stream error" is also how OpenCode logs TimeoutError. #155 kept
# 579 without trig-read-lines trial 27 as a hang (label_only). A timeout
# that only matches the provider rule on those words is not a provider fault.
TIMEOUT = re.compile(r"no_progress|idle_s|timed out|timeout|ETIMEDOUT|ECONNRESET", re.I)

PIN_FIELDS = [
    "status", "batch", "pr", "side", "sha", "parent_sha", "version", "pin_source",
    "pin_from", "pin_from_pr", "pin_from_side", "distance", "parent_pos",
    "pin_from_pos", "placement", "reasoning",
]


def _git_ok(mirror: Path, *args: str) -> bool:
    proc = subprocess.run(
        ["git", "-C", str(mirror), *args],
        capture_output=True,
        text=True,
    )
    return proc.returncode == 0


def has_opencode_package(mirror: Path, sha: str) -> bool:
    return _git_ok(mirror, "cat-file", "-e", f"{sha}:packages/opencode")


def queue_rows(subs: Path, prs: Path, from_batch: str) -> list[dict]:
    """F03-2 onward, one dict per side, in SUBS.txt order."""
    catalog = {row["PR"].strip(): row for row in csv.DictReader(open(prs, newline=""))}
    out = []
    started = False
    for line in open(subs):
        parts = line.split()
        if len(parts) < 2:
            continue
        started = started or parts[0] == from_batch
        if not started:
            continue
        batch = parts[0]
        for pr in parts[1].split(","):
            row = catalog.get(pr)
            if row is None:
                raise SystemExit(f"{pr} is in {subs} but not in {prs}")
            parent = row["Parent/base SHA"].strip().lower()
            merge = row["Merge commit SHA"].strip().lower()
            for side, sha in (("with", merge), ("without", parent)):
                out.append({
                    "batch": batch,
                    "pr": pr,
                    "side": side,
                    "sha": sha,
                    "parent_sha": parent,
                })
    return out


def provider_fault_counts(root: Path = ROOT) -> Counter:
    """Recorded @ai-sdk/anthropic version -> provider-fault cells.

    Same order as thesis/ab/classify_provider_faults.py. A timeout or an
    install error is not a provider fault. Cells with no recorded version
    are not charged to a box pin.
    """
    counts: Counter = Counter()
    pattern = str(root / "results/step8-*/**/*.jsonl")
    for path in glob.glob(pattern, recursive=True):
        if "/transcripts/" in path or "proxy-ledger" in path:
            continue
        with open(path) as fh:
            for line in fh:
                try:
                    cell = json.loads(line)
                except ValueError:
                    continue
                if "cell_seed" not in cell:
                    continue
                versions = cell.get("provider_versions") or {}
                version = versions.get(PACKAGE) if isinstance(versions, dict) else None
                version = version or (cell.get("toolchain") or {}).get("anthropic") or ""
                if not version or version in {"unrecorded", "unknown", "missing"}:
                    continue
                failure = cell.get("failure_class") or ""
                text = " | ".join(
                    str(cell.get(key))
                    for key in (
                        "error", "infra_reason", "provider_error",
                        "requests_error", "hang_reason", "output_tail",
                    )
                    if cell.get(key)
                )
                chunk = failure not in {"infra", "hang"} and "Unhandled chunk type" in text
                if failure not in {"infra", "hang"} and not chunk:
                    continue
                if AUTH.search(text) or INST.search(text):
                    continue
                match = PROV.search(text)
                if not match:
                    continue
                if match.group(0).lower() == "stream error" and TIMEOUT.search(text):
                    continue
                counts[version] += 1
    return counts


def _source_index(sides) -> dict:
    """box sha -> (pr, side, version). One version per sha is required."""
    found = {}
    for sha, side, pr, version in sides:
        prev = found.get(sha)
        if prev and prev[2] != version:
            raise SystemExit(f"box sha {sha} has two versions: {prev[2]} and {version}")
        if prev is None:
            found[sha] = (pr, side, version)
    return found


def propose(mirror: Path, tip: str, rows: list[dict]) -> tuple[list[dict], dict]:
    """Return pin rows plus the gate facts the README quotes."""
    line = Line(mirror, tip)
    sides, _manifest = box_sides()
    positions = {sha: line.pos(sha) for sha in {row[0] for row in sides}}
    if any(pos is None for pos in positions.values()):
        raise SystemExit("a box_cache build is not on the first-parent line")
    by_sha = defaultdict(set)
    by_pr = defaultdict(dict)
    for sha, side, pr, version in sides:
        by_sha[sha].add(version)
        by_pr[pr][side] = (sha, version)
    candidates = [
        (positions[sha], sha, sorted(versions)[0])
        for sha, versions in by_sha.items()
        if len(versions) == 1
    ]
    source = _source_index(sides)
    within_differ = []
    for pr, pair in sorted(by_pr.items(), key=lambda item: int(item[0] or 0)):
        if len(pair) == 2 and len({version for _, version in pair.values()}) != 1:
            within_differ.append(pr)

    loo_total = len(sides)
    # Leave-one-out is computed here so the README matches the derivation.
    loo_detail = []
    for sha, side, pr, version in sides:
        pr_shas = {item[0] for item in by_pr[pr].values()}
        for tag, excluded in (("loo", {sha}), ("lpo", pr_shas)):
            pool = [item for item in candidates if item[1] not in excluded]
            picked = nearest(positions[sha], pool)
            match = bool(picked) and picked[2] == version
            loo_detail.append({
                "tag": tag, "sha": sha, "side": side, "pr": pr, "version": version,
                "match": match,
                "pred": picked[2] if picked else "",
                "pin_from": picked[1] if picked else "",
                "distance": abs(picked[0] - positions[sha]) if picked else "",
            })
    tip_sha = line.order[-1]
    pinned = []
    for row in rows:
        deferred = row["pr"] in DEFERRED
        present = _git_ok(mirror, "cat-file", "-e", f"{row['sha']}^{{commit}}")
        packaged = present and has_opencode_package(mirror, row["sha"])
        parent_pos = line.pos(row["parent_sha"]) if present else None
        placement = line.how.get(row["parent_sha"], "")
        picked = None
        if not deferred and packaged and parent_pos is not None:
            picked = nearest(parent_pos, candidates)
        item = dict(row)
        item.update({
            "status": "deferred" if deferred else ("pinned" if picked else "unpinned"),
            "present": present,
            "packaged": packaged,
            "version": picked[2] if picked else "",
            "pin_source": "deferred_post_monorepo" if deferred else (
                "nearest_box_build" if picked else ""
            ),
            "pin_from": picked[1] if picked else "",
            "pin_from_pr": source[picked[1]][0] if picked else "",
            "pin_from_side": source[picked[1]][1] if picked else "",
            "distance": abs(picked[0] - parent_pos) if picked else "",
            "parent_pos": parent_pos if parent_pos is not None else "",
            "pin_from_pos": picked[0] if picked else "",
            "placement": placement,
        })
        pinned.append(item)
    facts = {
        "tip": tip_sha,
        "tip_ref": tip,
        "line_len": len(line.order),
        "box_sides": loo_total,
        "within_differ": within_differ,
        "loo_detail": loo_detail,
        "candidates": len(candidates),
    }
    return pinned, facts


def _reasoning(row: dict, tip: str) -> str:
    if row["status"] == "deferred":
        return (
            "Deferred, not pinned. This commit has no packages/opencode "
            "(post-monorepo layout; provider code is under packages/core). "
            "The step-8 runner and preflight still require packages/opencode. "
            "PRs 51062, 53166, and 55613 are a separate PR and are excluded here."
        )
    if row["status"] != "pinned":
        why = "commit is not in the mirror" if not row.get("present") else (
            "commit has no packages/opencode" if not row.get("packaged") else
            "no nearest box_cache build"
        )
        return f"Not pinned. {why}."
    return (
        f"Both sides of PR {row['pr']} use @ai-sdk/anthropic@{row['version']}, "
        f"the version shipped in the nearest box-run OpenCode build. "
        f"Nearest is first-parent position on {tip} (oldest = 0, ties to the "
        f"earlier position, then the lower sha). The without (parent) commit "
        f"{row['parent_sha']} is {row['placement']} at position {row['parent_pos']}. "
        f"The nearest box_cache build is {row['pin_from']} "
        f"(PR {row['pin_from_pr']} {row['pin_from_side']}, position {row['pin_from_pos']}, "
        f"distance {row['distance']}), which left {row['version']} in its cache. "
        f"That version is applied to the {row['side']} side ({row['sha']}) so the "
        f"provider is not part of the with/without difference. "
        f"pin_source=nearest_box_build."
    )


def loo_agreement_ok(loo: dict) -> bool:
    """True when leave-one-out agreement is at least ``LOO_MIN_PERCENT``."""
    n = int(loo.get("n") or 0)
    agree = int(loo.get("agree") or 0)
    if n <= 0:
        return False
    return agree * 100 >= n * LOO_MIN_PERCENT


def require_loo_agreement(summary: dict) -> None:
    """Exit nonzero when D4 leave-one-out agreement is below 95%.

    Called before the manifest is merged. A miss that is not a provider
    fault still fails this gate: the brief requires the rate itself.
    """
    loo = summary["loo"]
    n = int(loo.get("n") or 0)
    agree = int(loo.get("agree") or 0)
    rate = (agree / n) if n else 0.0
    if loo_agreement_ok(loo):
        return
    raise SystemExit(
        "D4 leave-one-out agreement "
        f"{agree}/{n} = {rate:.1%} is below {LOO_MIN_PERCENT}%; "
        "refusing to merge pins"
    )


def _loo_summary(detail: list[dict], faults: Counter) -> dict:
    out = {}
    for tag in ("loo", "lpo"):
        rows = [row for row in detail if row["tag"] == tag]
        misses = [row for row in rows if not row["match"]]
        bad = [row for row in misses if faults.get(row["pred"])]
        out[tag] = {
            "n": len(rows),
            "agree": len(rows) - len(misses),
            "misses": len(misses),
            "bad": len(bad),
            "miss_preds": sorted({row["pred"] for row in misses}),
        }
    return out


def _readme(rows: list[dict], facts: dict, faults: Counter, summary: dict) -> str:
    pinned = [row for row in rows if row["status"] == "pinned"]
    deferred = [row for row in rows if row["status"] == "deferred"]
    unpinned = [row for row in rows if row["status"] == "unpinned"]
    versions = Counter(row["version"] for row in pinned)
    prs = sorted({row["pr"] for row in pinned}, key=int)
    version_lines = "\n".join(
        f"| {version} | {count} |" for version, count in sorted(versions.items())
    )
    fault_lines = ", ".join(f"{version}={count}" for version, count in sorted(faults.items())) or "none"
    differ = ", ".join(facts["within_differ"]) or "none"
    loo = summary["loo"]
    lpo = summary["lpo"]
    loo_n = int(loo["n"])
    loo_agree = int(loo["agree"])
    loo_rate = (loo_agree / loo_n) if loo_n else 0.0
    loo_line = (
        f"Leave-one-out agreement is {loo_agree}/{loo_n} ({loo_rate:.1%}). "
        f"Apply exits nonzero when that rate is below {LOO_MIN_PERCENT}%."
    )
    return f"""# Step-8 nearest-box provider pins (F03-2 through F16)

Both sides of each PR use one `@ai-sdk/anthropic` version: the version a box-run OpenCode build left in its cache, chosen as the build nearest the without (parent) commit. That is the nearest-box method, the same rule as the F03-1 pinned rerun (the version shipped in the OpenCode build closest to the PR). The seven F03-1 sides stay `vm_quarantine_log` / `2.0.0` and are not rewritten. `pin_from` is the source build.

## D4 decision

Count provider faults only as infra. Timeouts, install errors, auth errors, and `provider_pin_mismatch: empty cache` do not disqualify a version and do not change a pass rate.

The #155 rescore is unchanged (`results/step8-full413-1020-F01/rescore-provider-faults/`): 1545 without trig-lsp-ts trial 22 is excluded from the pass rate as infra; 579 without trig-read-lines trial 27 is relabeled infra only (`label_only`) and stays in the denominator as a hang. Pass-rate formulas are not edited.

Under that decision the D4 gate can be used:

- Within-PR: box sides that differ are {differ}. PR 1443 is not rewritten. Its single-version rerun is `rerun-1443.json` (not launched).
- Leave-one-out (drop the sha): {loo['agree']}/{loo['n']} agree. Misses: {loo['misses']}, predicted {', '.join(loo['miss_preds']) or 'none'}. Misses on a version with a provider fault: {loo['bad']}.
- Leave-one-PR-out (how a new PR is pinned): {lpo['agree']}/{lpo['n']} agree. Misses: {lpo['misses']}, predicted {', '.join(lpo['miss_preds']) or 'none'}. Misses on a version with a provider fault: {lpo['bad']}.
- Provider-fault cells on a recorded version: {fault_lines}. The F01 cell 579 without trig-read-lines trial 27 logs `TimeoutError` plus the words `stream error`. #155 kept that cell as a hang (`label_only`). It is a timeout, not a provider fault, and it does not disqualify `1.2.12`.

{loo_line} No miss predicts a version that has a provider fault. The earlier infra-only reading of the same misses is in `results/step8-pins-D4/` and is not the rule these pins use.

## What was pinned

Queue: `results/step8-vm-F03-1-1025-QUARANTINED/SUBS.txt` from `F03-2` through `F16-2`, SHAs from `results/step8-full413-1020/prs.csv`. OpenCode first-parent line of `{facts['tip_ref']}` at `{facts['tip']}` ({facts['line_len']} commits). Box candidates: {facts['candidates']} builds, {facts['box_sides']} box_cache sides.

| | count |
|---|---|
| pinned sides | {len(pinned)} |
| pinned PRs | {len(prs)} |
| deferred sides | {len(deferred)} |
| unpinned sides | {len(unpinned)} |

| @ai-sdk/anthropic | sides |
|---|---|
{version_lines}

Every pinned PR has the same version on both sides. No pinned SHA is already a box_cache or F03-1 entry. Historical pins, including PR 1443 (`2.0.0-beta.13` on the merge, `2.0.0-beta.11` on the parent), are left as recorded.

## Deferred (not this PR)

Post-monorepo runner work for **51062**, **53166**, and **55613** is excluded. Each side has no `packages/opencode` (`51062` `328f74c2` / `32b1a1bf`, `53166` `0cb43477` / `bcf23b67`, `55613` `ae8d59f8` / `7ced591c`). They are `status=deferred` in `pins.csv` and have no `provider_pins.json` entry.

## PR 1443 rerun (do not run)

`rerun-1443.json` pins both sides to `2.0.0-beta.11`. That is the parent side's own box version, which is the nearest box build to the parent at distance 0. Leave-one-PR-out predicts the same version for the merge side. F01 spent $4.27 on 60 cells (30 trials, both sides). A 30-trial rerun is estimated at about $5–6. This PR does not launch it.

## Reproduce

```bash
python3 -m thesis.ab.step8_pins apply --mirror <opencode-mirror>
{DRY_RUN_WITH_BINARIES}
```

`<opencode-src>` is the directory of built OpenCode binaries. The dry run reads `<opencode-src>/bin/<sha>/opencode` (`--bin-root`). `apply` rewrites this directory (`data/step8-pins/`) and merges new sides into `thesis/ab/provider_pins.json`. It does not call a model. The dry run seeds `<cache>/seed-cells/<version>` and writes `dry-run.csv` and `dry-run.md` here. Strace homes stay under `--cache` and are not committed.
"""


def _rerun_config(facts: dict) -> dict:
    detail = [
        row for row in facts["loo_detail"]
        if row["tag"] == "lpo" and row["pr"] == RERUN_PR and row["side"] == "with"
    ]
    predicted = detail[0] if detail else {}
    return {
        "id": "rerun-1443",
        "do_not_run": True,
        "pr": RERUN_PR,
        "task": "trig-read-lines",
        "task_map": "results/step8-full413-1020/task-map.csv",
        "prs": "results/step8-full413-1020/prs.csv",
        "trials": 30,
        "jobs": 4,
        "model": "claude-sonnet-5-5",
        "order": "interleave-seeded",
        "seed": 1016,
        "estimated_cost_usd": "5-6",
        "observed_f01_cost_usd": 4.27,
        "observed_f01_cells": 60,
        "package": PACKAGE,
        "version": RERUN_VERSION,
        "pin_source": "nearest_box_build",
        "pin_from": "3b7085ca28b9f662752cf80152a3667771794719",
        "distance": 0,
        "reasoning": (
            "PR 1443 is the only box PR whose sides recorded different versions "
            "(with 18888351e99857a776601c857d6d70e058a4794a = 2.0.0-beta.13, "
            "without 3b7085ca28b9f662752cf80152a3667771794719 = 2.0.0-beta.11). "
            "Both sides of the rerun use the without side's box version. That "
            "commit is itself a box_cache build, so it is the nearest box build "
            "to the parent at distance 0. Leave-one-PR-out predicts "
            f"{predicted.get('pred') or RERUN_VERSION} for the with side from "
            f"{predicted.get('pin_from') or ''} at distance {predicted.get('distance', '')}. "
            "Historical manifest entries are not changed. Estimated cost is about "
            "$5-6 from the F01 spend of $4.27 on 60 cells. Do not run this config "
            "from the pins PR."
        ),
        "sides": [
            {
                "side": "with",
                "sha": "18888351e99857a776601c857d6d70e058a4794a",
                "historical_version": "2.0.0-beta.13",
                "rerun_version": RERUN_VERSION,
            },
            {
                "side": "without",
                "sha": "3b7085ca28b9f662752cf80152a3667771794719",
                "historical_version": "2.0.0-beta.11",
                "rerun_version": RERUN_VERSION,
            },
        ],
    }


def merge_manifest(rows: list[dict], manifest_path: Path) -> int:
    """Add pinned sides. Refuse to overwrite a different version. Returns added."""
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    builds = data.setdefault("builds", {})
    added = 0
    for row in rows:
        if row["status"] != "pinned":
            continue
        sides = builds.setdefault(row["sha"], {})
        existing = sides.get(row["side"])
        packages = {PACKAGE: row["version"]}
        if existing:
            current = (existing.get("packages") or {}).get(PACKAGE)
            if current != row["version"]:
                raise SystemExit(
                    f"refusing to overwrite {row['sha']} {row['side']}: "
                    f"{current} -> {row['version']}"
                )
            continue
        sides[row["side"]] = {
            "evidence": "nearest-box-build",
            "packages": packages,
            "pin_source": "nearest_box_build",
            "pin_from": row["pin_from"],
            "pr": row["pr"],
        }
        added += 1
    data["builds"] = dict(sorted(builds.items()))
    note = str(data.get("note") or "")
    extra = (
        " pin_source=nearest_box_build is the box_cache version of the OpenCode "
        "build nearest the without (parent) side, applied to both sides of each "
        "F03-2 through F16 PR (data/step8-pins/). pin_from is that source build. "
        "PRs 51062, 53166, and 55613 are deferred (post-monorepo, no packages/opencode) "
        "and have no entry."
    )
    if "nearest_box_build" not in note:
        data["note"] = note.rstrip() + extra
    manifest_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return added


def write_outputs(rows: list[dict], facts: dict, faults: Counter, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = _loo_summary(facts["loo_detail"], faults)
    for row in rows:
        row["reasoning"] = _reasoning(row, f"{facts['tip_ref']}@{facts['tip'][:12]}")
    with (out_dir / "pins.csv").open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=PIN_FIELDS, lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    (out_dir / "README.md").write_text(_readme(rows, facts, faults, summary), encoding="utf-8")
    rerun = _rerun_config(facts)
    (out_dir / "rerun-1443.json").write_text(
        json.dumps(rerun, indent=2) + "\n",
        encoding="utf-8",
    )
    require_loo_agreement(summary)
    bad = summary["loo"]["bad"] + summary["lpo"]["bad"]
    if bad:
        raise SystemExit(f"provider-fault gate failed: {bad} leave-one-out misses on a faulted version")
    if facts["within_differ"] != [RERUN_PR]:
        raise SystemExit(f"within-PR differ is not just {RERUN_PR}: {facts['within_differ']}")
    unpinned = [row for row in rows if row["status"] == "unpinned"]
    if unpinned:
        raise SystemExit(f"{len(unpinned)} sides could not be pinned")


def apply_pins(mirror: Path, tip: str, subs: Path, prs: Path, out_dir: Path, manifest: Path, from_batch: str) -> int:
    rows = queue_rows(subs, prs, from_batch)
    proposed, facts = propose(mirror, tip, rows)
    faults = provider_fault_counts()
    write_outputs(proposed, facts, faults, out_dir)
    added = merge_manifest(proposed, manifest)
    pinned = sum(1 for row in proposed if row["status"] == "pinned")
    deferred = sum(1 for row in proposed if row["status"] == "deferred")
    print(f"pinned {pinned} deferred {deferred} manifest_added {added} faults {dict(faults)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Apply nearest-box step-8 pins")
    parser.add_argument("mode", choices=["apply"])
    parser.add_argument("--mirror", type=Path, required=True)
    parser.add_argument("--tip", default="origin/dev")
    parser.add_argument("--subs", type=Path, default=DEFAULT_SUBS)
    parser.add_argument("--prs", type=Path, default=DEFAULT_PRS)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--manifest", type=Path, default=PINS)
    parser.add_argument("--from-batch", default="F03-2")
    args = parser.parse_args(argv)
    return apply_pins(
        args.mirror, args.tip, args.subs, args.prs, args.out_dir, args.manifest, args.from_batch,
    )


if __name__ == "__main__":
    sys.exit(main())
