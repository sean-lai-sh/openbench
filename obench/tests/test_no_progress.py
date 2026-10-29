"""No-progress watchdog, proxy-byte progress, and silent-gap report."""

import csv
import io
import json
import os
import stat
import sys
import tempfile
import textwrap
import threading
import time
import unittest
import unittest.mock
from pathlib import Path

from thesis.ab.durable import publish_text
from thesis.ab.prs import PullRequest
from thesis.ab.run_ab import drive
from thesis.ab.summarize import pr_record, render_csv, render_markdown
from thesis.ab.watch import WatchdogKill, apply_watchdog_class, run_piped

ROOT = Path(__file__).resolve().parents[2]
SHA_A = "a" * 40
SHA_B = "b" * 40


def _pr(number="9"):
    return PullRequest(
        pr=number, title="Limit", merged="yes", with_sha=SHA_B, without_sha=SHA_A,
        nearest_release="", category="tool", files_changed="", key_paths="",
        one_line="", harness_change="Adds a limit.", bugfix_check="",
    )


class WatchdogTests(unittest.TestCase):
    def test_silent_process_is_no_progress(self):
        started = time.monotonic()
        with self.assertRaises(WatchdogKill) as caught:
            run_piped(
                [sys.executable, "-c", "import time; time.sleep(30)"],
                None,
                os.environ.copy(),
                5,
                no_progress_s=0.6,
            )
        self.assertEqual(caught.exception.reason, "no_progress")
        self.assertGreaterEqual(caught.exception.idle_s, 0.6)
        self.assertLess(time.monotonic() - started, 3)
        self.assertIsNone(caught.exception.last_progress_kind)
        self.assertIn("openbench-infra:no_progress", caught.exception.marker())

    def test_finished_request_ledger_is_progress(self):
        ledger = Path(tempfile.mkdtemp()) / "cell.jsonl"
        stop = threading.Event()

        def append():
            n = 0
            while not stop.is_set():
                n += 1
                with ledger.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps({"record_type": "request", "usage": {"output_tokens": n}}) + "\n")
                time.sleep(0.15)

        thread = threading.Thread(target=append)
        thread.start()
        self.addCleanup(stop.set)
        self.addCleanup(lambda: thread.join(timeout=2))
        done = run_piped(
            [sys.executable, "-c", "import time; time.sleep(1.2)"],
            None,
            os.environ.copy(),
            5,
            no_progress_s=0.8,
            ledger_path=str(ledger),
        )
        self.assertEqual(done.returncode, 0)
        self.assertEqual(done.last_progress_kind, "ledger")

    def test_proxy_byte_file_is_progress(self):
        path = Path(tempfile.mkdtemp()) / "cell.bytes"
        stop = threading.Event()

        def bump():
            total = 0
            while not stop.is_set():
                total += 8
                tmp = path.with_suffix(".tmp")
                tmp.write_text(str(total), encoding="utf-8")
                os.replace(tmp, path)
                time.sleep(0.15)

        thread = threading.Thread(target=bump)
        thread.start()
        self.addCleanup(stop.set)
        self.addCleanup(lambda: thread.join(timeout=2))
        done = run_piped(
            [sys.executable, "-c", "import time; time.sleep(1.2)"],
            None,
            os.environ.copy(),
            5,
            no_progress_s=0.8,
            bytes_path=str(path),
        )
        self.assertEqual(done.returncode, 0)
        self.assertEqual(done.last_progress_kind, "stream_bytes")

    def test_part_updated_stdout_resets_the_idle_timer(self):
        script = (
            "import time\n"
            "for i in range(8):\n"
            "    print('INFO 2026-01-01T00:00:0%d +10ms service=bus "
            "type=message.part.updated publishing' % (i % 10), flush=True)\n"
            "    time.sleep(0.15)\n"
        )
        done = run_piped(
            [sys.executable, "-c", script],
            None,
            os.environ.copy(),
            5,
            no_progress_s=0.4,
        )
        self.assertEqual(done.returncode, 0)
        self.assertEqual(done.last_progress_kind, "part_updated")

    def test_part_updated_then_silence_is_still_no_progress(self):
        script = (
            "import time\n"
            "print('INFO 2026-01-01T00:00:00 +1ms service=bus "
            "type=message.part.updated publishing', flush=True)\n"
            "time.sleep(30)\n"
        )
        started = time.monotonic()
        with self.assertRaises(WatchdogKill) as caught:
            run_piped(
                [sys.executable, "-c", script],
                None,
                os.environ.copy(),
                5,
                no_progress_s=0.45,
            )
        self.assertEqual(caught.exception.reason, "no_progress")
        self.assertEqual(caught.exception.last_progress_kind, "part_updated")
        self.assertGreaterEqual(caught.exception.idle_s, 0.45)
        self.assertLess(time.monotonic() - started, 3)

    def test_part_updated_during_a_slow_tree_walk_is_not_a_kill(self):
        import thesis.ab.watch as watch
        real = watch._tree_signature

        def slow(root):
            time.sleep(0.55)
            return real(root)

        script = (
            "import time\n"
            "for i in range(6):\n"
            "    print('{\"type\":\"message.part.updated\",\"text\":\"%d\"}' % i, flush=True)\n"
            "    time.sleep(0.2)\n"
        )
        with unittest.mock.patch.object(watch, "_tree_signature", side_effect=slow):
            done = run_piped(
                [sys.executable, "-c", script],
                None,
                os.environ.copy(),
                8,
                no_progress_s=0.4,
            )
        self.assertEqual(done.returncode, 0)
        self.assertEqual(done.last_progress_kind, "part_updated")

    def test_part_updated_log_line_resets_the_idle_timer(self):
        home = Path(tempfile.mkdtemp())
        stop = threading.Event()

        def write():
            n = 0
            while not stop.is_set():
                n += 1
                log = home / "opencode" / "log" / "opencode.log"
                log.parent.mkdir(parents=True, exist_ok=True)
                with log.open("a", encoding="utf-8") as handle:
                    handle.write(
                        "INFO 2026-01-01T00:00:0%d +10ms service=bus "
                        "type=message.part.updated publishing\n" % (n % 10)
                    )
                time.sleep(0.15)

        thread = threading.Thread(target=write)
        thread.start()
        self.addCleanup(stop.set)
        self.addCleanup(lambda: thread.join(timeout=2))
        env = os.environ.copy()
        env["XDG_DATA_HOME"] = str(home)
        done = run_piped(
            [sys.executable, "-c", "import time; time.sleep(1.2)"],
            None,
            env,
            5,
            no_progress_s=0.45,
        )
        self.assertEqual(done.returncode, 0)
        self.assertEqual(done.last_progress_kind, "part_updated")

    def test_unparsed_byte_file_is_not_progress(self):
        path = Path(tempfile.mkdtemp()) / "cell.bytes"
        path.write_text("nope", encoding="utf-8")
        with self.assertRaises(WatchdogKill) as caught:
            run_piped(
                [sys.executable, "-c", "import time; time.sleep(30)"],
                None,
                os.environ.copy(),
                5,
                no_progress_s=0.5,
                bytes_path=str(path),
            )
        self.assertEqual(caught.exception.reason, "no_progress")

    def test_storage_and_log_growth_are_progress(self):
        home = Path(tempfile.mkdtemp())
        data = home / "opencode"
        stop = threading.Event()

        def write():
            n = 0
            while not stop.is_set():
                n += 1
                log = data / "log" / "opencode.log"
                log.parent.mkdir(parents=True, exist_ok=True)
                with log.open("a", encoding="utf-8") as handle:
                    handle.write(f"INFO 2026-01-01T00:00:0{n % 10} +10ms tick\n")
                storage = data / "storage" / f"{n}.json"
                storage.parent.mkdir(parents=True, exist_ok=True)
                storage.write_text("{}", encoding="utf-8")
                time.sleep(0.15)

        thread = threading.Thread(target=write)
        thread.start()
        self.addCleanup(stop.set)
        self.addCleanup(lambda: thread.join(timeout=2))
        env = os.environ.copy()
        env["XDG_DATA_HOME"] = str(home)
        done = run_piped(
            [sys.executable, "-c", "import time; time.sleep(1.2)"],
            None,
            env,
            5,
            no_progress_s=0.8,
        )
        self.assertEqual(done.returncode, 0)

    def test_aborted_line_kills_immediately(self):
        started = time.monotonic()
        script = "import time; print('e=Aborted(oops)', flush=True); time.sleep(30)"
        with self.assertRaises(WatchdogKill) as caught:
            run_piped(
                [sys.executable, "-c", script],
                None,
                os.environ.copy(),
                5,
                no_progress_s=30,
            )
        self.assertEqual(caught.exception.reason, "wasm_abort")
        self.assertLess(time.monotonic() - started, 2)
        self.assertIn("Aborted(", caught.exception.output)

    def test_wasm_enoent_in_the_log_kills_immediately(self):
        home = Path(tempfile.mkdtemp())
        env = os.environ.copy()
        env["XDG_DATA_HOME"] = str(home)

        def write():
            time.sleep(0.3)
            log = home / "opencode" / "log" / "opencode.log"
            log.parent.mkdir(parents=True, exist_ok=True)
            log.write_text(
                "ERROR 2026-01-01T00:00:00 +10ms "
                "failed to asynchronously prepare wasm: Error: ENOENT: "
                "open '/$bunfs/tree-sitter-kvge7et4.wasm'\n",
                encoding="utf-8",
            )

        thread = threading.Thread(target=write)
        thread.start()
        self.addCleanup(lambda: thread.join(timeout=2))
        started = time.monotonic()
        with self.assertRaises(WatchdogKill) as caught:
            run_piped(
                [sys.executable, "-c", "import time; time.sleep(30)"],
                None,
                env,
                5,
                no_progress_s=30,
            )
        self.assertEqual(caught.exception.reason, "wasm_abort")
        self.assertLess(time.monotonic() - started, 2)


