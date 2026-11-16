"""Containerized trial executor (obench/reflection/cell_executor.py) against a fake docker.

FakeTrialDocker plays the container: it reads the OpenCode config it was
given, calls the per-trial recording proxy over HTTP (which forwards to a fake
Vertex), prints OpenCode's JSON event stream, and writes into the mounted
workspace. The proxy, wire records, trace and checker run for real."""

from __future__ import annotations

import json
import os
import shutil
import stat
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch as mock_patch

from obench.hardsuite import config as hs_config
from obench.reflection import cell_executor as ce
from obench.reflection import opencode as oc
from obench.reflection import runner as rn
from obench.reflection.patches import PATCH_SCHEMA
from obench.tests.test_reflection_vertex import FakeVertex, default_reply

OPUS = "claude-opus-5-5"
TOOLS = [{"name": "bash", "description": "run", "input_schema": {"type": "object", "properties": {"command": {}}}}]


class FakeTrialDocker:
    def __init__(self, steps=2, write_output=True, timeout=False, image_ids=None, absent=()):
        self.steps, self.write_output, self.timeout = steps, write_output, timeout
        self.image_ids, self.calls, self.absent = image_ids or {}, [], set(absent)

    def has_image(self, ref):
        return ref not in self.absent

    def bridge_gateway(self):
        self.gateways = getattr(self, "gateways", []) + ["bridge"]
        return "127.0.0.1"

    def offline_gateway(self):
        self.gateways = getattr(self, "gateways", []) + ["offline"]
        return "127.0.0.1"

    def image_id(self, ref):
        return self.image_ids.get(ref, "sha256:" + "0" * 64)

    def run_agent(self, args, stdout_path, timeout):
        self.calls.append(args)
        env = dict(args[i + 1].split("=", 1) for i, a in enumerate(args) if a == "-e")
        cfg = json.loads(env["OPENCODE_CONFIG_CONTENT"])
        base = next(iter(cfg["provider"].values()))["options"]["baseURL"]
        workspace = next(args[i + 1].split(":")[0] for i, a in enumerate(args) if a == "-v")
        if self.timeout:
            return None, True
        events = []
        for n in range(1, self.steps + 1):
            body = {"model": OPUS, "stream": True, "max_tokens": 1000, "tools": TOOLS,
                    "system": [{"type": "text", "text": "You are OpenCode."}],
                    "messages": [{"role": "user", "content": "go"}]}
            req = urllib.request.Request(base + "/messages", data=json.dumps(body).encode(), method="POST",
                                         headers={"Content-Type": "application/json", "x-api-key": "openbench-proxy"})
            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    resp.read()
            except urllib.error.HTTPError:
                pass  # OpenCode sees the error; the wire record keeps the status
            msg = f"m{n}"
            events += [{"type": "step_start", "timestamp": n * 10, "sessionID": "s", "part": {"messageID": msg, "type": "step-start"}},
                       {"type": "text", "timestamp": n * 10 + 1, "sessionID": "s",
                        "part": {"messageID": msg, "type": "text", "text": f"step {n}", "time": {"start": 1, "end": 2}}},
                       {"type": "step_finish", "timestamp": n * 10 + 2, "sessionID": "s",
                        "part": {"messageID": msg, "type": "step-finish", "reason": "stop" if n == self.steps else "tool-calls",
                                 "cost": 0.0, "tokens": {"input": 1, "output": 1, "reasoning": 0, "cache": {"read": 0, "write": 0}}}}]
        if self.write_output:
            Path(workspace, "out.txt").write_text("done\n")
        Path(stdout_path).write_text("".join(json.dumps(e) + "\n" for e in events))
        return 0, False


def make_task(root, name="t1", toml=True, checker_image=None, needs_network=None):
    d = Path(root) / name
    (d / "workspace").mkdir(parents=True)
    (d / "workspace" / "seed.txt").write_text("seed\n")
    (d / "solution").mkdir()
    (d / "instruction.md").write_text("Create out.txt in /app.\n")
    head = f'IMAGE="${{BENCH_TASK_IMAGE:-{checker_image}}}"\nWORKDIR="/work"\n' if checker_image else ""
    (d / "checker.sh").write_text(f"#!/bin/bash\n{head}test -f out.txt && echo 'SCORE: 1.0' && exit 0\necho 'SCORE: 0'; exit 1\n")
    if toml:
        flag = "" if needs_network is None else f"solution_needs_network = {str(needs_network).lower()}\n"
        (d / "task.toml").write_text('docker_image = "task-img:pinned"\ndocker_workdir = "/app"\nagent_timeout_s = 600\n' + flag)
    return d


