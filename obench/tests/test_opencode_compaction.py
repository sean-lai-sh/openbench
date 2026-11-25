"""Compacting OpenCode trials: the synthetic continue text is not a step.

Fixtures are scrubbed event streams and wire summaries. ``wire.jsonl`` is not
committed (tens of MB). ``expected_counts.json`` is derived from the summaries
by ``fixtures/opencode-compaction/derive_expected.py``, which also records the
sha256 of each source wire file.

871d15b8 did not compact. Its ``trace-before-fix.jsonl`` is the trace the
runner wrote at 9acf060c. Rebuilding it from these events must match those
bytes. The request bodies the rebuild needs are already inside that trace, so
the check does not need ``wire.jsonl``.
"""

from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path

from obench.reflection import trace as tr
from obench.reflection import vertex_models as vm

FIX = Path(__file__).resolve().parent / "fixtures" / "opencode-compaction"
STORE = Path("/cursor/stores/bot/parser-fixtures")


def _load_derive():
    path = FIX / "derive_expected.py"
    spec = importlib.util.spec_from_file_location("derive_expected", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _events(trial: str) -> list[dict]:
    return tr.parse_events((FIX / trial / "opencode-events.jsonl").read_text(encoding="utf-8").splitlines())


def _summary(trial: str) -> list[dict]:
    return [json.loads(line) for line in (FIX / trial / "wire-summary.jsonl").read_text().splitlines() if line.strip()]


def _wires_from_trace(records: list[dict]) -> list[dict]:
    """Main wire records rebuilt from a trace. Side calls are not in the trace
    and are not needed to rebuild it: tool results come from the next main request."""
    wires = []
    for record in records:
        request = record["request"]
        wires.append({
            "schema": tr.WIRE_SCHEMA,
            "call_index": request["call_index"],
            "ts": request["sent_at"],
            "provider_wire": record["model"]["wire"],
            "call_role": "main",
            "requested_model": record["model"]["requested"],
            "upstream_model": record["model"]["served"],
            "request": request["payload"],
            "response_usage": record["usage"]["raw"],
            "status": 200,
            "response_arrived": request["response_arrived"],
            "first_byte_at": request["first_byte_at"],
            "stripped_side_thinking_blocks": record["stripped_side_thinking_blocks"],
        })
    return wires


class ExpectedCounts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.derive = _load_derive()
        cls.expected = json.loads((FIX / "expected_counts.json").read_text(encoding="utf-8"))

    def test_committed_counts_match_the_summaries(self):
        derived = self.derive.derive(FIX, None, self.expected)
        self.assertEqual(derived["trials"].keys(), self.expected["trials"].keys())
        for trial, counts in derived["trials"].items():
            self.assertEqual(counts, self.expected["trials"][trial], trial)
            self.assertRegex(counts["wire_sha256"], r"^[0-9a-f]{64}$")

    def test_source_wire_hashes_when_the_files_are_present(self):
        if not STORE.is_dir():
            return
        for trial, counts in self.expected["trials"].items():
            source = STORE / trial / "wire.jsonl"
            if not source.is_file():
                continue
            self.assertEqual(self.derive.sha256_file(source), counts["wire_sha256"], trial)


class CompactingTrials(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.expected = json.loads((FIX / "expected_counts.json").read_text(encoding="utf-8"))["trials"]

    def test_each_fixture_reparses_to_the_wire_counts(self):
        self.assertEqual(set(self.expected), {
            "87c18248152a10de", "c0a78cb7846266af", "ebf7daae69d40458",
            "c7d166acb03e2ef2", "6eb91275974b6bb7", "871d15b8",
        })
        for trial, counts in self.expected.items():
            with self.subTest(trial=trial):
                events = _events(trial)
                report = tr.trace_side_counts(events, _summary(trial))
                self.assertEqual(report["steps"], counts["steps"])
                self.assertEqual(report["compaction_steps"], counts["compaction_steps"])
                self.assertEqual(report["summary_steps"], counts["summary_steps"])
                self.assertEqual(report["synthetic_continue_messages"], counts["synthetic_continue_messages"])
                self.assertEqual(report["thinking_tokens"], counts["thinking_tokens"])
                self.assertEqual(report["compaction_thinking_tokens"], counts["compaction_thinking_tokens"])
                self.assertIsNotNone(report["thinking_tokens_status"])
                self.assertEqual(report["thinking_tokens_status"], counts["thinking_tokens_status"])
                self.assertEqual(report["trace_warnings"],
                                 [tr.IMPLICIT_TEXT_WARNING] * counts["synthetic_continue_messages"])
                # OpenCode's step_finish tokens.reasoning on the compaction steps.
                # These fixtures report 0. The row field stays the paired provider
                # usage above; it is not replaced with this counter.
                self.assertEqual(report["compaction_event_reasoning_tokens"], 0)
                self.assertNotIn("compaction_step_call_mismatch", " ".join(report["trace_warnings"]))
                source = STORE / trial / "wire.jsonl"
                if not source.is_file():
                    continue
                wires = [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines() if line.strip()]
                full = tr.trace_side_counts(events, wires)
                self.assertEqual(full["thinking_tokens"], counts["thinking_tokens"])
                self.assertEqual(full["compaction_thinking_tokens"], counts["compaction_thinking_tokens"])
                self.assertEqual(full["steps"], counts["steps"])
                records = tr.build_trace(events, wires, run={"trial": trial})
                self.assertEqual(len(records), counts["steps"])
                thinking = [r["usage"]["thinking_tokens"] for r in records
                            if isinstance(r["usage"]["thinking_tokens"], int)]
                self.assertEqual(sum(thinking), counts["thinking_tokens"])
                statuses = [r["usage"].get("thinking_tokens_status", "reported") for r in records]
                self.assertEqual({k: statuses.count(k) for k in sorted(set(statuses))},
                                 counts["thinking_tokens_status"])

    def test_noncompacting_trace_matches_the_pre_fix_bytes(self):
        trial = "871d15b8"
        saved_path = FIX / trial / "trace-before-fix.jsonl"
        saved_text = saved_path.read_text(encoding="utf-8")
        saved = [json.loads(line) for line in saved_text.splitlines()]
        events = _events(trial)
        model = vm.resolve(saved[0]["run"]["model"])
        records = tr.build_trace(
            events, _wires_from_trace(saved), run=saved[0]["run"],
            cost_fn=lambda rec: (vm.cost_usd(model, rec["usage"]), "reflection.vertex_models"))
        rebuilt = "".join(json.dumps(record, sort_keys=True) + "\n" for record in records)
        self.assertEqual(rebuilt, saved_text)
        source = STORE / trial / "wire.jsonl"
        if source.is_file():
            wires = [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines() if line.strip()]
            from_wire = tr.build_trace(
                events, wires, run=saved[0]["run"],
                cost_fn=lambda rec: (vm.cost_usd(model, rec["usage"]), "reflection.vertex_models"))
            self.assertEqual("".join(json.dumps(record, sort_keys=True) + "\n" for record in from_wire), saved_text)
        # The file itself stays under the repo size cap.
        self.assertLess(saved_path.stat().st_size, 2 * 1024 * 1024)
        for path in FIX.rglob("*"):
            if path.is_file():
                self.assertLess(path.stat().st_size, 2 * 1024 * 1024, path.name)
                self.assertFalse(path.name == "wire.jsonl")


class NoCommittedWire(unittest.TestCase):
    def test_summaries_have_only_the_five_fields(self):
        for path in sorted(FIX.glob("*/wire-summary.jsonl")):
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                row = json.loads(line)
                self.assertEqual(set(row), {"call_index", "call_role", "side_kind", "status", "thinking_tokens"})


if __name__ == "__main__":
    unittest.main()
