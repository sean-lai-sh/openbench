#!/usr/bin/env python3
"""Dry-run F03-2..F16 pins and the PR 1443 rerun. No model calls.

Loads every pinned side plus ``rerun-1443.json``, resolves the pin, seeds the
shared provider cache once per version, and checks that the OpenCode binary
for that SHA is present. When the binary is present and ``strace`` can see an
``openat`` of ``node_modules/@ai-sdk/anthropic``, the loaded version is
compared to the pin (the PR #156 path). The trace uses the seeded cache
(``<cache>/seed-cells/<version>``) via ``HOME`` and ``XDG_CACHE_HOME``, not
the caller's home. A missing binary is not ready. An unproven load (binary
present, no open of the package) is recorded and does not by itself fail the
side.

The six post-monorepo sides (51062, 53166, 55613) stay ``deferred`` in
``dry-run.csv``, which keeps the #160 columns and format. They are also
assessed on the provider-free path (``thesis/ab/monorepo.py``) and written to
their own table, ``dry-run-monorepo.csv`` (``--monorepo-out``), keyed by side
(``side_key`` = ``<pr>:<side>``), with four more columns: ``provider_mode``,
``bundled_provider``, ``scoring_parity``, ``scorable``. Ready needs the monorepo layout, the bundled ``@opencode/ai``
(from ``<bin-root>/worktrees/<sha>``, ``--mirror``, or ``<bin-root>/mirror``),
the binary, the build gate (``monorepo-builds.csv``: control step passed and
the binary's sha256 matches its record), and a strace check that opens no
``node_modules/@ai-sdk/anthropic``. The three PRs are scorable together or
not at all: every side ready, all six cells in ``monorepo-smoke.csv`` with a
bundled load and zero provider faults, and ``scoring_parity`` passing
(``scoring-parity.csv``: the box's saved outputs for two PRs it scored,
replayed through this runner's scoring path, reproduce the box's pass/fail on
100% of cells). Otherwise every side is ``scorable=excluded``. All of it is
recomputed here from those tables.
``--monorepo-only`` writes only that table and needs neither bun nor a seeded
cache. See ``data/step8-pins/MONOREPO.md``.

  python3 -m thesis.ab.step8_pin_dry_run --cache /tmp/step8-pin-cache --bin-root <opencode-src>

``<opencode-src>`` is the directory of built OpenCode binaries
(``<opencode-src>/bin/<sha>/opencode``). Writes ``data/step8-pins/dry-run.csv``.
The seeded cache and strace homes stay under ``--cache`` and are not committed.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from thesis.ab.build_opencode import can_exec, ensure_bun
from thesis.ab.monorepo import (
    LOADED_SOURCE,
    MONOREPO_PRS,
    bundled_label,
    bundled_provider_at,
    bundled_provider_for_tree,
    bundled_reason,
    layout_at,
    layout_of_tree,
)
from thesis.ab.provider_pin import (
    load_manifest,
    lookup_entry,
    mismatch_reason,
    pin_sha256,
    seed_cell_cache,
)
from thesis.ab.step8_monorepo_build import DEFAULT_BUILDS_CSV, build_gate_reason, load_records
from thesis.ab.step8_monorepo_smoke import (
    DEFAULT_SMOKE_CSV,
    load_smoke,
    group_decision,
)
from thesis.ab.step8_scoring_parity import DEFAULT_PARITY_CSV, default_parity_from_table
from thesis.ab.step8_pins import DEFAULT_OUT, DRY_RUN_WITH_BINARIES, PACKAGE, RERUN_PR

ROOT = Path(__file__).resolve().parents[2]
TRACE_OPEN_RE = re.compile(r'openat\([^,]*,\s*"((?:\\.|[^"\\])*)"')
ANTHROPIC_OPEN_MARKER = "node_modules/@ai-sdk/anthropic"
FIELDS = [
    "group", "batch", "pr", "side", "sha", "version", "pin_resolved",
    "cache_seeded", "binary_present", "binary_path", "loaded_check",
    "loaded_version", "loaded_source", "ready", "reason",
]
# dry-run-monorepo.csv only, one row per side keyed by side_key. dry-run.csv keeps FIELDS.
MONOREPO_FIELDS = ["side_key"] + FIELDS + ["provider_mode", "bundled_provider", "scoring_parity", "scorable"]
MONOREPO_GROUP = "monorepo"
DEFAULT_MONOREPO_OUT = DEFAULT_OUT / "dry-run-monorepo.csv"


def version_from_trace_line(line: str) -> str:
    """Version from one strace ``openat`` line, or ``""``.

    The first path under ``node_modules/@ai-sdk/anthropic`` whose
    ``package.json`` has a version wins. A truncated path is ignored. This
    matches the PR #156 parser.
    """
    match = TRACE_OPEN_RE.search(line or "")
    if not match:
        return ""
    try:
        raw = bytes(match.group(1), "utf-8").decode("unicode_escape")
    except UnicodeError:
        raw = match.group(1)
    if raw.endswith("..."):
        return ""
    index = raw.find(ANTHROPIC_OPEN_MARKER)
    if index < 0:
        return ""
    root = raw[: index + len(ANTHROPIC_OPEN_MARKER)]
    package = Path(root) / "package.json"
    if not package.is_file():
        return ""
    try:
        parsed = json.loads(package.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    if not isinstance(parsed, dict):
        return ""
    return str(parsed.get("version") or "")


def version_from_trace(text: str) -> str:
    for line in (text or "").splitlines():
        found = version_from_trace_line(line)
        if found:
            return found
    return ""


def seeded_cell_cache(cache: Path, version: str) -> Path:
    """Directory ``seed_cell_cache`` fills for one provider version."""
    return Path(cache) / "seed-cells" / version


def provider_cache_env(seed_cache: Path, home: Path) -> dict:
    """Environment for one loaded-version trace.

    The runner keeps provider packages at ``$XDG_CACHE_HOME/opencode``
    (``obench.adapters.opencode``). ``seed_cache`` is that tree
    (``<cache>/seed-cells/<version>``). ``HOME`` is ``home``, an isolated
    directory, never the caller's home. ``$HOME/.cache/opencode`` is a
    symlink to ``seed_cache``, and ``XDG_CACHE_HOME`` is ``$HOME/.cache``.
    """
    seed_cache = Path(seed_cache)
    home = Path(home)
    xdg_cache = home / ".cache"
    xdg_config = home / ".config"
    xdg_data = home / ".local" / "share"
    xdg_state = home / ".local" / "state"
    for path in (home, xdg_cache, xdg_config, xdg_data, xdg_state):
        path.mkdir(parents=True, exist_ok=True)
    link = xdg_cache / "opencode"
    target = seed_cache.resolve()
    if link.is_symlink() or link.exists():
        current = link.resolve() if link.exists() else None
        if current != target:
            if link.is_symlink() or link.is_file():
                link.unlink()
            else:
                shutil.rmtree(link)
            link.symlink_to(target, target_is_directory=True)
    else:
        link.symlink_to(target, target_is_directory=True)
    env = dict(os.environ)
    env["HOME"] = str(home)
    env["XDG_CONFIG_HOME"] = str(xdg_config)
    env["XDG_DATA_HOME"] = str(xdg_data)
    env["XDG_STATE_HOME"] = str(xdg_state)
    env["XDG_CACHE_HOME"] = str(xdg_cache)
    for name in ("OPENCODE_CONFIG", "OPENCODE_CONFIG_DIR", "OPENCODE_CONFIG_CONTENT"):
        env.pop(name, None)
    return env


def trace_cache_path(env: dict) -> Path:
    """OpenCode cache directory the trace is pointed at."""
    return Path(env["XDG_CACHE_HOME"]) / "opencode"


def trace_binary(binary: Path, trace_path: Path, seed_cache: Path) -> tuple[str, str]:
    """Run ``strace -e openat`` on ``binary --version``. No model call.

    ``seed_cache`` is the seeded provider tree for this side's version.
    The subprocess ``HOME`` and ``XDG_CACHE_HOME`` point at that tree.
    The seeded path is printed before the trace runs.

    Returns ``(version, source)``. ``source`` is ``strace`` when an open
    resolved a version, ``none`` when the trace has no such open, and
    ``skipped`` when strace cannot be run.
    """
    seed_cache = Path(seed_cache)
    home = trace_path.with_suffix(".home")
    env = provider_cache_env(seed_cache, home)
    print(
        f"strace loaded-version cache: {seed_cache.resolve()} "
        f"(HOME={env['HOME']} XDG_CACHE_HOME={env['XDG_CACHE_HOME']})",
        flush=True,
    )
    strace = shutil.which("strace") or ""
    if not strace:
        return "", "skipped"
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            [strace, "-f", "-qq", "-e", "trace=openat", "-o", str(trace_path), "--",
             str(binary), "--version"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=30,
            check=False,
            env=env,
            cwd=str(home),
        )
    except (OSError, subprocess.SubprocessError):
        return "", "skipped"
    try:
        text = trace_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "", "skipped"
    version = version_from_trace(text)
    if version:
        return version, "strace"
    return "", "none"


def binary_path(bin_root: Path, sha: str) -> Path:
    return Path(bin_root) / "bin" / sha / "opencode"


def _load_rows(pins_csv: Path, rerun_path: Path) -> list[dict]:
    rows = []
    for row in csv.DictReader(open(pins_csv, newline="")):
        item = dict(row)
        item["group"] = "F03-2-F16"
        rows.append(item)
    rerun = json.loads(rerun_path.read_text(encoding="utf-8"))
    if str(rerun.get("pr")) != RERUN_PR:
        raise SystemExit(f"rerun config is not PR {RERUN_PR}")
    if not rerun.get("do_not_run"):
        raise SystemExit("rerun-1443.json must set do_not_run")
    version = str(rerun.get("version") or "")
    for side in rerun.get("sides") or []:
        rows.append({
            "group": "rerun-1443",
            "batch": "rerun-1443",
            "pr": RERUN_PR,
            "side": side["side"],
            "sha": side["sha"],
            "version": version,
            "status": "rerun",
            "pin_source": rerun.get("pin_source") or "",
            "pin_from": rerun.get("pin_from") or "",
        })
    return rows


def resolve_pin(row: dict, manifest: dict) -> tuple[str, str]:
    """Return ``(version, reason)``. A deferred row does not resolve."""
    if row.get("status") == "deferred":
        return "", "deferred post-monorepo; excluded from this pin set"
    if row.get("group") == "rerun-1443":
        version = str(row.get("version") or "")
        if not version:
            return "", "rerun config has no version"
        # The historical with-side pin is a different version. The rerun
        # config is the pin for both sides; the manifest is only a check
        # that the parent side still records this version.
        if row.get("side") == "without":
            found = lookup_entry(row["sha"], "without", RERUN_PR, manifest)
            recorded = ""
            if found:
                recorded = str(found["packages"].get(PACKAGE) or "")
            if recorded and recorded != version:
                return "", f"rerun version {version} != manifest {recorded}"
        return version, ""
    found = lookup_entry(str(row.get("sha") or ""), str(row.get("side") or ""), str(row.get("pr") or ""), manifest)
    if not found:
        return "", "pin not in manifest"
    version = str(found["packages"].get(PACKAGE) or "")
    wanted = str(row.get("version") or "")
    if wanted and version != wanted:
        return "", f"manifest {version} != table {wanted}"
    if str((found.get("entry") or {}).get("pin_source") or "") != "nearest_box_build":
        return "", "manifest pin_source is not nearest_box_build"
    return version, ""


def assess_row(
    row: dict,
    *,
    version: str,
    resolve_reason: str,
    cache_seeded: bool,
    seed_reason: str,
    binary: Path,
    loaded_version: str = "",
    loaded_source: str = "",
) -> dict:
    """One readiness row. Ready needs a resolved pin, a seeded cache, and a binary.

    The loaded-version check fails the side only when it runs and disagrees
    with the pin. ``skipped`` and ``none`` are recorded; they are the
    "where possible" case from PR #156 (warn-only when the process never
    opened the package).
    """
    reasons = []
    if row.get("status") == "deferred":
        reasons.append("deferred post-monorepo; not pinned and not seeded")
    elif resolve_reason:
        reasons.append(resolve_reason)
    elif not version:
        reasons.append("pin not resolved")
    if row.get("status") != "deferred":
        if not cache_seeded:
            reasons.append(seed_reason or "cache was not seeded")
        present = binary.is_file() and can_exec(binary)
        if not present:
            reasons.append(f"opencode binary missing at {binary}")
            loaded_source = loaded_source or "skipped"
            loaded_check = "skipped"
        elif loaded_source == "skipped":
            loaded_check = "skipped"
        elif loaded_source == "none" or not loaded_version:
            loaded_check = "unproven"
            loaded_source = loaded_source or "none"
        elif loaded_version != version:
            loaded_check = "mismatch"
            reasons.append(
                f"loaded {loaded_version} != pin {version} (strace openat)"
            )
        else:
            loaded_check = "pass"
    else:
        present = False
        loaded_check = "skipped"
        loaded_source = "skipped"
    return {
        "group": row.get("group") or "",
        "batch": row.get("batch") or "",
        "pr": row.get("pr") or "",
        "side": row.get("side") or "",
        "sha": row.get("sha") or "",
        "version": version,
        "pin_resolved": "no" if (resolve_reason or not version or row.get("status") == "deferred") else "yes",
        "cache_seeded": "yes" if cache_seeded and row.get("status") != "deferred" else "no",
        "binary_present": "yes" if present else "no",
        "binary_path": str(binary),
        "loaded_check": loaded_check,
        "loaded_version": loaded_version,
        "loaded_source": loaded_source,
        "ready": "yes" if not reasons else "no",
        "reason": "; ".join(reasons),
    }


def locate_monorepo(sha: str, *, bin_root: Path, mirror: Path | None) -> tuple[str, dict | None, str]:
    """``(layout, bundled provider, where)`` for one monorepo side.

    The build worktree (``<bin-root>/worktrees/<sha>``) wins, then
    ``--mirror``, then ``<bin-root>/mirror``. ``where`` is ``""`` when none
    of those has the commit.
    """
    worktree = Path(bin_root) / "worktrees" / sha
    layout = layout_of_tree(worktree)
    if layout != "missing":
        provider = bundled_provider_for_tree(worktree) if layout == "monorepo" else None
        return layout, provider, "worktree"
    for repo, where in ((mirror, "mirror"), (Path(bin_root) / "mirror", "bin-root mirror")):
        if repo is None or not Path(repo).exists():
            continue
        layout = layout_at(Path(repo), sha)
        if layout == "missing":
            continue
        provider = bundled_provider_at(Path(repo), sha) if layout == "monorepo" else None
        return layout, provider, where
    return "missing", None, ""


def assess_monorepo_row(
    row: dict,
    *,
    layout: str,
    provider: dict | None,
    binary: Path,
    loaded_version: str = "",
    loaded_source: str = "",
    build_reason: str = "",
) -> dict:
    """One readiness row for a provider-free monorepo side.

    Ready needs the monorepo layout, a bundled provider, and a runnable
    binary. The strace check fails the side when the binary opens a
    separately installed ``@ai-sdk/anthropic``. ``build_reason`` is the
    build gate (``step8_monorepo_build.build_gate_reason``); non-empty is not
    ready. ``scoring_parity`` and ``scorable`` are set for all six sides at
    once by ``apply_monorepo_gate``.
    """
    reasons = []
    why = bundled_reason(layout, provider)
    if why:
        reasons.append(f"monorepo: {why}")
    present = binary.is_file() and can_exec(binary)
    if not present:
        reasons.append(f"opencode binary missing at {binary}")
        loaded_check = "skipped"
        loaded_source = "skipped"
    elif loaded_source == "skipped":
        loaded_check = "skipped"
    elif loaded_version:
        loaded_check = "mismatch"
        loaded_source = "separate_install"
        reasons.append(
            f"binary opened {PACKAGE}@{loaded_version}; expected the bundled provider (strace openat)"
        )
    else:
        loaded_check = "pass"
        loaded_source = LOADED_SOURCE
    if present and build_reason:
        reasons.append(f"build gate: {build_reason}")
    ready = not reasons
    return {
        "side_key": f"{row.get('pr') or ''}:{row.get('side') or ''}",
        "group": MONOREPO_GROUP,
        "batch": row.get("batch") or "",
        "pr": row.get("pr") or "",
        "side": row.get("side") or "",
        "sha": row.get("sha") or "",
        "version": "",
        "pin_resolved": "bundled" if provider else "no",
        "cache_seeded": "n/a",
        "binary_present": "yes" if present else "no",
        "binary_path": str(binary),
        "loaded_check": loaded_check,
        "loaded_version": loaded_version,
        "loaded_source": loaded_source,
        "ready": "yes" if ready else "no",
        "reason": "; ".join(reasons),
        "provider_mode": "bundled",
        "bundled_provider": bundled_label(provider),
        "scoring_parity": "",
        "scorable": "excluded",
        "_provider": provider,
        "_scorable_reason": "",
    }


def check_pr_providers(rows: list[dict]) -> None:
    """Both sides of a monorepo PR must bundle the same ``packages/ai/src``.

    Otherwise the provider would be part of the with/without difference.
    Mutates the rows in place.
    """
    by_pr: dict[str, list[dict]] = {}
    for row in rows:
        by_pr.setdefault(row["pr"], []).append(row)
    for pr_rows in by_pr.values():
        providers = [row.get("_provider") for row in pr_rows]
        if len(pr_rows) != 2 or not all(providers):
            continue
        keys = {(item["version"], item.get("tree") or "") for item in providers}
        if len(keys) == 1:
            continue
        labels = " vs ".join(bundled_label(item) for item in providers)
        for row in pr_rows:
            reason = f"bundled provider differs between sides ({labels})"
            row["reason"] = "; ".join(part for part in (row["reason"], reason) if part)
            row["ready"] = "no"


def apply_monorepo_gate(
    rows: list[dict],
    smoke: dict[tuple[str, str], dict],
    parity: tuple[bool, str],
) -> list[dict]:
    """All-or-nothing ``scorable`` for the three PRs (D5 §4).

    ``yes`` for every side only when every side is ready, all six smoke cells
    loaded the bundled provider with zero provider faults, and
    ``scoring_parity`` passes. Otherwise every side is ``excluded``.
    """
    sides = [{"pr": row["pr"], "side": row["side"]} for row in rows]
    ok, reasons = group_decision(smoke, sides, parity)
    not_ready = [f"{row['pr']} {row['side']} not ready" for row in rows if row["ready"] != "yes"]
    reasons = not_ready + reasons
    for row in rows:
        row["scoring_parity"] = "pass" if parity[0] else "fail"
        row["scorable"] = "yes" if ok and not not_ready else "excluded"
        row["_scorable_reason"] = "; ".join(reasons)
    return rows


def run_monorepo(
    rows: list[dict],
    *,
    cache: Path,
    bin_root: Path,
    mirror: Path | None,
    smoke_csv: Path,
    builds_csv: Path = DEFAULT_BUILDS_CSV,
    parity_csv: Path = DEFAULT_PARITY_CSV,
) -> list[dict]:
    """Assess the monorepo rows. No bun, no seeding, no model call."""
    smoke = load_smoke(smoke_csv)
    records = load_records(builds_csv)
    out = []
    for row in rows:
        sha = str(row.get("sha") or "")
        layout, provider, _where = locate_monorepo(sha, bin_root=bin_root, mirror=mirror)
        binary = binary_path(bin_root, sha)
        loaded_version = ""
        loaded_source = ""
        if binary.is_file() and can_exec(binary):
            # An empty provider cache: a bundled binary has nothing to open.
            empty = Path(cache) / "monorepo-empty-provider"
            empty.mkdir(parents=True, exist_ok=True)
            loaded_version, loaded_source = trace_binary(
                binary,
                Path(cache) / "traces" / f"{sha}-{row['side']}.trace",
                empty,
            )
        out.append(assess_monorepo_row(
            row,
            layout=layout,
            provider=provider,
            binary=binary,
            loaded_version=loaded_version,
            loaded_source=loaded_source,
            build_reason=build_gate_reason(records, sha, binary),
        ))
    check_pr_providers(out)
    return apply_monorepo_gate(out, smoke, default_parity_from_table(parity_csv))


def monorepo_rows(pins_csv: Path, rerun_path: Path) -> list[dict]:
    """The six monorepo sides from ``pins.csv``, in table order."""
    return [row for row in _load_rows(pins_csv, rerun_path) if row.get("pr") in MONOREPO_PRS]


def write_monorepo_csv(rows: list[dict], out_csv: Path) -> None:
    keys = [row.get("side_key") for row in rows]
    if len(set(keys)) != len(keys) or not all(keys):
        raise SystemExit(f"dry-run-monorepo.csv needs one row per side, got {keys}")
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=MONOREPO_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows({key: row.get(key, "") for key in MONOREPO_FIELDS} for row in rows)


def refresh_monorepo(
    pins_csv: Path,
    rerun_path: Path,
    out_csv: Path,
    *,
    cache: Path,
    bin_root: Path,
    mirror: Path | None,
    smoke_csv: Path = DEFAULT_SMOKE_CSV,
    builds_csv: Path = DEFAULT_BUILDS_CSV,
    parity_csv: Path = DEFAULT_PARITY_CSV,
) -> list[dict]:
    """Assess only the monorepo rows and write them to ``out_csv``.

    ``out_csv`` is its own table (default ``dry-run-monorepo.csv``).
    ``dry-run.csv`` and ``dry-run.md`` are not read or written.
    """
    rows = run_monorepo(
        monorepo_rows(pins_csv, rerun_path),
        cache=cache, bin_root=bin_root, mirror=mirror, smoke_csv=smoke_csv,
        builds_csv=builds_csv, parity_csv=parity_csv,
    )
    write_monorepo_csv(rows, out_csv)
    return rows


def summarize_monorepo(rows: list[dict]) -> str:
    scorable = sum(1 for row in rows if row.get("scorable") == "yes")
    ready = sum(1 for row in rows if row["ready"] == "yes")
    lines = [f"monorepo sides {len(rows)} ready {ready} scorable {scorable}"]
    for row in rows:
        status = "ready" if row["ready"] == "yes" else f"not ready: {row['reason']}"
        lines.append(
            f"  {row['pr']} {row['side']:<7} {row['sha'][:8]} "
            f"{row.get('bundled_provider') or 'bundled provider unknown'}; {status}; "
            f"scorable={row.get('scorable') or 'excluded'}"
        )
    if rows:
        lines.append(f"scoring_parity {rows[0].get('scoring_parity') or 'fail'}; "
                     f"scorable {rows[0].get('scorable')}"
                     + (f" ({rows[0]['_scorable_reason']})" if rows[0].get("_scorable_reason") else ""))
    return "\n".join(lines)


def seed_versions(versions: list[str], cache: Path, bun: str) -> dict[str, str]:
    """Install each version once under ``cache/provider-pins``. Empty reason is success."""
    store = cache / "provider-pins"
    reasons = {}
    for version in versions:
        cell = seeded_cell_cache(cache, version)
        reason = seed_cell_cache(cell, store, {PACKAGE: version}, bun)
        if reason:
            reasons[version] = reason
            continue
        # The shared template is what later cells copy. Confirm it, not only the cell.
        template = store / pin_sha256({PACKAGE: version})
        reasons[version] = mismatch_reason(template, {PACKAGE: version})
    return reasons


def run_dry(pins_csv: Path, rerun_path: Path, cache: Path, bin_root: Path, bun: str, out_csv: Path) -> list[dict]:
    manifest = load_manifest()
    # Drop a stale in-process cache if apply just rewrote the file.
    import thesis.ab.provider_pin as provider_pin
    provider_pin._MANIFEST = None
    manifest = load_manifest()
    rows = _load_rows(pins_csv, rerun_path)
    resolved = []
    for row in rows:
        version, reason = resolve_pin(row, manifest)
        resolved.append((row, version, reason))
    versions = sorted({version for _row, version, reason in resolved if version and not reason})
    seeded = seed_versions(versions, cache, bun) if versions else {}
    out_rows = []
    for row, version, reason in resolved:
        binary = binary_path(bin_root, row["sha"])
        seed_reason = seeded.get(version, "version was not seeded") if version else "version was not seeded"
        cache_ok = bool(version) and not reason and seed_reason == ""
        loaded_version = ""
        loaded_source = ""
        if row.get("status") != "deferred" and version and binary.is_file() and can_exec(binary):
            loaded_version, loaded_source = trace_binary(
                binary,
                cache / "traces" / f"{row['sha']}-{row['side']}.trace",
                seeded_cell_cache(cache, version),
            )
        out_rows.append(assess_row(
            row,
            version=version,
            resolve_reason=reason,
            cache_seeded=cache_ok,
            seed_reason=seed_reason,
            binary=binary,
            loaded_version=loaded_version,
            loaded_source=loaded_source,
        ))
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(out_rows)
    return out_rows


def _reason_bucket(reason: str) -> str:
    if reason.startswith("deferred"):
        return "deferred post-monorepo; not pinned and not seeded"
    if "opencode binary missing" in reason and reason.startswith("opencode binary missing"):
        return "opencode binary missing (loaded-version check skipped; no binary to strace)"
    return reason


def summarize(rows: list[dict]) -> str:
    ready = [row for row in rows if row["ready"] == "yes"]
    not_ready = [row for row in rows if row["ready"] != "yes"]
    buckets: dict[str, int] = {}
    for row in not_ready:
        key = _reason_bucket(row["reason"])
        buckets[key] = buckets.get(key, 0) + 1
    lines = [
        f"sides {len(rows)} ready {len(ready)} not-ready {len(not_ready)}",
    ]
    for reason, count in sorted(buckets.items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"  {count} {reason}")
    return "\n".join(lines)


def write_summary(rows: list[dict], path: Path) -> None:
    """Short counts next to dry-run.csv. The per-side reasons stay in the CSV."""
    text = summarize(rows)
    seeded = sorted({row["version"] for row in rows if row["cache_seeded"] == "yes"})
    body = f"""# Step-8 pin dry run

