"""Step 8 F03-2 sign-off conditions: route halt, reruns, completeness, egress refresh."""
import json, os, subprocess, tempfile, unittest
from pathlib import Path
from unittest import mock

from thesis.ab import run_ab, step8_gate

ROOT = Path(__file__).resolve().parents[2]


def _cell(d, pr, side, task, trial, route="on:provider-options", **kw):
    p = Path(d) / pr / "cells" / side / task / f"{trial}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(dict(route=route, **kw)))
    return p


class RouteHaltTests(unittest.TestCase):
    def test_third_off_route_cell_stops_side(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {"OBENCH_ROUTE_HALT": "1"}):
            out = Path(d)
            spec = dict(pr="3251", side="before", sha="abc", repo="r", task="t", trial=0)
            prepared = {}
            for i in range(2):
                _cell(out, "3251", "before", "t", i, route="off:provider-options")
            with mock.patch.object(run_ab, "write_infra") as wi:
                run_ab._absorb_route_halt(spec, out, prepared)
                self.assertNotIn(run_ab._side_key(spec), prepared)
                _cell(out, "3251", "before", "t", 2, route="off:provider-options")
                run_ab._absorb_route_halt(spec, out, prepared)
                wi.assert_called_once()
            st = prepared[run_ab._side_key(spec)]
            self.assertFalse(st["ok"]); self.assertEqual(st["status"], "infra")
            self.assertTrue((out / "3251" / "route-halt-before.json").is_file())

    def test_off_by_default(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {"OBENCH_ROUTE_HALT": ""}):
            for i in range(3):
                _cell(d, "1", "after", "t", i, route="off:x")
            prepared = {}
            run_ab._absorb_route_halt(dict(pr="1", side="after", sha="s", repo="r"), Path(d), prepared)
            self.assertEqual(prepared, {})


class RerunTests(unittest.TestCase):
    def test_rerun_list_matches_gate_keys_and_tag(self):
        with tempfile.TemporaryDirectory() as d:
            _cell(d, "1", "after", "t", 3, route="off:x")
            out, _ = step8_gate.route_check(d)
            f = Path(d) / "route.json"; f.write_text(json.dumps(out))
            with mock.patch.dict(os.environ, {"OBENCH_RERUN_CELLS": str(f)}):
                keys = run_ab.rerun_cells_from_env()
            self.assertIn(run_ab._cell_rel(dict(pr="1", side="after", task="t", trial=3)), keys)
            with mock.patch.dict(os.environ, {"OBENCH_RERUN": "1"}):
                row = {}
                run_ab.attach_cell_meta(row, dict(pr="1", side="after", task="t", trial=3, sha="s"), "x")
            self.assertEqual(row.get("rerun"), 1)

    def test_complete_needs_30_on_route_and_gate(self):
        with tempfile.TemporaryDirectory() as s, tempfile.TemporaryDirectory() as r:
            for side in ("before", "after"):
                for i in range(30):
                    _cell(s, "1", side, "t", i, route="off:x" if i < 2 else "on:provider-options")
            _cell(r, "1", "before", "t", 0, rerun=1)
            _cell(r, "1", "before", "t", 1, rerun=1)
            _cell(r, "1", "after", "t", 0)  # untagged: ignored
            out, _ = step8_gate.complete(s, {"ok_prs": ["1"], "mismatch_sides": []}, [r])
            self.assertEqual(out["complete"]["1/before"]["on_route"], 30)
            self.assertEqual(out["complete"]["1/before"]["reruns"], 2)
            self.assertEqual(out["incomplete"]["1/after"]["on_route"], 28)
            self.assertEqual(len(out["untagged_rerun_cells"]), 1)
            out, _ = step8_gate.complete(s, {"ok_prs": [], "mismatch_sides": []}, [r])
            self.assertEqual(out["complete"], {})

    def test_spend_after_halt(self):
        with tempfile.TemporaryDirectory() as d:
            for i in range(5):
                _cell(d, "1", "after", "t", i, route="off:x",
                      started_et=f"2026-10-27T01:0{i}:00-04:00", ended_et=f"2026-10-27T01:0{i}:30-04:00",
                      requests_cost_usd=0.5)
            out, _ = step8_gate.route_check(d)
            hs = out["halted_spend"]["1/after"]
            self.assertEqual(hs["cells_after"], 2); self.assertEqual(hs["spend_after_usd"], 1.0)


class EgressRefreshTests(unittest.TestCase):
    def _run(self, sudo_body):
        with tempfile.TemporaryDirectory() as d:
            b = Path(d)
            (b / "getent").write_text("#!/bin/sh\n[ \"$1\" = ahostsv4 ] && echo '1.2.3.4 STREAM h'\n[ \"$1\" = ahostsv6 ] && echo '2001:db8::1 STREAM h'\nexit 0\n")
            (b / "sudo").write_text("#!/bin/sh\necho \"$@\" >> %s/calls\n%s\n" % (d, sudo_body))
            for x in ("getent", "sudo"):
                os.chmod(b / x, 0o755)
            env = dict(os.environ, PATH=f"{d}:{os.environ['PATH']}", EGRESS_STATE=f"{d}/ips")
            p = subprocess.run(["bash", "-c", f"source {ROOT}/thesis/ab/launchers/egress_block.sh; egress_refresh"],
                               env=env, capture_output=True, text=True)
            calls = (b / "calls").read_text() if (b / "calls").exists() else ""
            return p.returncode, calls, p.stdout

    def test_adds_new_a_and_aaaa(self):
        rc, calls, out = self._run('case "$2" in -C) exit 1;; esac; exit 0')
        self.assertEqual(rc, 0)
        self.assertIn("iptables -I OUTPUT 1 -d 1.2.3.4", calls)
        self.assertIn("ip6tables -I OUTPUT 1 -d 2001:db8::1", calls)

    def test_failed_add_aborts(self):
        rc, _, out = self._run("exit 1")
        self.assertNotEqual(rc, 0); self.assertIn("FAILED", out)


if __name__ == "__main__":
    unittest.main()
