"""SEA-106 import pipeline (obench/taskimport): TB1->Harbor conversion, dedupe planning,
the import steps and drop-outs, against a fake docker and a fake validator. No Docker needed."""

from __future__ import annotations

import json
import subprocess
import tempfile
import tomllib
import unittest
from pathlib import Path

from obench.taskimport import pipeline as pl
from obench.taskimport import tb1_to_harbor as tb1
from obench.taskimport.docker import DockerError


class FakeDocker:
    platform = "linux/amd64"

    def __init__(self, images=None, missing=()):
        self.images = images or {}
        self.missing, self.calls = set(missing), []

    def _img(self, ref):
        if ref not in self.images:
            raise DockerError(f"no such image {ref}")
        return self.images[ref]

    def pull(self, ref):
        self.calls.append(("pull", ref))
        if ref in self.missing:
            raise DockerError(f"pull {ref}: manifest unknown")
        self.images.setdefault(ref, {"workdir": "/app", "files": {"data.txt": "x"}, "user": ""})

    def pinned_ref(self, ref):
        self._img(ref)
        return ref.split(":")[0] + "@sha256:" + "a" * 64

    def inspect(self, ref):
        img = self._lookup(ref)
        return {"Id": "sha256:" + "b" * 64, "Config": {"WorkingDir": img["workdir"], "User": img.get("user", "")},
                "RepoDigests": [ref.split(":")[0] + "@sha256:" + "a" * 64]}

    def image_id(self, ref):
        self._img(ref.split("@")[0] if "@" in ref else ref)
        return "sha256:" + ("c" if ref.endswith(":pinned") else "d") * 64

    def workdir(self, ref):
        return self._lookup(ref)["workdir"]

    def _lookup(self, ref):
        if ref in self.images:
            return self.images[ref]
        base = ref.split("@")[0]
        for name, img in self.images.items():
            if name.split(":")[0] == base:
                return img
        raise DockerError(f"no such image {ref}")

    def build(self, context, tag, dockerfile=None, timeout=3600):
        self.calls.append(("build", tag, Path(dockerfile or Path(context) / "Dockerfile").read_text()))
        self.images[tag] = {"workdir": "/app", "files": {"main.py": "print(1)\n"}, "user": ""}

    def copy_out(self, image, src, dest):
        self.calls.append(("copy_out", image, src))
        for rel, text in self._lookup(image)["files"].items():
            (Path(dest) / rel).parent.mkdir(parents=True, exist_ok=True)
            (Path(dest) / rel).write_text(text)


def ok_validator(overrides=None):
    overrides = overrides or {}

    def validate(task_dir, overlay):
        name = Path(task_dir).name
        if name in overrides:
            return overrides[name](overlay)
        return (0, "SCORE: 1.0", 1.0) if overlay else (1, "SCORE: 0", 0.0)
    return validate


def harbor_task(root, name, *, image=f"upstream/x:1", instruction=None, gpus=0, solve=True):
    d = Path(root) / name
    (d / "tests").mkdir(parents=True)
    (d / "tests" / "test.sh").write_text("#!/bin/bash\npytest /tests/test_outputs.py && echo 1 > /logs/verifier/reward.txt\n")
    (d / "tests" / "test_outputs.py").write_text("def test_x():\n    assert True\n")
    (d / "instruction.md").write_text(instruction or f"Do the {name} thing in /app.\n")
    env = f'docker_image = "{image}"\n' if image else ""
    (d / "task.toml").write_text(f'schema_version = "1.1"\n[verifier]\ntimeout_sec = 900.0\n[agent]\ntimeout_sec = 1800.0\n'
                                 f"[environment]\n{env}gpus = {gpus}\n")
    if not image:
        (d / "environment").mkdir()
        (d / "environment" / "Dockerfile").write_text("FROM ghcr.io/laude-institute/t-bench/python-3-13:latest\nWORKDIR /app\n")
    if solve:
        (d / "solution").mkdir()
        (d / "solution" / "solve.sh").write_text("#!/bin/bash\necho done > out.txt\n")
    return d


