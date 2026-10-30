"""Stage 4 base agent (AC1): slots, fixed rows, version hash, run loop.

Stubbed model only; no network beyond a loopback test server.
"""
import copy
import csv
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from thesis.base_agent import config as C
from thesis.base_agent import modules
from thesis.base_agent.agent import Agent, HttpModelClient
from thesis.base_agent.interfaces import INTERFACES, ModelClient, ModelError
from thesis.base_agent.slots import ROWS, SLOTS, fully_fixed_slots, non_swappable_rows

REPO = Path(__file__).resolve().parents[2]
SHEET = REPO / "prereg" / "harness-components-2026-10-24.csv"


def text(t):
    return {"role": "assistant", "content": [{"type": "text", "text": t}], "stop_reason": "end_turn",
            "usage": {"input_tokens": 10, "output_tokens": 2}}


def use(name, args, i=1):
    return {"role": "assistant", "stop_reason": "tool_use",
            "content": [{"type": "tool_use", "id": f"t{i}", "name": name, "input": args}],
            "usage": {"input_tokens": 100, "output_tokens": 5, "cache_read_input_tokens": 7}}


class Scripted(ModelClient):
    def __init__(self, replies):
        self.replies, self.requests = list(replies), []

    def complete(self, request, role="main"):
        self.requests.append((role, copy.deepcopy(request)))
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def agent_for(cfg_name, client, workdir, instruction="do it", arm="swap", cfg=None, fixed=None):
    cfg = cfg or C.load_config(cfg_name)
    fixed = fixed or C.load_fixed()
    resolved = C.resolve(cfg, fixed, arm)
    a = Agent(resolved, C.version_record(cfg, fixed, resolved), client, "claude-test", workdir, instruction)
    a.m["M12"].sleep = lambda s: None
    return a


class SlotTable(unittest.TestCase):
    def test_rows_match_the_sheet(self):
        with open(SHEET) as fh:
            sheet = list(csv.DictReader(fh))
        self.assertEqual(len(sheet), 34)
        self.assertEqual([(r.layer, r.feature) for r in ROWS], [(s["layer"], s["feature"]) for s in sheet])

    def test_every_slot_has_an_interface_rows_and_an_implementation(self):
        self.assertEqual(list(SLOTS), [f"M{i}" for i in range(1, 14)])
        self.assertEqual(set(INTERFACES), set(SLOTS))
        for slot in SLOTS:
            self.assertTrue(modules.REGISTRY[slot], slot)
            self.assertTrue(any(r.slot == slot for r in ROWS), slot)

    def test_fully_fixed_slots(self):
        self.assertEqual(fully_fixed_slots(), ["M4", "M12", "M13"])

    def test_register_rejects_wrong_interface(self):
        with self.assertRaises(TypeError):
            modules.register("M1", "bogus", modules.ORIGINAL)(modules.NoCache)


class FixedRows(unittest.TestCase):
    def test_fixed_file_covers_every_fixed_and_infra_row(self):
        fixed = C.load_fixed()
        self.assertEqual({int(k) for k in fixed["rows"]}, {r.row for r in non_swappable_rows()})

    def test_missing_row_fails(self):
        fixed = C.load_fixed()
        del fixed["rows"]["19"]
        with self.assertRaisesRegex(C.ConfigError, "19"):
            C.validate_fixed(fixed)

    def test_infra_row_cannot_change_a_module(self):
        fixed = C.load_fixed()
        fixed["rows"]["6"]["set"] = {"x": 1}
        with self.assertRaisesRegex(C.ConfigError, "infra"):
            C.validate_fixed(fixed)