class CellCase(unittest.TestCase):
    def setUp(self):
        self.vertex = ThreadingHTTPServer(("127.0.0.1", 0), FakeVertex)
        self.vertex.seen, self.vertex.reply = [], default_reply
        threading.Thread(target=self.vertex.serve_forever, daemon=True).start()
        self.addCleanup(self.vertex.server_close)
        self.addCleanup(self.vertex.shutdown)
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        pin = oc.load_pin()
        binary = self.tmp / "opencode-src" / "bin" / pin["sha"] / "opencode"
        binary.parent.mkdir(parents=True)
        binary.write_text("#!/bin/sh\necho openbench\n")
        binary.chmod(binary.stat().st_mode | stat.S_IEXEC)
        (binary.parent / "build-stamp.json").write_text('{"kind": "compile"}')
        self.binary = binary
        self.tasks = self.tmp / "tasks"
        make_task(self.tasks)
        host, port = self.vertex.server_address
        self.upstream = f"http://{host}:{port}"

    def executor(self, docker=None, **kw):
        return ce.CellExecutor(self.binary, "proj", lambda: "tok", docker=docker or FakeTrialDocker(),
                               upstream_host=self.upstream, **kw)

    def spec(self, task="t1", patch=None, patch_id=None, index=0):
        tid = rn.trial_id("r", task, OPUS, patch_id, index)
        return rn.TrialSpec(run_id="r", trial_id=tid, task=task, tasks_dir=str(self.tasks), model=OPUS, trial_index=index,
                            patch_id=patch_id, patch=patch, trial_dir=f"trials/{OPUS}/{task}/{tid}")


