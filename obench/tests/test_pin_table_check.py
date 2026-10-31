"""pin_table_check refuses a driver pin that differs from the rev2 pin table."""
import unittest

from thesis.ab.h2env import pin_table_check as p


class PinTableCheckTests(unittest.TestCase):
    def test_rev2_pins(self):
        self.assertTrue(p.check(p.DEFAULT_TABLE, "H2", "3052", "opus", "2.0.25")[0])
        self.assertTrue(p.check(p.DEFAULT_TABLE, "H2", "13090", "opus", "2.0.58")[0])
        self.assertTrue(p.check(p.DEFAULT_TABLE, "H2", "13331", "sonnet", "2.0.58")[0])

    def test_mismatch_refused(self):
        ok, msg = p.check(p.DEFAULT_TABLE, "H2", "13090", "opus", "2.0.25")
        self.assertFalse(ok); self.assertIn("2.0.58", msg)
        self.assertEqual(p.main(["--pr", "13331", "--model", "opus", "--pin", "2.0.25"]), 9)

    def test_unknown_refused(self):
        self.assertFalse(p.check(p.DEFAULT_TABLE, "H2", "99999", "opus", "2.0.25")[0])


if __name__ == "__main__":
    unittest.main()
