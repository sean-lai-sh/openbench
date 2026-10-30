"""Checker env guards: fail-closed venvs, infra classification, free disk, spend monitor."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from obench import failure_class
from obench.cell_columns import excluded_from_scoring, rescore_cell
from obench.checker_env import (
    ENV_CAUSE_DOWNLOAD,
    ENV_CAUSE_ENOSPC,
    ENV_CAUSE_LOW_DISK,
    ENV_CAUSE_VENV_BYPASSED,
    ENV_CAUSE_VENV_MISMATCH,
    ENV_CAUSE_VENV_MISSING,
    CheckerEnvError,
    check_free_disk,
    classify_checker_output,
    verify_checker_venv,
)
from obench.checker_venv import STAGE_ENV, attach_checker_venvs
from obench.tests.test_checker_timeout_env import _task
from thesis.ab.h2env import spend_monitor
from thesis.ab.summarize import countable

ROOT = Path(__file__).resolve().parents[2]
PACK = ROOT / "data" / "packs" / "openbench-tb-hard"
H2ENV = ROOT / "thesis" / "ab" / "h2env"
PY = "%d.%d" % sys.version_info[:2]
PY3 = "%d.%d.%d" % sys.version_info[:3]


def _req(d: Path, task: str, pin: str = PY) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{task}.txt").write_text(f"# python: {pin}\npytest\n", encoding="utf-8")
    return d


def _venv(root: Path, task: str, target: str, version: str = PY3) -> Path:
    v = root / task
    (v / "bin").mkdir(parents=True)
    os.symlink(target, v / "bin" / "python")
    (v / "pyvenv.cfg").write_text(
        f"home = {Path(target).parent}\nversion_info = {version}\n", encoding="utf-8",
    )
    return v


class VerifyVenvTests(unittest.TestCase):
    def test_missing_venv_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            req = _req(Path(tmp) / "req", "t")
            with self.assertRaises(CheckerEnvError) as cm:
                verify_checker_venv(Path(tmp) / "root", "t", req)
            self.assertEqual(cm.exception.cause, ENV_CAUSE_VENV_MISSING)

    def test_dangling_interpreter_symlink_fails_closed(self):
        # The 10-30 gate: bin/python -> /root/.local/share/uv/python/... absent.
        with tempfile.TemporaryDirectory() as tmp:
            req = _req(Path(tmp) / "req", "t")
            _venv(Path(tmp) / "root", "t",
                  "/root/.local/share/uv/python/cpython-3.13.9-linux-x86_64-gnu/bin/python3.13-absent")
            with self.assertRaises(CheckerEnvError) as cm:
                verify_checker_venv(Path(tmp) / "root", "t", req)
            self.assertEqual(cm.exception.cause, ENV_CAUSE_VENV_MISSING)
            self.assertIn("symlink", str(cm.exception))

    def test_version_mismatch_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            req = _req(Path(tmp) / "req", "t", pin="2.7")
            _venv(Path(tmp) / "root", "t", sys.executable)
            with self.assertRaises(CheckerEnvError) as cm:
                verify_checker_venv(Path(tmp) / "root", "t", req, probe=False)
            self.assertEqual(cm.exception.cause, ENV_CAUSE_VENV_MISMATCH)

    def test_good_venv_passes_and_task_without_requirements_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            req = _req(Path(tmp) / "req", "t")
            _venv(Path(tmp) / "root", "t", sys.executable)
            py = verify_checker_venv(Path(tmp) / "root", "t", req, probe=False)
            self.assertEqual(py, Path(tmp) / "root" / "t" / "bin" / "python")
            self.assertIsNone(verify_checker_venv(Path(tmp) / "root", "other", req))

    def test_probe_runs_the_interpreter(self):
        with tempfile.TemporaryDirectory() as tmp:
            req = _req(Path(tmp) / "req", "t")
            _venv(Path(tmp) / "root", "t", sys.executable)
            try:
                import pytest  # noqa: F401
            except ImportError:
                with self.assertRaises(CheckerEnvError):
                    verify_checker_venv(Path(tmp) / "root", "t", req)
            else:
                self.assertIsNotNone(verify_checker_venv(Path(tmp) / "root", "t", req))

    def test_every_pack_requirement_has_a_python_pin(self):
        for req in (H2ENV / "requirements").glob("*.txt"):
            self.assertRegex(req.read_text(encoding="utf-8"), r"(?m)^# python: \d")


class AttachRelocationTests(unittest.TestCase):
    def test_interpreter_links_are_rewritten_into_the_cell_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            stage = Path(tmp) / "stage"
            interp = stage / ".uv-python" / "cpython" / "bin"
            interp.mkdir(parents=True)
            os.symlink(sys.executable, interp / "python3")
            _venv(stage, "t", "/opt/h2-checker-venvs/.uv-python/cpython/bin/python3")
            dest = attach_checker_venvs(stage, Path(tmp) / "cell" / "h2-checker-venvs")
            link = dest / "t" / "bin" / "python"
            self.assertEqual(os.readlink(link), str(dest / ".uv-python/cpython/bin/python3"))
            self.assertTrue(os.access(link, os.X_OK))
            cfg = (dest / "t" / "pyvenv.cfg").read_text(encoding="utf-8")
            self.assertIn(str(dest / ".uv-python/cpython/bin"), cfg)
            self.assertNotIn("/opt/h2-checker-venvs", cfg)
            # The read-only stage is untouched.
            self.assertTrue(os.readlink(stage / "t" / "bin" / "python").startswith("/opt/"))

    def test_dockerfile_ships_the_interpreter_inside_the_artifact(self):
        text = (H2ENV / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("UV_PYTHON_INSTALL_DIR=/opt/h2-checker-venvs/.uv-python", text)


class ClassifyTests(unittest.TestCase):
    def test_signatures(self):
        enospc = "error: Failed to install: torch\n  Caused by: No space left on device (os error 28)"
        self.assertEqual(classify_checker_output(1, enospc, ""), ENV_CAUSE_ENOSPC)
        self.assertEqual(classify_checker_output(1, "", "OSError: [Errno 28] No space left on device"), ENV_CAUSE_ENOSPC)
        self.assertEqual(classify_checker_output(1, "error: Failed to download `torch==2.7.0`", ""), ENV_CAUSE_DOWNLOAD)
        self.assertEqual(classify_checker_output(1, "OBENCH_ENV_FAILURE: checker_venv_missing x", ""), "checker_venv_missing")
        fallback = "downloading uv 0.9.5 x86_64-unknown-linux-gnu\neverything's installed!\n1 failed"
        self.assertEqual(classify_checker_output(1, fallback, "", split_enabled=True), ENV_CAUSE_VENV_BYPASSED)
        self.assertIsNone(classify_checker_output(1, fallback, "", split_enabled=False))

    def test_real_wrong_answer_and_passes_are_untouched(self):
        self.assertIsNone(classify_checker_output(1, "FAILED test_outputs.py::test_x - assert 1 == 2", ""))
        self.assertIsNone(classify_checker_output(0, "No space left on device", ""))
        self.assertIsNone(classify_checker_output("timeout", "No space left on device", ""))

    def test_test_sh_fails_closed_before_any_install(self):
        scripts = sorted(PACK.glob("*/checker_data/harbor-tests/test.sh"))
        self.assertEqual(len(scripts), 9)
        for script in scripts:
            text = script.read_text(encoding="utf-8")
            branch = text.split('if [ -x "${_h2_py}" ]; then', 1)[1].split("\nelse\n", 1)[1]
            guard = branch.index("OBENCH_ENV_FAILURE: checker_venv_missing")
            for install in ("apt-get", "curl", "uvx", "pip install"):
                if install in branch:
                    self.assertLess(guard, branch.index(install), f"{script}: {install}")


class ForcedEnospcTests(unittest.TestCase):
    def test_forced_enospc_is_env_failure_not_wrong_answer(self):
        # /dev/full returns a real ENOSPC on write.
        if not os.path.exists("/dev/full"):
            self.skipTest("/dev/full unavailable")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _task(root / "tasks", "demo", "#!/bin/bash\necho torch > /dev/full\nexit 1\n")
            workspace = root / "workspace"
            workspace.mkdir()
            source_root = root / "original"
            cell = source_root / "1" / "cells" / "with" / "demo" / "1.json"
            cell.parent.mkdir(parents=True)
            cell.write_text(json.dumps({
                "run_id": "opencode:demo:m:trial1", "task": "demo",
                "success": False, "failure_class": "wrong_answer",
                "wall_time_s": 600, "tokens_output": 9000,
                "final_workspace": str(workspace),
            }), encoding="utf-8")
            loaded = json.loads(rescore_cell(cell, source_root, root / "rescored", root / "tasks")
                                .read_text(encoding="utf-8"))
            self.assertIn("No space left on device", loaded["checker_stdout"] + loaded["checker_stderr"])
            self.assertTrue(loaded["env_failure"])
            self.assertEqual(loaded["env_cause"], ENV_CAUSE_ENOSPC)
            self.assertNotEqual(loaded["failure_class"], "wrong_answer")
            self.assertTrue(excluded_from_scoring(loaded))
            self.assertFalse(countable(loaded))
            self.assertNotEqual(failure_class.class_for_report(loaded), "wrong_answer")

    def test_rescore_with_missing_venv_does_not_run_the_checker(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            marker = root / "ran"
            _task(root / "tasks", "torch-tensor-parallelism", f"#!/bin/bash\ntouch {marker}\nexit 0\n")
            (root / "stage").mkdir()
            workspace = root / "workspace"
            workspace.mkdir()
            source_root = root / "original"
            cell = source_root / "1" / "cells" / "with" / "torch-tensor-parallelism" / "1.json"
            cell.parent.mkdir(parents=True)
            cell.write_text(json.dumps({
                "run_id": "opencode:torch-tensor-parallelism:m:trial1",
                "task": "torch-tensor-parallelism", "final_workspace": str(workspace),
            }), encoding="utf-8")
            with mock.patch.dict(os.environ, {STAGE_ENV: str(root / "stage")}):
                loaded = json.loads(rescore_cell(cell, source_root, root / "rescored", root / "tasks")
                                    .read_text(encoding="utf-8"))
            self.assertFalse(marker.exists())
            self.assertTrue(loaded["env_failure"])
            self.assertEqual(loaded["env_cause"], ENV_CAUSE_VENV_MISSING)
            self.assertFalse(countable(loaded))


class FreeDiskTests(unittest.TestCase):
    def test_floor(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertGreater(check_free_disk(tmp, None), 0)
            with self.assertRaises(CheckerEnvError) as cm:
                check_free_disk(tmp, 1e12)
            self.assertEqual(cm.exception.cause, ENV_CAUSE_LOW_DISK)

    def test_run_records_free_disk_column(self):
        from obench.run import ROW_FIELDS
        self.assertIn("free_disk_gb", ROW_FIELDS)


class SpendMonitorTests(unittest.TestCase):
    def test_self_test_reads_the_known_nonzero_fixture(self):
        ok, msg = spend_monitor.self_test()
        self.assertTrue(ok, msg)
        total, n = spend_monitor.total_cost(spend_monitor.FIXTURE)
        self.assertEqual(n, 2)
        self.assertAlmostEqual(total, 0.3708288, places=6)

    def test_old_driver_glob_read_zero_on_the_same_tree(self):
        import glob
        old = glob.glob(str(spend_monitor.FIXTURE / "*" / "*" / "cells" / "*" / "*" / "*.json"))
        self.assertEqual(old, [])

    def test_self_test_fails_on_an_empty_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            ok, _ = spend_monitor.self_test(Path(tmp))
            self.assertFalse(ok)

    def test_stop_exit_code(self):
        self.assertEqual(spend_monitor.main([str(spend_monitor.FIXTURE), "--stop-at", "0.3"]), 10)
        self.assertEqual(spend_monitor.main([str(spend_monitor.FIXTURE), "--stop-at", "5"]), 0)


if __name__ == "__main__":
    unittest.main()
