"""Adapters must run inside a cell that only has /bench/adapters and entry.py.

The harness image does not install the obench or thesis packages. This test
copies those files into an empty directory and drives each adapter's in-cell
entry path with both packages blocked. It fails on the c001fe7c imports
(`from obench.adapters import pi`, `from thesis.ab.provider_pin import ...`).
"""

import os
import shutil
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[1]


def _stage(dest: Path) -> None:
    adapters = dest / "adapters"
    adapters.mkdir()
    for path in (_ROOT / "adapters").glob("*.py"):
        shutil.copy2(path, adapters / path.name)
    shutil.copy2(_ROOT / "entry.py", dest / "entry.py")


_DRIVE = textwrap.dedent(
    r"""
    import importlib.abc
    import importlib.util
    import json
    import os
    import re
    import sys
    import traceback

    class Block(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path, target=None):
            root = fullname.split(".", 1)[0]
            if root in {"obench", "thesis"}:
                raise ModuleNotFoundError(fullname)
            return None

    sys.meta_path.insert(0, Block())
    for name in list(sys.modules):
        if name == "obench" or name.startswith("obench.") or name == "thesis" or name.startswith("thesis."):
            del sys.modules[name]

    bench = os.environ["CELL_BENCH"]
    os.environ["BENCH_ADAPTERS_DIR"] = os.path.join(bench, "adapters")
    os.environ["BENCH_IN_CONTAINER"] = "1"
    os.environ["OBENCH_DOCKER_NETWORK"] = "bridge"
    os.environ["HOME"] = os.environ["CELL_HOME"]
    os.environ["XDG_CONFIG_HOME"] = os.path.join(os.environ["CELL_HOME"], ".config")
    os.environ["XDG_DATA_HOME"] = os.path.join(os.environ["CELL_HOME"], ".local", "share")
    os.environ["XDG_CACHE_HOME"] = os.path.join(os.environ["CELL_HOME"], ".cache")

    spec = importlib.util.spec_from_file_location(
        "bench_entry", os.path.join(bench, "entry.py"),
    )
    entry = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(entry)

    def check(name, result):
        if not isinstance(result, dict):
            raise SystemExit(f"{name}: result is {type(result).__name__}")
        blob = json.dumps(result)
        for banned in ("No module named 'obench'", "No module named 'thesis'", "No module named \"obench\"", "No module named \"thesis\""):
            if banned in blob:
                raise SystemExit(f"{name}: {blob[:1500]}")
        print(name, "ok", result.get("completed"), str(result.get("error") or "")[:180])

    work = os.environ["CELL_WORK"]
    os.makedirs(work, exist_ok=True)

    pi = entry._load_adapter("pi")
    text = open(os.path.join(bench, "adapters", "pi_harness.py"), encoding="utf-8").read()
    pin = re.search(r'^PIN = "([0-9a-f]+)"', text, re.M).group(1)
    pin_path = os.path.join(os.environ["CELL_HOME"], "pi.pin")
    open(pin_path, "w", encoding="utf-8").write(pin + "\n")
    os.environ["OBENCH_PI_HARNESS"] = "1"
    os.environ["OBENCH_VERTEX_PROXY_URL"] = "http://127.0.0.1:9"
    os.environ["OBENCH_VERTEX_CELL_ID"] = "cellpi"
    os.environ["OBENCH_VERTEX_LEDGER_DIR"] = os.environ["CELL_HOME"]
    os.environ["OBENCH_PI_BIN"] = os.environ["CELL_PI_BIN"]
    os.environ["OBENCH_PI_PIN_FILE"] = pin_path
    os.environ.pop("OBENCH_PI_VERTEX", None)
    try:
        pi_result = pi.run("say hi", work, "claude-sonnet-5-5", 30)
    except Exception:
        traceback.print_exc()
        raise SystemExit(1)
    check("pi", pi_result)

    opencode = entry._load_adapter("opencode")
    os.environ["OBENCH_OPENCODE_BIN"] = os.environ["CELL_OC_BIN"]
    os.environ["OBENCH_OPENCODE_PROXY"] = json.dumps({
        "model_ref": "anthropic/claude-opus-5-5",
        "base_url": "http://127.0.0.1:9/v1",
        "api_key": "proxy",
    })
    os.environ["OBENCH_OPENCODE_CONFIG_JSON"] = json.dumps({
        "provider": {"anthropic": {"options": {"apiKey": "proxy", "baseURL": "http://127.0.0.1:9/v1"}}},
    })
    os.environ.pop("OBENCH_OPENCODE_PERMISSION_CONFIG", None)
    os.environ["OBENCH_NO_PROGRESS_S"] = "30"
    os.environ["OBENCH_OPENCODE_EVIDENCE_DIR"] = os.path.join(os.environ["CELL_HOME"], "evidence")
    try:
        oc_result = opencode.run("say hi", work, "claude-opus-5-5", 30)
    except Exception:
        traceback.print_exc()
        raise SystemExit(1)
    check("opencode", oc_result)
    """
)


class CellImportTests(unittest.TestCase):
    def test_pi_and_opencode_run_without_obench_or_thesis(self):
        import tempfile
        bench = Path(tempfile.mkdtemp(prefix="cell-bench-"))
        home = Path(tempfile.mkdtemp(prefix="cell-home-"))
        work = Path(tempfile.mkdtemp(prefix="cell-work-"))
        self.addCleanup(shutil.rmtree, bench, True)
        self.addCleanup(shutil.rmtree, home, True)
        self.addCleanup(shutil.rmtree, work, True)
        _stage(bench)
        pi_bin = home / "pi"
        pi_bin.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        pi_bin.chmod(0o755)
        oc_bin = home / "opencode"
        oc_bin.write_text(
            "#!/bin/sh\n"
            "case \"$*\" in\n"
            "  *help*) printf '%s\\n' '--auto' '-m, --model' '--format' '--dir' '--title' '--mode'; exit 0 ;;\n"
            "esac\n"
            "printf '%s\\n' 'hello from fake opencode'\n"
            "exit 0\n",
            encoding="utf-8",
        )
        oc_bin.chmod(0o755)
        env = os.environ.copy()
        env["PYTHONPATH"] = str(bench)
        env["CELL_BENCH"] = str(bench)
        env["CELL_HOME"] = str(home)
        env["CELL_WORK"] = str(work)
        env["CELL_PI_BIN"] = str(pi_bin)
        env["CELL_OC_BIN"] = str(oc_bin)
        for key in (
            "ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL", "OPENAI_API_KEY",
            "OBENCH_PI_VERTEX", "OBENCH_OPENCODE_LSP",
        ):
            env.pop(key, None)
        proc = subprocess.run(
            [sys.executable, "-c", _DRIVE],
            cwd=str(home),
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + "\n" + proc.stderr)
        self.assertIn("pi ok", proc.stdout)
        self.assertIn("opencode ok", proc.stdout)


if __name__ == "__main__":
    unittest.main()
