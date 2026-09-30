#!/usr/bin/env python3
import importlib.util
import json
import os
import shutil
import stat
import subprocess
import tempfile
import types
import unittest

from obench import doctor

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ADAPTERS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "adapters")
MODEL = "gcp-vllm/glm-4.7-flash"
BASE_URL = "http://127.0.0.1:8000/v1"
SERVED = "zai-org/GLM-4.7-Flash"


def load_opencode():
    spec = importlib.util.spec_from_file_location(
        "opencode_gcp_vllm_adapter", os.path.join(ADAPTERS_DIR, "opencode.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakeProc:
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


class EnvPatch:
    def __enter__(self):
        self.saved = dict(os.environ)
        return os.environ

    def __exit__(self, *exc):
        os.environ.clear()
        os.environ.update(self.saved)


def _step_finish():
    tok = {
        "input": 3,
        "output": 2,
        "reasoning": 1,
        "cache": {"read": 0, "write": 0},
        "total": 6,
    }
    return json.dumps({"type": "step_finish", "part": {"tokens": tok}}) + "\n"


class TestOpenCodeGcpVllm(unittest.TestCase):
    def setUp(self):
        self.openc = load_opencode()

    def _run(self, model, env_updates):
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append((cmd, kwargs))
            return FakeProc(stdout=_step_finish())

        old = self.openc.subprocess.run
        self.openc.subprocess.run = fake_run
        try:
            with EnvPatch() as env:
                for key in (
                    "OPENBENCH_PROXY",
                    "OPENBENCH_GCP_VLLM_BASE_URL",
                    "OPENBENCH_GCP_VLLM_MODEL",
                    "OPENBENCH_GCP_VLLM_API_KEY",
                    "ZAI_API_KEY",
                ):
                    env.pop(key, None)
                env.update(env_updates)
                result = self.openc.run("fix the tests", "/tmp/work", model, 5)
        finally:
            self.openc.subprocess.run = old
        return result, calls

    def test_missing_endpoint_does_not_launch(self):
        result, calls = self._run(MODEL, {})
        self.assertEqual(calls, [])
        self.assertFalse(result["completed"])
        self.assertIsNone(result["cmd"])
        self.assertIn("SETUP-NEEDED", result["error"])
        self.assertIn("OPENBENCH_GCP_VLLM_BASE_URL", result["error"])
        self.assertIn("OPENBENCH_GCP_VLLM_MODEL", result["error"])

    def test_builds_openai_compatible_config_without_api_key(self):
        result, calls = self._run(MODEL, {
            "OPENBENCH_GCP_VLLM_BASE_URL": BASE_URL,
            "OPENBENCH_GCP_VLLM_MODEL": SERVED,
        })
        self.assertTrue(result["completed"])
        self.assertEqual(len(calls), 1)
        cmd, kwargs = calls[0]
        self.assertEqual(cmd[cmd.index("-m") + 1], f"gcp-vllm/{SERVED}")
        self.assertNotIn("--variant", cmd)
        self.assertEqual(cmd[-1], "fix the tests")
        config = json.loads(kwargs["env"]["OPENCODE_CONFIG_CONTENT"])
        options = config["provider"]["gcp-vllm"]["options"]
        self.assertEqual(options["baseURL"], BASE_URL)
        self.assertNotIn("apiKey", options)
        self.assertIn(SERVED, config["provider"]["gcp-vllm"]["models"])
        self.assertNotIn("OPENBENCH_GCP_VLLM_API_KEY", kwargs["env"])

    def test_api_key_is_referenced_not_copied_into_config(self):
        secret = "thesis-secret-key"
        result, calls = self._run(MODEL, {
            "OPENBENCH_GCP_VLLM_BASE_URL": BASE_URL,
            "OPENBENCH_GCP_VLLM_MODEL": SERVED,
            "OPENBENCH_GCP_VLLM_API_KEY": secret,
        })
        self.assertTrue(result["completed"])
        cmd, kwargs = calls[0]
        config_text = kwargs["env"]["OPENCODE_CONFIG_CONTENT"]
        self.assertNotIn(secret, config_text)
        self.assertNotIn(secret, cmd)
        config = json.loads(config_text)
        self.assertEqual(
            config["provider"]["gcp-vllm"]["options"]["apiKey"],
            "{env:OPENBENCH_GCP_VLLM_API_KEY}",
        )
        self.assertEqual(kwargs["env"]["OPENBENCH_GCP_VLLM_API_KEY"], secret)

    def test_rejects_credentials_in_base_url(self):
        result, calls = self._run(MODEL, {
            "OPENBENCH_GCP_VLLM_BASE_URL": "http://user:pass@127.0.0.1:8000/v1",
            "OPENBENCH_GCP_VLLM_MODEL": SERVED,
        })
        self.assertEqual(calls, [])
        self.assertFalse(result["completed"])
        self.assertIn("credentials", result["error"])

    def test_hosted_glm_still_requires_zai_key_and_variant(self):
        missing, calls = self._run("glm-4.7-flash", {})
        self.assertEqual(calls, [])
        self.assertIn("ZAI_API_KEY", missing["error"])

        result, calls = self._run("glm-4.7-flash", {"ZAI_API_KEY": "zai-secret"})
        self.assertTrue(result["completed"])
        cmd, kwargs = calls[0]
        self.assertEqual(cmd[cmd.index("-m") + 1], "zai/glm-4.7-flash")
        self.assertEqual(cmd[cmd.index("--variant") + 1], "medium")
        config = json.loads(kwargs["env"]["OPENCODE_CONFIG_CONTENT"])
        self.assertEqual(
            config["provider"]["zai"]["options"]["baseURL"],
            "https://api.z.ai/api/paas/v4",
        )
        self.assertNotIn("zai-secret", kwargs["env"]["OPENCODE_CONFIG_CONTENT"])


class _DoctorProbes:
    def __init__(self, env, open_models):
        self.env = env
        self.open_models = open_models

    def which(self, cli):
        return "/bin/opencode" if cli == "opencode" else None

    def run(self, argv, timeout=15):
        if tuple(argv) == ("opencode", "--version"):
            return 0, "1.18.3"
        return 1, ""

    def getenv(self, name):
        return self.env.get(name)

    def exists(self, path):
        return False

    def read_text(self, path):
        return None

    def import_adapter(self, name):
        mod = types.ModuleType("fake_opencode")
        mod.MODELS = {"gpt-5.5-medium": "openai/gpt-5.5"}
        mod.OPEN_MODELS = self.open_models
        return mod


class TestDoctorSelfHosted(unittest.TestCase):
    def _spec(self):
        return dict(load_opencode().OPEN_MODELS[MODEL])

    def test_auth_passes_without_optional_key(self):
        probes = _DoctorProbes(
            {
                "OPENBENCH_GCP_VLLM_BASE_URL": BASE_URL,
                "OPENBENCH_GCP_VLLM_MODEL": SERVED,
            },
            {MODEL: self._spec()},
        )
        rows, ok = doctor.evaluate(["opencode"], MODEL, probes)
        self.assertTrue(ok, rows)
        auth = next(row for row in rows if row["check"] == "AUTH")
        self.assertTrue(auth["ok"])
        self.assertIn("optional and unset", auth["detail"])
        self.assertNotIn("oauth", auth["detail"])
        model_row = next(row for row in rows if row["check"] == "MODEL")
        self.assertIn(SERVED, model_row["detail"])

    def test_auth_names_missing_endpoint_vars(self):
        probes = _DoctorProbes({}, {MODEL: self._spec()})
        rows, ok = doctor.evaluate(["opencode"], MODEL, probes)
        self.assertFalse(ok)
        auth = next(row for row in rows if row["check"] == "AUTH")
        self.assertFalse(auth["ok"])
        self.assertIn("OPENBENCH_GCP_VLLM_BASE_URL", auth["detail"])
        self.assertIn("OPENBENCH_GCP_VLLM_MODEL", auth["detail"])
        self.assertNotIn("oauth", auth["detail"])

    def test_import_failure_does_not_fall_through_to_oauth(self):
        class Broken:
            def which(self, cli):
                return "/bin/opencode"

            def run(self, argv, timeout=15):
                return 0, "1.18.3"

            def getenv(self, name):
                return None

            def exists(self, path):
                return False

            def read_text(self, path):
                return None

            def import_adapter(self, name):
                raise RuntimeError("boom")

        rows, ok = doctor.evaluate(["opencode"], MODEL, Broken())
        self.assertFalse(ok)
        auth = next(row for row in rows if row["check"] == "AUTH")
        self.assertFalse(auth["ok"])
        self.assertIn("import failed", auth["detail"])
        self.assertIn("boom", auth["detail"])
        self.assertNotIn("oauth", auth["detail"])


def _write_executable(path, body):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(body)
    os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)


class TestThesisScripts(unittest.TestCase):
    def test_create_dry_run_is_iap_only_and_does_not_call_gcloud(self):
        bindir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, bindir, True)
        marker = os.path.join(bindir, "gcloud-called")
        _write_executable(
            os.path.join(bindir, "gcloud"),
            "#!/bin/sh\necho called >> \"$MARKER\"\nexit 99\n",
        )
        env = os.environ.copy()
        env["PATH"] = bindir + os.pathsep + env.get("PATH", "")
        env["MARKER"] = marker
        env["HF_TOKEN"] = "super-secret-token"
        env.pop("VM_NAME", None)
        proc = subprocess.run(
            ["bash", "thesis/gcp/create-vllm-vm.sh", "--dry-run"],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertFalse(os.path.exists(marker))
        text = proc.stdout
        self.assertNotIn("super-secret-token", text)
        self.assertNotIn("super-secret-token", proc.stderr)
        self.assertIn("thesis-hf-token=REDACTED", text)
        script = text.split("----- startup-script -----\n", 1)[1]
        checked = subprocess.run(
            ["bash", "-n"],
            input=script,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(checked.returncode, 0, checked.stderr)
        self.assertIn("--machine-type=a2-highgpu-1g", text)
        self.assertIn("--project=nyu-rdg-fy26-js11531-a68d", text)
        self.assertIn("--zone=us-central1-a", text)
        self.assertIn("thesis-vllm-glm47", text)
        self.assertIn("--image-family=common-cu128-ubuntu-2204-nvidia-570", text)
        self.assertIn("--source-ranges=35.235.240.0/20", text)
        self.assertIn("--action=DENY", text)
        self.assertIn("--target-tags=thesis-iap", text)
        self.assertIn("--host 127.0.0.1", text)
        self.assertNotIn("--host 0.0.0.0", text)
        self.assertNotIn("course-", text)

    def test_create_refuses_name_without_thesis_prefix(self):
        env = os.environ.copy()
        env["VM_NAME"] = "shared-lab-vm"
        proc = subprocess.run(
            ["bash", "thesis/gcp/create-vllm-vm.sh", "--dry-run"],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 1)
        self.assertIn("thesis-", proc.stderr)
        self.assertNotIn("gcloud compute instances create", proc.stdout)

    def test_extra_args_are_not_expanded_as_globs(self):
        env = os.environ.copy()
        env.pop("VM_NAME", None)
        env["VLLM_EXTRA_ARGS"] = "--chat-template *.md"
        proc = subprocess.run(
            ["bash", "thesis/gcp/create-vllm-vm.sh", "--dry-run"],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn("AGENTS.md", proc.stdout)
        self.assertIn("*.md", proc.stdout.replace("\\*", "*"))

    def test_teardown_stop_and_delete_name_only_thesis_resources(self):
        env = os.environ.copy()
        env.pop("VM_NAME", None)
        stop = subprocess.run(
            ["bash", "thesis/gcp/teardown-vllm-vm.sh", "--dry-run", "stop"],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(stop.returncode, 0, stop.stderr)
        self.assertIn("instances stop thesis-vllm-glm47", stop.stdout)
        self.assertNotIn("instances delete", stop.stdout)
        self.assertNotIn("firewall-rules delete", stop.stdout)

        delete = subprocess.run(
            ["bash", "thesis/gcp/teardown-vllm-vm.sh", "--dry-run", "delete"],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(delete.returncode, 0, delete.stderr)
        self.assertIn("instances delete thesis-vllm-glm47", delete.stdout)
        self.assertIn("firewall-rules delete thesis-allow-iap-ssh thesis-deny-ingress", delete.stdout)

        env["VM_NAME"] = "other-people-gpu"
        refused = subprocess.run(
            ["bash", "thesis/gcp/teardown-vllm-vm.sh", "--dry-run", "delete"],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(refused.returncode, 1)
        self.assertNotIn("gcloud", refused.stdout)

    def test_run_script_calls_legacy_run_for_the_three_tasks(self):
        bindir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, bindir, True)
        recorded = os.path.join(bindir, "obench-args")
        curl_log = os.path.join(bindir, "curl-args")
        _write_executable(
            os.path.join(bindir, "curl"),
            "#!/bin/sh\nprintf '%s\\n' \"$@\" > \"$CURL_LOG\"\nexit 0\n",
        )
        _write_executable(
            os.path.join(bindir, "obench"),
            "#!/bin/sh\nprintf '%s\\n' \"$@\" > \"$OBENCH_LOG\"\nexit 0\n",
        )
        env = os.environ.copy()
        env["PATH"] = bindir + os.pathsep + env.get("PATH", "")
        env["CURL_LOG"] = curl_log
        env["OBENCH_LOG"] = recorded
        env["OPENBENCH_GCP_VLLM_BASE_URL"] = BASE_URL
        env["OPENBENCH_GCP_VLLM_MODEL"] = SERVED
        env["OPENBENCH_GCP_VLLM_API_KEY"] = "run-secret"
        proc = subprocess.run(
            ["bash", "thesis/run-hard-tasks.sh"],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        with open(recorded, encoding="utf-8") as fh:
            args = fh.read().splitlines()
        self.assertEqual(args[:2], ["legacy", "run"])
        self.assertEqual(args[args.index("--exec") + 1], "local")
        self.assertEqual(args[args.index("--harness") + 1], "opencode")
        self.assertEqual(args[args.index("--model") + 1], MODEL)
        self.assertEqual(
            args[args.index("--task") + 1],
            "make-ci-green,add-feature,misleading-error",
        )
        self.assertTrue(args[args.index("--results-path") + 1].endswith(
            "results/thesis-opencode-glm-4.7-flash.jsonl"))
        with open(curl_log, encoding="utf-8") as fh:
            curl_args = fh.read()
        self.assertIn(BASE_URL + "/models", curl_args)
        self.assertIn("run-secret", curl_args)

        env.pop("OPENBENCH_GCP_VLLM_API_KEY")
        _write_executable(
            os.path.join(bindir, "curl"),
            "#!/bin/sh\nexit 1\n",
        )
        os.remove(recorded)
        failed = subprocess.run(
            ["bash", "thesis/run-hard-tasks.sh"],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(failed.returncode, 1)
        self.assertFalse(os.path.exists(recorded))
        self.assertIn("IAP tunnel", failed.stderr)


if __name__ == "__main__":
    unittest.main()