class Sources(unittest.TestCase):
    def test_every_module_and_tool_cites_a_source(self):
        modules.load_harness_modules()
        for slot, impls in modules.REGISTRY.items():
            for name in impls:
                self.assertIn(f"{slot}:{name}", modules.SOURCES)
        for family, name in modules.TOOLS:
            self.assertIn(f"tool:{family}:{name}", modules.SOURCES)
        for key, src in modules.SOURCES.items():
            self.assertNotRegex(src.lower(), r"claude[- ]?code|anthropic-ai/claude", key)

    def test_source_must_be_original_or_pinned_repo(self):
        for bad in ("", "pi", "badlogic/pi-mono:core/x.ts", "badlogic/pi-mono@main:core/x.ts"):
            with self.assertRaises(ValueError, msg=bad):
                modules.register("M3", f"bad{len(bad)}", bad)(modules.NoCache)
        modules._check_source("badlogic/pi-mono@d0aa218:packages/coding-agent/src/core/tools/edit.ts", "ok")


class Configs(unittest.TestCase):
    def test_config_cannot_choose_a_fixed_slot(self):
        cfg = C.load_config("base")
        cfg["modules"]["M4"] = {"impl": "fixed", "params": {"temperature": 1.0}}
        with self.assertRaisesRegex(C.ConfigError, "fixed slots go in fixed.toml"):
            C.resolve(cfg, C.load_fixed(), "swap")

    def test_missing_slot_and_unknown_impl_fail(self):
        cfg = C.load_config("base")
        del cfg["modules"]["M6"]
        with self.assertRaisesRegex(C.ConfigError, "M6"):
            C.resolve(cfg, C.load_fixed(), "swap")
        cfg = C.load_config("base")
        cfg["modules"]["M6"] = {"impl": "nope"}
        with self.assertRaisesRegex(C.ConfigError, "unknown implementation"):
            C.resolve(cfg, C.load_fixed(), "swap")

    def test_harness_config_needs_citations(self):
        cfg = C.load_config("base")
        cfg["harness"], cfg["harness_pin"] = "pi", "abc"
        with self.assertRaisesRegex(C.ConfigError, "row 1 .*citation"):
            C.validate_config(cfg)

    def test_swap_applies_fixed_rows_parity_keeps_harness_values(self):
        cfg = C.load_config("base")
        cfg["modules"]["M2"]["params"]["tools"] = ["bash", "read", "edit", "write", "webfetch"]
        cfg["parity"] = {"M4": {"impl": "fixed", "params": {"max_tokens": 8000, "temperature": 0.3}}}
        fixed = C.load_fixed()
        swap, parity = C.resolve(cfg, fixed, "swap"), C.resolve(cfg, fixed, "parity")
        self.assertIn("webfetch", swap["modules"]["M2"]["params"]["drop_tools"])
        self.assertNotIn("drop_tools", parity["modules"]["M2"]["params"])
        self.assertEqual(swap["modules"]["M4"]["params"], {"max_tokens": 32000})
        self.assertEqual(parity["modules"]["M4"]["params"]["temperature"], 0.3)
        for r in (swap, parity):  # enforced in both arms
            self.assertIs(r["modules"]["M1"]["params"]["memory_files"], False)
            self.assertEqual(r["modules"]["M11"]["params"]["max_steps"], 1000)
            self.assertEqual(r["modules"]["M13"]["impl"], "allow_all")