No model calls and no GCP. Each F03-2..F16 side and both sides of `rerun-1443.json` were loaded. Pins were resolved from `provider_pins.json` (the 1443 rerun uses the single version in that config). The shared cache was seeded once per version with `bun add --exact` under `<cache>/seed-cells/<version>`. The OpenCode binary check is `<bin-root>/bin/<sha>/opencode` (`--bin-root`, default `results/opencode-src`). The loaded-version check is the PR #156 strace `openat` of `node_modules/@ai-sdk/anthropic`. It runs only when that binary is present. The trace sets `HOME` to a directory under `<cache>/traces/` and points `$XDG_CACHE_HOME/opencode` at `<cache>/seed-cells/<version>`, not the caller's home. That seeded path is printed as `strace loaded-version cache: ...`.

On a machine that has the built binaries:

```bash
{DRY_RUN_WITH_BINARIES}
```

`<opencode-src>` is the directory that contains `bin/<sha>/opencode`.

```
{text}
```

Cache seeded for: {', '.join(f'`{version}`' for version in seeded) or 'none'}.

Not ready because the OpenCode binaries for these SHAs are not built in this checkout. The pin resolved and the cache holds that version, so the remaining gap is the binary. Deferred rows (51062, 53166, 55613) were not pinned and were not seeded. Per-side paths are in `dry-run.csv`.
"""
    path.write_text(body, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Dry-run step-8 nearest-box pins")
    parser.add_argument("--pins", type=Path, default=DEFAULT_OUT / "pins.csv")
    parser.add_argument("--rerun", type=Path, default=DEFAULT_OUT / "rerun-1443.json")
    parser.add_argument("--cache", type=Path, default=Path("/tmp/step8-pin-cache"))
    parser.add_argument(
        "--bin-root",
        type=Path,
        default=ROOT / "results" / "opencode-src",
        help="directory of built OpenCode binaries; reads <bin-root>/bin/<sha>/opencode",
    )
    parser.add_argument("--bun-version", default="1.2.21")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT / "dry-run.csv")
    parser.add_argument(
        "--mirror",
        type=Path,
        default=None,
        help="OpenCode git mirror for the monorepo layout check (default <bin-root>/mirror)",
    )
    parser.add_argument("--builds", type=Path, default=DEFAULT_BUILDS_CSV,
                        help="monorepo build records; a monorepo binary is used only with a passed control step")
    parser.add_argument("--smoke", type=Path, default=DEFAULT_SMOKE_CSV,
                        help="monorepo smoke report; a monorepo side is scorable only from it")
    parser.add_argument("--parity", type=Path, default=DEFAULT_PARITY_CSV,
                        help="scoring parity table (thesis.ab.step8_scoring_parity)")
    parser.add_argument("--monorepo-out", type=Path, default=DEFAULT_MONOREPO_OUT,
                        help="table for the 51062/53166/55613 sides (dry-run.csv keeps them deferred)")
    parser.add_argument(
        "--monorepo-only",
        action="store_true",
        help="write only --monorepo-out; no bun, no seeding; dry-run.csv and dry-run.md are not touched",
    )
    args = parser.parse_args(argv)
    mono = refresh_monorepo(
        args.pins, args.rerun, args.monorepo_out,
        cache=args.cache, bin_root=args.bin_root, mirror=args.mirror,
        smoke_csv=args.smoke, builds_csv=args.builds, parity_csv=args.parity,
    )
    if args.monorepo_only:
        print(summarize_monorepo(mono))
        print(f"wrote {args.monorepo_out}")
        return 0
    bun = str(ensure_bun(args.bun_version, args.cache))
    rows = run_dry(args.pins, args.rerun, args.cache, args.bin_root, bun, args.out)
    print(summarize(rows))
    summary = args.out.with_name("dry-run.md")
    write_summary(rows, summary)
    print(f"wrote {args.out}")
    print(f"wrote {summary}")
    print(summarize_monorepo(mono))
    print(f"wrote {args.monorepo_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
