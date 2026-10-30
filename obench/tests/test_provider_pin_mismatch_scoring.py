"""A provider pin mismatch mid-run is an unscored env failure, not a NameError.

opencode.py caught ``ProviderPinMismatch`` by a bare name that was never
imported, so any exception reaching that handler raised NameError instead.
"""
import json
import textwrap
import tempfile
import unittest
from pathlib import Path

from obench.cell_columns import excluded_from_scoring, scoring_override_class
from obench.tests import test_provider_pin as _tp
from obench.tests.test_provider_pin import _write_script



class PinMismatchScoringTests(unittest.TestCase):
    _proxy = _tp.CellAbortTests._proxy
    _binary = _tp.CellAbortTests._binary
    _run = _tp.CellAbortTests._run

    def _bun(self, root: Path) -> Path:
        bun = root / "bun"
        _write_script(bun, textwrap.dedent("""\
            #!/usr/bin/env python3
            import pathlib, sys
            args = sys.argv[1:]
            cwd = pathlib.Path(args[args.index("--cwd") + 1])
            for arg in args:
                if arg.startswith("@ai-sdk/anthropic@"):
                    version = arg.rsplit("@", 1)[1]
                    module = cwd / "node_modules" / "@ai-sdk" / "anthropic" / "package.json"
                    module.parent.mkdir(parents=True, exist_ok=True)
                    module.write_text('{"version": "%s"}' % version, encoding="utf-8")
        """))
        return bun

    def test_mismatch_is_env_failure_not_name_error(self):
        root = Path(tempfile.mkdtemp())
        started, request = root / "started", root / "request"
        binary = root / "opencode"
        self._binary(binary, started, request, textwrap.dedent("""\
            print("pkg=@ai-sdk/anthropic version=latest", flush=True)
            time.sleep(15)
            pathlib.Path(REQUEST).write_text("sent", encoding="utf-8")
        """).replace("REQUEST", repr(str(request))))
        row = self._run(root, binary, self._bun(root), no_progress_s=30)
        dump = json.dumps(row)
        self.assertNotIn("NameError", dump)
        self.assertTrue(started.exists())
        self.assertFalse(request.exists())
        self.assertFalse(row.get("completed"))
        self.assertFalse(row["success"])
        self.assertEqual(row["failure_class"], "infra")
        self.assertIn("provider_pin_mismatch", row["failure_reason"])
        self.assertIn("version=latest", row["failure_reason"])
        # Scored as env failure (rerun), not an agent fail.
        self.assertIs(row["env_failure"], True)
        self.assertEqual(row["env_cause"], "provider_pin_mismatch")
        self.assertTrue(excluded_from_scoring(row))
        self.assertEqual(scoring_override_class(row), "infra")
        self.assertNotEqual(row["failure_class"], "wrong_answer")

    def test_infra_row_is_excluded_even_without_env_flag(self):
        row = {"success": False, "failure_class": "infra"}
        self.assertTrue(excluded_from_scoring(row))
        self.assertFalse(excluded_from_scoring({"success": False, "failure_class": "wrong_answer"}))


if __name__ == "__main__":
    unittest.main()