class Trial(CellCase):
    def test_full_trial_in_the_task_image(self):
        docker = FakeTrialDocker()
        run_dir = self.tmp / "run"
        result = self.executor(docker).run_trial(self.spec(), run_dir)
        self.assertEqual((result.status, result.passed, result.checker_exit, result.steps), ("completed", True, 0, 2))
        self.assertEqual(result.served_models, [OPUS])
        self.assertEqual(result.route_counts["model_calls"], 2)
        self.assertEqual(result.route_counts["route_repairs"], 0)  # Opus is never rewritten
        self.assertEqual(result.thinking_tokens, 240)  # 120 per call, from response usage
        self.assertEqual(result.thinking_tokens_per_step, [120, 120])
        opus_sent = {"thinking": {"type": "adaptive", "display": "summarized"}, "output_config": {"effort": "high"}}
        self.assertEqual(result.thinking_setting["configured"], opus_sent)
        self.assertEqual(result.thinking_setting["sent"], [{"explicit": True, "field": "thinking", "effort": "high",
                                                            "value": opus_sent["thinking"]}])
        self.assertGreater(result.cost_usd, 0)
        self.assertTrue((run_dir / result.trace).is_file())
        self.assertFalse(result.trace.startswith("/"))
        args = docker.calls[0]
        self.assertIn("task-img:pinned", args)
        self.assertTrue(any(a.endswith(":/app") for a in args))
        self.assertTrue(any(a.endswith(":ro") and "opencode-src" in a for a in args))
        self.assertIn("--thinking", args)
        self.assertIn("api.anthropic.com:0.0.0.0", args)
        self.assertEqual(args[args.index("--model") + 1], "vertex-claude-opus-5-5/claude-opus-5-5")
        cell = json.loads((run_dir / result.trace).with_name("cell.json").read_text())
        self.assertEqual((cell["image"], cell["image_source"]), ("task-img:pinned", "task.toml"))
        self.assertEqual(self.vertex.seen[0]["body"]["thinking"], {"type": "adaptive", "display": "summarized"})

    def test_ideation_patch_reaches_the_model_request(self):
        patch = {"schema": PATCH_SCHEMA, "ops": [{"op": "system_append", "text": "Always run the tests."}]}
        result = self.executor().run_trial(self.spec(patch=patch, patch_id="p1"), self.tmp / "run")
        self.assertEqual(result.status, "completed")
        self.assertEqual(self.vertex.seen[0]["body"]["system"][-1]["text"], "Always run the tests.")
        wire = [json.loads(l) for l in (self.tmp / "run" / result.wire).read_text().splitlines()]
        self.assertEqual({w["patch_id"] for w in wire}, {"p1"})

    def test_checker_failure_timeout_and_missing_trace(self):
        result = self.executor(FakeTrialDocker(write_output=False)).run_trial(self.spec(index=1), self.tmp / "run")
        self.assertEqual((result.status, result.passed, result.checker_exit), ("completed", False, 1))
        result = self.executor(FakeTrialDocker(timeout=True)).run_trial(self.spec(index=2), self.tmp / "run")
        self.assertEqual((result.status, result.passed), ("timeout", None))

        class Lossy(FakeTrialDocker):
            def run_agent(self, args, stdout_path, timeout):
                code, t = super().run_agent(args, stdout_path, timeout)
                lines = Path(stdout_path).read_text().splitlines()
                Path(stdout_path).write_text("\n".join(lines[:3]) + "\n")  # one step lost from the stream
                return code, t
        result = self.executor(Lossy()).run_trial(self.spec(index=3), self.tmp / "run")
        self.assertEqual(result.status, "error")
        self.assertIn("trace_error: step_call_mismatch", result.error)

    def test_empty_stop_is_route_truncated_not_a_fail(self):
        from obench.tests.test_reflection_vertex import sse
        calls = []

        def reply(path):
            calls.append(path)
            stop = "end_turn" if len(calls) == 2 else "tool_use"
            body = [{"type": "message_start", "message": {"model": OPUS, "usage": {"input_tokens": 5, "output_tokens": 1}}},
                    {"type": "content_block_delta", "delta": {"type": "thinking_delta", "thinking": "hmm"}}]
            if stop == "tool_use":
                body.append({"type": "content_block_start", "content_block": {"type": "tool_use", "name": "bash", "id": "t"}})
            body += [{"type": "message_delta", "delta": {"stop_reason": stop},
                      "usage": {"output_tokens": 30, "output_tokens_details": {"thinking_tokens": 10}}},
                     {"type": "message_stop"}]
            return 200, "text/event-stream", sse(*body)
        self.vertex.reply = reply
        run_dir = self.tmp / "run"
        result = self.executor(FakeTrialDocker(write_output=False)).run_trial(self.spec(index=4), run_dir)
        self.assertEqual((result.status, result.passed, result.checker_exit), ("route_truncated", None, 1))
        self.assertIn("route_truncated", result.error)
        self.assertTrue((run_dir / result.trace).is_file())
        detail = json.loads((run_dir / result.trace).with_name("route_truncated.json").read_text())
        self.assertEqual(detail["finish_reasons"], ["end_turn"])

    def test_agent_network_follows_solution_needs_network(self):
        make_task(self.tasks, "online", needs_network=True)
        make_task(self.tasks, "offline", needs_network=False)
        cases = [("online", {}, "bridge", "bridge"), ("offline", {}, "offline", ce.OFFLINE_NETWORK),
                 ("t1", {}, "bridge", "bridge"), ("t1", {"unflagged_network": "offline"}, "offline", ce.OFFLINE_NETWORK)]
        for i, (task, kw, network, docker_net) in enumerate(cases):
            with self.subTest(task=task, **kw):
                docker = FakeTrialDocker()
                result = self.executor(docker, **kw).run_trial(self.spec(task=task, index=10 + i), self.tmp / "run")
                self.assertEqual(result.status, "completed")
                args = docker.calls[0]
                self.assertEqual(args[args.index("--network") + 1], docker_net)
                self.assertEqual(docker.gateways, [network])   # the proxy binds on that network's gateway
                self.assertEqual("OPENCODE_DISABLE_MODELS_FETCH=1" in args, network == "offline")
                cell = json.loads((self.tmp / "run" / result.trace).with_name("cell.json").read_text())
                self.assertEqual((cell["agent_network"], cell["network_unflagged"]), (network, task == "t1"))

    def test_missing_digest_image_fails_before_any_call_or_runs_the_tag_when_allowed(self):
        digest = "openbench-tb2-x@sha256:" + "d" * 64
        make_task(self.tasks, "mid")
        (self.tasks / "mid" / "task.toml").write_text(
            f'docker_image = "{digest}"\ndocker_image_tag = "openbench-tb2-x:pinned"\ndocker_workdir = "/app"\n')
        docker = FakeTrialDocker(absent={digest})
        with self.assertRaisesRegex(ce.CellError, "--use-image-tag"):
            self.executor(docker).run_trial(self.spec(task="mid", index=20), self.tmp / "run")
        self.assertEqual((docker.calls, self.vertex.seen), ([], []))
        self.assertEqual(set(self.executor(docker).missing_images([(str(self.tasks), "mid"), (str(self.tasks), "t1")])),
                         {"mid"})
        docker = FakeTrialDocker(absent={digest}, image_ids={"openbench-tb2-x:pinned": "sha256:" + "e" * 64})
        result = self.executor(docker, use_image_tag=True).run_trial(self.spec(task="mid", index=21), self.tmp / "run")
        self.assertEqual(result.status, "completed")
        self.assertIn("openbench-tb2-x:pinned", docker.calls[0])
        cell = json.loads((self.tmp / "run" / result.trace).with_name("cell.json").read_text())
        self.assertEqual(cell["image_pin"], {"pinned": digest, "used": "openbench-tb2-x:pinned",
                                             "used_id": "sha256:" + "e" * 64, "match": False})
        self.assertEqual(result.image, {"ref": "openbench-tb2-x:pinned", "id": "sha256:" + "e" * 64, "pinned": digest,
                                        "matches_pin": False})
        self.assertEqual(cell["image_record"], result.image)
        with self.assertRaisesRegex(ce.CellError, "not on this host either"):
            self.executor(FakeTrialDocker(absent={digest, "openbench-tb2-x:pinned"}), use_image_tag=True).run_trial(
                self.spec(task="mid", index=22), self.tmp / "run")

    def test_4xx_is_an_infra_failure(self):
        calls = []

        def reply(path):
            calls.append(path)
            if len(calls) == 2:
                return 429, "application/json", b'{"error": {"code": 429, "status": "RESOURCE_EXHAUSTED"}}'
            from obench.tests.test_reflection_vertex import default_reply
            return default_reply(path)
        self.vertex.reply = reply
        result = self.executor().run_trial(self.spec(index=30), self.tmp / "run")
        self.assertEqual((result.status, result.passed), ("upstream_4xx", None))
        self.assertIn("-> 429", result.error)
        self.assertEqual(result.thinking_setting["configured"]["output_config"], {"effort": "high"})

    def test_retried_4xx_is_a_covariate_not_a_failure(self):
        calls = []

        def reply(path):
            calls.append(path)
            if len(calls) == 1:
                return 429, "application/json", b'{"error": {"code": 429}}'
            from obench.tests.test_reflection_vertex import default_reply
            return default_reply(path)
        self.vertex.reply = reply

        class Retrying(FakeTrialDocker):  # the 429 is followed by a successful retry, then the next step
            def run_agent(self, args, stdout_path, timeout):
                self.steps = 2
                code, t = super().run_agent(args, stdout_path, timeout)
                return code, t
        docker = Retrying()
        orig = docker.run_agent

        def run_agent(args, stdout_path, timeout):
            env = dict(args[i + 1].split("=", 1) for i, a in enumerate(args) if a == "-e")
            base = next(iter(json.loads(env["OPENCODE_CONFIG_CONTENT"])["provider"].values()))["options"]["baseURL"]
            body = {"model": OPUS, "stream": True, "max_tokens": 10, "tools": TOOLS, "messages": [{"role": "user", "content": "go"}]}
            for _ in range(1):  # call 1 -> 429; OpenCode retries and both steps then succeed
                try:
                    urllib.request.urlopen(urllib.request.Request(base + "/messages", data=json.dumps(body).encode(),
                                                                  method="POST", headers={"Content-Type": "application/json"}),
                                           timeout=10).read()
                except urllib.error.HTTPError:
                    pass
            return orig(args, stdout_path, timeout)
        docker.run_agent = run_agent
        result = self.executor(docker).run_trial(self.spec(index=31), self.tmp / "run")
        self.assertEqual(result.retried_4xx, {"429": 1})
        self.assertEqual((result.status, result.passed, result.steps), ("completed", True, 2))
        trial_dir = self.tmp / "run" / self.spec(index=31).trial_dir
        cell = json.loads((trial_dir / "cell.json").read_text())
        self.assertEqual((cell["retried_4xx"], cell["status"]), ({"429": 1}, "completed"))
        self.assertRegex(cell["code"]["commit"], r"^[0-9a-f]{40}$")
        self.assertEqual(cell["thinking_tokens_status"], {"reported": 2})
        counters = json.loads((trial_dir.parent / "cell_counters.json").read_text())
        self.assertEqual((counters["retried_4xx"], counters["status"]["completed"]), ({"429": 1}, 1))

    def test_gpt_oss_rebuilt_calls_are_logged_per_cell(self):
        from obench.tests.test_reflection_vertex import GptOssRepair
        leak = '<|start|>assistant<|channel|>commentary to=repo_browser.print_tree code<|message|>{"path": "", "depth": 3}<|call|>'
        docs = [GptOssRepair().doc("Explore.", content=leak, finish="tool_calls"),
                GptOssRepair().doc('Read it.{"filePath": "/app/out.txt"}')]
        self.vertex.reply = lambda path: (200, "application/json", docs.pop(0) if docs else GptOssRepair().doc("done", content="Done."))

        class OssDocker(FakeTrialDocker):
            def run_agent(inner, args, stdout_path, timeout):
                env = dict(args[i + 1].split("=", 1) for i, a in enumerate(args) if a == "-e")
                base = next(iter(json.loads(env["OPENCODE_CONFIG_CONTENT"])["provider"].values()))["options"]["baseURL"]
                events = []
                for n in (1, 2):
                    body = {"model": "gpt-oss-120b-maas", "stream": True, "tools": GptOssRepair.TOOLS,
                            "messages": [{"role": "user", "content": "go"}]}
                    urllib.request.urlopen(urllib.request.Request(base + "/chat/completions", data=json.dumps(body).encode(),
                                           method="POST", headers={"Content-Type": "application/json"}), timeout=10).read()
                    events += [{"type": "step_start", "timestamp": n * 10, "sessionID": "s", "part": {"messageID": f"m{n}", "type": "step-start"}},
                               {"type": "reasoning", "timestamp": n * 10 + 1, "sessionID": "s",
                                "part": {"messageID": f"m{n}", "type": "reasoning", "text": "think", "time": {"start": 1, "end": 2}}},
                               {"type": "step_finish", "timestamp": n * 10 + 2, "sessionID": "s",
                                "part": {"messageID": f"m{n}", "type": "step-finish", "reason": "tool-calls", "cost": 0.0,
                                         "tokens": {"input": 1, "output": 1, "reasoning": 0, "cache": {"read": 0, "write": 0}}}}]
                workspace = next(args[i + 1].split(":")[0] for i, a in enumerate(args) if a == "-v")
                Path(workspace, "out.txt").write_text("done\n")
                Path(stdout_path).write_text("".join(json.dumps(e) + "\n" for e in events))
                return 0, False
        spec = rn.TrialSpec(run_id="r", trial_id="oss0", task="t1", tasks_dir=str(self.tasks), model="gpt-oss-120b",
                            trial_index=0, patch_id=None, patch=None, trial_dir="trials/gpt-oss-120b/t1/oss0")
        result = self.executor(OssDocker()).run_trial(spec, self.tmp / "run")
        self.assertEqual(result.route_counts["unknown_recipient_calls"], 1)
        cell_dir = self.tmp / "run" / "trials" / "gpt-oss-120b" / "t1"
        log = [json.loads(l) for l in (cell_dir / "route_repairs.jsonl").read_text().splitlines()]
        self.assertEqual([(r["trial_id"], r["tool"], r["known_tool"]) for r in log],
                         [("oss0", "repo_browser.print_tree", False), ("oss0", "read", True)])
        self.assertEqual(json.loads(log[0]["arguments"]), {"path": "", "depth": 3})
        counters = json.loads((cell_dir / "cell_counters.json").read_text())
        self.assertEqual((counters["route_repairs"], counters["model_errors"]), (2, {"unknown_tool": 1}))

    def test_image_resolution_order(self):
        make_task(self.tasks, "from-checker", toml=False, checker_image="openbench-tb2-x@sha256:" + "1" * 64)
        make_task(self.tasks, "bare", toml=False)
        ex = self.executor()
        t = ex._task(self.spec("from-checker"))
        self.assertEqual((t["image"], t["image_source"], t["workdir"]),
                         ("openbench-tb2-x@sha256:" + "1" * 64, "checker.sh", "/work"))
        t = ex._task(self.spec("bare"))
        self.assertEqual((t["image"], t["image_source"]), ("h1-env:1027-strace", "default_image"))
        with self.assertRaises(ce.CellError):
            self.executor(default_image=None)._task(self.spec("bare"))
        real = Path(__file__).resolve().parents[2] / "tasks-imported" / "terminal-bench-2"
        if (real / "extract-elf" / "checker.sh").is_file():
            spec = rn.TrialSpec("r", "x", "extract-elf", str(real), OPUS, 0, None, None, "t")
            self.assertEqual(ex._task(spec)["image"], "openbench-tb2-extract-elf:pinned")

    def test_pinned_image_id_is_checked(self):
        (self.tasks / "t1" / "task.toml").write_text('docker_image = "task-img:pinned"\ndocker_image_id = "sha256:abc"\n')
        with self.assertRaises(ce.CellError):
            self.executor(FakeTrialDocker(image_ids={"task-img:pinned": "sha256:other"})).run_trial(self.spec(), self.tmp / "r")


