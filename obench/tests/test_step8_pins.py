"""Nearest-box pins for step-8 F03-2..F16, the 1443 rerun, and the dry run.

No model calls. The OpenCode mirror is not required: these tests check the
committed table against provider_pins.json and the dry-run readiness rules.
"""
from __future__ import annotations

import csv
import json
import stat
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PINS = ROOT / "results" / "step8-pins" / "pins.csv"
RERUN = ROOT / "results" / "step8-pins" / "rerun-1443.json"
DRY = ROOT / "results" / "step8-pins" / "dry-run.csv"
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
        self.assertTrue(all(row["ready"] == "no" for row in deferred))
        self.assertTrue(all(row["pin_resolved"] == "no" for row in deferred))
        self.assertTrue(all(row["cache_seeded"] == "no" for row in deferred))
        self.assertTrue(all("deferred" in row["reason"] for row in deferred))
        for row in pinned + rerun:
            self.assertEqual(row["pin_resolved"], "yes", row)
            self.assertEqual(row["cache_seeded"], "yes", row)
            self.assertEqual(row["binary_present"], "no", row)
            self.assertEqual(row["ready"], "no", row)
            self.assertIn("opencode binary missing", row["reason"])
            self.assertEqual(row["loaded_check"], "skipped")
        self.assertEqual({row["version"] for row in rerun}, {"2.0.0-beta.11"})
        self.assertNotIn("4.0.88", {row["version"] for row in rows})


if __name__ == "__main__":
    unittest.main()
