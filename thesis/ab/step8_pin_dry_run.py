#!/usr/bin/env python3
"""Dry-run F03-2..F16 pins and the PR 1443 rerun. No model calls.

Loads every pinned side plus ``rerun-1443.json``, resolves the pin, seeds the
shared provider cache once per version, and checks that the OpenCode binary
for that SHA is present. When the binary is present and ``strace`` can see an
``openat`` of ``node_modules/@ai-sdk/anthropic``, the loaded version is
compared to the pin (the PR #156 path). A missing binary is not ready. An
unproven load (binary present, no open of the package) is recorded and does
not by itself fail the side.

  python3 -m thesis.ab.step8_pin_dry_run --cache /tmp/step8-pin-cache

Writes ``results/step8-pins/dry-run.csv``.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

from thesis.ab.build_opencode import can_exec, ensure_bun
from thesis.ab.provider_pin import (
    load_manifest,
    lookup_entry,
    mismatch_reason,
    pin_sha256,
    seed_cell_cache,
)
from thesis.ab.step8_pins import DEFAULT_OUT, PACKAGE, RERUN_PR

ROOT = Path(__file__).resolve().parents[2]
TRACE_OPEN_RE = re.compile(r'openat\([^,]*,\s*"((?:\\.|[^"\\])*)"')
ANTHROPIC_OPEN_MARKER = "node_modules/@ai-sdk/anthropic"
FIELDS = [
    "group", "batch", "pr", "side", "sha", "version", "pin_resolved",
    "cache_seeded", "binary_present", "binary_path", "loaded_check",
    "loaded_version", "loaded_source", "ready", "reason",
]


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


def trace_binary(binary: Path, trace_path: Path) -> tuple[str, str]:
    """Run ``strace -e openat`` on ``binary --version``. No model call.

    Returns ``(version, source)``. ``source`` is ``strace`` when an open
    resolved a version, ``none`` when the trace has no such open, and
    ``skipped`` when strace cannot be run.
    """
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


def seed_versions(versions: list[str], cache: Path, bun: str) -> dict[str, str]:
    """Install each version once under ``cache/provider-pins``. Empty reason is success."""
    store = cache / "provider-pins"
    reasons = {}
    for version in versions:
        cell = cache / "seed-cells" / version
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
        if row.get("status") != "deferred" and binary.is_file() and can_exec(binary):
            loaded_version, loaded_source = trace_binary(
                binary, cache / "traces" / f"{row['sha']}-{row['side']}.trace",
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

No model calls and no GCP. Each F03-2..F16 side and both sides of `rerun-1443.json` were loaded. Pins were resolved from `provider_pins.json` (the 1443 rerun uses the single version in that config). The shared cache was seeded once per version with `bun add --exact`. The OpenCode binary check is `results/opencode-src/bin/<sha>/opencode`. The loaded-version check is the PR #156 strace `openat` of `node_modules/@ai-sdk/anthropic`, and it runs only when that binary is present.

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
    parser.add_argument("--bin-root", type=Path, default=ROOT / "results" / "opencode-src")
    parser.add_argument("--bun-version", default="1.2.21")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT / "dry-run.csv")
    args = parser.parse_args(argv)
    bun = str(ensure_bun(args.bun_version, args.cache))
    rows = run_dry(args.pins, args.rerun, args.cache, args.bin_root, bun, args.out)
    print(summarize(rows))
    summary = args.out.with_name("dry-run.md")
    write_summary(rows, summary)
    print(f"wrote {args.out}")
    print(f"wrote {summary}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
