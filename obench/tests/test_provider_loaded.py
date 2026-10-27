"""The OpenCode process's loaded @ai-sdk/anthropic version, not the cache copy."""

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from obench.run import ROW_FIELDS, _apply_sdk_drift


def _package(root, version):
    module = root / "node_modules" / "@ai-sdk" / "anthropic" / "package.json"
    module.parent.mkdir(parents=True, exist_ok=True)
    module.write_text(
        json.dumps({"name": "@ai-sdk/anthropic", "version": version}),
        encoding="utf-8",
    )
    return module.parent


class ParseTests(unittest.TestCase):
    def test_preload_line_is_the_loaded_version(self):
        import obench.adapters.opencode as opencode

        text = (
            "noise\n"
            "OBENCH_PROVIDER_LOADED pkg=@ai-sdk/anthropic version=2.0.77 "
            "path=/cache/node_modules/@ai-sdk/anthropic\n"
        )
        version, source, path = opencode._loaded_provider_version({}, text)
        self.assertEqual(version, "2.0.77")
        self.assertEqual(source, "preload")
        self.assertEqual(path, "/cache/node_modules/@ai-sdk/anthropic")

    def test_later_preload_line_wins(self):
        import obench.adapters.opencode as opencode

        text = (
            "OBENCH_PROVIDER_LOADED pkg=@ai-sdk/anthropic version=1.2.12 "
            "path=/cache/node_modules/@ai-sdk/anthropic\n"
            "OBENCH_PROVIDER_RESOLVE pkg=@ai-sdk/anthropic path=/other\n"
            "OBENCH_PROVIDER_LOADED pkg=@ai-sdk/anthropic version=4.0.88 "
            "path=/real/node_modules/@ai-sdk/anthropic\n"
        )
        version, source, path = opencode._loaded_provider_version({}, text)
        self.assertEqual((version, source, path), (
            "4.0.88", "preload", "/real/node_modules/@ai-sdk/anthropic",
        ))

    def test_strace_reads_the_opened_package_json(self):
        import obench.adapters.opencode as opencode

        root = Path(tempfile.mkdtemp())
        pkg = _package(root, "4.0.88")
        opened = pkg / "dist" / "index.js"
        opened.parent.mkdir(parents=True, exist_ok=True)
        opened.write_text("export {}\n", encoding="utf-8")
        trace = root / "provider-open.trace"
        trace.write_text(
            '123 openat(AT_FDCWD, "/etc/ld.so.cache", O_RDONLY) = 3\n'
            f'123 openat(AT_FDCWD, "{opened}", O_RDONLY) = 4\n',
            encoding="utf-8",
        )
        env = {"OBENCH_PROVIDER_TRACE_FILE": str(trace)}
        version, source, path = opencode._loaded_provider_version(env, "")
        self.assertEqual(version, "4.0.88")
        self.assertEqual(source, "strace")
        self.assertEqual(path, str(pkg))

    def test_unopened_cache_package_json_is_not_a_version(self):
        import obench.adapters.opencode as opencode

        root = Path(tempfile.mkdtemp())
        _package(root, "2.0.0")
        trace = root / "provider-open.trace"
        trace.write_text(
            '123 openat(AT_FDCWD, "/tmp/other/node_modules/@ai-sdk/anthropic/dist/index.js", O_RDONLY) = -1 ENOENT\n',
            encoding="utf-8",
        )
        env = {
            "XDG_CACHE_HOME": str(root),
            "OBENCH_PROVIDER_TRACE_FILE": str(trace),
        }
        version, source, path = opencode._loaded_provider_version(env, "")
        self.assertEqual((version, source, path), (None, "none", ""))

    def test_none_when_there_is_no_line_and_no_trace(self):
        import obench.adapters.opencode as opencode

        version, source, path = opencode._loaded_provider_version({}, "hello\n")
        self.assertEqual((version, source, path), (None, "none", ""))

    def test_enoent_opens_do_not_count_as_loaded(self):
        """Failed openat calls are not proof, even when package.json is on disk."""
        import obench.adapters.opencode as opencode

        root = Path(tempfile.mkdtemp())
        pkg = _package(root, "4.0.88")
        missing = pkg / "dist" / "missing.js"
        trace = root / "provider-open.trace"
        env = {"OBENCH_PROVIDER_TRACE_FILE": str(trace)}
        cases = {
            "enoent": (
                f'123 openat(AT_FDCWD, "{missing}", O_RDONLY|O_CLOEXEC) = -1 '
                "ENOENT (No such file or directory)\n"
            ),
            "eacces": (
                f'124 openat(AT_FDCWD, "{missing}", O_RDONLY) = -1 '
                "EACCES (Permission denied)\n"
            ),
        }
        for name, line in cases.items():
            with self.subTest(name=name):
                trace.write_text(line, encoding="utf-8")
                version, source, path = opencode._loaded_provider_version(env, "")
                self.assertEqual((version, source, path), (None, "none", ""))

    def test_failed_open_does_not_mask_a_later_successful_load(self):
        import obench.adapters.opencode as opencode

        root = Path(tempfile.mkdtemp())
        missed = _package(root / "miss", "9.9.9")
        hit = _package(root / "hit", "2.0.0")
        missing = missed / "dist" / "missing.js"
        opened = hit / "dist" / "index.js"
        opened.parent.mkdir(parents=True, exist_ok=True)
        opened.write_text("export {}\n", encoding="utf-8")
        trace = root / "provider-open.trace"
        trace.write_text(
            f'1 openat(AT_FDCWD, "{missing}", O_RDONLY) = -1 ENOENT '
            "(No such file or directory)\n"
            f'1 openat(AT_FDCWD, "{opened}", O_RDONLY) = 5\n',
            encoding="utf-8",
        )
        env = {"OBENCH_PROVIDER_TRACE_FILE": str(trace)}
        version, source, path = opencode._loaded_provider_version(env, "")
        self.assertEqual((version, source, path), ("2.0.0", "strace", str(hit)))