class ClassifyTests(unittest.TestCase):
    def test_marker_sets_idle_seconds_and_drops_the_score(self):
        row = apply_watchdog_class({
            "error": "openbench-infra:no_progress idle_s=301.2",
            "score": 0.4,
            "success": False,
            "failure_class": "timeout",
        })
        self.assertEqual(row["failure_class"], "infra")
        self.assertEqual(row["infra_reason"], "no_progress")
        self.assertEqual(row["no_progress_idle_s"], 301.2)
        self.assertEqual(row["score"], 0.0)
        self.assertFalse(row["success"])

    def test_no_progress_after_model_requests_is_a_hang_not_infra(self):
        row = apply_watchdog_class({
            "error": "openbench-infra:no_progress idle_s=300.1",
            "score": 0.4, "success": False, "requests_count": 5,
            "tokens_output": 1440, "infra_reason": "no_progress",
        })
        self.assertEqual(row["failure_class"], "hang")
        self.assertNotIn("infra_reason", row)
        self.assertEqual(row["no_progress_idle_s"], 300.1)
        self.assertEqual(row["tokens_output"], 1440)
        self.assertFalse(row["success"])
        from obench.failure_class import class_for_report, is_excluded_from_solve_rate
        self.assertEqual(class_for_report(row), "hang")
        self.assertFalse(is_excluded_from_solve_rate(row))

    def test_no_progress_with_zero_requests_stays_infra(self):
        row = apply_watchdog_class({
            "error": "openbench-infra:no_progress idle_s=300.1",
            "success": False, "requests_count": 0,
        })
        self.assertEqual(row["failure_class"], "infra")
        self.assertEqual(row["infra_reason"], "no_progress")

    def test_rescore_rewrites_stored_mid_session_kills(self):
        from thesis.ab.watch import rescore
        out = Path(tempfile.mkdtemp())
        cell = out / "9" / "cells" / "aa-1" / "t"
        cell.mkdir(parents=True)
        base = {"task": "t", "error": "openbench-infra:no_progress idle_s=300.1",
                "failure_class": "infra", "infra_reason": "no_progress", "success": False}
        (cell / "1.json").write_text(json.dumps(dict(base, trial=1, requests_count=4)))
        (cell / "2.json").write_text(json.dumps(dict(base, trial=2, requests_count=0)))
        changes = rescore(out)
        self.assertEqual(changes, {"9/aa-1": {"infra->hang": 1}})
        rows = [json.loads(l) for l in (out / "9" / "aa-1.jsonl").read_text().splitlines()]
        self.assertEqual(sorted(r["failure_class"] for r in rows), ["hang", "infra"])

    def test_fatal_tail_without_a_marker_is_wasm_abort(self):
        row = apply_watchdog_class({
            "error": "timeout after 840s",
            "output_tail": "ENOENT: no such file, open '/$bunfs/tree-sitter-kvge7et4.wasm'\nAborted(",
            "score": 0.4,
            "success": False,
        })
        self.assertEqual(row["infra_reason"], "wasm_abort")
        self.assertNotIn("no_progress_idle_s", row)
        self.assertEqual(row["score"], 0.0)

    def test_clean_row_is_unchanged(self):
        row = {"error": "exit 1", "score": 0.0, "success": False}
        self.assertIs(apply_watchdog_class(row), row)
        self.assertNotIn("infra_reason", row)

    def test_replay_classifier_does_not_relabel_a_streaming_kill(self):
        # Scoring parity replays apply_watchdog_class. A part update in the
        # tail must stay a hang there; the stream label is a separate helper.
        row = apply_watchdog_class({
            "error": "openbench-infra:no_progress idle_s=300.2",
            "output_tail": (
                "INFO  2026-10-24T04:52:06 +15ms service=bus "
                "type=message.part.updated publishing\n"
            ),
            "requests_count": 5,
            "score": 0.4,
            "success": False,
            "started_at": "2026-10-24T04:49:13+00:00",
            "t_agent_s": 472.3,
        })
        self.assertEqual(row["failure_class"], "hang")
        self.assertNotIn("env_cause", row)


