"""env_rerun_drive.sh launches every spec line, including one cell per line.

The 1031e 13090 rerun spec had one cell per line and the driver launched
only the first ("launched 1"): docker run read the rest of the spec from the
loop's stdin, and repeat lines would also have clashed on $PFX-<model>.
"""
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

from thesis.ab.h2env import spec_merge as sm

REPO = Path(__file__).resolve().parents[2]
DRIVER = REPO / "thesis/ab/h2env/env_rerun_drive.sh"
DIG = "sha256:72c59033194aae26f6de67c62c77d742aef1d71849000e308f3ee875ff5169ff"
SRC = "/h2/env-rerun-1031/opus"

STUBS = {
    # sudo just runs the command; docker drains stdin on `run` like the real CLI did.
    "sudo": '#!/bin/bash\nexec "$@"\n',
    "docker": f"""#!/bin/bash
case "$1" in
 image) echo {DIG} ;;
 run) cat >/dev/null; printf '%s\\n' "$*" >> "$STUB_LOG"; echo cid ;;
 *) : ;;
esac
""",
    "curl": "#!/bin/bash\necho stub\n",
}


class MergeTests(unittest.TestCase):
    def test_one_cell_per_line_folds(self):
        lines = [f"opus 13090 2.0.58 {SRC} with/mx-relu/3\n",
                 "\n", "# note\n",
                 f"opus 13090 2.0.58 {SRC} with/mx-relu/7,without/mx-relu/10\n",
                 f"opus 13090 2.0.58 {SRC} with/mx-relu/3\n",
                 f"sonnet 13331 2.0.58 /h2/x/sonnet with/a/1\n"]
        self.assertEqual(sm.merge(lines), [
            f"opus 13090 2.0.58 {SRC} with/mx-relu/3,with/mx-relu/7,without/mx-relu/10",
            "sonnet 13331 2.0.58 /h2/x/sonnet with/a/1"])

    def test_full_run_line_kept(self):
        self.assertEqual(sm.merge([f"opus 3052 2.0.25 {SRC}\n"]), [f"opus 3052 2.0.25 {SRC}"])

    def test_conflicts_refused(self):
        with self.assertRaises(sm.SpecError):
            sm.merge([f"opus 13090 2.0.58 {SRC} a/b/1\n", f"opus 3052 2.0.25 {SRC} a/b/2\n"])
        with self.assertRaises(sm.SpecError):
            sm.merge([f"opus 13090 2.0.58 {SRC}\n", f"opus 13090 2.0.58 {SRC} a/b/2\n"])
        with self.assertRaises(sm.SpecError):
            sm.merge(["opus 13090 2.0.58\n"])


@unittest.skipUnless(shutil.which("bash") and shutil.which("python3"), "needs bash")
class DriverLaunchTests(unittest.TestCase):
    def run_driver(self, spec_text):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        bin_dir = tmp / "bin"; bin_dir.mkdir()
        for name, body in STUBS.items():
            path = bin_dir / name
            path.write_text(body)
            path.chmod(path.stat().st_mode | stat.S_IEXEC)
        spec = tmp / "spec.txt"; spec.write_text(spec_text)
        log = tmp / "docker-run.log"
        env = dict(os.environ, HOME=str(tmp), OB=str(REPO), STOPAT="1", PFX="t",
                   PATH=f"{bin_dir}:{os.environ['PATH']}", STUB_LOG=str(log),
                   PYTHONPATH=str(REPO))
        proc = subprocess.run(["bash", str(DRIVER), str(spec), "out"], env=env,
                              capture_output=True, text=True, timeout=120)
        runs = log.read_text().splitlines() if log.exists() else []
        return proc, runs, (tmp / "h2/out/driver.log").read_text()

    def test_one_cell_per_line_launches_all_cells(self):
        spec = "".join(f"opus 13090 2.0.58 {SRC} {c}\n" for c in
                       ["with/mx-relu/3", "with/mx-relu/7", "without/mx-relu/10",
                        "with/torch-tensor/2"])
        spec += "sonnet 13331 2.0.58 /h2/env-rerun-1031/sonnet without/mx-relu/4\n"
        proc, runs, dlog = self.run_driver(spec)
        self.assertEqual(proc.returncode, 0, dlog + proc.stderr)
        self.assertEqual(len(runs), 2, runs)
        self.assertIn("--name t-opus", runs[0])
        self.assertTrue(runs[0].endswith(
            "with/mx-relu/3,with/mx-relu/7,without/mx-relu/10,with/torch-tensor/2"), runs[0])
        self.assertIn("--name t-sonnet", runs[1])
        self.assertTrue(runs[1].endswith("without/mx-relu/4"), runs[1])

    def test_conflicting_spec_refused_before_launch(self):
        spec = (f"opus 13090 2.0.58 {SRC} a/b/1\n"
                f"opus 3052 2.0.25 {SRC} a/b/2\n")
        proc, runs, dlog = self.run_driver(spec)
        self.assertEqual(proc.returncode, 9)
        self.assertEqual(runs, [])
        self.assertIn("REFUSE spec", dlog)


if __name__ == "__main__":
    unittest.main()
