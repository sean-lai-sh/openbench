"""The launcher imports thesis from its own checkout, not from cwd.

Invoked from ~/ob-f032, ``python -m`` searches that pinned runner first.
Its thesis package has no step8_project, so projection never starts.
"""
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SHELL = ROOT / "thesis/ab/launchers/step8_f032.sh"


def _pin(dest: Path) -> None:
    pkg = dest / "thesis" / "ab"
    pkg.mkdir(parents=True)
    (dest / "thesis" / "__init__.py").write_text("")
    (pkg / "__init__.py").write_text("")
    (pkg / "step8_project.py").write_text(textwrap.dedent("""\
        import sys
        sys.stdout.write("PINNED\\n")
        raise SystemExit(86)
    """))


def launcher_import_cmd(repo: Path) -> list[str]:
    """The command the launcher uses to load step8_project."""
    sh = (repo / "thesis/ab/launchers/step8_f032.sh").read_text()
    if "thesis/ab/launchers/run_module.py" in sh:
        return [sys.executable, str(repo / "thesis/ab/launchers/run_module.py"),
                "thesis.ab.step8_project", "--help"]
    return [sys.executable, "-m", "thesis.ab.step8_project", "--help"]


class LauncherImportTests(unittest.TestCase):
    def test_cwd_pin_does_not_shadow_launcher_thesis(self):
        with tempfile.TemporaryDirectory() as pin:
            _pin(Path(pin))
            env = dict(os.environ)
            # The pin is on the module path ahead of this repo, and it is cwd.
            env["PYTHONPATH"] = pin + os.pathsep + str(ROOT)
            proc = subprocess.run(
                launcher_import_cmd(ROOT), cwd=pin, env=env,
                capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertNotIn("PINNED", proc.stdout + proc.stderr)
            self.assertIn("run_dir", proc.stdout)
            # A checkout that is not the launcher's fails loudly when it has
            # no step8_project. Copy the bootstrap into an empty thesis tree.
            bare = Path(pin) / "bare"
            launchers = bare / "thesis" / "ab" / "launchers"
            launchers.mkdir(parents=True)
            (bare / "thesis" / "__init__.py").write_text("")
            (bare / "thesis" / "ab" / "__init__.py").write_text("")
            bootstrap = ROOT / "thesis/ab/launchers/run_module.py"
            (launchers / "run_module.py").write_text(bootstrap.read_text())
            loud = subprocess.run(
                [sys.executable, str(launchers / "run_module.py"), "thesis.ab.step8_project"],
                cwd=pin, env=env, capture_output=True, text=True)
            self.assertNotEqual(loud.returncode, 0)
            self.assertIn("step8_project", loud.stderr)


if __name__ == "__main__":
    unittest.main()