class StreamLabelTests(unittest.TestCase):
    def _stream_row(self, **extra):
        row = {
            "error": "openbench-infra:no_progress idle_s=300.2",
            "failure_class": "hang",
            "hang_reason": "no_progress",
            "no_progress_idle_s": 300.2,
            "requests_count": 5,
            "tokens_output": 15705,
            "score": 0.0,
            "started_at": "2026-10-24T04:49:13.132513+00:00",
            "t_agent_s": 472.293,
            "output_tail": (
                "INFO  2026-10-24T04:52:06 +15ms service=bus "
                "type=message.part.updated publishing\n"
            ),
        }
        row.update(extra)
        return row

    def test_boundary_gap_stays_hang(self):
        # opus/26821 without regex-chess trial 3: last update 299.4s before
        # the kill, idle_s 300.2. That started the idle clock.
        from thesis.ab.watch import (
            label_watchdog_stream, last_part_updated_gap_s, part_updated_within_idle,
            stream_kill_verdict,
        )
        row = self._stream_row()
        gap = last_part_updated_gap_s(row)
        self.assertAlmostEqual(gap, 299.4, delta=0.15)
        self.assertEqual(stream_kill_verdict(row), "stays_hang")
        self.assertFalse(part_updated_within_idle(row))
        labeled = label_watchdog_stream(row)
        self.assertEqual(labeled["failure_class"], "hang")
        self.assertNotIn("env_cause", labeled)
        self.assertEqual(labeled["tokens_output"], 15705)
        self.assertEqual(labeled["hang_reason"], "no_progress")

    def test_part_updated_only_in_a_side_log_uses_that_gap(self):
        from thesis.ab.watch import label_watchdog_stream, stream_kill_verdict
        row = self._stream_row(output_tail="INFO  2026-10-24T04:52:00 +1ms service=app startup\n")
        logs = (
            "INFO  2026-10-24T04:52:06 +12ms service=bus "
            "type=message.part.updated publishing\n"
        )
        self.assertEqual(stream_kill_verdict(row, logs), "stays_hang")
        labeled = label_watchdog_stream(row, logs)
        self.assertEqual(labeled["failure_class"], "hang")
        self.assertNotIn("env_cause", labeled)

    def test_clearly_inside_the_window_is_relabeled(self):
        from thesis.ab.watch import label_watchdog_stream, stream_kill_verdict
        # Kill is 400s after start (04:55:53). The last part update is
        # 04:55:13, 40s before the kill and 260s inside a 300s idle.
        row = self._stream_row(
            started_at="2026-10-24T04:49:13+00:00",
            t_agent_s=400.0,
            no_progress_idle_s=300.0,
            output_tail=(
                "INFO  2026-10-24T04:55:13 +10ms service=bus "
                "type=message.part.updated publishing\n"
            ),
        )
        self.assertEqual(stream_kill_verdict(row), "relabel")
        labeled = label_watchdog_stream(row)
        self.assertEqual(labeled["failure_class"], "env_failure")
        self.assertEqual(labeled["env_cause"], "watchdog_stream")

    def test_a_few_seconds_inside_300_is_borderline(self):
        from thesis.ab.watch import label_watchdog_stream, stream_kill_verdict
        # 297.1s before the kill: past the 2s clock/poll band, not 30s inside.
        row = self._stream_row(
            started_at="2026-10-24T02:44:00+00:00",
            t_agent_s=297.1,
            no_progress_idle_s=300.0,
            output_tail=(
                "INFO  2026-10-24T02:44:00 +10ms service=bus "
                "type=message.part.updated publishing\n"
            ),
        )
        self.assertEqual(stream_kill_verdict(row), "borderline")
        labeled = label_watchdog_stream(row)
        self.assertEqual(labeled["failure_class"], "hang")
        self.assertNotIn("env_cause", labeled)

    def test_part_updated_long_before_the_kill_stays_unlabeled(self):
        from thesis.ab.watch import label_watchdog_stream, part_updated_within_idle
        row = self._stream_row(
            started_at="2026-10-24T04:49:13+00:00",
            t_agent_s=1500.0,
            no_progress_idle_s=300.1,
            output_tail=(
                "INFO  2026-10-24T04:50:00 +10ms service=bus "
                "type=message.part.updated publishing\n"
                "INFO  2026-10-24T05:09:00 +1ms service=app name=mcp shutdown\n"
            ),
        )
        self.assertFalse(part_updated_within_idle(row))
        labeled = label_watchdog_stream(row)
        self.assertEqual(labeled["failure_class"], "hang")
        self.assertNotIn("env_cause", labeled)

    def test_silence_without_a_part_update_is_not_a_stream(self):
        from thesis.ab.watch import part_updated_within_idle
        row = self._stream_row(output_tail="INFO  2026-10-24T04:52:06 +1ms service=app name=mcp shutdown\n")
        self.assertFalse(part_updated_within_idle(row))

    def test_non_kill_is_left_alone(self):
        from thesis.ab.watch import label_watchdog_stream
        row = {"failure_class": "solved", "success": True, "output_tail": "message.part.updated"}
        self.assertIs(label_watchdog_stream(row), row)
        self.assertEqual(row["failure_class"], "solved")
        self.assertNotIn("env_cause", row)


