#!/usr/bin/env python3
"""Unit + CLI tests for the PII scrubber (bench/scrub.py).

Covers each PII class, idempotency, --check reporting/exit code, that originals
are never modified, tree scrubbing into a parallel dir, and the in-place guard.
A fixed context (synthetic user/home/hostname) keeps results independent of the
machine running the tests.
"""

import os

BENCH_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

import subprocess
import sys
import tempfile
import unittest

SCRUB_MOD = ["-m", "obench.scrub"]
from obench import scrub  # noqa: E402

# Synthetic identity so tests don't depend on the real machine.
CTX = scrub.build_context(
    user="alice",
    home="/Users/alice",
    hostnames=["Alices-Laptop.local"],
)


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _write_file(path, text):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


class TestScrubClasses(unittest.TestCase):
    def _scrub(self, text):
        return scrub.scrub_text(text, CTX)

    def test_email(self):
        out = self._scrub("contact me at jane.doe+test@example.co.uk please")
        self.assertNotIn("jane.doe", out)
        self.assertIn("<EMAIL>", out)

    def test_home_path(self):
        out = self._scrub("cd /Users/alice/dev/openbench && ls")
        self.assertIn("<HOME>/dev/openbench", out)
        self.assertNotIn("/Users/alice", out)

    def test_alt_home_path_forms(self):
        out = self._scrub("linux path /home/alice/x and mac /Users/alice/y")
        self.assertNotIn("/home/alice", out)
        self.assertNotIn("/Users/alice", out)
        self.assertEqual(out.count("<HOME>"), 2)

    def test_username_standalone(self):
        out = self._scrub("the user alice ran it")
        self.assertIn("<USER>", out)
        self.assertNotIn(" alice ", out)

    def test_username_not_substring(self):
        # Word-boundary: 'alice' inside 'malice' must NOT be replaced.
        out = self._scrub("this was done without malice")
        self.assertIn("malice", out)
        self.assertNotIn("<USER>", out)

    def test_hostname(self):
        out = self._scrub("running on Alices-Laptop.local now")
        self.assertIn("<HOST>", out)
        self.assertNotIn("Alices-Laptop", out)

    def test_api_key(self):
        out = self._scrub("export OPENAI_API_KEY=sk-abcDEF0123456789ghijklmnop")
        self.assertIn("<REDACTED_KEY>", out)
        self.assertNotIn("sk-abcDEF", out)

    def test_github_token(self):
        out = self._scrub("token ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 used")
        self.assertIn("<REDACTED_KEY>", out)
        self.assertNotIn("ghp_ABCDEF", out)

    def test_aws_key(self):
        out = self._scrub("AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE end")
        self.assertIn("<REDACTED_KEY>", out)
        self.assertNotIn("AKIAIOSFODNN7EXAMPLE", out)

    def test_huggingface_token(self):
        # Regression: GitHub push protection blocked a results file this
        # scrubber had already passed. sanitize-git-repo's checker echoes the
        # fixture credentials it finds into checker_stdout, and hf_ was the one
        # prefix with no rule.
        out = self._scrub("HF_TOKEN=hf_abcdefghijklmnopqrstuvwxyz123456 end")
        self.assertIn("<REDACTED_KEY>", out)
        self.assertNotIn("hf_abcdefghij", out)

    def test_hex_blob(self):
        out = self._scrub("sha " + "a1b2c3d4" * 5 + " done")  # 40 hex chars
        self.assertIn("<REDACTED_HEX>", out)

    def test_base64_blob(self):
        blob = "QWxpY2VJc0FTZWNyZXRWYWx1ZVRoYXRJc1F1aXRlTG9uZ0Vub3VnaA1234"  # >40, has no @
        out = self._scrub("data: " + blob)
        self.assertTrue("<REDACTED_B64>" in out or "<REDACTED_HEX>" in out)

    def test_short_token_not_redacted(self):
        # Short, low-entropy strings must survive (no false positives).
        out = self._scrub("the cat sat on the mat with abc123")
        self.assertEqual(out, "the cat sat on the mat with abc123")

    def test_idempotent(self):
        text = ("user alice at /Users/alice on Alices-Laptop.local, "
                "email jane@example.com, key sk-abcDEF0123456789ghijklmnop")
        once = self._scrub(text)
        twice = self._scrub(once)
        self.assertEqual(once, twice)
        # And a fully-scrubbed string reports zero remaining PII.
        self.assertEqual(scrub.find_pii(once, CTX), [])


class TestFindPii(unittest.TestCase):
    def test_find_reports_categories_and_lines(self):
        text = "line one clean\nemail jane@example.com here\n/Users/alice/x"
        hits = scrub.find_pii(text, CTX)
        cats = {c for c, _ln, _s in hits}
        self.assertIn("email", cats)
        self.assertIn("home-path", cats)
        lines = {ln for _c, ln, _s in hits}
        self.assertIn(2, lines)
        self.assertIn(3, lines)

    def test_find_clean_text_empty(self):
        self.assertEqual(scrub.find_pii("nothing to see here", CTX), [])