class FixedRowsAcrossConfigs(unittest.TestCase):
    """Fixed and runner-owned rows must be identical across configs. This
    diffs ``fixed_projection`` for every config in configs/, per arm."""

    def projections(self, arm):
        fixed = C.load_fixed()
        out = {}
        for path in sorted(C.CONFIG_DIR.glob("*.toml")):
            if path.stem == "fixed":
                continue
            cfg = C.load_config(path.stem)
            out[path.stem] = C.fixed_projection(C.resolve(cfg, fixed, arm), fixed)
        return out

    def test_identical_in_each_arm(self):
        for arm in C.ARMS:
            proj = self.projections(arm)
            first_name, first = next(iter(proj.items()))
            for name, p in proj.items():
                with self.subTest(arm=arm, config=name):
                    self.assertEqual(p, first, f"{name} differs from {first_name} on a fixed row")

    def test_swap_projection_covers_every_fixed_and_infra_row(self):
        for p in self.projections("swap").values():
            self.assertEqual({k for k in p if k.startswith("row")},
                             {f"row{r.row}" for r in non_swappable_rows()})
            anchored = {s for s, v in C.load_fixed()["slots"].items() if v.get("swap") == "anchor"}
            self.assertEqual(set(fully_fixed_slots()) - anchored - set(p), set())
            self.assertEqual(anchored, {"M4"})
            self.assertEqual(p["row19"]["still_exposed"], [])

    def test_swap_holds_the_anchor_value_for_row_9(self):
        """Row 9 ruling: swap configs hold the anchor's sampling; every config
        sharing an anchor sends the same M4."""
        fixed = C.load_fixed()
        derived = C.load_config("base")
        derived["name"], derived["anchor"] = "base-on-pi", "pi"
        pi_swap = C.resolve(C.load_config("pi"), fixed, "swap")
        derived_swap = C.resolve(derived, fixed, "swap")
        self.assertEqual(C.anchor_projection(pi_swap, fixed), C.anchor_projection(derived_swap, fixed))
        self.assertEqual(derived_swap["modules"]["M4"], C.load_config("pi")["parity"]["M4"])
        self.assertEqual(derived_swap["anchor"], "pi")
        base_swap = C.resolve(C.load_config("base"), fixed, "swap")
        self.assertEqual(base_swap["modules"]["M4"]["params"], {"max_tokens": 32000})
        self.assertIsNone(base_swap["anchor"])

    def test_parity_projection_leaves_out_harness_rows_even_when_not_overridden(self):
        fixed = C.load_fixed()
        cfg = C.load_config("base")
        with_override = copy.deepcopy(cfg)
        with_override["parity"] = {"M4": {"impl": "fixed", "params": {"max_tokens": 1}}}
        a = C.fixed_projection(C.resolve(cfg, fixed, "parity"), fixed)
        b = C.fixed_projection(C.resolve(with_override, fixed, "parity"), fixed)
        self.assertEqual(a, b)
        self.assertNotIn("M4", a)
        self.assertNotIn("row19", a)

    def test_a_config_that_overrides_a_fixed_value_is_caught(self):
        fixed = C.load_fixed()
        cfg = C.load_config("base")
        cfg["modules"]["M1"]["params"]["memory_files"] = True  # overwritten by row 14
        cfg["modules"]["M2"]["params"]["mcp"] = True  # overwritten by row 20
        good = C.fixed_projection(C.resolve(C.load_config("base"), fixed, "swap"), fixed)
        self.assertEqual(C.fixed_projection(C.resolve(cfg, fixed, "swap"), fixed), good)
        resolved = C.resolve(C.load_config("base"), fixed, "swap")
        resolved["modules"]["M11"]["params"]["max_steps"] = 5  # simulated drift
        self.assertNotEqual(C.fixed_projection(resolved, fixed), good)


class VersionHash(unittest.TestCase):
    def setUp(self):
        self.fixed = C.load_fixed()
        self.cfg = C.load_config("base")

    def record(self, cfg=None, arm="swap", fixed=None):
        cfg, fixed = cfg or self.cfg, fixed or self.fixed
        return C.version_record(cfg, fixed, C.resolve(cfg, fixed, arm))

    def test_stable_across_key_order(self):
        reordered = json.loads(json.dumps(self.cfg), object_pairs_hook=lambda kv: dict(reversed(kv)))
        self.assertEqual(self.record()["base_agent_version"], self.record(reordered)["base_agent_version"])

    def test_changes_with_config_arm_and_fixed_rows(self):
        base = self.record()["base_agent_version"]
        cfg = copy.deepcopy(self.cfg)
        cfg["modules"]["M8"]["params"]["default_timeout_s"] = 10
        self.assertNotEqual(base, self.record(cfg)["base_agent_version"])
        self.assertNotEqual(base, self.record(arm="parity")["base_agent_version"])
        fixed = copy.deepcopy(self.fixed)
        fixed["rows"]["23"]["set"]["max_steps"] = 50
        self.assertNotEqual(base, self.record(fixed=fixed)["base_agent_version"])

    def test_record_fields_and_provisional_rows(self):
        r = self.record()
        for k in ("base_agent_version", "framework_hash", "config_hash", "fixed_hash", "resolved_hash", "fixed_rows_hash",
                  "anchor_rows_hash", "anchor",
                  "arm", "harness", "harness_pin", "provisional_fixed_rows"):
            self.assertIn(k, r)
        self.assertEqual(r["provisional_fixed_rows"], [23, 24])  # row 9 ruled 2026-10-30

    def test_framework_hash_covers_code_not_configs(self):
        files = {str(p.relative_to(C.PKG)) for p in C.framework_files()}
        self.assertIn("agent.py", files)
        self.assertFalse(any(f.startswith("configs/") for f in files))


