"""step8_summarize reads complete.json. It does not re-count cell files."""
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from thesis.ab.step8_summarize import main, summarize

ROOT = Path(__file__).resolve().parents[2]
F032 = ROOT / "results" / "step8-f032-1027"


class SummarizeFixture(unittest.TestCase):
    def test_reads_complete_json_and_ignores_extra_cell_files(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            complete = {
                "complete": {
                    "1/with": {
                        "on_route": 1,
                        "cells": ["scored/1/cells/with/t/1.json"],
                        "reruns": 0,
                    },
                },
                "incomplete": {"1/without": {"on_route": 0, "cells": 0, "why": "short"}},
                "untagged_rerun_cells": [],
                "excluded_traced": [],
            }
            (root / "complete.json").write_text(json.dumps(complete))
            (root / "route-scored.json").write_text(json.dumps({
                "off_route": {"1/with": [{"cell": "extra", "route": "off:missing"}]},
            }))
            extra = root / "scored" / "1" / "cells" / "with" / "t"
            extra.mkdir(parents=True)
            (extra / "1.json").write_text("{}")
            (extra / "2.json").write_text("{}")  # on disk, not in complete.json
            out = summarize(root)
            self.assertEqual(out["sides"], 1)
            self.assertEqual(out["per_side"], {"1/with": 1})
            self.assertEqual(out["scored_cells"], 1)
            self.assertEqual(out["off_route"], 1)
            self.assertEqual(out["complete"], complete["complete"])
            buf = io.StringIO()
            with redirect_stdout(buf):
                self.assertEqual(main([str(root)]), 0)
            self.assertIn("sides 1", buf.getvalue())
            self.assertIn("total 1", buf.getvalue())
            self.assertIn("off-route 1", buf.getvalue())


class SummarizeF032(unittest.TestCase):
    def test_f032_matches_complete_json(self):
        self.assertTrue((F032 / "complete.json").is_file(), F032)
        doc = json.loads((F032 / "complete.json").read_text())
        out = summarize(F032)
        self.assertEqual(out["sides"], 22)
        self.assertEqual(len(out["per_side"]), 22)
        self.assertEqual(set(out["per_side"].values()), {30})
        self.assertEqual(out["scored_cells"], 660)
        self.assertEqual(out["off_route"], 0)
        self.assertEqual(out["complete"], doc["complete"])
        self.assertEqual(out["per_side"], {k: len(v["cells"]) for k, v in doc["complete"].items()})
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(main([str(F032)]), 0)
        text = buf.getvalue()
        self.assertIn("sides 22", text)
        self.assertIn("scored_cells_per_side 30", text)
        self.assertIn("total 660", text)
        self.assertIn("off-route 0", text)


if __name__ == "__main__":
    unittest.main()