def tb1_task(root, name, *, compose_services=1, solution_yaml=None, instruction="Write hello.txt"):
    d = Path(root) / name
    (d / "tests").mkdir(parents=True)
    (d / "tests" / "test_outputs.py").write_text("def test_x():\n    assert True\n")
    (d / "tests" / "setup-uv-pytest.sh").write_text("uv add pytest\n")
    (d / "run-tests.sh").write_text("#!/bin/bash\nsource $TEST_DIR/setup-uv-pytest.sh\nuv run pytest $TEST_DIR/test_outputs.py\n")
    (d / "Dockerfile").write_text("FROM ghcr.io/laude-institute/t-bench/python-3-13:latest\nWORKDIR /app\n")
    (d / "data.csv").write_text("a,b\n")
    services = {f"svc{i}" if i else "client": {"build": {"context": "."}} for i in range(compose_services)}
    (d / "docker-compose.yaml").write_text(json.dumps({"services": services}))
    meta = {"instruction": instruction, "difficulty": "hard", "category": "software", "tags": ["x"],
            "max_agent_timeout_sec": 900, "max_test_timeout_sec": 120}
    (d / "task.yaml").write_text(json.dumps(meta))
    if solution_yaml is None:
        (d / "solution.sh").write_text("#!/bin/bash\necho hello > hello.txt\n")
    else:
        (d / "solution.yaml").write_text(json.dumps(solution_yaml))
    return d


class Converter(unittest.TestCase):
    def setUp(self):
        self.src, self.out = Path(tempfile.mkdtemp()), Path(tempfile.mkdtemp())

    def test_tb1_layout_becomes_harbor(self):
        tb1_task(self.src, "make-hello")
        res = tb1.convert_task(self.src / "make-hello", self.out)
        self.assertTrue(res.ok, res.reasons)
        d = self.out / "make-hello"
        self.assertEqual((d / "instruction.md").read_text(), "Write hello.txt\n")
        self.assertTrue((d / "environment" / "Dockerfile").is_file())
        self.assertTrue((d / "environment" / "data.csv").is_file())  # build context kept
        self.assertFalse((d / "environment" / "tests").exists())
        self.assertEqual(sorted(p.name for p in (d / "tests").iterdir()),
                         ["run-tests.sh", "setup-uv-pytest.sh", "test.sh", "test_outputs.py"])
        test_sh = (d / "tests" / "test.sh").read_text()
        self.assertIn("export TEST_DIR=/tests", test_sh)
        self.assertIn("/logs/verifier/reward.txt", test_sh)
        meta = tomllib.loads((d / "task.toml").read_text())
        self.assertEqual((meta["metadata"]["upstream_commit"], meta["verifier"]["timeout_sec"], meta["agent"]["timeout_sec"]),
                         (tb1.TB1_CORE_COMMIT, 120.0, 900.0))
        self.assertIn("echo hello", (d / "solution" / "solve.sh").read_text())
        self.assertEqual(subprocess.run(["bash", "-n", str(d / "tests" / "test.sh")]).returncode, 0)

    def test_refusals(self):
        tb1_task(self.src, "multi", compose_services=2)
        tb1_task(self.src, "interactive", solution_yaml=[{"command": "vim x", "append_enter": True},
                                                         {"command": ":wq", "append_enter": False}])
        tb1_task(self.src, "noinstr", instruction="")
        self.assertIn("multi-container", tb1.convert_task(self.src / "multi", self.out).reasons[0])
        self.assertIn("interactive", tb1.convert_task(self.src / "interactive", self.out).reasons[0])
        self.assertIn("no instruction", tb1.convert_task(self.src / "noinstr", self.out).reasons[0])
        self.assertFalse((self.out / "multi").exists())

    def test_solution_yaml_commands(self):
        tb1_task(self.src, "steps", solution_yaml=[{"command": "apt-get update", "block": True},
                                                   {"command": "echo hi > hi.txt\n", "append_enter": True}])
        res = tb1.convert_task(self.src / "steps", self.out)
        self.assertTrue(res.ok)
        self.assertEqual((self.out / "steps" / "solution" / "solve.sh").read_text().splitlines()[-2:],
                         ["apt-get update", "echo hi > hi.txt"])

    def test_core_ids_from_registry(self):
        reg = self.src / "registry.json"
        reg.write_text(json.dumps([{"name": "terminal-bench-core", "version": "0.1.1", "task_id_subset": ["a", "b"]},
                                   {"name": "terminal-bench-core", "version": "head", "task_id_subset": None}]))
        self.assertEqual(tb1.core_ids(reg), ["a", "b"])
        with self.assertRaises(tb1.ConvertError):
            tb1.core_ids(reg, "9.9")