SHA40 = "b1cbded32a92eb08c107428dc46a1b015ce777c4"
SHA64 = "2aeae8457f8eaf862375526cc555b84ac8040b9b94a34ce0a88d2809fcb7ced1"


def _cell(**fields):
    import json
    return json.dumps(dict(sorted(fields.items())))


def _cats(hits):
    return {c for c, _ln, _s in hits}


class TestProvenanceHexException(unittest.TestCase):
    """Codex P2 / PR #258: exact provenance hashes survive in cell JSON/jsonl
    under their own keys only; the same value anywhere else is still flagged."""

    def _allowed_line(self):
        return _cell(
            binary_sha256=SHA64,
            runner_commit=SHA40,
            lockfile_sha256=SHA64,
            final_workspace_tar_sha256=SHA64,
            binary_path=f"/h1/opencode-src/bin/{SHA40}/opencode",
            task="dna-insert",
        )

    # (a) the five fields pass, in cell JSON and in jsonl
    def test_allowed_keys_not_flagged_structured(self):
        self.assertEqual(scrub.find_pii(self._allowed_line(), CTX, structured=True), [])

    def test_allowed_keys_pretty_printed_json(self):
        import json
        text = json.dumps(json.loads(self._allowed_line()), indent=2)
        self.assertEqual(scrub.find_pii(text, CTX, structured=True), [])

    def test_allowed_keys_survive_scrub(self):
        line = self._allowed_line()
        self.assertEqual(scrub.scrub_text(line, CTX, structured=True), line)

    def test_check_tree_allows_in_json_and_jsonl(self):
        tmp = tempfile.mkdtemp(prefix="bench_scrub_prov_")
        try:
            line = self._allowed_line()
            _write_file(os.path.join(tmp, "1.json"), line)
            _write_file(os.path.join(tmp, "with.jsonl"), line + "\n" + line + "\n")
            self.assertEqual(scrub.check_tree(tmp, CTX), {})
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)

    # (b) the same values elsewhere are still flagged
    def test_same_value_under_other_key_flagged(self):
        for key in ("provider_pin_sha256", "sha256", "cell_image", "note",
                    "binary_sha256_extra", "x_runner_commit"):
            for value in (SHA40, SHA64):
                hits = scrub.find_pii(_cell(**{key: value}), CTX, structured=True)
                self.assertIn("hex-blob", _cats(hits), msg=(key, value))
                out = scrub.scrub_text(_cell(**{key: value}), CTX, structured=True)
                self.assertNotIn(value, out, msg=(key, value))

    def test_nested_other_key_flagged(self):
        text = _cell(checker_workspace_files={"a.txt": {"sha256": SHA64}})
        self.assertIn("hex-blob", _cats(scrub.find_pii(text, CTX, structured=True)))

    def test_free_text_flagged(self):
        for text in (f"runner_commit: {SHA40}",
                     f'"runner_commit": "{SHA40}"',
                     f"binary at /h1/opencode-src/bin/{SHA40}/opencode",
                     f"sha256 {SHA64}"):
            # Free text (structured=False) never gets the exception...
            self.assertIn("hex-blob", _cats(scrub.find_pii(text, CTX)), msg=text)
            self.assertNotIn(SHA40 if SHA40 in text else SHA64, scrub.scrub_text(text, CTX))

    def test_txt_file_with_key_syntax_flagged(self):
        tmp = tempfile.mkdtemp(prefix="bench_scrub_prov_")
        try:
            _write_file(os.path.join(tmp, "MANIFEST.txt"),
                        f"opus/x.workspace.tar.gz 1607 {SHA64}\n")
            _write_file(os.path.join(tmp, "notes.md"), self._allowed_line())
            report = scrub.check_tree(tmp, CTX)
            self.assertIn("MANIFEST.txt", report)
            self.assertIn("notes.md", report)
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)

    def test_value_in_free_text_field_of_cell_flagged(self):
        # Escaped JSON inside a string value is free text, not a key.
        inner = '{"runner_commit": "%s"}' % SHA40
        text = _cell(output_tail=inner, checker_stdout=f"commit {SHA64}")
        hits = scrub.find_pii(text, CTX, structured=True)
        snippets = {s for _c, _ln, s in hits}
        self.assertTrue(any(SHA40[:20] in s for s in snippets), hits)
        self.assertTrue(any(SHA64[:20] in s for s in snippets), hits)

    def test_inexact_values_flagged(self):
        for bad in (SHA64[:48], SHA64 + "ab", "0x" + SHA40, SHA40 + " ", "v" + SHA40):
            hits = scrub.find_pii(_cell(runner_commit=bad), CTX, structured=True)
            self.assertTrue(hits, msg=bad)

    def test_binary_path_only_hex_segment(self):
        # Hex embedded in a longer segment is not an exact segment -> flagged.
        text = _cell(binary_path=f"/h1/bin/build-{SHA40}/opencode")
        self.assertTrue(scrub.find_pii(text, CTX, structured=True))
        # Other PII in binary_path is still caught.
        text = _cell(binary_path=f"/Users/alice/bin/{SHA40}/opencode")
        self.assertIn("home-path", _cats(scrub.find_pii(text, CTX, structured=True)))
        # The hex segment of other path-like keys stays flagged.
        text = _cell(harness_version=f"0.0.0 (/h1/opencode-src/bin/{SHA40}/opencode)",
                     cmd=[f"/h1/opencode-src/bin/{SHA40}/opencode", "run"])
        hits = scrub.find_pii(text, CTX, structured=True)
        self.assertEqual(sum(1 for c, _l, _s in hits if c == "hex-blob"), 2)

    def test_allowed_and_other_on_same_line(self):
        text = _cell(runner_commit=SHA40, provider_pin_sha256=SHA64)
        hits = scrub.find_pii(text, CTX, structured=True)
        self.assertEqual([s for c, _l, s in hits if c == "hex-blob"], [SHA64[:57] + "..."])
        out = scrub.scrub_text(text, CTX, structured=True)
        self.assertIn(SHA40, out)
        self.assertNotIn(SHA64, out)


