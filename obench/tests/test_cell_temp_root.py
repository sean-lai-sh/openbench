"""Each cell gets its own temp root, even inside one worker process."""

from __future__ import annotations

import json
import os
import stat
import tempfile
import unittest
from pathlib import Path

from obench import run as bench_run


class CellTempRootTests(unittest.TestCase):
    def test_two_cells_in_one_worker_keep_separate_temp_roots(self):
        base = Path(tempfile.mkdtemp(prefix="obench-cell-test-", dir="/tmp"))
        self.addCleanup(lambda: __import__("shutil").rmtree(base, ignore_errors=True))
        task_dir = base / "tasks" / "tiny"
        (task_dir / "workspace").mkdir(parents=True)
        (task_dir / "instruction.md").write_text("do it\n", encoding="utf-8")
        checker = task_dir / "checker.sh"
        checker.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        checker.chmod(checker.stat().st_mode | stat.S_IEXEC)
        adapters = base / "adapters"
        adapters.mkdir()
        record = base / "record.jsonl"
        (adapters / "fake.py").write_text(
            "import json, os, tempfile\n"
            "def run(instruction, workdir, model, timeout_s):\n"
            "    made = tempfile.mkdtemp(prefix='agenttmp_')\n"
            "    note = open(os.path.join(made, 'note.txt'), 'w', encoding='utf-8')\n"
            "    note.write('x')\n"
            "    note.close()\n"
            f"    handle = open({str(record)!r}, 'a', encoding='utf-8')\n"
            "    handle.write(json.dumps({\n"
            "        'workdir': workdir,\n"
            "        'tmpdir': os.environ.get('TMPDIR'),\n"
            "        'tmp': os.environ.get('TMP'),\n"
            "        'temp': os.environ.get('TEMP'),\n"
            "        'made': made,\n"
            "        'cached': tempfile.tempdir,\n"
            "    }) + '\\n')\n"
            "    handle.close()\n"
            "    return {'completed': True, 'output_tail': 'ok', 'full_output': 'ok'}\n",
            encoding="utf-8",
        )
        poisoned = Path(tempfile.mkdtemp(prefix="poisoned-cell-", dir="/tmp"))
        self.addCleanup(lambda: __import__("shutil").rmtree(poisoned, ignore_errors=True))
        previous_tempdir = tempfile.tempdir
        tempfile.tempdir = str(poisoned)
        try:
            for trial in (1, 2):
                bench_run.run_cell(
                    "fake", "tiny", "model", trial, 30,
                    str(base / "tasks"), str(adapters), 30,
                )
        finally:
            tempfile.tempdir = previous_tempdir
        self.assertEqual(tempfile.tempdir, previous_tempdir)
        rows = [
            json.loads(line)
            for line in record.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self.assertEqual(len(rows), 2)
        roots = []
        poisoned_real = os.path.realpath(poisoned)
        for row in rows:
            workdir = os.path.realpath(row["workdir"])
            root = os.path.realpath(os.path.dirname(workdir))
            made = os.path.realpath(row["made"])
            roots.append(root)
            self.assertEqual(os.path.realpath(row["tmpdir"]), root)
            self.assertEqual(os.path.realpath(row["tmp"]), root)
            self.assertEqual(os.path.realpath(row["temp"]), root)
            self.assertEqual(os.path.dirname(made), root)
            self.assertFalse(workdir.startswith(poisoned_real + os.sep))
            self.assertFalse(made.startswith(poisoned_real + os.sep))
            self.assertNotEqual(root, poisoned_real)
            self.assertEqual(row["cached"], str(poisoned))
        self.assertNotEqual(roots[0], roots[1])
        self.assertFalse(roots[0].startswith(roots[1] + os.sep))
        self.assertFalse(roots[1].startswith(roots[0] + os.sep))
        # The worker did not keep the cell root cached for the next cell.
        self.assertNotEqual(tempfile.tempdir, roots[0])
        self.assertNotEqual(tempfile.tempdir, roots[1])


if __name__ == "__main__":
    unittest.main()