class Loop(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.wd = self.tmp.name
        Path(self.wd, "a.txt").write_text("hello world\n")

    def tearDown(self):
        self.tmp.cleanup()

    def test_tools_edit_files_and_result_logs_version(self):
        client = Scripted([
            use("bash", {"command": "echo hi > b.txt"}, 1),
            use("edit", {"path": "a.txt", "old_text": "world", "new_text": "there"}, 2),
            use("read", {"path": "a.txt"}, 3),
            text("done"),
        ])
        a = agent_for("base", client, self.wd)
        res = a.run()
        self.assertEqual(res["stop"], "end_turn")
        self.assertEqual(Path(self.wd, "b.txt").read_text(), "hi\n")
        self.assertEqual(Path(self.wd, "a.txt").read_text(), "hello there\n")
        self.assertEqual(res["final_text"], "done")
        self.assertEqual(res["tool_calls"], {"bash": 1, "edit": 1, "read": 1})
        self.assertEqual(res["usage"]["input_tokens"], 310)
        self.assertEqual(res["usage"]["cache_read_input_tokens"], 21)
        self.assertEqual(res["version"], a.version)
        role, req = client.requests[0]
        self.assertEqual(role, "main")
        self.assertEqual([t["name"] for t in req["tools"]], ["bash", "read", "edit", "write"])
        self.assertEqual(req["system"][-1]["cache_control"], {"type": "ephemeral"})
        self.assertEqual(req["max_tokens"], 32000)
        read_result = client.requests[3][1]["messages"][-1]["content"][0]
        self.assertIn("hello there", read_result["content"])

    def test_cache_marks_do_not_accumulate_in_history(self):
        client = Scripted([use("bash", {"command": "true"}), text("ok")])
        a = agent_for("base", client, self.wd)
        res = a.run()
        marked = [b for m in res["messages"] if isinstance(m["content"], list) for b in m["content"]
                  if "cache_control" in b]
        self.assertEqual(marked, [])

    def test_tool_error_goes_back_to_the_model(self):
        client = Scripted([use("edit", {"path": "a.txt", "old_text": "absent", "new_text": "x"}), text("ok")])
        agent_for("base", client, self.wd).run()
        result = client.requests[1][1]["messages"][-1]["content"][0]
        self.assertTrue(result["is_error"])
        self.assertIn("Could not find", result["content"])

    def test_step_cap(self):
        fixed = C.load_fixed()
        fixed["rows"]["23"]["set"]["max_steps"] = 2
        client = Scripted([use("bash", {"command": "true"}, i) for i in range(5)])
        res = agent_for("base", client, self.wd, fixed=fixed).run()
        self.assertEqual((res["stop"], res["steps"]), ("max_steps", 2))

    def test_retry_then_success_and_non_retryable_stops(self):
        client = Scripted([ModelError("overloaded", 529, True), text("ok")])
        res = agent_for("base", client, self.wd).run()
        self.assertEqual(res["stop"], "end_turn")
        self.assertEqual([e["event"] for e in res["events"]], ["retry"])
        client = Scripted([ModelError("bad request", 400, False)])
        self.assertEqual(agent_for("base", client, self.wd).run()["stop"], "model_error")

    def test_permissions_deny_is_logged(self):
        fixed = C.load_fixed()
        fixed["slots"]["M13"]["params"] = {"deny_tools": ["bash"]}
        client = Scripted([use("bash", {"command": "touch x"}), text("ok")])
        res = agent_for("base", client, self.wd, fixed=fixed).run()
        self.assertFalse(Path(self.wd, "x").exists())
        self.assertEqual(res["events"][0]["event"], "permission_denied")

    def test_title_side_call_is_tagged(self):
        cfg = C.load_config("base")
        cfg["modules"]["M5"] = {"impl": "title", "params": {"max_tokens": 32}}
        client = Scripted([text("A title"), text("ok")])
        agent_for("base", client, self.wd, cfg=cfg).run()
        self.assertEqual([r for r, _ in client.requests], ["side:title", "main"])
        self.assertNotIn("tools", client.requests[0][1])

    def test_summarize_compacts_at_threshold(self):
        cfg = C.load_config("base")
        cfg["modules"]["M6"] = {"impl": "summarize", "params": {"context_window": 1000, "threshold": 0.1}}
        client = Scripted([use("bash", {"command": "true"}), text("summary text"), text("ok")])
        res = agent_for("base", client, self.wd, cfg=cfg).run()
        self.assertEqual([r for r, _ in client.requests], ["main", "side:summary", "main"])
        self.assertIn("summary text", client.requests[2][1]["messages"][0]["content"][0]["text"])
        self.assertIn("compaction", [e["event"] for e in res["events"]])

    def test_doom_loop_warns(self):
        cfg = C.load_config("base")
        cfg["modules"]["M11"]["params"] = {"hooks": ["doom_loop"], "doom_action": "warn"}
        client = Scripted([use("bash", {"command": "true"}, i) for i in range(3)] + [text("ok")])
        agent_for("base", client, self.wd, cfg=cfg).run()
        last_turn = client.requests[3][1]["messages"][-1]["content"]
        self.assertEqual(last_turn[-1]["type"], "text")
        self.assertIn("same tool call 3 times", last_turn[-1]["text"])


class Executor(unittest.TestCase):
    def test_timeout_and_tail_truncation(self):
        ex = modules.build("M8", "shell", {"default_timeout_s": 0.5, "max_lines": 3, "keep": "tail"})
        with tempfile.TemporaryDirectory() as wd:
            r = ex.run("sleep 5", wd)
            self.assertTrue(r.timed_out)
            self.assertIn("timed out", ex.format(r))
            r = ex.run("seq 1 10", wd)
            self.assertTrue(r.truncated)
            self.assertEqual(r.output.split("\n")[-2:], ["10", ""])
            self.assertNotIn("\n1\n", "\n" + r.output)

    def test_millisecond_timeouts(self):
        ex = modules.build("M8", "shell", {"timeout_unit": "ms"})
        with tempfile.TemporaryDirectory() as wd:
            self.assertTrue(ex.run("sleep 5", wd, timeout_s=300).timed_out)


class Http(unittest.TestCase):
    def test_posts_messages_with_call_role(self):
        seen = []

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                body = self.rfile.read(int(self.headers["content-length"]))
                seen.append((self.path, dict(self.headers), json.loads(body)))
                out = json.dumps(text("ok")).encode()
                self.send_response(200)
                self.send_header("content-length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)

        srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            c = HttpModelClient(f"http://127.0.0.1:{srv.server_address[1]}")
            self.assertEqual(c.complete({"model": "m"}, role="side:title")["content"][0]["text"], "ok")
        finally:
            srv.shutdown()
            srv.server_close()
        path, headers, body = seen[0]
        self.assertEqual(path, "/v1/messages")
        self.assertEqual({k.lower(): v for k, v in headers.items()}["x-ob-call-role"], "side:title")
        self.assertEqual(body, {"model": "m"})


if __name__ == "__main__":
    unittest.main()
