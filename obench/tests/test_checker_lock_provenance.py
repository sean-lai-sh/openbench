import contextlib, io, json, os, tempfile, threading, time, unittest
from unittest import mock

from obench import run as R
from thesis.ab import run_ab


class CheckerLockTest(unittest.TestCase):
    def _task(self, d, body):
        os.makedirs(os.path.join(d, "checker_data"))
        with open(os.path.join(d, "checker_data", "test_x.py"), "w") as fh:
            fh.write(body)
        return d

    def test_port_binding_detection(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertTrue(R.checker_binds_port(self._task(os.path.join(d, "a"), "os.environ['MASTER_PORT']='12355'")))
            self.assertFalse(R.checker_binds_port(self._task(os.path.join(d, "b"), "assert 1")))

    def test_non_port_task_has_no_lock(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(R.checker_lock_for(self._task(os.path.join(d, "b"), "x=1")).path)

    def test_lock_serializes_and_measures_wait(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "checker.lock")
            order, waits = [], []

            def worker(tag, hold):
                t0 = time.monotonic()
                with R.CheckerLock(path):
                    waits.append((tag, time.monotonic() - t0))
                    order.append(("in", tag))
                    time.sleep(hold)
                    order.append(("out", tag))

            a = threading.Thread(target=worker, args=("a", 0.4)); a.start()
            time.sleep(0.1)
            b = threading.Thread(target=worker, args=("b", 0.0)); b.start()
            a.join(); b.join()
            self.assertEqual(order, [("in", "a"), ("out", "a"), ("in", "b"), ("out", "b")])
            self.assertGreater(dict(waits)["b"], 0.2)

    def test_lock_wait_is_a_row_column(self):
        self.assertIn("lock_wait_s", R.ROW_FIELDS)


class ProvenanceFallbackTest(unittest.TestCase):
    def _row(self):
        return {"route": "proxy", "loaded_anthropic": "2.0.0", "provider_loaded_source": "none", "provider_loaded_mismatch": None,
                "requests_cost_usd": 0.1, "started_et": "a", "ended_et": "b", "strace_on": False,
                "gate_cell": True, "provider_trace": "off", "opencode_cache": "/c",
                "lockfile_sha256": "ab", "provider_versions": {"@ai-sdk/anthropic": "2.0.0"}}

    def test_gate_row_no_longer_warns(self):
        with tempfile.TemporaryDirectory() as d:
            binary = os.path.join(d, "opencode")
            with open(binary, "wb") as fh:
                fh.write(b"bin")
            with open(os.path.join(d, "build-stamp.json"), "w") as fh:
                json.dump({"args": [], "kind": "build.ts"}, fh)
            row = self._row()
            env = {"OBENCH_AGENT_IMAGE": "h1-env:1022", "OBENCH_RUNNER_COMMIT": "deadbeef",
                   "OBENCH_BINARY_SOURCE": "original"}
            err = io.StringIO()
            with mock.patch.dict(os.environ, env), contextlib.redirect_stderr(err):
                run_ab.attach_required_fields(row, {"pr": 1, "side": "with", "binary": binary})
            self.assertNotIn("cell missing required fields", err.getvalue())
            self.assertNotIn("missing_fields", row)
            self.assertEqual(row["probe_method"], "manifest")
            self.assertIsNone(row["provider_loaded_version"])
            self.assertEqual(row["provider_manifest_version"], "2.0.0")
            self.assertEqual(row["provider_version_source"], "manifest")
            self.assertIs(row["provider_version_proven"], False)
            self.assertEqual(row["cell_image"], "h1-env:1022")
            self.assertEqual(row["build_channel"], "local:build.ts")
            self.assertEqual(row["runner_commit"], "deadbeef")
            self.assertEqual(row["binary_hash_source"], "post_hoc_disk")
            self.assertEqual(row["binary_source"], "original")
            self.assertEqual(len(row["binary_sha256"]), 64)

    def test_captured_binary_sha_fills_proven_version(self):
        with tempfile.TemporaryDirectory() as d:
            toml = os.path.join(d, "pv.toml")
            with open(toml, "w") as fh:
                fh.write('[binary.abc123]\nprovider_version = "2.0.58"\nsource = "capture:#201"\n')
            row = self._row(); row["binary_sha256"] = "ABC123"
            run_ab.fill_provenance_fallbacks(row, {}, versions_path=toml)
            self.assertEqual(row["provider_loaded_version"], "2.0.58")
            self.assertEqual(row["provider_version_source"], "capture")
            self.assertEqual(row["provider_version_ref"], "capture:#201")
            self.assertIs(row["provider_version_proven"], True)
            self.assertEqual(row["provider_manifest_version"], "2.0.0")

    def test_seeded_map_has_ba54cee5(self):
        m = run_ab.proven_provider_versions()
        self.assertEqual(m["53398f0fcf8c3cfe70814723fb1bd7c8f80c7d6e6abfc858c9d17b9670e2a67e"],
                         {"version": "2.0.58", "source": "capture:#201"})

    def test_traced_probe_is_not_overwritten(self):
        row = self._row(); row.update(probe_method="strace", provider_loaded_version="2.0.1")
        run_ab.fill_provenance_fallbacks(row, {})
        self.assertEqual((row["probe_method"], row["provider_loaded_version"]), ("strace", "2.0.1"))


if __name__ == "__main__":
    unittest.main()
