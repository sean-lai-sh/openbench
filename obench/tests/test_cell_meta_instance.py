"""--cell-meta records the GCE VM name and instance id from the driver env."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from thesis.ab import run_ab
from obench.tests.test_ab import SHA_A, SHA_B, _csv


class CellMetaInstanceTests(unittest.TestCase):
    def _main(self, env):
        path = _csv(
            [{"PR": "3052", "Title": "t", "Category": "tool", "Harness change": "x",
              "Merge commit SHA": SHA_B, "Parent/base SHA": SHA_A}],
            ["PR", "Title", "Category", "Harness change", "Merge commit SHA", "Parent/base SHA"],
        )
        self.addCleanup(path.unlink)
        out = tempfile.mkdtemp()
        tasks = Path(tempfile.mkdtemp()); (tasks / "make-it-run").mkdir()
        with mock.patch.dict(os.environ, env, clear=False), \
                mock.patch.object(run_ab, "drive", return_value=("plan\n", 0, None)), \
                mock.patch.object(run_ab, "resolve_tasks", return_value=("make-it-run",)), \
                mock.patch.object(run_ab, "CELL_META", None):
            rc = run_ab.main([str(path), "--trials", "2", "--out", out, "--cell-meta",
                              "--runner-commit", "c" * 40, "--dry-run", "--tasks-dir", str(tasks)])
            return rc, run_ab.CELL_META

    def test_vm_name_and_instance_id_recorded(self):
        rc, meta = self._main({"OBENCH_VM_NAME": "thesis-h1-cpu-2", "OBENCH_INSTANCE_ID": "123456789"})
        self.assertEqual(rc, 0)
        self.assertEqual(meta["vm_name"], "thesis-h1-cpu-2")
        self.assertEqual(meta["instance_id"], "123456789")

    def test_unset_is_none(self):
        rc, meta = self._main({"OBENCH_VM_NAME": "", "OBENCH_INSTANCE_ID": ""})
        self.assertEqual(rc, 0)
        self.assertIsNone(meta["vm_name"])
        self.assertIsNone(meta["instance_id"])

    def test_row_carries_vm_name_and_instance_id(self):
        row = {}
        run_ab.attach_cell_meta(row, {"cell_meta": {"vm_name": "thesis-h1-cpu-3", "instance_id": "42"}},
                                "2026-10-31T17:00:00+00:00")
        self.assertEqual(row["vm_name"], "thesis-h1-cpu-3")
        self.assertEqual(row["instance_id"], "42")


if __name__ == "__main__":
    unittest.main()
