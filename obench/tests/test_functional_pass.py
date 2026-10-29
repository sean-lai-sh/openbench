"""functional_pass: polyglot-rust-c secondary grade from a saved workspace.

Primary score stays the existing checker. functional_pass reruns that checker
inside the task image and skips only the check that /app/polyglot contains
only main.rs. Gate cells in results/pi-oc-gate-1029 are primary 0 because
compiled binaries were left beside main.rs; the saved main.rs still passes
every other check. A known-bad answer is functional_pass 0.
"""

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

from obench.functional_pass import (
    functional_pass,
    strip_only_main_rs_check,
)
from obench.run import ROW_FIELDS, run_cell, run_checker

REPO = Path(__file__).resolve().parents[2]
PACK_TASK = REPO / "data" / "packs" / "openbench-tb-hard" / "polyglot-rust-c"
GATE = REPO / "results" / "pi-oc-gate-1029"
IMAGE = "obench-polyglot-rustc:functional-pass"
CHECKER_TIMEOUT_S = 300

DOCKERFILE = """\
FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \\
      rustc g++ python3 ca-certificates curl bash \\
    && rm -rf /var/lib/apt/lists/* \\
    && mkdir -p /app \\
    && echo polyglot-task-image > /etc/openbench-checker-image
RUN curl -LsSf https://astral.sh/uv/0.9.5/install.sh | sh
ENV PATH="/root/.local/bin:${PATH}"
RUN uv python install 3.13 \\
    && uvx -p 3.13 -w pytest==8.4.1 -w pytest-json-ctrf==0.3.5 pytest --version
"""

# The shell heredoc keeps the newline that terminates the last line. That
# byte is the difference between the captured command text and the file the
# checker hashed.
_HEREDOC = re.compile(r"cat >[^\n]*main\.rs <<'EOF'\n(.*?)\nEOF\n", re.S)

GATE_CELLS = (
    {
        "name": "pi",
        "cell": GATE / "pi" / "claude-sonnet-5-5.json",
        "transcript": (
            GATE / "pi" / "transcripts" / "claude-sonnet-5-5"
            / "pi_polyglot-rust-c_claude-sonnet-5-5_trial1.txt"
        ),
    },
    {
        "name": "opencode",
        "cell": GATE / "opencode" / "claude-sonnet-5-5.json",
        "transcript": (
            GATE / "opencode" / "transcripts" / "claude-sonnet-5-5"
            / "opencode_polyglot-rust-c_claude-opus-5-5_trial1.txt"
        ),
    },
)

KNOWN_BAD_MAIN_RS = 'fn main() { println!("0"); }\n'