class SummaryTests(unittest.TestCase):
    def test_counts_come_from_cell_json_even_when_jsonl_is_dropped(self):
        out = Path(tempfile.mkdtemp())
        root = out / "9"
        killed = root / "cells" / "without" / "make-it-run"
        other = root / "cells" / "with" / "make-it-run"
        killed.mkdir(parents=True)
        other.mkdir(parents=True)
        (killed / "1.json").write_text(json.dumps({
            "task": "make-it-run", "trial": 1, "score": 0, "success": False,
            "failure_class": "infra", "infra_reason": "no_progress",
            "no_progress_idle_s": 300.4,
            "wall_time_s": 300,
        }), encoding="utf-8")
        (other / "1.json").write_text(json.dumps({
            "task": "make-it-run", "trial": 1, "score": 1, "success": True,
            "failure_class": None, "wall_time_s": 2,
            "tokens_input_uncached": 1, "tokens_output": 1,
            "tokens_cache_read": 0, "tokens_cache_write": 0,
        }), encoding="utf-8")
        (root / "without.infra.json").write_text(json.dumps({
            "status": "infra", "reason": "first cells died in under 10s",
        }), encoding="utf-8")
        (root / "with.jsonl").write_text("", encoding="utf-8")
        record = pr_record(_pr(), out)
        self.assertEqual(record["no_progress"], {"without": 1, "with": 0})
        text = render_markdown([record])
        self.assertIn("Watchdog kills (no_progress): without 1, with 0.", text)
        parsed = list(csv.DictReader(io.StringIO(render_csv([record]))))
        self.assertEqual(parsed[0]["without_no_progress"], "1")
        self.assertEqual(parsed[0]["with_no_progress"], "0")

    def test_parent_noise_counts_each_replica(self):
        out = Path(tempfile.mkdtemp())
        root = out / "9"
        for side, reason in (("aa-1", "no_progress"), ("aa-2", None)):
            cell = root / "cells" / side / "make-it-run"
            cell.mkdir(parents=True)
            body = {
                "task": "make-it-run", "trial": 1, "score": 0, "success": False,
                "wall_time_s": 1,
            }
            if reason:
                body["failure_class"] = "infra"
                body["infra_reason"] = reason
            (cell / "1.json").write_text(json.dumps(body), encoding="utf-8")
            (root / f"{side}.jsonl").write_text(json.dumps(body) + "\n", encoding="utf-8")
        record = pr_record(_pr(), out)
        text = render_markdown([record])
        self.assertIn("Watchdog kills (no_progress): aa-1 1, aa-2 0.", text)


