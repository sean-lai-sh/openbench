"""Nearest-box pins for step-8 F03-2..F16, the 1443 rerun, and the dry run.

No model calls. The OpenCode mirror is not required: these tests check the
committed table against provider_pins.json and the dry-run readiness rules.
"""
from __future__ import annotations

import csv
import json
import os
import stat
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from thesis.ab.step8_pins import DEFAULT_OUT

ROOT = Path(__file__).resolve().parents[2]
PINS = DEFAULT_OUT / "pins.csv"
RERUN = DEFAULT_OUT / "rerun-1443.json"
DRY = DEFAULT_OUT / "dry-run.csv"
OVERRIDES = ROOT / "results" / "step8-full413-1020-F01" / "rescore-provider-faults" / "overrides.csv"
DEFERRED = {"51062", "53166", "55613"}
PACKAGE = "@ai-sdk/anthropic"


def _rows(path: Path) -> list[dict]:
    with path.open(newline="") as fh:
        return list(csv.DictReader(fh))


class PinTableTests(unittest.TestCase):
    def test_pinned_sides_match_the_manifest_and_share_one_version(self):
        from thesis.ab.provider_pin import apply_provider_pin, lookup_entry

        rows = _rows(PINS)
        pinned = [row for row in rows if row["status"] == "pinned"]
        deferred = [row for row in rows if row["status"] == "deferred"]
        self.assertEqual(len(pinned), 586)
        self.assertEqual(len(deferred), 6)
        self.assertEqual({row["pr"] for row in deferred}, DEFERRED)
        by_pr: dict[str, set[str]] = {}
        for row in pinned:
            self.assertEqual(row["pin_source"], "nearest_box_build")
            self.assertRegex(row["pin_from"], r"^[0-9a-f]{40}$")
            self.assertTrue(row["reasoning"])
            self.assertIn(row["version"], row["reasoning"])
            self.assertIn(row["pin_from"], row["reasoning"])
            found = lookup_entry(row["sha"], row["side"], row["pr"])
            self.assertIsNotNone(found, row["sha"])
            self.assertEqual(found["packages"][PACKAGE], row["version"])
            self.assertEqual(found["entry"]["pin_source"], "nearest_box_build")
            self.assertEqual(found["entry"]["pin_from"], row["pin_from"])
            self.assertEqual(found["entry"]["evidence"], "nearest-box-build")
            source = lookup_entry(row["pin_from"])
            self.assertIsNotNone(source, row["pin_from"])
            self.assertEqual(source["entry"]["pin_source"], "box_cache")
            self.assertEqual(source["packages"][PACKAGE], row["version"])
            by_pr.setdefault(row["pr"], set()).add(row["version"])
        self.assertTrue(all(len(versions) == 1 for versions in by_pr.values()))
        self.assertEqual(len(by_pr), 293)
        for row in deferred:
            self.assertEqual(row["version"], "")
            self.assertEqual(row["pin_source"], "deferred_post_monorepo")
            self.assertIn("separate PR", row["reasoning"])
            self.assertIsNone(lookup_entry(row["sha"], row["side"], row["pr"]))
        sample = pinned[0]
        proxy = apply_provider_pin({}, "/tmp/step8-pins", sample["sha"], sample["side"], sample["pr"])
        self.assertEqual(proxy["pin_source"], "nearest_box_build")
        self.assertEqual(proxy["pin_from"], sample["pin_from"])
        self.assertEqual(proxy["provider_pins"][PACKAGE], sample["version"])

    def test_1443_history_stays_split_and_the_rerun_is_one_version(self):
        from thesis.ab.provider_pin import lookup_packages

        rerun = json.loads(RERUN.read_text(encoding="utf-8"))
        self.assertTrue(rerun["do_not_run"])
        self.assertEqual(rerun["pr"], "1443")
        self.assertEqual(rerun["version"], "2.0.0-beta.11")
        self.assertEqual(rerun["estimated_cost_usd"], "5-6")
        self.assertEqual(rerun["trials"], 30)
        self.assertEqual(
            {side["side"]: side["rerun_version"] for side in rerun["sides"]},
            {"with": "2.0.0-beta.11", "without": "2.0.0-beta.11"},
        )
        with_sha = next(side["sha"] for side in rerun["sides"] if side["side"] == "with")
        without_sha = next(side["sha"] for side in rerun["sides"] if side["side"] == "without")
        self.assertEqual(lookup_packages(with_sha, "with", "1443"), {PACKAGE: "2.0.0-beta.13"})
        self.assertEqual(lookup_packages(without_sha, "without", "1443"), {PACKAGE: "2.0.0-beta.11"})
        self.assertNotIn("1443", {row["pr"] for row in _rows(PINS)})

    def test_rescore_155_and_pass_rate_exclusion_are_unchanged(self):
        from obench.failure_class import EXCLUDED_FROM_SOLVE_RATE, HANG

        overrides = _rows(OVERRIDES)
        self.assertEqual(
            [(row["pr"], row["scoring"], row["from_class"], row["to_class"]) for row in overrides],
            [
                ("1545", "exclude", "wrong_answer", "infra"),
                ("579", "label_only", "hang", "infra"),
            ],
        )
        self.assertIn("infra", EXCLUDED_FROM_SOLVE_RATE)
        self.assertNotIn(HANG, EXCLUDED_FROM_SOLVE_RATE)

    def test_tables_live_under_data(self):
        self.assertEqual(DEFAULT_OUT, ROOT / "data" / "step8-pins")
        self.assertTrue(PINS.is_file())
        self.assertTrue(RERUN.is_file())
        self.assertTrue(DRY.is_file())
        self.assertFalse(str(PINS).startswith(str(ROOT / "results")))

    def test_leave_one_out_below_95_percent_exits_nonzero(self):
        from thesis.ab.step8_pins import require_loo_agreement

        with self.assertRaises(SystemExit) as caught:
            require_loo_agreement({"loo": {"n": 116, "agree": 110, "misses": 6, "bad": 0}})
        self.assertNotEqual(caught.exception.code, 0)
        message = str(caught.exception)
        self.assertIn("110/116", message)
        self.assertIn("below 95%", message)
        self.assertIn("refusing to merge pins", message)
        require_loo_agreement({"loo": {"n": 116, "agree": 114}})
        require_loo_agreement({"loo": {"n": 100, "agree": 95}})
        with self.assertRaises(SystemExit):
            require_loo_agreement({"loo": {"n": 100, "agree": 94}})
        with self.assertRaises(SystemExit):
            require_loo_agreement({"loo": {"n": 0, "agree": 0}})

    def test_write_outputs_stops_before_a_low_agreement_manifest_merge(self):
        from collections import Counter

        from thesis.ab.step8_pins import write_outputs

        detail = []
        for index in range(10):
            detail.append({
                "tag": "loo", "sha": f"{index:040x}", "side": "with", "pr": "1",
                "version": "2.0.0", "match": index < 9, "pred": "2.0.0",
                "pin_from": "a" * 40, "distance": 1,
            })
        facts = {
            "tip": "b" * 40,
            "tip_ref": "origin/dev",
            "line_len": 1,
            "box_sides": 10,
            "within_differ": ["1443"],
            "loo_detail": detail,
            "candidates": 1,
        }
        with self.assertRaises(SystemExit) as caught:
            write_outputs([], facts, Counter(), Path(tempfile.mkdtemp()))
        self.assertIn("below 95%", str(caught.exception))
        self.assertIn("refusing to merge pins", str(caught.exception))