def _docker_ok():
    try:
        proc = subprocess.run(
            ["docker", "info", "--format", "{{.ServerVersion}}"],
            capture_output=True, text=True, timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


def _walk_strings(obj, found):
    if isinstance(obj, str):
        found.extend(_HEREDOC.findall(obj))
    elif isinstance(obj, dict):
        for value in obj.values():
            _walk_strings(value, found)
    elif isinstance(obj, list):
        for value in obj:
            _walk_strings(value, found)


def recover_saved_main_rs(transcript):
    """Return the main.rs bytes the cell wrote, including the heredoc newline.

    Accepted only when a later hash check matches checker_workspace_files.
    """
    text = Path(transcript).read_text(encoding="utf-8", errors="replace")
    found = []
    for line in text.splitlines():
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        _walk_strings(obj, found)
    unique = list(dict.fromkeys(found))
    if len(unique) != 1:
        raise AssertionError(
            "expected one main.rs write in %s, found %d" % (transcript, len(unique)))
    return (unique[0] + "\n").encode()


def _primary_score(exit_code, raw_score):
    """Same rule run_cell uses for a checker verdict."""
    if exit_code == 0:
        return 1.0
    if raw_score is not None:
        return raw_score
    return 0.0


class FunctionalPassFieldTests(unittest.TestCase):
    def test_only_the_directory_check_is_removed(self):
        source = (PACK_TASK / "checker_data" / "harbor-tests" / "test_outputs.py").read_text(
            encoding="utf-8")
        patched = strip_only_main_rs_check(source)
        self.assertIsNotNone(patched)
        self.assertNotIn("Expected only main.rs", patched)
        self.assertNotIn('polyglot_files == ["main.rs"]', patched)
        self.assertIn("rustc /app/polyglot/main.rs", patched)
        self.assertIn("g++ -x c++ /app/polyglot/main.rs", patched)
        self.assertIn("assert rust_out == expected and cpp_out == expected", patched)
        self.assertIn("(42, \"433494437\")", patched)
        self.assertIsNone(strip_only_main_rs_check(patched))
        self.assertIsNone(strip_only_main_rs_check(source + source))

    def test_other_tasks_are_null_without_a_checker_run(self):
        self.assertIsNone(functional_pass(
            "regex-chess", "/no/such/workspace", str(PACK_TASK),
            task_image="obench-polyglot-rustc:functional-pass",
        ))
        self.assertIsNone(functional_pass(
            "polyglot-rust-c", "/no/such/workspace", str(PACK_TASK),
            task_image=None,
        ))
        self.assertEqual(ROW_FIELDS[-1], "functional_pass")

    def test_cell_row_is_null_for_other_tasks(self):
        root = tempfile.mkdtemp(prefix="obench-functional-null-")
        self.addCleanup(shutil.rmtree, root, True)
        task = os.path.join(root, "tasks", "tiny")
        os.makedirs(os.path.join(task, "workspace"))
        with open(os.path.join(task, "instruction.md"), "w", encoding="utf-8") as fh:
            fh.write("do nothing\n")
        checker = os.path.join(task, "checker.sh")
        with open(checker, "w", encoding="utf-8") as fh:
            fh.write("#!/bin/sh\nexit 0\n")
        os.chmod(checker, os.stat(checker).st_mode | stat.S_IXUSR)
        row = run_cell(
            "null", "tiny", "m", 1, 30,
            os.path.join(root, "tasks"), os.path.join(root, "adapters"), 30,
            exec_mode="local",
        )
        self.assertEqual(row["score"], 1.0)
        self.assertIsNone(row["functional_pass"])
        self.assertIs(row["checker_defect"], False)


@unittest.skipUnless(_docker_ok(), "docker daemon is not available")
class FunctionalPassGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        probe = subprocess.run(
            ["docker", "image", "inspect", IMAGE],
            capture_output=True, text=True, timeout=30,
        )
        if probe.returncode == 0:
            return
        ctx = tempfile.mkdtemp(prefix="obench-polyglot-image-")
        try:
            with open(os.path.join(ctx, "Dockerfile"), "w", encoding="utf-8") as fh:
                fh.write(DOCKERFILE)
            built = subprocess.run(
                ["docker", "build", "-t", IMAGE, ctx],
                capture_output=True, text=True, timeout=900,
            )
        finally:
            shutil.rmtree(ctx, ignore_errors=True)
        if built.returncode != 0:
            raise unittest.SkipTest(
                "could not build %s: %s" % (IMAGE, (built.stderr or "")[-400:]))

    def _workspace(self, main_rs, leftovers):
        root = tempfile.mkdtemp(prefix="obench-functional-gate-")
        self.addCleanup(shutil.rmtree, root, True)
        poly = os.path.join(root, "polyglot")
        os.makedirs(poly)
        path = os.path.join(poly, "main.rs")
        with open(path, "wb") as fh:
            fh.write(main_rs)
        for name in leftovers:
            with open(os.path.join(poly, name), "wb") as fh:
                fh.write(b"")
        return root

    def test_gate_cells_are_primary_0_and_functional_pass_1(self):
        for spec in GATE_CELLS:
            with self.subTest(cell=spec["name"]):
                cell = json.loads(spec["cell"].read_text(encoding="utf-8"))
                row = cell["row"]
                self.assertEqual(row["task"], "polyglot-rust-c")
                self.assertEqual(row["score"], 0)
                self.assertEqual(row["checker_exit"], 1)
                self.assertIs(row["checker_defect"], False)
                files = row["checker_workspace_files"]
                evidence = files["polyglot/main.rs"]
                main_rs = recover_saved_main_rs(spec["transcript"])
                self.assertEqual(len(main_rs), evidence["bytes"])
                self.assertEqual(hashlib.sha256(main_rs).hexdigest(), evidence["sha256"])
                self.assertIn("polyglot/main", files)
                self.assertIn("polyglot/cmain", files)
                workdir = self._workspace(main_rs, ("main", "cmain"))
                before = hashlib.sha256(
                    (Path(workdir) / "polyglot" / "main.rs").read_bytes()
                ).hexdigest()
                exit_code, raw_score, stdout, _stderr = run_checker(
                    str(PACK_TASK), workdir, CHECKER_TIMEOUT_S,
                    task_image=IMAGE, container_workdir="/app",
                )
                self.assertEqual(exit_code, 1, stdout)
                self.assertIn("Expected only main.rs", stdout)
                self.assertEqual(_primary_score(exit_code, raw_score), 0)
                grade = functional_pass(
                    "polyglot-rust-c", workdir, str(PACK_TASK),
                    task_image=IMAGE, container_workdir="/app",
                    timeout_s=CHECKER_TIMEOUT_S,
                )
                self.assertEqual(grade, 1)
                # The grade is computed from a copy. Leftover names stay.
                self.assertEqual(
                    hashlib.sha256(
                        (Path(workdir) / "polyglot" / "main.rs").read_bytes()
                    ).hexdigest(),
                    before,
                )
                self.assertEqual((Path(workdir) / "polyglot" / "main").read_bytes(), b"")
                self.assertEqual((Path(workdir) / "polyglot" / "cmain").read_bytes(), b"")

    def test_known_bad_answer_is_functional_pass_0(self):
        workdir = self._workspace(KNOWN_BAD_MAIN_RS.encode(), ())
        grade = functional_pass(
            "polyglot-rust-c", workdir, str(PACK_TASK),
            task_image=IMAGE, container_workdir="/app",
            timeout_s=CHECKER_TIMEOUT_S,
        )
        self.assertEqual(grade, 0)


if __name__ == "__main__":
    unittest.main()
