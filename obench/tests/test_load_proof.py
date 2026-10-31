"""load_proof: module hook log, image scan, compiled-in builds, and the rule."""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from obench import load_proof as lp
from obench.run import _apply_load_proof


def _pkg(root, version, *sub):
    d = Path(root, *sub, "node_modules", "@ai-sdk", "anthropic")
    d.mkdir(parents=True, exist_ok=True)
    (d / "package.json").write_text(json.dumps({"name": "@ai-sdk/anthropic", "version": version}))
    (d / "dist").mkdir(exist_ok=True)
    (d / "dist" / "index.mjs").write_text("export const x = 1;\n")
    return str(d)


def _log(path, *recs):
    Path(path).write_text("".join(json.dumps(r) + "\n" for r in recs))


class Judge(unittest.TestCase):
    def test_user_agent_stays_main_proof(self):
        v = lp.judge_load_proof(pin="2.0.25", ua_version="2.0.25", hook=None)
        self.assertEqual((v["load_proof_basis"], v["load_proof"]), ("user_agent", "pass"))
        v = lp.judge_load_proof(pin="2.0.25", ua_version="2.0.58",
                                hook={"started": True, "loaded": [{"path": "/x", "version": "2.0.25"}]}, copies=[])
        self.assertEqual((v["load_proof_basis"], v["load_proof"]), ("user_agent", "fail"))
        self.assertEqual(lp.judge_load_proof(pin="2.0.25", ua_version="mixed:2.0.25,2.0.58")["load_proof"], "fail")

    def test_module_hook_pass(self):
        hook = {"started": True, "loaded": [{"path": "/c/node_modules/@ai-sdk/anthropic", "version": "2.0.0-beta.5"}]}
        v = lp.judge_load_proof(pin="2.0.0-beta.5", hook=hook,
                                copies=[{"path": "/c/node_modules/@ai-sdk/anthropic", "version": "2.0.0-beta.5"}])
        self.assertEqual((v["load_proof_basis"], v["load_proof"]), ("module_hook", "pass"))

    def test_missing_log_is_unproven(self):
        self.assertEqual(lp.judge_load_proof(pin="2.0.0")["load_proof"], "unproven")
        self.assertEqual(lp.judge_load_proof(pin="2.0.0", hook={"started": False, "loaded": []})["load_proof"], "unproven")
        self.assertEqual(lp.judge_load_proof(pin="2.0.0", hook={"started": True, "loaded": []}, copies=[])["load_proof"], "unproven")

    def test_mixed_versions_fail(self):
        hook = {"started": True, "loaded": [{"path": "/a", "version": "2.0.0"}, {"path": "/b", "version": "2.0.58"}]}
        v = lp.judge_load_proof(pin="2.0.0", hook=hook, copies=[])
        self.assertEqual(v["load_proof"], "fail")
        self.assertIn("mixed", v["load_proof_reason"])

    def test_wrong_version_and_other_copy_fail(self):
        one = {"started": True, "loaded": [{"path": "/a", "version": "2.0.0"}]}
        self.assertEqual(lp.judge_load_proof(pin="2.0.25", hook=one, copies=[])["load_proof"], "fail")
        v = lp.judge_load_proof(pin="2.0.0", hook=one, copies=[{"path": "/a", "version": "2.0.0"},
                                                               {"path": "/usr/lib/node_modules/@ai-sdk/anthropic", "version": "3.0.1"}])
        self.assertEqual(v["load_proof"], "fail")
        self.assertIn("other copies", v["load_proof_reason"])
        self.assertEqual(lp.judge_load_proof(pin="2.0.0", hook=one, copies=None)["load_proof"], "unproven")

    def test_compiled_in_build(self):
        clean = {"started": True, "loaded": []}
        v = lp.judge_load_proof(pin="3.0.71", hook=clean, embedded_version="3.0.71", compiled=True)
        self.assertEqual((v["load_proof_basis"], v["load_proof"]), ("module_hook", "pass"))
        self.assertEqual(lp.judge_load_proof(pin="3.0.71", hook=clean, embedded_version="3.0.64", compiled=True)["load_proof"], "fail")
        self.assertEqual(lp.judge_load_proof(pin="3.0.71", hook=None, embedded_version="3.0.71", compiled=True)["load_proof"], "unproven")
        out = {"started": True, "loaded": [{"path": "/c", "version": "3.0.71"}]}
        self.assertEqual(lp.judge_load_proof(pin="3.0.71", hook=out, embedded_version="3.0.71", compiled=True)["load_proof"], "fail")


class Evidence(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def test_read_hook_log(self):
        p = os.path.join(self.d, "h.jsonl")
        self.assertIsNone(lp.read_hook_log(p))
        _log(p, {"event": "start"}, {"event": "loaded", "path": "/a", "version": "2.0.0"},
             {"event": "loaded", "path": "/a", "version": "2.0.0"})
        with open(p, "a") as fh:
            fh.write("not json\n")
        self.assertEqual(lp.read_hook_log(p), {"started": True, "loaded": [{"path": "/a", "version": "2.0.0"}]})

    def test_scan_copies_excludes_pin_store(self):
        a = _pkg(self.d, "2.0.25", "cell")
        b = _pkg(self.d, "3.0.1", "cell", "node_modules", "foo")
        _pkg(self.d, "2.0.58", "pins", "2.0.58")
        got = lp.scan_copies([self.d], exclude=[os.path.join(self.d, "pins")])
        self.assertEqual({c["path"] for c in got}, {os.path.realpath(a), os.path.realpath(b)})

    def test_apply_load_proof_on_row(self):
        row = {"anthropic_pin": "2.0.0", "loaded_anthropic": None,
               "module_hook_log": {"started": True, "loaded": [{"path": "/a", "version": "2.0.0"}]},
               "image_scan_copies": [{"path": "/a", "version": "2.0.0"}]}
        _apply_load_proof(row)
        self.assertEqual((row["load_proof_basis"], row["load_proof"]), ("module_hook", "pass"))
        row = {"anthropic_pin": "3.0.71", "embedded_version": "3.0.71",
               "module_hook_log": {"started": True, "loaded": []}, "image_scan_copies": []}
        _apply_load_proof(row)
        self.assertEqual(row["load_proof"], "pass")
        self.assertNotIn("load_proof", _apply_load_proof({}))

    def test_install_hook_writes_plugin(self):
        path = lp.install_hook(os.path.join(self.d, ".config"), os.path.join(self.d, "h.jsonl"))
        self.assertTrue(path.endswith("opencode/plugin/obench-load-proof.js"))
        src = Path(path).read_text()
        self.assertIn("export const ObenchLoadProof", src)
        self.assertIn(lp.HOOK_LOG_ENV, src)

    @unittest.skipUnless(shutil.which("bun"), "bun not installed")
    def test_hook_runs_under_bun(self):
        mod = _pkg(self.d, "2.0.0-beta.5", "cell")
        log = os.path.join(self.d, "h.jsonl")
        hook = lp.install_hook(os.path.join(self.d, ".config"), log)
        main = Path(self.d, "main.mjs")
        main.write_text(f"import {{ ObenchLoadProof }} from {json.dumps(hook)};\n"
                        f"await import({json.dumps(mod + '/dist/index.mjs')});\n"
                        "const h = await ObenchLoadProof(); await h.event();\n")
        subprocess.run(["bun", str(main)], check=True, timeout=30)
        got = lp.read_hook_log(log)
        self.assertTrue(got["started"])
        self.assertEqual([e["version"] for e in got["loaded"]], ["2.0.0-beta.5"])


if __name__ == "__main__":
    unittest.main()
