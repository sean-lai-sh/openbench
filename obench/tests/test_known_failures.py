"""The known-failures gate: a failing test not on the baseline fails the check."""
import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from obench.tests import check_known_failures as K

LOG = """\
======================================================================
ERROR: test_a (obench.tests.test_x.A.test_a)
----------------------------------------------------------------------
======================================================================
FAIL: test_b (obench.tests.test_x.B)
----------------------------------------------------------------------
"""


class KnownFailures(unittest.TestCase):
    def test_parses_both_header_forms(self):
        self.assertEqual(K.failing_ids(LOG), {"obench.tests.test_x.A.test_a", "obench.tests.test_x.B.test_b"})

    def test_new_failure_fails_and_listed_ones_pass(self):
        base = "# reason\nobench.tests.test_x.A.test_a\nobench.tests.test_x.C.test_c  # gone\n"
        new, fixed = K.check(LOG, base)
        self.assertEqual(new, {"obench.tests.test_x.B.test_b"})
        self.assertEqual(fixed, {"obench.tests.test_x.C.test_c"})
        with tempfile.TemporaryDirectory() as d:
            p = Path(d, "log")
            p.write_text(LOG)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(K.main([str(p)]), 1)

    def test_baseline_ids_are_well_formed(self):
        ids = K.known_ids(K.BASELINE.read_text())
        self.assertTrue(ids)
        for t in ids:
            self.assertRegex(t, r"^obench\.tests\.test_\w+(\.\w+)+$")


if __name__ == "__main__":
    unittest.main()