class MismatchTests(unittest.TestCase):
    def test_loaded_mismatch_is_infra(self):
        import obench.adapters.opencode as opencode

        text = opencode._loaded_mismatch_text("2.0.0", "4.0.88", "strace")
        self.assertEqual(text, "provider_pin_mismatch: loaded 4.0.88 != pin 2.0.0")
        row = _apply_sdk_drift(
            {"success": True, "score": 1.0, "failure_class": "ok", "sdk_drift": "cache"},
            {
                "sdk_drift": "sdk drift: installed @ai-sdk/anthropic 2.0.0 != pin 2.0.0",
                "provider_loaded_mismatch": text,
            },
        )
        self.assertEqual(row["failure_class"], "infra")
        self.assertEqual(row["failure_reason"], text)
        self.assertFalse(row["success"])
        self.assertEqual(row["score"], 0.0)
        self.assertIn("sdk drift", row["sdk_drift"])

    def test_unproven_is_warn_only_unless_required(self):
        import obench.adapters.opencode as opencode

        saved = os.environ.get("OBENCH_REQUIRE_LOADED_PROOF")
        try:
            os.environ.pop("OBENCH_REQUIRE_LOADED_PROOF", None)
            self.assertEqual(opencode._loaded_mismatch_text("2.0.0", None, "none"), "")
            row = _apply_sdk_drift(
                {"success": True, "score": 1.0, "failure_class": "ok"},
                {"provider_loaded_source": "none"},
            )
            self.assertEqual(row["failure_class"], "ok")
            self.assertTrue(row["success"])
            self.assertNotIn("provider_loaded_mismatch", row)
            os.environ["OBENCH_REQUIRE_LOADED_PROOF"] = "1"
            text = opencode._loaded_mismatch_text("2.0.0", None, "none")
            self.assertEqual(text, "provider_pin_mismatch: loaded version unproven")
            forced = _apply_sdk_drift(
                {"success": True, "score": 1.0, "failure_class": "ok"},
                {"provider_loaded_mismatch": text},
            )
            self.assertEqual(forced["failure_class"], "infra")
            self.assertEqual(forced["failure_reason"], text)
            self.assertFalse(forced["success"])
            self.assertEqual(forced["score"], 0.0)
        finally:
            if saved is None:
                os.environ.pop("OBENCH_REQUIRE_LOADED_PROOF", None)
            else:
                os.environ["OBENCH_REQUIRE_LOADED_PROOF"] = saved

    def test_matching_loaded_version_is_not_a_mismatch(self):
        import obench.adapters.opencode as opencode

        self.assertEqual(opencode._loaded_mismatch_text("2.0.0", "2.0.0", "preload"), "")
        self.assertEqual(opencode._loaded_mismatch_text("", "9.9.9", "strace"), "")


