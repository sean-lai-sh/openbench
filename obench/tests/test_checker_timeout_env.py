"""Checker timeout, env columns, rerun/rescore links, and scoring exclusions.

No model calls. Checker timeouts are forced with a one-second task.toml budget
and a short sleep, not the 600-second heavy-task budget.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

from obench import failure_class
from obench.checker_venv import (
    AGENT_IMAGE,
    AgentEnvironmentError,
    assert_agent_phase,
    attach_checker_venvs,
    normalize_torch_probe,
    note_agent_image,
    run_torch_probe,
)
from obench.cell_columns import (
    CELL_ENV_FIELDS,
    CellWriteError,
    ENV_CAUSE_CHECKER_TIMEOUT,
    excluded_from_scoring,
    rescore_cell,
    write_rerun_cell,
)
from obench.checker_timeout import (
    DEFAULT_CHECKER_TIMEOUT_S,
    HEAVY_CHECKER_TIMEOUT_S,
    checker_timeout_s,
)
from obench.gateway_run import _checker_timeout_for
from obench.run import ROW_FIELDS, append_row
from obench.validate_tasks import run_checker
from thesis.ab.run_ab import execute_cell
from thesis.ab.summarize import countable, load_jsonl

ROOT = Path(__file__).resolve().parents[2]
PACK = ROOT / "data" / "packs" / "openbench-tb-hard"
H2ENV = ROOT / "thesis" / "ab" / "h2env"


def _fake_opencode(path: Path) -> None:
    path.write_text(textwrap.dedent("""\
        #!/usr/bin/env python3
        import json, sys
        args = sys.argv[1:]
        if args == ["--version"]:
            print("cell-test")
            raise SystemExit(0)
        if args[:2] == ["run", "--help"]:
            print("--auto")
            print("-m, --model")
            print("--variant")
            print("--format")
            print("--dir")
            print("--title")
            raise SystemExit(0)
        print(json.dumps({"type": "step_finish", "part": {"tokens": {
            "input": 3, "output": 2, "reasoning": 1,
            "cache": {"read": 0, "write": 0}, "total": 6,
        }}}))
    """), encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def _task(root: Path, name: str, checker: str, *, timeout=None) -> Path:
    task = root / name
    (task / "workspace").mkdir(parents=True)
    (task / "instruction.md").write_text("do the task\n", encoding="utf-8")
    script = task / "checker.sh"
    script.write_text(checker, encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    if timeout is not None:
        (task / "task.toml").write_text(
            f"checker_timeout_s = {timeout}\n", encoding="utf-8",
        )
    return task


class TimeoutResolutionTests(unittest.TestCase):
    def test_heavy_tasks_are_600_and_the_rest_stay_120(self):
        heavy = (
            "torch-tensor",
            "torch-tensor-parallelism",
            "torch-pipeline",
            "torch-pipeline-parallelism",
            "model-extraction",
            "model-extraction-relu-logits",
            "sam-cell-seg",
        )
        for name in heavy:
            with self.subTest(name=name):
                self.assertEqual(
                    checker_timeout_s(name, PACK / name if (PACK / name).is_dir() else None),
                    HEAVY_CHECKER_TIMEOUT_S,
                )
        self.assertEqual(checker_timeout_s("dna-insert", PACK / "dna-insert"), DEFAULT_CHECKER_TIMEOUT_S)
        self.assertEqual(checker_timeout_s("regex-chess", PACK / "regex-chess"), 120)

    def test_task_toml_overrides_the_table(self):
        with tempfile.TemporaryDirectory() as tmp:
            task = _task(Path(tmp), "torch-tensor-parallelism", "#!/bin/bash\nexit 1\n", timeout=45)
            self.assertEqual(checker_timeout_s(task.name, task), 45)

    def test_gateway_and_validate_use_the_same_budget(self):
        torch = PACK / "torch-tensor-parallelism"
        plain = PACK / "dna-insert"
        self.assertEqual(
            _checker_timeout_for(type("T", (), {"name": torch.name, "path": torch})()),
            600,
        )
        self.assertEqual(
            _checker_timeout_for(type("T", (), {"name": plain.name, "path": plain})()),
            120,
        )
        with tempfile.TemporaryDirectory() as tmp:
            task = _task(
                Path(tmp), "quick",
                "#!/bin/bash\nsleep 3\nexit 0\n",
                timeout=1,
            )
            code, output, _score = run_checker(str(task), False)
            self.assertEqual(code, 124)
            self.assertIn("checker timed out after 1s", output)

    def test_execute_cell_records_the_heavy_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _task(root / "tasks", "torch-tensor-parallelism", "#!/bin/bash\nsleep 1\nexit 0\n")
            binary = root / "opencode"
            _fake_opencode(binary)
            dest = root / "cell.json"
            execute_cell({
                "binary": str(binary),
                "config": {},
                "permission_config": False,
                "cell_path": str(dest),
                "tasks_dir": str(root / "tasks"),
                "adapters_dir": str(ROOT / "obench" / "adapters"),
                "model": "claude-opus-5-5",
                "task": "torch-tensor-parallelism",
                "trial": 1,
                "timeout_s": 30,
            })
            row = json.loads(dest.read_text(encoding="utf-8"))
            self.assertTrue(row["success"])
            self.assertEqual(row["checker_timeout_s"], 600)
            self.assertFalse(row["env_failure"])
            self.assertIsNone(row["env_cause"])
            for field in CELL_ENV_FIELDS:
                self.assertIn(field, row)

    def test_execute_cell_marks_a_checker_timeout_as_env_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _task(
                root / "tasks", "demo",
                "#!/bin/bash\nsleep 3\nexit 0\n",
                timeout=1,
            )
            binary = root / "opencode"
            _fake_opencode(binary)
            dest = root / "out" / "1" / "cells" / "with" / "demo" / "1.json"
            (root / "out").mkdir()
            (root / "out" / "quarantine.txt").write_text("pre_fix_runner\n", encoding="utf-8")
            execute_cell({
                "binary": str(binary),
                "config": {},
                "permission_config": False,
                "cell_path": str(dest),
                "tasks_dir": str(root / "tasks"),
                "adapters_dir": str(ROOT / "obench" / "adapters"),
                "model": "claude-opus-5-5",
                "task": "demo",
                "trial": 1,
                "timeout_s": 30,
                "results_dir": str(root / "out"),
            })
            row = json.loads(dest.read_text(encoding="utf-8"))
            self.assertEqual(row["checker_exit"], "timeout")
            self.assertEqual(row["checker_timeout_s"], 1)
            self.assertTrue(row["env_failure"])
            self.assertEqual(row["env_cause"], ENV_CAUSE_CHECKER_TIMEOUT)
            self.assertEqual(row["quarantine"], "pre_fix_runner")
            self.assertFalse(row["success"])
            self.assertNotEqual(failure_class.class_for_report(row), "wrong_answer")
            self.assertFalse(countable(row))


class ColumnAndRerunTests(unittest.TestCase):
    def test_columns_round_trip_through_the_results_log(self):
        for field in CELL_ENV_FIELDS:
            self.assertIn(field, ROW_FIELDS)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "results.jsonl"
            row = {field: None for field in ROW_FIELDS}
            row.update({
                "run_id": "opencode:torch-tensor-parallelism:claude-opus-5-5:trial1",
                "checker_timeout_s": 600,
                "env_failure": True,
                "env_cause": "checker_timeout",
                "rerun_of": None,
                "rescored_from": None,
                "suspect_startup_exit": False,
                "quarantine": None,
            })
            self.assertTrue(append_row(str(path), row))
            loaded = json.loads(path.read_text(encoding="utf-8").strip())
            self.assertEqual(loaded["checker_timeout_s"], 600)
            self.assertTrue(loaded["env_failure"])
            self.assertEqual(loaded["env_cause"], "checker_timeout")
            self.assertIsNone(loaded["rerun_of"])
            self.assertIsNone(loaded["rescored_from"])

    def test_rerun_of_round_trip_leaves_the_original_cell(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_root = root / "original"
            dest_root = root / "rerun"
            cell = source_root / "4204" / "cells" / "without" / "torch-tensor-parallelism" / "1.json"
            cell.parent.mkdir(parents=True)
            original = {
                "run_id": "opencode:torch-tensor-parallelism:claude-opus-5-5:trial1",
                "task": "torch-tensor-parallelism",
                "trial": 1,
                "success": False,
                "failure_class": "timeout",
                "checker_exit": "timeout",
                "env_failure": True,
                "env_cause": "checker_timeout",
            }
            cell.write_text(json.dumps(original, sort_keys=True), encoding="utf-8")
            before = cell.read_bytes()
            written = write_rerun_cell(cell, source_root, dest_root)
            self.assertTrue(written.is_file())
            self.assertNotEqual(written.resolve(), cell.resolve())
            loaded = json.loads(written.read_text(encoding="utf-8"))
            self.assertEqual(loaded["rerun_of"], original["run_id"])
            self.assertIsNone(loaded["rescored_from"])
            self.assertEqual(cell.read_bytes(), before)
            with self.assertRaises(CellWriteError):
                write_rerun_cell(cell, source_root, dest_root)
            self.assertEqual(cell.read_bytes(), before)
            with self.assertRaises(CellWriteError):
                write_rerun_cell(cell, source_root, source_root)
            self.assertEqual(cell.read_bytes(), before)

    def test_execute_cell_rerun_writes_a_new_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _task(root / "tasks", "demo", "#!/bin/bash\nexit 0\n")
            binary = root / "opencode"
            _fake_opencode(binary)
            source_root = root / "original"
            dest_root = root / "rerun"
            rel = Path("1") / "cells" / "with" / "demo" / "1.json"
            source = source_root / rel
            source.parent.mkdir(parents=True)
            original_id = "opencode:demo:claude-opus-5-5:trial1"
            source.write_text(json.dumps({
                "run_id": original_id,
                "task": "demo",
                "success": False,
                "checker_exit": "timeout",
            }), encoding="utf-8")
            before = source.read_bytes()
            dest = dest_root / rel
            execute_cell({
                "binary": str(binary),
                "config": {},
                "permission_config": False,
                "cell_path": str(dest),
                "tasks_dir": str(root / "tasks"),
                "adapters_dir": str(ROOT / "obench" / "adapters"),
                "model": "claude-opus-5-5",
                "task": "demo",
                "trial": 1,
                "timeout_s": 30,
                "results_dir": str(dest_root),
                "rerun_from": str(source_root),
            })
            loaded = json.loads(dest.read_text(encoding="utf-8"))
            self.assertEqual(loaded["rerun_of"], original_id)
            self.assertTrue(loaded["success"])
            self.assertEqual(source.read_bytes(), before)
            self.assertTrue(dest.resolve().is_relative_to(dest_root.resolve()))
            self.assertFalse(str(dest.resolve()).startswith(str(source_root.resolve()) + os.sep))


class RescoreTests(unittest.TestCase):
    def test_rescore_rewrites_only_the_new_cell(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task = _task(
                root / "tasks", "torch-tensor-parallelism",
                "#!/bin/bash\ntest -f answer.txt && exit 0\nexit 1\n",
            )
            workspace = root / "workspace"
            workspace.mkdir()
            (workspace / "answer.txt").write_text("ok\n", encoding="utf-8")
            source_root = root / "original"
            cell = source_root / "4204" / "cells" / "without" / "torch-tensor-parallelism" / "1.json"
            cell.parent.mkdir(parents=True)
            original = {
                "run_id": "opencode:torch-tensor-parallelism:claude-opus-5-5:trial1",
                "task": "torch-tensor-parallelism",
                "trial": 1,
                "success": False,
                "score": 0.0,
                "failure_class": "timeout",
                "checker_exit": "timeout",
                "env_failure": True,
                "env_cause": "checker_timeout",
                "checker_timeout_s": 120,
                "wall_time_s": 68.1,
                "tokens_output": 4502,
                "final_workspace": str(workspace),
            }
            cell.write_text(json.dumps(original), encoding="utf-8")
            before = cell.read_bytes()
            dest = rescore_cell(cell, source_root, root / "rescored", root / "tasks")
            loaded = json.loads(dest.read_text(encoding="utf-8"))
            self.assertEqual(cell.read_bytes(), before)
            self.assertEqual(loaded["rescored_from"], original["run_id"])
            self.assertIsNone(loaded["rerun_of"])
            self.assertTrue(loaded["success"])
            self.assertEqual(loaded["checker_timeout_s"], 600)
            self.assertFalse(loaded["env_failure"])
            self.assertIsNone(loaded["env_cause"])
            self.assertEqual(loaded["failure_class"], "solved")

    def test_rescore_timeout_sets_env_cause_and_does_not_touch_the_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _task(
                root / "tasks", "demo",
                "#!/bin/bash\nsleep 3\nexit 0\n",
                timeout=1,
            )
            workspace = root / "workspace"
            workspace.mkdir()
            source_root = root / "original"
            cell = source_root / "1" / "cells" / "with" / "demo" / "1.json"
            cell.parent.mkdir(parents=True)
            cell.write_text(json.dumps({
                "run_id": "opencode:demo:m:trial1",
                "task": "demo",
                "success": False,
                "failure_class": "wrong_answer",
                "final_workspace": str(workspace),
            }), encoding="utf-8")
            before = cell.read_bytes()
            dest = rescore_cell(cell, source_root, root / "rescored", root / "tasks")
            loaded = json.loads(dest.read_text(encoding="utf-8"))
            self.assertEqual(cell.read_bytes(), before)
            self.assertEqual(loaded["rescored_from"], "opencode:demo:m:trial1")
            self.assertEqual(loaded["checker_exit"], "timeout")
            self.assertTrue(loaded["env_failure"])
            self.assertEqual(loaded["env_cause"], ENV_CAUSE_CHECKER_TIMEOUT)
            self.assertEqual(loaded["checker_timeout_s"], 1)
            self.assertFalse(countable(loaded))
            self.assertNotEqual(failure_class.class_for_report(loaded), "wrong_answer")

    def test_rescore_without_a_workspace_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_root = root / "original"
            cell = source_root / "1" / "cells" / "with" / "demo" / "1.json"
            cell.parent.mkdir(parents=True)
            cell.write_text(json.dumps({
                "run_id": "opencode:demo:m:trial1",
                "task": "demo",
            }), encoding="utf-8")
            before = cell.read_bytes()
            with self.assertRaises(CellWriteError):
                rescore_cell(cell, source_root, root / "rescored", root / "tasks")
            self.assertEqual(cell.read_bytes(), before)
            self.assertFalse((root / "rescored").exists())


class ScoringExclusionTests(unittest.TestCase):
    def test_suspect_startup_exit_is_not_a_wrong_answer(self):
        short = {
            "success": False,
            "failure_class": "wrong_answer",
            "checker_exit": 1,
            "wall_time_s": 12.0,
            "tokens_output": 40,
            "completed": True,
        }
        self.assertTrue(failure_class.class_for_report(short) != "wrong_answer")
        self.assertEqual(failure_class.class_for_report(short), "infra")
        self.assertTrue(excluded_from_scoring(short))
        self.assertFalse(countable(short))
        self.assertTrue(failure_class.is_excluded_from_solve_rate(short))

        at_wall = dict(short, wall_time_s=30)
        at_tokens = dict(short, tokens_output=500)
        self.assertEqual(failure_class.class_for_report(at_wall), "wrong_answer")
        self.assertEqual(failure_class.class_for_report(at_tokens), "wrong_answer")
        self.assertTrue(countable(at_wall))
        self.assertTrue(countable(at_tokens))

        solved = dict(short, success=True, failure_class="solved", checker_exit=0)
        self.assertEqual(failure_class.class_for_report(solved), "solved")
        self.assertTrue(countable(solved))

    def test_explicit_flag_excludes_without_recomputing_tokens(self):
        row = {
            "success": False,
            "failure_class": "wrong_answer",
            "wall_time_s": 900,
            "tokens_output": 8000,
            "suspect_startup_exit": True,
        }
        self.assertNotEqual(failure_class.class_for_report(row), "wrong_answer")
        self.assertFalse(countable(row))

    def test_quarantine_label_drops_the_folder_including_solves(self):
        solved = {
            "success": True,
            "failure_class": "solved",
            "score": 1.0,
            "quarantine": "pre_fix_runner",
        }
        self.assertFalse(countable(solved))
        self.assertTrue(failure_class.is_excluded_from_solve_rate(solved))
        self.assertEqual(failure_class.class_for_report(solved), "infra")
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / "quarantine.txt").write_text("# note\npre_fix_runner\n", encoding="utf-8")
            side = out / "4204" / "with.jsonl"
            side.parent.mkdir(parents=True)
            side.write_text(json.dumps({
                "success": False,
                "failure_class": "wrong_answer",
                "wall_time_s": 100,
                "tokens_output": 1000,
            }) + "\n", encoding="utf-8")
            rows = load_jsonl(side)
            self.assertEqual(rows[0]["quarantine"], "pre_fix_runner")
            self.assertFalse(countable(rows[0]))


class ImagePinTests(unittest.TestCase):
    def test_image_pins_match_the_checker_uvx_lines(self):
        dockerfile = (H2ENV / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("install-checker-deps.sh", dockerfile)
        self.assertIn("FROM h1-env:1022 AS build", dockerfile)
        self.assertIn("FROM scratch", dockerfile)
        self.assertNotIn("h2-env", dockerfile)
        build = (H2ENV / "build.sh").read_text(encoding="utf-8")
        self.assertIn("h2-checker-venvs:latest", build)
        self.assertNotIn("h2-env:1022", build)
        script = (H2ENV / "install-checker-deps.sh").read_text(encoding="utf-8")
        self.assertIn("--index-url", script)
        self.assertIn("torch-index", script)
        for name in (
            "torch-tensor-parallelism",
            "torch-pipeline-parallelism",
            "sam-cell-seg",
        ):
            pinned = (H2ENV / "requirements" / f"{name}.txt").read_text(encoding="utf-8")
            self.assertIn("https://download.pytorch.org/whl/cpu", pinned)
        expected = {
            "torch-tensor-parallelism": ["torch==2.7.0"],
            "torch-pipeline-parallelism": ["torch==2.7.0", "transformers==4.55.0"],
            "model-extraction-relu-logits": ["numpy==2.3.1"],
            "sam-cell-seg": [
                "torch==2.5.1", "torchvision==0.20.1",
                "34bbbfdface3c18e5221aa7de6032d7220c6c6a1",
            ],
        }
        for task, pins in expected.items():
            req = (H2ENV / "requirements" / f"{task}.txt").read_text(encoding="utf-8")
            checker = (
                PACK / task / "checker_data" / "harbor-tests" / "test.sh"
            ).read_text(encoding="utf-8")
            self.assertIn("H2_CHECKER_VENV_ROOT", checker)
            self.assertIn('if [ -x "${_h2_py}" ]', checker)
            for pin in pins:
                self.assertIn(pin, req)
                self.assertIn(pin, checker)


class AgentImageTests(unittest.TestCase):
    def test_build_refuses_to_tag_the_agent_image(self):
        for tag in ("h1-env:1022", "h2-env:1022"):
            proc = subprocess.run(
                ["bash", str(H2ENV / "build.sh"), tag],
                capture_output=True, text=True,
            )
            self.assertEqual(proc.returncode, 2, proc.stderr)
            self.assertIn("agent image", proc.stderr)

    def test_agent_phase_has_no_checker_venvs_and_matches_h1_torch(self):
        h1 = normalize_torch_probe(1, "ModuleNotFoundError: No module named 'torch'\n")
        with tempfile.TemporaryDirectory() as tmp:
            mount = Path(tmp) / "opt" / "h2-checker-venvs"
            assert_agent_phase(mount, (1, "ModuleNotFoundError: No module named 'torch'"), h1)
            self.assertFalse(mount.exists())
            mount.parent.mkdir(parents=True)
            mount.mkdir()
            with self.assertRaises(AgentEnvironmentError) as caught:
                assert_agent_phase(mount, h1, h1)
            self.assertIn("agent phase", str(caught.exception))
            mount.rmdir()
            with self.assertRaises(AgentEnvironmentError) as drifted:
                assert_agent_phase(mount, "imported", h1)
            self.assertIn("import torch", str(drifted.exception))
            self.assertIn(AGENT_IMAGE, str(drifted.exception))

    def test_checker_venvs_are_attached_only_after_the_agent_phase(self):
        h1 = "ModuleNotFoundError:torch"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agent_mount = root / "opt" / "h2-checker-venvs"
            stage = root / "stage"
            (stage / "torch-tensor-parallelism" / "bin").mkdir(parents=True)
            seen = []

            def agent():
                assert_agent_phase(agent_mount, h1, h1)
                seen.append(("agent", agent_mount.exists()))

            agent()
            self.assertEqual(seen, [("agent", False)])
            dest = attach_checker_venvs(stage, root / "cell" / "h2-checker-venvs")
            seen.append(("checker", dest.is_dir(), agent_mount.exists()))
            self.assertEqual(seen[1][0], "checker")
            self.assertTrue((dest / "torch-tensor-parallelism" / "bin").is_dir())
            self.assertFalse(agent_mount.exists())
            with self.assertRaises(AgentEnvironmentError):
                attach_checker_venvs(stage, Path("/opt/h2-checker-venvs"))

    def test_cell_records_the_h1_image_digest_and_hides_venvs_from_the_agent(self):
        live = normalize_torch_probe(*run_torch_probe())
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stage = root / "stage"
            (stage / "marker").mkdir(parents=True)
            _task(root / "tasks", "demo", textwrap.dedent("""\
                #!/bin/bash
                if [ -e /opt/h2-checker-venvs ]; then
                  echo baked into the agent image
                  exit 3
                fi
                test -d "${H2_CHECKER_VENV_ROOT}/marker"
                exit $?
            """))
            binary = root / "opencode"
            _fake_opencode(binary)
            dest = root / "cell.json"
            keys = {
                "OBENCH_AGENT_IMAGE": AGENT_IMAGE,
                "OBENCH_AGENT_IMAGE_DIGEST": "sha256:h1-agent",
                "OBENCH_CHECKER_VENV_STAGE": str(stage),
                "OBENCH_H1_TORCH_PROBE": live,
            }
            saved = {key: os.environ.get(key) for key in keys}
            try:
                os.environ.update(keys)
                execute_cell({
                    "binary": str(binary),
                    "config": {},
                    "permission_config": False,
                    "cell_path": str(dest),
                    "tasks_dir": str(root / "tasks"),
                    "adapters_dir": str(ROOT / "obench" / "adapters"),
                    "model": "claude-opus-5-5",
                    "task": "demo",
                    "trial": 1,
                    "timeout_s": 30,
                })
            finally:
                for key, value in saved.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value
            row = json.loads(dest.read_text(encoding="utf-8"))
            self.assertTrue(row["success"], row.get("checker_stdout"))
            self.assertEqual(row["agent_image"], AGENT_IMAGE)
            self.assertEqual(row["agent_image_digest"], "sha256:h1-agent")
            self.assertNotEqual(row["agent_image"], "h2-checker-venvs")
            self.assertFalse(Path("/opt/h2-checker-venvs").exists())

    def test_digest_is_stamped_without_calling_docker(self):
        saved = {key: os.environ.get(key) for key in (
            "OBENCH_AGENT_IMAGE", "OBENCH_AGENT_IMAGE_DIGEST",
        )}
        try:
            os.environ["OBENCH_AGENT_IMAGE"] = AGENT_IMAGE
            os.environ["OBENCH_AGENT_IMAGE_DIGEST"] = "sha256:pair"
            row = note_agent_image({})
        finally:
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
        self.assertEqual(row["agent_image"], "h1-env:1022")
        self.assertEqual(row["agent_image_digest"], "sha256:pair")


if __name__ == "__main__":
    unittest.main()