class TestFileOps(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="bench_scrub_")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, rel, text):
        path = os.path.join(self.tmp, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    def test_scrub_tree_never_modifies_original(self):
        src = os.path.join(self.tmp, "src")
        original = "/Users/alice/secret and jane@example.com"
        self._write("src/a.txt", original)
        out = os.path.join(self.tmp, "out")

        written = scrub.scrub_tree(src, out, CTX)
        self.assertEqual(len(written), 1)
        # Original is byte-for-byte unchanged.
        self.assertEqual(_read(os.path.join(src, "a.txt")), original)
        # Scrubbed copy has placeholders, no PII.
        scrubbed = _read(os.path.join(out, "a.txt"))
        self.assertIn("<HOME>", scrubbed)
        self.assertIn("<EMAIL>", scrubbed)
        self.assertNotIn("/Users/alice", scrubbed)

    def test_scrub_tree_mirrors_nested_layout(self):
        src = os.path.join(self.tmp, "src")
        self._write("src/sub/deep.txt", "at /Users/alice/here")
        out = os.path.join(self.tmp, "out")
        scrub.scrub_tree(src, out, CTX)
        self.assertTrue(os.path.isfile(os.path.join(out, "sub", "deep.txt")))

    def test_scrub_tree_refuses_in_place(self):
        src = os.path.join(self.tmp, "src")
        self._write("src/a.txt", "x")
        with self.assertRaises(ValueError):
            scrub.scrub_tree(src, os.path.join(src, "nested"), CTX)


class TestCli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="bench_scrub_cli_")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, *args):
        return subprocess.run(
            [sys.executable, *SCRUB_MOD, *args,
             "--user", "alice", "--home", "/Users/alice",
             "--hostname", "Alices-Laptop.local"],
            capture_output=True, text=True,
        )

    def test_check_exit1_when_pii_present(self):
        f = os.path.join(self.tmp, "t.txt")
        _write_file(f, "email jane@example.com")
        proc = self._run(f, "--check")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("email", proc.stdout)
        self.assertIn("POTENTIAL PII", proc.stdout)

    def test_check_exit0_when_clean(self):
        f = os.path.join(self.tmp, "t.txt")
        _write_file(f, "nothing sensitive here")
        proc = self._run(f, "--check")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("CLEAN", proc.stdout)

    def test_check_writes_nothing(self):
        f = os.path.join(self.tmp, "t.txt")
        _write_file(f, "email jane@example.com")
        before = sorted(os.listdir(self.tmp))
        self._run(f, "--check")
        self.assertEqual(sorted(os.listdir(self.tmp)), before)

    def test_scrub_mode_writes_copies(self):
        f = os.path.join(self.tmp, "t.txt")
        _write_file(f, "at /Users/alice/x")
        out = os.path.join(self.tmp, "out")
        proc = self._run(f, "--out", out)
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn("<HOME>", _read(os.path.join(out, "t.txt")))

    def test_scrub_mode_requires_out(self):
        f = os.path.join(self.tmp, "t.txt")
        _write_file(f, "x")
        proc = self._run(f)
        self.assertNotEqual(proc.returncode, 0)


if __name__ == "__main__":
    unittest.main()