class WatcherTests(unittest.TestCase):
    def test_mismatching_live_line_kills_the_cell(self):
        from thesis.ab.provider_pin import ProviderPinMismatch, violation_in_text
        from thesis.ab.watch import run_piped

        pins = json.dumps({"@ai-sdk/anthropic": "2.0.0"}, separators=(",", ":"))
        line = "OBENCH_PROVIDER_LOADED pkg=@ai-sdk/anthropic version=9.9.9 path=/tmp/pkg\n"
        self.assertEqual(
            violation_in_text(line, pins),
            "provider_pin_mismatch: loaded 9.9.9 != pin 2.0.0",
        )
        self.assertEqual(violation_in_text(line), "")
        self.assertEqual(
            violation_in_text(
                "OBENCH_PROVIDER_LOADED pkg=@ai-sdk/anthropic version=2.0.0 path=/tmp/pkg\n",
                pins,
            ),
            "",
        )
        env = os.environ.copy()
        env["OBENCH_PROVIDER_PINS"] = pins
        env["XDG_DATA_HOME"] = tempfile.mkdtemp()
        script = (
            "import time; "
            "print('OBENCH_PROVIDER_LOADED pkg=@ai-sdk/anthropic version=9.9.9 path=/tmp/pkg', flush=True); "
            "time.sleep(30)"
        )
        with self.assertRaises(ProviderPinMismatch) as caught:
            run_piped(
                [sys.executable, "-c", script],
                None,
                env,
                5,
                no_progress_s=30,
            )
        self.assertEqual(
            caught.exception.reason,
            "provider_pin_mismatch: loaded 9.9.9 != pin 2.0.0",
        )
        self.assertIn("version=9.9.9", caught.exception.output)

    def test_matching_live_line_does_not_kill(self):
        from thesis.ab.watch import run_piped

        env = os.environ.copy()
        env["OBENCH_PROVIDER_PINS"] = json.dumps({"@ai-sdk/anthropic": "2.0.0"})
        env["XDG_DATA_HOME"] = tempfile.mkdtemp()
        script = (
            "print('OBENCH_PROVIDER_LOADED pkg=@ai-sdk/anthropic version=2.0.0 path=/tmp/pkg', flush=True)"
        )
        done = run_piped(
            [sys.executable, "-c", script],
            None,
            env,
            5,
            no_progress_s=30,
        )
        self.assertEqual(done.returncode, 0)