class SilentGapTests(unittest.TestCase):
    def test_first_startup_delta_is_not_a_gap_and_p99_is_per_side(self):
        from thesis.ab.max_silent_gap import longest_gap_s, render
        text = (
            "INFO 2026-01-01T00:00:00 +999999ms start\n"
            "INFO 2026-01-01T00:00:01 +1500ms next\n"
            "INFO 2026-01-01T00:02:01 +120000ms later\n"
        )
        self.assertEqual(longest_gap_s(text), 120.0)
        stamped = (
            "INFO 2026-01-01T00:00:00 +10ms start\n"
            "INFO 2026-01-01T00:05:00 later\n"
        )
        self.assertEqual(longest_gap_s(stamped), 300.0)
        out = Path(tempfile.mkdtemp())
        left = out / "9" / "cells" / "without" / "make-it-run"
        right = out / "9" / "cells" / "with" / "make-it-run"
        left.mkdir(parents=True)
        right.mkdir(parents=True)
        (left / "1.json").write_text(json.dumps({
            "task": "make-it-run", "trial": 1, "output_tail": text,
        }), encoding="utf-8")
        log = out / "9" / "transcripts" / "with" / "make-it-run" / "1" / "log" / "opencode.log"
        log.parent.mkdir(parents=True)
        log.write_text(
            "INFO 2026-01-01T00:00:00 +1ms start\n"
            "INFO 2026-01-01T00:00:01 +1000ms next\n",
            encoding="utf-8",
        )
        (right / "1.json").write_text(json.dumps({
            "task": "make-it-run", "trial": 1,
            "output_tail": "INFO 2026-01-01T00:00:00 +999999ms ignored\n",
        }), encoding="utf-8")
        report = render(out)
        self.assertIn("9 without make-it-run 1 gap=120.000", report)
        self.assertIn("9 with make-it-run 1 gap=1.000", report)
        self.assertIn("9 without n=1 max=120.000 p99=120.000", report)
        self.assertIn("9 with n=1 max=1.000 p99=1.000", report)

    def test_separate_log_files_do_not_invent_a_boundary_gap(self):
        from thesis.ab.max_silent_gap import cell_gap
        first = (
            "INFO 2026-01-01T00:00:00 +1ms start\n"
            "INFO 2026-01-01T00:00:01 +1000ms next\n"
        )
        second = "INFO 2026-01-01T00:00:00 +999999ms startup\n"
        self.assertEqual(cell_gap([first, second]), 1.0)


