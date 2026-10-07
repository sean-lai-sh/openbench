"""Language-server provisioning uses fake bun and dotnet binaries."""

from __future__ import annotations

import os
import stat
import tempfile
import unittest
from pathlib import Path

from obench.lsp_cell import (
    LspProvisionError,
    lsp_boolean_enables_all,
    provision_language_servers,
    worktree_root,
)
import obench.lsp_cell as lsp_cell

BUN = """#!/usr/bin/env python3
import os, sys
from pathlib import Path
args = sys.argv[1:]
cwd = Path.cwd()
if args[:2] == ["install", "pyright"]:
    bindir = cwd / "node_modules" / ".bin"
    bindir.mkdir(parents=True)
    link = bindir / "pyright-langserver"
    link.write_text("#!/bin/sh\\n", encoding="utf-8")
    link.chmod(0o755)
    raise SystemExit(0)
if len(args) >= 3 and args[0] == "add" and args[1] == "--exact" and args[2].startswith("typescript@"):
    if args[2] != "typescript@5.8.3":
        sys.stderr.write("wrong pin " + args[2])
        raise SystemExit(2)
    lib = cwd / "node_modules" / "typescript" / "lib"
    lib.mkdir(parents=True)
    (lib / "tsserver.js").write_text("// stub\\n", encoding="utf-8")
    raise SystemExit(0)
sys.stderr.write("unexpected " + " ".join(args))
raise SystemExit(1)
"""

DOTNET = """#!/usr/bin/env python3
import os, sys
from pathlib import Path
args = sys.argv[1:]
if args == ["--version"]:
    print(os.environ.get("FAKE_DOTNET_VERSION", "10.0.401"))
    raise SystemExit(0)
if args[:4] == ["tool", "install", "roslyn-language-server", "--tool-path"]:
    dest = Path(args[4])
    dest.mkdir(parents=True, exist_ok=True)
    binary = dest / "roslyn-language-server"
    binary.write_text("#!/bin/sh\\n", encoding="utf-8")
    binary.chmod(0o755)
    raise SystemExit(0)
sys.stderr.write("unexpected " + " ".join(args))
raise SystemExit(1)
"""