class PlumbingTests(unittest.TestCase):
    def test_row_allowlist_and_side_jsonl_keep_the_fields(self):
        from thesis.ab.run_ab import attach_provider_pin

        for field in (
            "provider_loaded_version",
            "provider_loaded_source",
            "provider_loaded_mismatch",
        ):
            self.assertIn(field, ROW_FIELDS)
        row = {
            "provider_loaded_version": " 4.0.88 ",
            "provider_loaded_source": "strace",
            "provider_loaded_mismatch": " provider_pin_mismatch: loaded 4.0.88 != pin 2.0.0 ",
        }
        attach_provider_pin(row, {"proxy": {}})
        self.assertEqual(row["provider_loaded_version"], "4.0.88")
        self.assertEqual(row["provider_loaded_source"], "strace")
        self.assertIn("4.0.88", row["provider_loaded_mismatch"])
        side = json.loads(json.dumps(row, sort_keys=True))
        self.assertEqual(side["provider_loaded_source"], "strace")

    def test_preload_appends_bun_options_and_writes_the_probe(self):
        import obench.adapters.opencode as opencode

        cache = Path(tempfile.mkdtemp()) / "opencode"
        env = {"BUN_OPTIONS": "--smol"}
        probe = opencode._arm_provider_probe(env, str(cache))
        self.assertTrue(probe.endswith(".obench-provider-probe.mjs"))
        self.assertTrue(env["BUN_OPTIONS"].startswith("--smol "))
        self.assertIn(f"--preload {probe}", env["BUN_OPTIONS"])
        text = Path(probe).read_text(encoding="utf-8")
        self.assertIn("require.resolve(\"@ai-sdk/anthropic/package.json\"", text)
        self.assertIn("Bun.plugin", text)
        self.assertIn("build.onLoad(", text)
        self.assertIn("/^@ai-sdk\\/anthropic/", text)
        self.assertIn("OBENCH_PROVIDER_LOADED pkg=@ai-sdk/anthropic version=", text)
        self.assertNotIn("emit(versionOf(pkgPath)", text)
        again = dict(env)
        opencode._append_bun_preload(again, probe)
        self.assertEqual(again["BUN_OPTIONS"], env["BUN_OPTIONS"])


def _executable(path, body):
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


