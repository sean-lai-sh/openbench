#!/usr/bin/env python3
"""Build the six post-monorepo step-8 binaries with build records and a control step.

Same build path as F03-2: the runner's own ``build_opencode`` (shared mirror,
one worktree per sha at ``<opencode-src>/worktrees/<sha>``, the bun version
the tree asks for, ``<opencode-src>/bin/<sha>/opencode``). On top of that:

1. Control step, before any rebuilt binary is used. Three step-8 builds that
   already have a binary in ``<opencode-src>/bin`` are rebuilt into
   ``<opencode-src>/control-rebuild`` (the existing binaries are not
   touched). Each rebuild must match its existing build on
   ``opencode --version`` (the build info OpenCode reports) and on the
   provider the binary loads (strace ``openat`` of
   ``node_modules/@ai-sdk/anthropic`` against the side's pinned cache). A
   check that cannot run (no strace) is not a match. If any control does not
   match, the step fails, the six sides are not built, and every record is
   ``used=no``.
2. The six monorepo sides are built only after all three controls match.
3. One build record per binary goes to ``data/step8-pins/monorepo-builds.csv``:
   source commit (and the worktree ``HEAD`` it was built from), lockfile
   sha256, binary sha256, build info, and loaded provider.

``step8_monorepo_smoke`` refuses to launch and ``step8_pin_dry_run`` marks a
side not ready unless this table shows a passed control step and a record
whose binary sha256 matches the binary on disk.

  python3 -m thesis.ab.step8_monorepo_build --cache <opencode-src>
  python3 -m thesis.ab.step8_monorepo_build --cache <opencode-src> --records-only --mirror <opencode-mirror>

``--records-only`` builds nothing: it writes the six source-commit and
lockfile rows from the mirror with ``used=no``. No model calls.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable

from thesis.ab.monorepo import MONOREPO_PRS, bundled_label, bundled_provider_for_tree
from thesis.ab.step8_pins import DEFAULT_OUT, PACKAGE

DEFAULT_BUILDS_CSV = DEFAULT_OUT / "monorepo-builds.csv"
CONTROL_COUNT = 3
LOCKFILES = ("bun.lock", "bun.lockb")
FIELDS = [
    "kind", "pr", "side", "sha", "worktree_head", "plan_kind", "bun_version",
    "lockfile", "lockfile_sha256", "binary_path", "binary_sha256",
    "opencode_build_info", "loaded_provider",
    "existing_binary_path", "existing_binary_sha256", "existing_build_info",
    "existing_loaded_provider", "control_match", "control_status", "used", "reason",
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def lockfile_of_tree(root: Path) -> tuple[str, str]:
    """``(name, sha256)`` of the tree's bun lockfile, or ``("", "")``."""
    for name in LOCKFILES:
        path = Path(root) / name
        if path.is_file():
            return name, sha256_file(path)
    return "", ""


def lockfile_at(mirror: Path, sha: str) -> tuple[str, str]:
    """``(name, sha256)`` of the lockfile at ``sha`` in a git mirror."""
    for name in LOCKFILES:
        proc = subprocess.run(
            ["git", "-C", str(mirror), "show", f"{sha}:{name}"],
            capture_output=True, check=False,
        )
        if proc.returncode == 0:
            return name, hashlib.sha256(proc.stdout).hexdigest()
    return "", ""


def worktree_head(root: Path) -> str:
    proc = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=False,
    )
    return proc.stdout.strip() if proc.returncode == 0 else ""