class WithRunner(CellCase):
    def test_runner_drives_the_cell_executor(self):
        p = mock_patch.dict(os.environ, {hs_config.CUTOFF_ENV: ""})
        p.start()
        self.addCleanup(p.stop)
        suites = self.tmp / "suites"
        suites.mkdir()
        task = '[[task]]\nid = "{id}"\nsource = "openbench-tb-hard"\nfrontier_rate = {r}\ndomain = "d"\nwhy = "w"\n'
        (suites / "mini.toml").write_text('schema = "openbench.hard-suite/v1"\nname = "mini"\npool = "mini-pool"\n'
                                          + task.format(id="t1", r=0.5))
        (suites / "mini-pool.toml").write_text('schema = "openbench.hard-suite/v1"\nname = "mini-pool"\n'
                                               + task.format(id="t2", r=0.1))
        with mock_patch.dict("obench.hardsuite.suite.SOURCES",
                             {"openbench-tb-hard": dict(rn.load_suite("pilot").tasks[0].bench, tasks_dir=str(self.tasks))}):
            make_task(self.tasks, "t2")
            cfg = rn.RunConfig.from_dict({"run_id": "cellrun", "suite": "mini", "models": [OPUS], "n_trials": 2,
                                          "max_rounds": 1})
            runner = rn.Runner(cfg, self.tmp / "run", self.executor(), suites_dir=suites)
            self.assertEqual(runner.preflight()["round_one_usd"], 4.0)  # 2 trials x the provisional $2 Opus estimate
            status = runner.run()
        self.assertEqual(status["state"], "done")
        rows = rn.read_rows(self.tmp / "run" / "trials.jsonl")
        self.assertEqual([(r["status"], r["passed"]) for r in rows], [("completed", True)] * 2)
        self.assertTrue(all(r["thinking_tokens"] == 240 and r["served_models"] == [OPUS] for r in rows))
        summary = rn.read_rows(self.tmp / "run" / "summary.jsonl")[0]
        self.assertEqual((summary["passes"], summary["verdict"]), (2, "pass"))


    def test_old_upstream_4xx_trials_are_reclassified_offline(self):
        """Rows written by 954286aa (any 4xx -> upstream_4xx, no cell.json, never graded) become completed when the
        4xx was retried and recovered; nothing calls the model again."""
        from obench.reflection import reclassify as rc
        p = mock_patch.dict(os.environ, {hs_config.CUTOFF_ENV: ""})
        p.start()
        self.addCleanup(p.stop)
        suites = self.tmp / "suites"
        suites.mkdir()
        task = '[[task]]\nid = "{id}"\nsource = "openbench-tb-hard"\nfrontier_rate = {r}\ndomain = "d"\nwhy = "w"\n'
        (suites / "mini.toml").write_text('schema = "openbench.hard-suite/v1"\nname = "mini"\npool = "mini-pool"\n'
                                          + task.format(id="t1", r=0.5))
        (suites / "mini-pool.toml").write_text('schema = "openbench.hard-suite/v1"\nname = "mini-pool"\n'
                                               + task.format(id="t2", r=0.1))
        calls = []

        def reply(path):
            calls.append(path)
            if len(calls) == 1:   # trial 0: its first call is a 429 that OpenCode retried
                return 429, "application/json", b'{"error": {"code": 429}}'
            from obench.tests.test_reflection_vertex import default_reply
            return default_reply(path)
        self.vertex.reply = reply

        class RetryFirst(FakeTrialDocker):
            def run_agent(inner, args, stdout_path, timeout):
                if len(calls) == 0:
                    env = dict(args[i + 1].split("=", 1) for i, a in enumerate(args) if a == "-e")
                    base = next(iter(json.loads(env["OPENCODE_CONFIG_CONTENT"])["provider"].values()))["options"]["baseURL"]
                    body = {"model": OPUS, "stream": True, "max_tokens": 10, "tools": TOOLS, "messages": []}
                    try:
                        urllib.request.urlopen(urllib.request.Request(base + "/messages", data=json.dumps(body).encode(),
                                               method="POST", headers={"Content-Type": "application/json"}), timeout=10)
                    except urllib.error.HTTPError:
                        pass
                return FakeTrialDocker.run_agent(inner, args, stdout_path, timeout)
        run_dir = self.tmp / "run"
        with mock_patch.dict("obench.hardsuite.suite.SOURCES",
                             {"openbench-tb-hard": dict(rn.load_suite("pilot").tasks[0].bench, tasks_dir=str(self.tasks))}):
            make_task(self.tasks, "t2")
            cfg = rn.RunConfig.from_dict({"run_id": "old", "suite": "mini", "models": [OPUS], "n_trials": 2, "max_rounds": 1})
            rn.Runner(cfg, run_dir, self.executor(RetryFirst()), suites_dir=suites).run()
            rows = rn.read_rows(run_dir / "trials.jsonl")
            self.assertEqual([r["status"] for r in rows], ["completed", "completed"])
            # make trial 0 look like 954286aa wrote it
            old = dict(rows[0], status="upstream_4xx", passed=None, checker_exit=None, steps=None, trace=None)
            for k in ("retried_4xx", "image_ref", "image_id", "image_matches_pin"):
                old.pop(k)
            (run_dir / rows[0]["trial_dir"] / "cell.json").unlink()
            (run_dir / rows[0]["trial_dir"] / "trace.jsonl").unlink()
            (run_dir / "trials.jsonl").write_text(json.dumps(old) + "\n" + json.dumps(rows[1]) + "\n")
            rn.Runner(cfg, run_dir, self.executor(), suites_dir=suites).rebuild_tables()
            self.assertEqual(rn.read_rows(run_dir / "summary.jsonl")[0]["verdict"], "incomplete")
            seen = len(self.vertex.seen)
            dry = rc.reclassify(run_dir, self.executor(), suites_dir=suites)
            self.assertEqual([(c["from"], c["to"], c["passed"]) for c in dry["changed"]], [("upstream_4xx", "completed", True)])
            self.assertEqual(rn.read_rows(run_dir / "trials.jsonl")[0]["status"], "upstream_4xx")  # dry run wrote nothing
            rc.reclassify(run_dir, self.executor(), apply=True, suites_dir=suites)
            self.assertEqual(len(self.vertex.seen), seen)  # no model calls
        rows = rn.read_rows(run_dir / "trials.jsonl")
        self.assertEqual([(r["status"], r["passed"]) for r in rows], [("completed", True)] * 2)
        self.assertEqual((rows[0]["retried_4xx"], rows[0]["reclassified"]["from"]), ({"429": 1}, "upstream_4xx"))
        self.assertTrue(all(r["image_id"].startswith("sha256:") for r in rows))
        self.assertEqual(rn.read_rows(run_dir / "summary.jsonl")[0]["verdict"], "pass")
        self.assertEqual(len(list(run_dir.glob("trials.pre-reclassify-*.jsonl"))), 1)


if __name__ == "__main__":
    unittest.main()