class CellTests(unittest.TestCase):
    def _proxy(self, bun):
        return {
            "model_ref": "anthropic/claude-opus-5-5",
            "api_key": "proxy",
            "base_url": "http://127.0.0.1:9/v1",
            "base_url_env": "1",
            "anthropic_sdk": "2.0.0",
            "cache_version": "9",
            "bun": str(bun),
            "provider_pins": {"@ai-sdk/anthropic": "2.0.0"},
            "provider_pin_sha256": "abc",
            "pin_source": "lockfile",
        }

    def _bun(self, root):
        bun = root / "bun"
        _executable(bun, textwrap.dedent("""\
            #!/usr/bin/env python3
            import os, pathlib, sys
            for arg in sys.argv[1:]:
                if arg.startswith("@ai-sdk/anthropic@"):
                    version = arg.rsplit("@", 1)[1]
                    module = pathlib.Path(os.environ["XDG_CACHE_HOME"]) / "opencode" / "node_modules" / "@ai-sdk" / "anthropic" / "package.json"
                    module.parent.mkdir(parents=True, exist_ok=True)
                    module.write_text('{"name": "@ai-sdk/anthropic", "version": "%s"}' % version, encoding="utf-8")
        """))
        return bun

    def _binary(self, root):
        binary = root / "opencode"
        _executable(binary, textwrap.dedent("""\
            #!/usr/bin/env python3
            import json, os, sys
            args = sys.argv[1:]
            if args[:2] == ["run", "--help"]:
                print("--auto")
                print("-m, --model")
                print("--format")
                print("--dir")
                print("--title")
                raise SystemExit(0)
            if os.environ.get("PRINT_LOADED") == "1":
                print(
                    "OBENCH_PROVIDER_LOADED pkg=@ai-sdk/anthropic version=9.9.9 path=/tmp/loaded",
                    file=sys.stderr,
                )
            print(json.dumps({"type": "step_finish", "part": {"tokens": {
                "input": 1, "output": 1, "reasoning": 0,
                "cache": {"read": 0, "write": 0}, "total": 2,
            }}}))
        """))
        return binary

    def _run(self, root, **env_extra):
        import obench.adapters.opencode as opencode

        keys = (
            "OBENCH_OPENCODE_BIN",
            "OBENCH_OPENCODE_PROXY",
            "OBENCH_OPENCODE_EVIDENCE_DIR",
            "OBENCH_PROVIDER_TRACE_FILE",
            "OBENCH_CELL_TEMP_ROOT",
            "PRINT_LOADED",
            "OBENCH_REQUIRE_LOADED_PROOF",
        )
        saved = {key: os.environ.get(key) for key in keys}
        bun = self._bun(root)
        binary = self._binary(root)
        work = root / "work"
        work.mkdir()
        evidence = root / "evidence"
        try:
            os.environ["OBENCH_OPENCODE_BIN"] = str(binary)
            os.environ["OBENCH_OPENCODE_PROXY"] = json.dumps(self._proxy(bun))
            os.environ["OBENCH_OPENCODE_EVIDENCE_DIR"] = str(evidence)
            os.environ.pop("OBENCH_REQUIRE_LOADED_PROOF", None)
            os.environ.pop("PRINT_LOADED", None)
            os.environ.pop("OBENCH_PROVIDER_TRACE_FILE", None)
            for key, value in env_extra.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            return opencode.run("say hi", str(work), "claude-opus-5-5", 30), evidence
        finally:
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def test_preload_mismatch_makes_the_cell_infra(self):
        root = Path(tempfile.mkdtemp())
        row, evidence = self._run(root, PRINT_LOADED="1")
        self.assertEqual(row["provider_loaded_version"], "9.9.9")
        self.assertEqual(row["provider_loaded_source"], "preload")
        self.assertEqual(
            row["provider_loaded_mismatch"],
            "provider_pin_mismatch: loaded 9.9.9 != pin 2.0.0",
        )
        self.assertEqual(row["failure_class"], "infra")
        self.assertFalse(row["completed"])
        self.assertIn("9.9.9", row["error"])
        self.assertTrue((evidence / "agent-output.txt").is_file())
        probe = evidence / ".obench-provider-probe.mjs"
        self.assertTrue(probe.is_file())
        self.assertIn("require.resolve", probe.read_text(encoding="utf-8"))

    def test_strace_mismatch_makes_the_cell_infra(self):
        root = Path(tempfile.mkdtemp())
        pkg = _package(root / "opened", "4.0.88")
        opened = pkg / "dist" / "index.js"
        opened.parent.mkdir(parents=True, exist_ok=True)
        opened.write_text("export {}\n", encoding="utf-8")
        trace = root / "provider-open.trace"
        trace.write_text(
            f'9 openat(AT_FDCWD, "{opened}", O_RDONLY) = 3\n',
            encoding="utf-8",
        )
        row, evidence = self._run(root, OBENCH_PROVIDER_TRACE_FILE=str(trace))
        self.assertEqual(row["provider_loaded_version"], "4.0.88")
        self.assertEqual(row["provider_loaded_source"], "strace")
        self.assertEqual(
            row["provider_loaded_mismatch"],
            "provider_pin_mismatch: loaded 4.0.88 != pin 2.0.0",
        )
        self.assertEqual(row["failure_class"], "infra")
        kept = evidence / "provider-open.trace"
        self.assertTrue(kept.is_file())
        self.assertIn("@ai-sdk/anthropic", kept.read_text(encoding="utf-8"))

    def test_missing_proof_stays_a_completed_cell(self):
        root = Path(tempfile.mkdtemp())
        row, _evidence = self._run(root)
        self.assertEqual(row["provider_loaded_source"], "none")
        self.assertNotIn("provider_loaded_version", row)
        self.assertNotIn("provider_loaded_mismatch", row)
        self.assertTrue(row["completed"])
        self.assertNotIn("sdk_drift", row)