def opencode_build_info(binary: Path) -> str:
    """What the binary reports for ``--version``, with an isolated HOME. No model call."""
    with tempfile.TemporaryDirectory(prefix="oc-build-info-") as home:
        env = dict(os.environ, HOME=home, XDG_CONFIG_HOME=f"{home}/.config",
                   XDG_CACHE_HOME=f"{home}/.cache", XDG_DATA_HOME=f"{home}/.local/share",
                   XDG_STATE_HOME=f"{home}/.local/state")
        for name in ("OPENCODE_CONFIG", "OPENCODE_CONFIG_DIR", "OPENCODE_CONFIG_CONTENT"):
            env.pop(name, None)
        try:
            proc = subprocess.run(
                [str(binary), "--version"], capture_output=True, text=True,
                timeout=30, check=False, env=env, cwd=home, stdin=subprocess.DEVNULL,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return f"error: {exc}"
    text = (proc.stdout or "").strip() or (proc.stderr or "").strip()
    first = text.splitlines()[0].strip() if text else ""
    return first if proc.returncode == 0 else f"exit {proc.returncode}: {first}"


def _loaded_label(version: str, source: str) -> str:
    if source == "skipped":
        return "unverified (strace unavailable)"
    if version:
        return f"{PACKAGE}@{version} ({source})"
    return f"no {PACKAGE} opened"


class Probe:
    """Real build-info and loaded-provider checks (strace, seeded pin caches)."""

    def __init__(self, cache: Path, bun_version: str = "1.2.21"):
        self.cache = Path(cache)
        self.bun_version = bun_version
        self._bun = ""
        self._seeded: dict[str, str] = {}

    def build_info(self, binary: Path) -> str:
        return opencode_build_info(binary)

    def _seed(self, version: str) -> Path | None:
        from thesis.ab.build_opencode import ensure_bun
        from thesis.ab.step8_pin_dry_run import seed_versions, seeded_cell_cache

        work = self.cache / "control-probe"
        if version not in self._seeded:
            if not self._bun:
                self._bun = str(ensure_bun(self.bun_version, work))
            self._seeded.update(seed_versions([version], work, self._bun))
        if self._seeded.get(version):
            return None
        return seeded_cell_cache(work, version)

    def loaded(self, binary: Path, sha: str, side: str, tag: str) -> str:
        from thesis.ab.provider_pin import lookup_packages
        from thesis.ab.step8_pin_dry_run import trace_binary

        packages = lookup_packages(sha, side) or {}
        version = str(packages.get(PACKAGE) or "")
        if version:
            seed = self._seed(version)
            if seed is None:
                return f"unverified (could not seed {PACKAGE}@{version})"
        else:
            seed = self.cache / "control-probe" / "empty-provider"
            seed.mkdir(parents=True, exist_ok=True)
        found, source = trace_binary(
            binary, self.cache / "control-probe" / "traces" / f"{sha}-{side}-{tag}.trace", seed,
        )
        return _loaded_label(found, source)


def _verified(label: str) -> bool:
    return bool(label) and not label.startswith("unverified")


def monorepo_sides(pins_csv: Path) -> list[dict]:
    from thesis.ab.step8_monorepo_smoke import monorepo_sides as sides
    return sides(pins_csv)


def control_candidates(pins_csv: Path, cache: Path) -> list[dict]:
    """Pinned step-8 sides with an existing binary, newest batch first."""
    out = []
    seen = set()
    with Path(pins_csv).open(newline="") as fh:
        rows = [row for row in csv.DictReader(fh) if row.get("status") == "pinned"]
    for row in reversed(rows):
        sha = row["sha"]
        if sha in seen:
            continue
        if (Path(cache) / "bin" / sha / "opencode").is_file():
            seen.add(sha)
            out.append({"pr": row["pr"], "side": row["side"], "sha": sha})
    return out


def _rebuild_cache(cache: Path) -> Path:
    """``<cache>/control-rebuild`` sharing the mirror and bun downloads."""
    cache = Path(cache).resolve()
    rebuild = cache / "control-rebuild"
    rebuild.mkdir(parents=True, exist_ok=True)
    for name in ("mirror", "bun"):
        link = rebuild / name
        target = cache / name
        if target.exists() and not link.exists() and not link.is_symlink():
            link.symlink_to(target, target_is_directory=True)
    return rebuild


def _plan_facts(root: Path) -> tuple[str, str]:
    from thesis.ab.build_opencode import build_plan
    try:
        plan = build_plan(Path(root))
    except (OSError, ValueError):
        return "", ""
    return str(plan.get("kind") or ""), str(plan.get("bun") or "")


def _built_row(kind: str, side: dict, cache: Path, binary: Path) -> dict:
    root = Path(cache) / "worktrees" / side["sha"]
    plan_kind, bun = _plan_facts(root)
    lockfile, lock_sha = lockfile_of_tree(root)
    return {
        "kind": kind, "pr": side["pr"], "side": side["side"], "sha": side["sha"],
        "worktree_head": worktree_head(root), "plan_kind": plan_kind, "bun_version": bun,
        "lockfile": lockfile, "lockfile_sha256": lock_sha,
        "binary_path": str(binary), "binary_sha256": sha256_file(binary),
    }


def run_controls(
    controls: list[dict],
    *,
    cache: Path,
    build_fn: Callable[[str, Path], Path],
    probe,
) -> tuple[bool, list[dict]]:
    """Rebuild each control and compare with its existing build."""
    rows = []
    rebuild_cache = _rebuild_cache(cache)
    if len(controls) < CONTROL_COUNT:
        rows.append({
            "kind": "control", "control_status": "fail", "control_match": "no", "used": "no",
            "reason": f"need {CONTROL_COUNT} existing builds for the control step, found {len(controls)}",
        })
        return False, rows
    ok = True
    for side in controls[:CONTROL_COUNT]:
        existing = Path(cache) / "bin" / side["sha"] / "opencode"
        try:
            rebuilt = Path(build_fn(side["sha"], rebuild_cache))
        except Exception as exc:  # noqa: BLE001 - a failed rebuild is a failed control
            rows.append({
                "kind": "control", **side, "existing_binary_path": str(existing),
                "existing_binary_sha256": sha256_file(existing),
                "control_match": "no", "used": "no", "reason": f"rebuild failed: {exc}",
            })
            ok = False
            continue
        row = _built_row("control", side, rebuild_cache, rebuilt)
        row["opencode_build_info"] = probe.build_info(rebuilt)
        row["loaded_provider"] = probe.loaded(rebuilt, side["sha"], side["side"], "rebuild")
        row["existing_binary_path"] = str(existing)
        row["existing_binary_sha256"] = sha256_file(existing)
        row["existing_build_info"] = probe.build_info(existing)
        row["existing_loaded_provider"] = probe.loaded(existing, side["sha"], side["side"], "existing")
        reasons = []
        if row["worktree_head"] and row["worktree_head"] != side["sha"]:
            reasons.append(f"worktree HEAD {row['worktree_head']} != {side['sha']}")
        if not row["opencode_build_info"] or row["opencode_build_info"] != row["existing_build_info"]:
            reasons.append(
                f"build info {row['opencode_build_info']!r} != existing {row['existing_build_info']!r}"
            )
        if not (_verified(row["loaded_provider"]) and _verified(row["existing_loaded_provider"])):
            reasons.append("loaded provider unverified")
        elif row["loaded_provider"] != row["existing_loaded_provider"]:
            reasons.append(
                f"loaded provider {row['loaded_provider']!r} != existing {row['existing_loaded_provider']!r}"
            )
        row["control_match"] = "no" if reasons else "yes"
        row["used"] = "no"
        row["reason"] = "; ".join(reasons)
        ok = ok and not reasons
        rows.append(row)
    status = "pass" if ok else "fail"
    for row in rows:
        row["control_status"] = status
    return ok, rows


def build_monorepo(
    sides: list[dict],
    *,
    cache: Path,
    build_fn: Callable[[str, Path], Path],
    probe,
) -> list[dict]:
    """Build the six sides. Called only after the control step passes."""
    rows = []
    for side in sides:
        try:
            binary = Path(build_fn(side["sha"], cache))
        except Exception as exc:  # noqa: BLE001
            rows.append({"kind": "monorepo", **side, "used": "no", "reason": f"build failed: {exc}"})
            continue
        row = _built_row("monorepo", side, cache, binary)
        root = Path(cache) / "worktrees" / side["sha"]
        row["opencode_build_info"] = probe.build_info(binary)
        provider = bundled_provider_for_tree(root)
        loaded = probe.loaded(binary, side["sha"], side["side"], "monorepo")
        row["loaded_provider"] = f"bundled {bundled_label(provider)}; {loaded}" if provider else loaded
        reasons = []
        if row["worktree_head"] != side["sha"]:
            reasons.append(f"worktree HEAD {row['worktree_head'] or 'unknown'} != source commit")
        if row["plan_kind"] != "monorepo":
            reasons.append(f"build plan {row['plan_kind'] or 'unknown'}, not monorepo")
        if not row["lockfile_sha256"]:
            reasons.append("no lockfile")
        if loaded.startswith(f"{PACKAGE}@"):
            reasons.append(f"binary opened a separate {PACKAGE}")
        row["used"] = "no" if reasons else "yes"
        row["reason"] = "; ".join(reasons)
        rows.append(row)
    return rows


def records_only(sides: list[dict], mirror: Path) -> list[dict]:
    rows = []
    for side in sides:
        lockfile, lock_sha = lockfile_at(mirror, side["sha"])
        rows.append({
            "kind": "monorepo", **side, "plan_kind": "monorepo",
            "lockfile": lockfile, "lockfile_sha256": lock_sha,
            "control_status": "not_run", "used": "no",
            "reason": "not built; control step not run",
        })
    return rows


def write_records(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with Path(path).open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows({key: row.get(key, "") for key in FIELDS} for row in rows)


def load_records(path: Path) -> list[dict]:
    path = Path(path)
    if not path.is_file():
        return []
    with path.open(newline="") as fh:
        return list(csv.DictReader(fh))


def control_problem(records: list[dict]) -> str:
    """Empty when the table shows a passed control step on enough builds."""
    controls = [row for row in records if row.get("kind") == "control"]
    if not controls:
        return "control step not run"
    matched = [row for row in controls if row.get("control_match") == "yes"]
    if any(row.get("control_match") != "yes" for row in controls):
        return "control step failed: " + "; ".join(
            f"{row.get('sha', '')[:8]} {row.get('reason') or 'no match'}"
            for row in controls if row.get("control_match") != "yes"
        )
    if len(matched) < CONTROL_COUNT:
        return f"control step matched {len(matched)} of {CONTROL_COUNT} builds"
    if any(row.get("control_status") != "pass" for row in controls):
        return "control step status is not pass"
    return ""


def build_gate_reason(records: list[dict], sha: str, binary: Path) -> str:
    """Why this side's binary may not be used, or ``""``."""
    problem = control_problem(records)
    if problem:
        return problem
    rows = [row for row in records if row.get("kind") == "monorepo" and row.get("sha") == sha]
    if not rows:
        return "no build record"
    row = rows[-1]
    if row.get("used") != "yes":
        return f"build record used=no ({row.get('reason') or 'no reason'})"
    if not Path(binary).is_file():
        return f"binary missing at {binary}"
    actual = sha256_file(binary)
    if actual != row.get("binary_sha256"):
        return f"binary sha256 {actual[:12]} != build record {str(row.get('binary_sha256'))[:12]}"
    return ""


def launch_gate(builds_csv: Path, sides: list[dict], cache: Path) -> list[str]:
    records = load_records(builds_csv)
    problems = []
    for side in sides:
        binary = Path(cache) / "bin" / side["sha"] / "opencode"
        reason = build_gate_reason(records, side["sha"], binary)
        if reason:
            problems.append(f"{side['pr']} {side['side']} {side['sha'][:8]}: {reason}")
    return problems


def run_build(
    *,
    pins_csv: Path,
    cache: Path,
    out: Path,
    controls: list[dict] | None = None,
    build_fn: Callable[[str, Path], Path] | None = None,
    probe=None,
) -> int:
    if build_fn is None:
        from thesis.ab.build_opencode import binary as build_fn  # noqa: F811
    probe = probe or Probe(cache)
    sides = monorepo_sides(pins_csv)
    chosen = controls if controls is not None else control_candidates(pins_csv, cache)
    ok, rows = run_controls(chosen, cache=cache, build_fn=build_fn, probe=probe)
    if ok:
        rows.extend(build_monorepo(sides, cache=cache, build_fn=build_fn, probe=probe))
    else:
        for side in sides:
            rows.append({
                "kind": "monorepo", **side, "control_status": "fail", "used": "no",
                "reason": "not built: control step failed",
            })
    write_records(rows, out)
    for row in rows:
        label = row.get("control_match") if row["kind"] == "control" else f"used={row.get('used')}"
        print(f"{row['kind']:<8} {row.get('pr', ''):>6} {row.get('side', ''):<7} "
              f"{str(row.get('sha', ''))[:8]} {label} {row.get('reason', '')}")
    print(f"wrote {out}")
    if not ok:
        print("control step failed: no rebuilt binary is used", file=sys.stderr)
        return 3
    return 0 if all(row.get("used") == "yes" for row in rows if row["kind"] == "monorepo") else 4


def _control_arg(text: str) -> dict:
    sha, _, side = text.partition(":")
    return {"pr": "", "side": side or "without", "sha": sha.strip().lower()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the monorepo step-8 binaries with a control step")
    parser.add_argument("--cache", type=Path, required=True, help="<opencode-src> (bin/, worktrees/, mirror/)")
    parser.add_argument("--pins", type=Path, default=DEFAULT_OUT / "pins.csv")
    parser.add_argument("--out", type=Path, default=DEFAULT_BUILDS_CSV)
    parser.add_argument("--control", action="append", default=[], metavar="SHA[:SIDE]",
                        help=f"existing build to rebuild as a control ({CONTROL_COUNT} needed); "
                             "default: newest pinned step-8 sides with a binary in <cache>/bin")
    parser.add_argument("--records-only", action="store_true",
                        help="build nothing; write source-commit and lockfile rows from --mirror")
    parser.add_argument("--mirror", type=Path, default=None)
    args = parser.parse_args(argv)
    if args.records_only:
        mirror = args.mirror or (args.cache / "mirror")
        rows = records_only(monorepo_sides(args.pins), mirror)
        write_records(rows, args.out)
        for row in rows:
            print(f"{row['pr']} {row['side']:<7} {row['sha'][:8]} {row['lockfile']} {row['lockfile_sha256'][:12]}")
        print(f"wrote {args.out}")
        return 0
    controls = [_control_arg(item) for item in args.control] or None
    return run_build(pins_csv=args.pins, cache=args.cache, out=args.out, controls=controls)


if __name__ == "__main__":
    sys.exit(main())