class Plan(unittest.TestCase):
    def test_dedupe_by_name_and_instruction_in_priority_order(self):
        repo = Path(tempfile.mkdtemp())
        (repo / "tasks-imported" / "terminal-bench-2" / "already").mkdir(parents=True)
        (repo / "tasks-imported" / "terminal-bench-2" / "already" / "checker.sh").write_text("")
        (repo / "tasks-imported" / "terminal-bench-2" / "already" / "instruction.md").write_text("old")
        tb2, tb1d, pro = (Path(tempfile.mkdtemp()) for _ in range(3))
        harbor_task(tb2, "already")
        harbor_task(tb2, "alpha", instruction="Build   the parser.\n")
        harbor_task(tb1d, "beta")
        harbor_task(pro, "alpha")                                          # same name as TB2
        harbor_task(pro, "renamed-alpha", instruction="build the PARSER.")  # same instruction, different name
        harbor_task(pro, "gamma")
        doc = pl.plan([pl.Source("terminal-bench-2", tb2, "r2", "c2"), pl.Source("terminal-bench-core", tb1d, "r1", "c1"),
                       pl.Source("terminal-bench-pro", pro, "rp", "cp")], repo)
        decisions = {(e["source"], e["task"]): (e["decision"], e["duplicate_of"]) for e in doc["entries"]}
        self.assertEqual(decisions[("terminal-bench-2", "already")][0], "duplicate_name")
        self.assertTrue(decisions[("terminal-bench-2", "already")][1].startswith("repo:"))
        self.assertEqual(decisions[("terminal-bench-2", "alpha")], ("import", None))
        self.assertEqual(decisions[("terminal-bench-pro", "alpha")], ("duplicate_name", "terminal-bench-2:alpha"))
        self.assertEqual(decisions[("terminal-bench-pro", "renamed-alpha")],
                         ("duplicate_instruction", "terminal-bench-2:alpha"))
        self.assertEqual(decisions[("terminal-bench-pro", "gamma")], ("import", None))