class DryRunRuleTests(unittest.TestCase):
    def test_trace_line_reads_the_opened_package_version(self):
        from thesis.ab.step8_pin_dry_run import version_from_trace

        root = Path(tempfile.mkdtemp())
        package = root / "node_modules" / "@ai-sdk" / "anthropic"
        package.mkdir(parents=True)
        (package / "package.json").write_text('{"version": "2.0.0"}', encoding="utf-8")
        opened = package / "dist" / "index.js"
        line = f'openat(AT_FDCWD, "{opened}", O_RDONLY) = 3\n'
        self.assertEqual(version_from_trace(line), "2.0.0")
        self.assertEqual(version_from_trace('openat(AT_FDCWD, "/tmp/other.js", O_RDONLY) = 3\n'), "")

    def test_ready_requires_binary_and_a_matching_load_when_traced(self):
        from thesis.ab.step8_pin_dry_run import assess_row

        root = Path(tempfile.mkdtemp())
        binary = root / "opencode"
        binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        binary.chmod(binary.stat().st_mode | stat.S_IEXEC)
        row = {"group": "F03-2-F16", "batch": "F03-2", "pr": "3251", "side": "with", "sha": "abc", "status": "pinned"}
        missing = assess_row(
            row, version="2.0.0", resolve_reason="", cache_seeded=True, seed_reason="",
            binary=root / "absent",
        )
        self.assertEqual(missing["ready"], "no")
        self.assertEqual(missing["pin_resolved"], "yes")
        self.assertEqual(missing["cache_seeded"], "yes")
        self.assertIn("opencode binary missing", missing["reason"])
        self.assertEqual(missing["loaded_check"], "skipped")
        ready = assess_row(
            row, version="2.0.0", resolve_reason="", cache_seeded=True, seed_reason="",
            binary=binary, loaded_version="2.0.0", loaded_source="strace",
        )
        self.assertEqual(ready["ready"], "yes")
        self.assertEqual(ready["loaded_check"], "pass")
        mismatch = assess_row(
            row, version="2.0.0", resolve_reason="", cache_seeded=True, seed_reason="",
            binary=binary, loaded_version="4.0.88", loaded_source="strace",
        )
        self.assertEqual(mismatch["ready"], "no")
        self.assertIn("loaded 4.0.88 != pin 2.0.0", mismatch["reason"])
        unproven = assess_row(
            row, version="2.0.0", resolve_reason="", cache_seeded=True, seed_reason="",
            binary=binary, loaded_version="", loaded_source="none",
        )
        self.assertEqual(unproven["ready"], "yes")
        self.assertEqual(unproven["loaded_check"], "unproven")
        deferred = assess_row(
            {**row, "status": "deferred", "pr": "55613"},
            version="", resolve_reason="deferred", cache_seeded=False, seed_reason="",
            binary=binary,
        )
        self.assertEqual(deferred["ready"], "no")
        self.assertEqual(deferred["pin_resolved"], "no")
        self.assertTrue(deferred["reason"].startswith("deferred"))

    def test_committed_dry_run_table_resolves_pins_without_binaries(self):
        rows = _rows(DRY)
        self.assertEqual(len(rows), 594)
        deferred = [row for row in rows if row["pr"] in DEFERRED]
        rerun = [row for row in rows if row["group"] == "rerun-1443"]
        pinned = [row for row in rows if row["group"] == "F03-2-F16" and row["pr"] not in DEFERRED]
        self.assertEqual(len(deferred), 6)
        self.assertEqual(len(rerun), 2)
        self.assertEqual(len(pinned), 586)
        # Post-monorepo sides take the bundled-provider path (test_step8_monorepo).
        self.assertTrue(all(row["group"] == "monorepo" for row in deferred))
        self.assertTrue(all(row["pin_resolved"] == "bundled" for row in deferred))
        self.assertTrue(all(row["cache_seeded"] == "n/a" for row in deferred))
        self.assertTrue(all(row["ready"] in {"yes", "no"} and row["reason"] for row in deferred))
        self.assertTrue(all("deferred" not in row["reason"] for row in deferred))
        for row in pinned + rerun:
            self.assertEqual(row["pin_resolved"], "yes", row)
            self.assertEqual(row["cache_seeded"], "yes", row)
            self.assertEqual(row["binary_present"], "no", row)
            self.assertEqual(row["ready"], "no", row)
            self.assertIn("opencode binary missing", row["reason"])
            self.assertEqual(row["loaded_check"], "skipped")
        self.assertEqual({row["version"] for row in rerun}, {"2.0.0-beta.11"})
        self.assertNotIn("4.0.88", {row["version"] for row in rows})

    def test_trace_points_at_the_seeded_cache_not_the_caller_home(self):
        from thesis.ab.step8_pin_dry_run import (
            provider_cache_env,
            trace_binary,
            trace_cache_path,
        )

        root = Path(tempfile.mkdtemp())
        seed = root / "seed-cells" / "2.0.0"
        package = seed / "node_modules" / "@ai-sdk" / "anthropic"
        package.mkdir(parents=True)
        (package / "package.json").write_text('{"version": "2.0.0"}', encoding="utf-8")
        home = root / "isolate"
        env = provider_cache_env(seed, home)
        self.assertEqual(Path(env["HOME"]), home)
        self.assertNotEqual(Path(env["HOME"]), Path.home())
        self.assertNotEqual(env["HOME"], os.environ.get("HOME"))
        self.assertEqual(env["XDG_CACHE_HOME"], str(home / ".cache"))
        linked = trace_cache_path(env)
        self.assertEqual(linked.resolve(), seed.resolve())
        self.assertEqual(
            (linked / "node_modules" / "@ai-sdk" / "anthropic" / "package.json").read_text(encoding="utf-8"),
            '{"version": "2.0.0"}',
        )
        seen = {}

        def fake_run(cmd, **kwargs):
            seen["cmd"] = cmd
            seen["env"] = kwargs.get("env")
            seen["cwd"] = kwargs.get("cwd")
            opened = (
                Path(kwargs["env"]["XDG_CACHE_HOME"]) / "opencode"
                / "node_modules" / "@ai-sdk" / "anthropic" / "dist" / "index.js"
            )
            trace = Path(cmd[cmd.index("-o") + 1])
            trace.parent.mkdir(parents=True, exist_ok=True)
            trace.write_text(
                f'openat(AT_FDCWD, "{opened}", O_RDONLY) = 3\n',
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(cmd, 0)

        binary = root / "opencode"
        binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        stdout = StringIO()
        with patch("thesis.ab.step8_pin_dry_run.shutil.which", return_value="/usr/bin/strace"), \
                patch("thesis.ab.step8_pin_dry_run.subprocess.run", side_effect=fake_run), \
                redirect_stdout(stdout):
            version, source = trace_binary(binary, root / "traces" / "abc-with.trace", seed)
        self.assertEqual((version, source), ("2.0.0", "strace"))
        self.assertEqual(seen["env"]["HOME"], str((root / "traces" / "abc-with.home")))
        self.assertNotEqual(seen["env"]["HOME"], os.environ.get("HOME"))
        self.assertEqual(Path(seen["env"]["XDG_CACHE_HOME"], "opencode").resolve(), seed.resolve())
        self.assertEqual(seen["cwd"], seen["env"]["HOME"])
        self.assertIn(str(seed.resolve()), stdout.getvalue())
        self.assertIn("strace loaded-version cache:", stdout.getvalue())
        self.assertNotIn(str(Path.home()), seen["env"]["HOME"])


if __name__ == "__main__":
    unittest.main()