_PROBE_HARNESS = textwrap.dedent("""\
    import { pathToFileURL } from "node:url";

    const probe = process.argv[2];
    const modulePath = process.argv[3];
    const missingPath = process.argv[4];
    const logs = [];
    const hooks = [];
    globalThis.Bun = {
      plugin(spec) {
        spec.setup({
          onResolve(opts, fn) {
            hooks.push({ kind: "resolve", filter: opts.filter, fn });
          },
          onLoad(opts, fn) {
            hooks.push({ kind: "load", filter: opts.filter, fn });
          },
        });
      },
    };
    console.error = (...args) => {
      logs.push(args.map((part) => String(part)).join(" "));
    };

    await import(pathToFileURL(probe).href);

    function loadedLines() {
      return logs.filter((line) => line.includes("OBENCH_PROVIDER_LOADED"));
    }

    const before = loadedLines();
    for (const hook of hooks) {
      if (hook.kind !== "resolve") continue;
      hook.fn({ path: "@ai-sdk/anthropic", importer: probe });
    }
    const afterResolve = loadedLines();

    let missingThrew = false;
    const loadHooks = hooks.filter((hook) => hook.kind === "load" && hook.filter.test(modulePath));
    for (const hook of loadHooks) {
      if (!hook.filter.test(missingPath)) continue;
      try {
        hook.fn({ path: missingPath });
      } catch {
        missingThrew = true;
      }
    }
    const afterMissing = loadedLines();

    let loadResult = null;
    let loadError = "";
    for (const hook of loadHooks) {
      try {
        loadResult = hook.fn({ path: modulePath });
      } catch (err) {
        loadError = String(err && err.stack || err);
      }
    }
    const afterLoad = loadedLines();
    const filter = loadHooks.length ? loadHooks[0].filter : null;
    process.stdout.write(JSON.stringify({
      before,
      afterResolve,
      afterMissing,
      missingThrew,
      afterLoad,
      loadError,
      loadResult,
      filterMatched: Boolean(filter && filter.test(modulePath) && filter.test(missingPath)),
      filterSkippedUnrelated: Boolean(filter && !filter.test("/tmp/other/file.js")),
    }) + "\\n");
    """)


class ProbeEmitTests(unittest.TestCase):
    def test_loaded_line_does_not_fire_before_the_import(self):
        import obench.adapters.opencode as opencode

        node = shutil.which("node")
        self.assertTrue(node, "node is required to execute the provider probe")
        root = Path(tempfile.mkdtemp())
        pkg = root / "node_modules" / "@ai-sdk" / "anthropic"
        module = pkg / "dist" / "index.js"
        module.parent.mkdir(parents=True)
        module.write_text("export const loaded = true;\n", encoding="utf-8")
        (pkg / "package.json").write_text(
            json.dumps({
                "name": "@ai-sdk/anthropic",
                "version": "2.0.0",
                "main": "dist/index.js",
            }),
            encoding="utf-8",
        )
        missing = pkg / "dist" / "missing.js"
        probe = opencode._arm_provider_probe({}, str(root))
        harness = root / "harness.mjs"
        harness.write_text(_PROBE_HARNESS, encoding="utf-8")
        proc = subprocess.run(
            [node, str(harness), probe, str(module), str(missing)],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        report = json.loads(proc.stdout)
        self.assertEqual(report["before"], [])
        self.assertEqual(report["afterResolve"], [])
        self.assertEqual(report["afterMissing"], [])
        self.assertTrue(report["missingThrew"])
        self.assertEqual(report["loadError"], "")
        self.assertEqual(len(report["afterLoad"]), 1)
        self.assertIn("version=2.0.0", report["afterLoad"][0])
        self.assertIn(str(pkg), report["afterLoad"][0])
        self.assertEqual(report["loadResult"]["loader"], "js")
        self.assertEqual(
            report["loadResult"]["contents"],
            module.read_text(encoding="utf-8"),
        )
        self.assertTrue(report["filterMatched"])
        self.assertTrue(report["filterSkippedUnrelated"])


if __name__ == "__main__":
    unittest.main()