class Import(unittest.TestCase):
    def setUp(self):
        self.src, self.out = Path(tempfile.mkdtemp()), Path(tempfile.mkdtemp())
        self.source = pl.Source("terminal-bench-2", self.src, "https://github.com/laude-institute/terminal-bench-2", "2fd12b88")

    def entry(self, name):
        return {"source": self.source.name, "task": name, "path": str(self.src / name), "decision": "import"}

    def test_admitted_task_layout(self):
        harbor_task(self.src, "alpha")
        docker = FakeDocker()
        row = pl.Importer(self.out, docker, ok_validator()).import_task(self.entry("alpha"), self.source)
        self.assertEqual(row["status"], "admitted", row)
        d = self.out / "terminal-bench-2" / "alpha"
        self.assertEqual((d / "workspace" / "data.txt").read_text(), "x")
        checker = (d / "checker.sh").read_text()
        self.assertIn("openbench-terminal-bench-2-alpha:pinned", checker)
        self.assertIn("--network none", checker)
        self.assertEqual(subprocess.run(["bash", "-n", str(d / "checker.sh")]).returncode, 0)
        meta = tomllib.loads((d / "task.toml").read_text())
        self.assertEqual((meta["docker_image"], meta["docker_workdir"], meta["checker_timeout_s"]),
                         ("openbench-terminal-bench-2-alpha:pinned", "/app", 1200))
        self.assertTrue(meta["docker_image_id"].startswith("sha256:"))
        derived = (d / "checker_data" / "image" / "Dockerfile").read_text()
        self.assertIn("FROM upstream/x@sha256:" + "a" * 64, derived)  # pinned by digest
        self.assertIn("UV_OFFLINE=1 PIP_NO_INDEX=1", derived)
        self.assertTrue((d / "checker_data" / "oracle" / "solve.sh").is_file())
        self.assertTrue((d / "solution" / "solve.sh").is_file())
        self.assertIn("pinned to `upstream/x@sha256:", (d / "PROVENANCE.md").read_text())
        self.assertEqual([c[0] for c in docker.calls], ["pull", "copy_out", "build"])

    def test_built_environment_records_image_and_bases(self):
        harbor_task(self.src, "built", image=None)
        docker = FakeDocker(images={"ghcr.io/laude-institute/t-bench/python-3-13:latest": {"workdir": "/", "files": {}}})
        row = pl.Importer(self.out, docker, ok_validator()).import_task(self.entry("built"), self.source)
        self.assertEqual(row["status"], "admitted", row)
        self.assertEqual(row["env_image"]["kind"], "built")
        self.assertIn("ghcr.io/laude-institute/t-bench/python-3-13:latest", row["env_image"]["bases"])
        self.assertEqual([c[1] for c in docker.calls if c[0] == "build"],
                         ["openbench-terminal-bench-2-built:env", "openbench-terminal-bench-2-built:pinned"])

    def test_drop_outs_are_moved_and_explained(self):
        cases = {
            "gpu": ({"gpus": 1}, None, "needs 1 GPU"),
            "nowork": ({}, None, "no WORKDIR"),
            "passes": ({}, lambda overlay: (0, "SCORE: 1.0", 1.0), "untouched workspace passes"),
            "netfail": ({}, lambda overlay: (1, "SCORE: 0", 0) if not overlay else
                        (1, "curl: (6) Could not resolve host: pypi.org\nFAIL", 0), "needs network"),
            "badsol": ({}, lambda overlay: (1, "SCORE: 0\nFAIL: reward=0", 0), "solution fails"),
            "pullfail": ({"image": "gone/img:1"}, None, "docker: pull"),
            "nosolve": ({"solve": False}, None, "no solution/solve.sh"),
        }
        docker = FakeDocker(missing={"gone/img:1"})
        overrides = {}
        for name, (kw, validator, _) in cases.items():
            harbor_task(self.src, name, gpus=kw.get("gpus", 0), image=kw.get("image", f"upstream/{name}:1"),
                        solve=kw.get("solve", True))
            if validator:
                overrides[name] = validator
        docker.images["upstream/nowork:1"] = {"workdir": "/", "files": {}}
        importer = pl.Importer(self.out, docker, ok_validator(overrides))
        for name, (_, _, reason) in cases.items():
            with self.subTest(task=name):
                row = importer.import_task(self.entry(name), self.source)
                self.assertEqual(row["status"], "dropped")
                self.assertIn(reason, row["reason"])
                self.assertFalse((self.out / "terminal-bench-2" / name).exists())

    def test_run_is_resumable_and_report_groups_by_source(self):
        harbor_task(self.src, "alpha")
        harbor_task(self.src, "beta", gpus=2)
        doc = pl.plan([self.source], Path(tempfile.mkdtemp()))
        report = self.out / "import-report.jsonl"
        importer = pl.Importer(self.out, FakeDocker(), ok_validator())
        rows = pl.run(doc, self.out, report, importer)
        self.assertEqual(sorted((r["task"], r["status"]) for r in rows), [("alpha", "admitted"), ("beta", "dropped")])
        self.assertEqual(pl.run(doc, self.out, report, importer), [])  # resumed: nothing redone
        md = pl.write_report_md(doc, pl.read_report(report), self.out / "IMPORT_REPORT.md")
        self.assertIn("| terminal-bench-2 | `2fd12b88` | 2 | 0 | 2 | 1 | 1 | 0 |", md)
        self.assertIn("| beta | plan | needs 2 GPU(s) |", md)


if __name__ == "__main__":
    unittest.main()