class DriveFlagTests(unittest.TestCase):
    def test_drive_passes_the_threshold_and_zero_disables_it(self):
        out = Path(tempfile.mkdtemp())
        seen = []

        def worker(spec):
            seen.append(spec.get("no_progress_s"))
            publish_text(Path(spec["cell_path"]), json.dumps({
                "task": spec["task"], "trial": spec["trial"], "score": 1, "success": True,
                "tokens_input_uncached": 1, "tokens_output": 1,
                "tokens_cache_read": 0, "tokens_cache_write": 0,
            }))

        def build_fn(sha, cache, repo=""):
            return Path("/tmp") / sha

        from thesis.ab.compat import Assessment

        def assess_fn(binary):
            return Assessment("native", "listed", {}, False)

        prs = (_pr("1"),)
        drive(
            prs, ("make-it-run",), 1, out,
            jobs=1, model="claude-opus-5-5", timeout_s=5, cache=out,
            max_cost_usd=None, dry_run=False, tasks_dir=Path("/tmp"),
            build_fn=build_fn, assess_fn=assess_fn, worker=worker,
            no_progress_s=300,
        )
        self.assertEqual(seen[0], 300.0)
        seen.clear()
        drive(
            prs, ("make-it-run",), 1, out / "off",
            jobs=1, model="claude-opus-5-5", timeout_s=5, cache=out,
            max_cost_usd=None, dry_run=False, tasks_dir=Path("/tmp"),
            build_fn=build_fn, assess_fn=assess_fn, worker=worker,
            no_progress_s=0,
        )
        self.assertIsNone(seen[0])


def _task(root: Path) -> None:
    task = root / "tasks" / "demo"
    (task / "workspace").mkdir(parents=True)
    (task / "instruction.md").write_text("say hi", encoding="utf-8")
    checker = task / "checker.sh"
    checker.write_text("#!/bin/bash\nexit 0\n", encoding="utf-8")
    checker.chmod(checker.stat().st_mode | stat.S_IEXEC)


def _binary(path: Path, body: str) -> None:
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    path.chmod(0o755)