def _write(directory: Path, name: str, text: str) -> Path:
    path = directory / name
    path.write_text(text, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


class LspProvisionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.bin = _write(root, "bun", BUN)
        self.dotnet = _write(root, "dotnet", DOTNET)
        self.work = root / "work"
        self.work.mkdir()
        self.data = root / "data"
        self.env = {
            "PATH": "/usr/bin",
            "HOME": str(root / "home"),
            "XDG_DATA_HOME": str(self.data),
            "XDG_CONFIG_HOME": str(root / "config"),
            "FAKE_DOTNET_VERSION": "10.0.401",
        }

    def test_pyright_and_typescript_land_where_opencode_looks(self):
        notes = provision_language_servers(
            self.env, str(self.work), ["pyright", "typescript"], bun=str(self.bin),
        )
        self.assertEqual(len(notes), 2)
        link = self.data / "opencode" / "bin" / "node_modules" / ".bin"
        self.assertTrue((link / "pyright-langserver").is_file())
        self.assertIn(str(link), self.env["PATH"])
        tsserver = self.work / "node_modules" / "typescript" / "lib" / "tsserver.js"
        self.assertTrue(tsserver.is_file())

    def test_pyright_already_on_path_skips_install(self):
        ready = Path(self.tmp.name) / "ready"
        ready.mkdir()
        _write(ready, "pyright-langserver", "#!/bin/sh\n")
        self.env["PATH"] = str(ready) + os.pathsep + self.env["PATH"]
        notes = provision_language_servers(
            self.env, str(self.work), ["pyright"], bun=str(self.bin),
        )
        self.assertIn("already", notes[0])
        self.assertFalse((self.data / "opencode" / "bin" / "node_modules").exists())

    def test_dotnet_sdk_10_installs_roslyn_onto_the_data_bin(self):
        notes = provision_language_servers(
            self.env, str(self.work), ["dotnet"], dotnet=str(self.dotnet),
        )
        bindir = self.data / "opencode" / "bin"
        self.assertTrue((bindir / "roslyn-language-server").is_file())
        self.assertTrue(self.env["PATH"].startswith(str(bindir)))
        self.assertIn("roslyn", notes[0])

    def test_dotnet_sdk_8_is_refused(self):
        self.env["FAKE_DOTNET_VERSION"] = "8.0.425"
        with self.assertRaises(LspProvisionError) as caught:
            provision_language_servers(
                self.env, str(self.work), ["dotnet"], dotnet=str(self.dotnet),
            )
        self.assertIn("SDK 10", str(caught.exception))

    def test_roslyn_already_on_path_skips_install(self):
        ready = Path(self.tmp.name) / "ready"
        ready.mkdir()
        _write(ready, "roslyn-language-server", "#!/bin/sh\n")
        self.env["PATH"] = str(ready) + os.pathsep + "/usr/bin"
        notes = provision_language_servers(self.env, str(self.work), ["dotnet"])
        self.assertIn("already", notes[0])
        self.assertFalse((self.data / "opencode" / "bin" / "roslyn-language-server").exists())

    def test_dotnet_root_is_used_when_path_misses_the_binary(self):
        self.env["DOTNET_ROOT"] = str(self.dotnet.parent)
        notes = provision_language_servers(self.env, str(self.work), ["dotnet"])
        self.assertIn("roslyn", notes[0])
        self.assertTrue((self.data / "opencode" / "bin" / "roslyn-language-server").is_file())

    def test_missing_dotnet_says_the_cell_cannot_run(self):
        with self.assertRaises(LspProvisionError) as caught:
            provision_language_servers(self.env, str(self.work), ["dotnet"])
        message = str(caught.exception)
        self.assertIn("SDK 10", message)
        self.assertIn("cannot", message)
        self.assertIn("--tool-path", message)

    def test_host_dotnet_root_is_prepended_when_the_directory_exists(self):
        saved = lsp_cell._HOST_DOTNET_ROOT
        lsp_cell._HOST_DOTNET_ROOT = str(self.dotnet.parent)
        try:
            notes = provision_language_servers(self.env, str(self.work), ["dotnet"])
        finally:
            lsp_cell._HOST_DOTNET_ROOT = saved
        self.assertEqual(self.env["DOTNET_ROOT"], str(self.dotnet.parent))
        self.assertIn(str(self.dotnet.parent), self.env["PATH"].split(os.pathsep))
        self.assertIn("roslyn", notes[0])

    def test_boolean_lsp_schema_is_detected_from_the_worktree(self):
        root = Path(self.tmp.name) / "src-tree"
        schema = root / "packages" / "opencode" / "src" / "config"
        runtime = root / "packages" / "opencode" / "src" / "lsp"
        schema.mkdir(parents=True)
        runtime.mkdir(parents=True)
        (schema / "lsp.ts").write_text(
            "export const Info = Schema.Union([Schema.Boolean, Schema.Record])\n",
            encoding="utf-8",
        )
        (runtime / "lsp.ts").write_text(
            'if (!cfg.lsp) { log.info("all LSPs are disabled") }\n',
            encoding="utf-8",
        )
        binary = root / "packages" / "opencode" / "dist" / "opencode"
        binary.parent.mkdir(parents=True)
        binary.write_text("", encoding="utf-8")
        self.assertTrue(lsp_boolean_enables_all(str(root)))
        self.assertEqual(worktree_root(str(binary)), str(root))
        (schema / "lsp.ts").write_text("export const Info = z.literal(false)\n", encoding="utf-8")
        self.assertFalse(lsp_boolean_enables_all(str(root)))

    def test_worktree_root_maps_cached_bin_and_embedded_paths(self):
        root = Path(self.tmp.name) / "worktrees" / ("ab" * 20)
        runtime = root / "packages" / "opencode" / "src" / "lsp"
        runtime.mkdir(parents=True)
        (runtime / "lsp.ts").write_text("all LSPs are disabled\n", encoding="utf-8")
        cached = Path(self.tmp.name) / "bin" / ("ab" * 20) / "opencode"
        cached.parent.mkdir(parents=True)
        cached.write_text("", encoding="utf-8")
        self.assertEqual(worktree_root(str(cached)), str(root))
        embedded = Path(self.tmp.name) / "loose" / "opencode"
        embedded.parent.mkdir(parents=True)
        embedded.write_text(
            "build /" + str(root).lstrip("/") + "/packages/opencode/src/index.ts\n",
            encoding="utf-8",
        )
        # The embedded path is absolute. Rewrite it as the regex expects.
        embedded.write_text(
            f"pre {root}/packages/opencode/src/index.ts tail\n",
            encoding="utf-8",
        )
        self.assertEqual(worktree_root(str(embedded)), str(root))

    def test_unknown_server_is_an_error(self):
        with self.assertRaises(LspProvisionError):
            provision_language_servers(self.env, str(self.work), ["vue"], bun=str(self.bin))


if __name__ == "__main__":
    unittest.main()