class ExecuteCellTests(unittest.TestCase):
    def _spec(self, root: Path, binary: Path, **extra):
        spec = {
            "binary": str(binary),
            "config": {},
            "permission_config": False,
            "cell_path": str(root / "cell.json"),
            "tasks_dir": str(root / "tasks"),
            "adapters_dir": str(ROOT / "obench" / "adapters"),
            "model": "claude-opus-5-5",
            "task": "demo",
            "trial": 1,
            "side": "with",
            "timeout_s": 8,
            "transcripts_dir": str(root / "transcripts"),
            "evidence_dir": str(root / "transcripts" / "with" / "demo" / "1"),
            "no_progress_s": 0.5,
        }
        spec.update(extra)
        return spec

    def _omp_spec(self, root: Path, binary: Path, **extra):
        spec = self._spec(root, binary, harness="omp", vertex={
            "bin": str(binary),
            "models_body": "{}\n",
            "models_filename": "models.json",
            "provider": "vertex-anthropic",
            "model_id": "claude-opus-5-5",
            "extra_args": [],
            "agent_env": "OMP_CODING_AGENT_DIR",
            "home_dir": ".omp",
        })
        spec.update(extra)
        return spec

    def test_execute_cell_records_no_progress(self):
        from thesis.ab.run_ab import execute_cell
        root = Path(tempfile.mkdtemp())
        _task(root)
        binary = root / "opencode"
        _binary(binary, """\
            #!/usr/bin/env python3
            import sys, time
            args = sys.argv[1:]
            if args == ["--version"]:
                print("cell-test")
                raise SystemExit(0)
            if args[:2] == ["run", "--help"]:
                print("--auto")
                print("-m, --model")
                print("--format")
                print("--dir")
                print("--title")
                print("--print-logs")
                raise SystemExit(0)
            time.sleep(30)
        """)
        execute_cell(self._spec(root, binary))
        row = json.loads((root / "cell.json").read_text(encoding="utf-8"))
        self.assertEqual(row["network_mode"], "local")
        self.assertEqual(row["proxy_observed"], [])
        self.assertEqual(row["infra_reason"], "no_progress")
        self.assertEqual(row["failure_class"], "infra")
        self.assertGreaterEqual(row["no_progress_idle_s"], 0.5)
        self.assertEqual(row["score"], 0.0)
        self.assertFalse(row["success"])
        self.assertLess(row["t_agent_s"], 4)
        self.assertNotIn("last_progress_kind", row)

    def test_execute_cell_records_part_updated_progress(self):
        from thesis.ab.run_ab import execute_cell
        root = Path(tempfile.mkdtemp())
        _task(root)
        binary = root / "opencode"
        _binary(binary, """\
            #!/usr/bin/env python3
            import sys
            args = sys.argv[1:]
            if args == ["--version"]:
                print("cell-test")
                raise SystemExit(0)
            if args[:2] == ["run", "--help"]:
                print("--auto")
                print("-m, --model")
                print("--format")
                print("--dir")
                print("--title")
                print("--print-logs")
                raise SystemExit(0)
            print(
                "INFO 2026-01-01T00:00:00 +1ms service=bus "
                "type=message.part.updated publishing",
                flush=True,
            )
        """)
        execute_cell(self._spec(root, binary, no_progress_s=2))
        row = json.loads((root / "cell.json").read_text(encoding="utf-8"))
        self.assertEqual(row.get("last_progress_kind"), "part_updated")
        self.assertNotEqual(row.get("infra_reason"), "no_progress")
        self.assertTrue(row["success"])

    def test_execute_cell_treats_proxy_bytes_as_progress(self):
        from thesis.ab.run_ab import execute_cell
        root = Path(tempfile.mkdtemp())
        _task(root)
        binary = root / "opencode"
        _binary(binary, """\
            #!/usr/bin/env python3
            import sys, time
            args = sys.argv[1:]
            if args == ["--version"]:
                print("cell-test")
                raise SystemExit(0)
            if args[:2] == ["run", "--help"]:
                print("--auto")
                print("-m, --model")
                print("--format")
                print("--dir")
                print("--title")
                print("--print-logs")
                raise SystemExit(0)
            time.sleep(1.2)
        """)
        ledger = root / "cell.jsonl"
        counter = ledger.with_suffix(".bytes")
        stop = threading.Event()

        def bump():
            total = 0
            while not stop.is_set():
                total += 4
                tmp = counter.with_suffix(".tmp")
                tmp.write_text(str(total), encoding="utf-8")
                os.replace(tmp, counter)
                time.sleep(0.1)

        thread = threading.Thread(target=bump)
        thread.start()
        self.addCleanup(stop.set)
        self.addCleanup(lambda: thread.join(timeout=2))
        execute_cell(self._spec(
            root, binary, no_progress_s=0.8, cell_ledger=str(ledger),
        ))
        row = json.loads((root / "cell.json").read_text(encoding="utf-8"))
        self.assertNotEqual(row.get("infra_reason"), "no_progress")
        self.assertTrue(row["success"])

    def test_pi_cell_keeps_the_final_workspace(self):
        from thesis.ab.run_ab import cell_workspace_dir, execute_cell, keep_cell_workspace
        root = Path(tempfile.mkdtemp())
        _task(root)
        source = root / "src"
        source.mkdir()
        (source / "kept.txt").write_text("real file\n", encoding="utf-8")
        link = source / "link.txt"
        link.symlink_to("kept.txt")
        dest = root / "copied"
        keep_cell_workspace(str(source), dest)
        self.assertEqual((dest / "kept.txt").read_text(encoding="utf-8"), "real file\n")
        self.assertTrue((dest / "link.txt").is_symlink())

        binary = root / "omp"
        _binary(binary, """\
            #!/usr/bin/env python3
            import json, sys
            from pathlib import Path
            if "--version" in sys.argv:
                print("omp-test")
                raise SystemExit(0)
            Path("kept.txt").write_text("from the cell\\n", encoding="utf-8")
            print(json.dumps({
                "type": "turn_end",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "done"}],
                    "usage": {
                        "input": 1, "cacheRead": 0, "cacheWrite": 0,
                        "output": 1, "reasoning": 0, "totalTokens": 2,
                    },
                },
            }))
        """)
        cell = root / "cells" / "with" / "demo" / "1.json"
        execute_cell(self._omp_spec(root, binary, cell_path=str(cell)))
        workspace = cell_workspace_dir(cell)
        self.assertEqual(
            workspace,
            root / "cells" / "with" / "demo" / "1" / "workspace",
        )
        self.assertEqual((workspace / "kept.txt").read_text(encoding="utf-8"), "from the cell\n")
        row = json.loads(cell.read_text(encoding="utf-8"))
        self.assertEqual(row["final_workspace"], str(workspace))
        self.assertTrue(row["success"])

    def test_hung_tool_call_is_a_timeout(self):
        from thesis.ab.run_ab import execute_cell
        root = Path(tempfile.mkdtemp())
        _task(root)
        marker = root / "hung.json"
        binary = root / "omp"
        _binary(binary, """\
            #!/usr/bin/env python3
            import json, os, sys, time
            from pathlib import Path
            if "--version" in sys.argv:
                print("omp-test")
                raise SystemExit(0)
            marker = Path(os.environ["OBENCH_HUNG_MARKER"])
            child = os.fork()
            if child == 0:
                time.sleep(60)
                raise SystemExit(0)
            marker.write_text(json.dumps({"parent": os.getpid(), "child": child}))
            print('{"type":"tool_execution_start","tool":"bash"}', flush=True)
            time.sleep(60)
        """)
        saved = os.environ.get("OBENCH_HUNG_MARKER")
        os.environ["OBENCH_HUNG_MARKER"] = str(marker)
        self.addCleanup(lambda: os.environ.pop("OBENCH_HUNG_MARKER", None) if saved is None else os.environ.__setitem__("OBENCH_HUNG_MARKER", saved))
        cell = root / "cell.json"
        started = time.monotonic()
        execute_cell(self._omp_spec(
            root, binary, cell_path=str(cell), no_progress_s=0.5, timeout_s=8,
        ))
        elapsed = time.monotonic() - started
        row = json.loads(cell.read_text(encoding="utf-8"))
        self.assertLess(elapsed, 4)
        self.assertGreaterEqual(row["t_agent_s"], 0.4)
        self.assertEqual(row["failure_class"], "timeout")
        self.assertNotEqual(row.get("failure_class"), "infra")
        self.assertIsNone(row.get("infra_reason"))
        self.assertEqual(row["checker_exit"], "timeout")
        self.assertEqual(row["score"], 0.0)
        self.assertFalse(row["success"])
        self.assertFalse(row["completed"])
        self.assertEqual(row["error"], "timeout after 0.5s")
        info = json.loads(marker.read_text(encoding="utf-8"))

        def gone(pid):
            for _ in range(40):
                proc = Path(f"/proc/{pid}")
                if not proc.exists():
                    return True
                state = ""
                for line in (proc / "status").read_text(encoding="utf-8").splitlines():
                    if line.startswith("State:"):
                        state = line
                        break
                if "zombie" in state.lower() or " Z " in f" {state} ":
                    return True
                time.sleep(0.05)
            return False

        self.assertTrue(gone(info["parent"]))
        self.assertTrue(gone(info["child"]))
        for pid in (info["parent"], info["child"]):
            try:
                os.kill(pid, 9)
            except OSError:
                pass


if __name__ == "__main__":
    unittest.main()
