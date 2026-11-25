"""SEA-111 draw: seeded picks and the rule-2 cap_cutoff filter. No model calls.

The committed fixture is the pilot-3 v2 draw reduced to cell, sorted eligible
trial ids, cap_cutoff slot+id, and expected picks. It has no traces, paths,
hostnames, or project ids. The run under test is built from that list.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import random
import tempfile
import unittest
from pathlib import Path

from obench.reflection import credit_draw as draw

FIXTURE = Path(__file__).parent / "fixtures" / "sea111_credit_draw.json"
DNA_INSERT = "gemini-4-carbon/dna-insert"
# The pilot cell is excluded because this many set-aside trials exceed the default cap of 3.
DNA_SET_ASIDE = 5

TOOL_ERROR = {"step": 1, "tool_calls": [{"name": "bash", "arguments": {}, "result": "permission denied", "status": "error"}],
              "assistant_text": ""}
OUTPUT_ERROR = {"step": 1, "tool_calls": [{"name": "bash", "arguments": {}, "result": "Traceback (most recent call last):\nNameError: x",
                                           "status": "completed"}], "assistant_text": ""}
SILENT = {"step": 1, "tool_calls": [{"name": "bash", "arguments": {}, "result": "ok", "status": "completed"}],
          "assistant_text": "finished"}
LATER_ERROR = [
    {"step": 1, "tool_calls": [{"name": "bash", "arguments": {}, "result": "ok", "status": "completed"}], "assistant_text": ""},
    {"step": 2, "tool_calls": [{"name": "bash", "arguments": {}, "result": "permission denied", "status": "error"}],
     "assistant_text": ""},
]


def spec_sample(cell: str, trial_ids: list[str], n_pick: int | str) -> list[str]:
    """The draw formula, written out here so the driver is checked against it."""
    ordered = sorted(trial_ids)
    if not ordered:
        return []
    digest = hashlib.sha256(("sea111-" + cell).encode("utf-8")).hexdigest()
    k = len(ordered) if n_pick == "all" else min(n_pick, len(ordered))
    return random.Random(int(digest, 16)).sample(ordered, k)


def load_fixture() -> list[dict]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _quiet_main(argv: list[str]) -> int:
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return draw.main(argv)


def _row(model, task, trial_id, slot, *, status="completed", passed=False, timed_out=False,
         trace="traces/tool_error.jsonl", patch_id=None):
    return {"run_id": "r", "trial_id": trial_id, "task": task, "model": model, "patch_id": patch_id,
            "trial_index": slot, "status": status, "passed": passed, "timed_out": timed_out, "trace": trace}


def _write_traces(run: Path) -> None:
    traces = run / "traces"
    traces.mkdir(parents=True)
    (traces / "tool_error.jsonl").write_text(json.dumps(TOOL_ERROR) + "\n", encoding="utf-8")
    (traces / "output_error.jsonl").write_text(json.dumps(OUTPUT_ERROR) + "\n", encoding="utf-8")
    (traces / "silent.jsonl").write_text(json.dumps(SILENT) + "\n", encoding="utf-8")
    (traces / "empty.jsonl").write_text("", encoding="utf-8")


def _dump(run: Path, rows: list[dict]) -> Path:
    (run / "trials.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    return run


def new_run(rows: list[dict]) -> Path:
    run = Path(tempfile.mkdtemp())
    _write_traces(run)
    return _dump(run, rows)


def fixture_run() -> Path:
    """Eligible ids get a tool-error trace. cap_cutoff ids are timeouts with a silent trace.

    dna-insert also gets DNA_SET_ASIDE provider-blocked trials, so the cap — not the
    cell name — is what keeps it out.
    """
    rows = []
    for cell in load_fixture():
        model, task = cell["cell"].split("/", 1)
        pick_slot = {pick["trial_id"]: pick["slot"] for pick in cell["picks"]}
        used = set(pick_slot.values()) | {item["slot"] for item in cell["cap_cutoff"]}
        next_slot = 0

        def allocate(preferred=None):
            nonlocal next_slot
            if preferred is not None:
                return preferred
            while next_slot in used:
                next_slot += 1
            slot = next_slot
            used.add(slot)
            next_slot += 1
            return slot

        for trial_id in cell["eligible"]:
            rows.append(_row(model, task, trial_id, allocate(pick_slot.get(trial_id))))
        for item in cell["cap_cutoff"]:
            rows.append(_row(model, task, item["trial_id"], item["slot"], timed_out=True, trace="traces/silent.jsonl"))
        if cell["cell"] == DNA_INSERT:
            for i in range(DNA_SET_ASIDE):
                rows.append(_row(model, task, f"aside-{i}", 1000 + i, status="provider_blocked", passed=None, trace=None))
    return new_run(rows)


class PostedDraw(unittest.TestCase):
    def test_fixture_picks_match_the_seed_formula(self):
        for cell in load_fixture():
            if not cell["picks"]:
                continue
            with self.subTest(cell=cell["cell"]):
                self.assertEqual(spec_sample(cell["cell"], cell["eligible"], 3),
                                 [pick["trial_id"] for pick in cell["picks"]])

    def test_eight_cells_reproduce_posted_picks_and_dna_insert_is_excluded(self):
        run = fixture_run()
        before = (run / "trials.jsonl").read_text(encoding="utf-8")
        manifests = draw.run_draw(run)
        again = draw.run_draw(run)
        self.assertEqual(again, manifests)  # same seed, same pool, same picks
        self.assertEqual((run / "trials.jsonl").read_text(encoding="utf-8"), before)
        on_disk = json.loads((run / "credit_draw.json").read_text(encoding="utf-8"))
        self.assertEqual(on_disk, manifests)
        self.assertEqual(set(manifests), {cell["cell"] for cell in load_fixture()})

        in_cells = []
        for cell in load_fixture():
            rec = manifests[cell["cell"]]
            with self.subTest(cell=cell["cell"]):
                per_cell = json.loads((run / "credit_draw" / f"{cell['cell'].replace('/', '__')}.json").read_text())
                self.assertEqual(per_cell, rec)
                self.assertEqual(rec["seed_string"], "sea111-" + cell["cell"])
                self.assertEqual(rec["seed_sha256"], hashlib.sha256(rec["seed_string"].encode("utf-8")).hexdigest())
                self.assertEqual(rec["max_set_aside"], 3)
                self.assertEqual(rec["cap_cutoff_dropped"], cell["cap_cutoff"])
                if cell["cell"] == DNA_INSERT:
                    self.assertEqual(rec["status"], "EXCLUDED")
                    self.assertEqual(rec["set_aside_count"], DNA_SET_ASIDE)
                    self.assertGreater(rec["set_aside_count"], rec["max_set_aside"])
                    self.assertEqual(rec["reason"],
                                     "max_set_aside=3: 5 set-aside (provider_blocked) trials > 3")
                    self.assertNotIn(cell["cell"], rec["reason"])
                    self.assertEqual(rec["eligible_pool"], 0)
                    self.assertEqual(rec["picks"], [])
                    self.assertEqual([item["trial_id"] for item in rec["cap_cutoff_dropped"]],
                                     ["c9a507efe5b663be", "63832e70ede377b0", "09c8fc998831be5c",
                                      "1bf6eb185db51015", "6a0de60a06f3be0e", "78daab61305063ba"])
                else:
                    in_cells.append(cell["cell"])
                    self.assertEqual(rec["status"], "IN")
                    self.assertIsNone(rec["reason"])
                    self.assertEqual(rec["set_aside_count"], 0)
                    self.assertEqual(rec["eligible_pool"], len(cell["eligible"]))
                    self.assertEqual(rec["picks"], cell["picks"])
                    self.assertEqual([pick["draw_order"] for pick in rec["picks"]], [1, 2, 3])
        self.assertEqual(len(in_cells), 8)
        opus = manifests["claude-opus-5-5/model-extraction-relu-logits"]["picks"]
        carbon = manifests["gemini-4-carbon/video-processing"]["picks"]
        self.assertEqual([pick["slot"] for pick in opus], [16, 19, 17])
        self.assertEqual([pick["trial_id"] for pick in opus],
                         ["64d1c53d6ac8bfd6", "824a3b8e917a2d65", "8cabc5c748164741"])
        self.assertEqual([pick["slot"] for pick in carbon], [1, 5, 12])
        self.assertEqual([pick["trial_id"] for pick in carbon],
                         ["8e77f50296b58395", "800321fd8859ee2e", "49a8868e86ee18e0"])

    def test_n_pick_all_returns_every_eligible_failure_in_draw_order(self):
        run = fixture_run()
        cell = next(item for item in load_fixture() if item["cell"] == "claude-opus-5-5/model-extraction-relu-logits")
        manifests = draw.run_draw(run, n_pick="all")
        picks = [pick["trial_id"] for pick in manifests[cell["cell"]]["picks"]]
        self.assertEqual(picks, spec_sample(cell["cell"], cell["eligible"], "all"))
        self.assertEqual(set(picks), set(cell["eligible"]))
        self.assertEqual(len(picks), len(cell["eligible"]))

        # A cell smaller than the numeric n_pick still returns every eligible failure.
        small = new_run([
            _row("m", "tiny", "b", 1),
            _row("m", "tiny", "a", 0),
        ])
        rec = draw.run_draw(small, n_pick=5)["m/tiny"]
        self.assertEqual([pick["trial_id"] for pick in rec["picks"]], spec_sample("m/tiny", ["b", "a"], "all"))
        self.assertEqual(rec["eligible_pool"], 2)


class Rule2(unittest.TestCase):
    def test_timeout_without_a_tool_error_is_cap_cutoff_and_with_one_is_not(self):
        run = Path(tempfile.mkdtemp())
        _write_traces(run)
        (run / "traces" / "later.jsonl").write_text(
            "".join(json.dumps(step) + "\n" for step in LATER_ERROR), encoding="utf-8")
        rows = [
            _row("m", "t", "silent-fail", 1, trace="traces/silent.jsonl"),
            _row("m", "t", "cap-silent", 2, timed_out=True, trace="traces/silent.jsonl"),
            _row("m", "t", "cap-status", 3, timed_out=True, trace="traces/tool_error.jsonl"),
            _row("m", "t", "cap-output", 4, timed_out=True, trace="traces/output_error.jsonl"),
            _row("m", "t", "cap-later", 10, timed_out=True, trace="traces/later.jsonl"),
            _row("m", "t", "cap-missing", 5, timed_out=True, trace="traces/missing.jsonl"),
            _row("m", "t", "cap-empty", 6, timed_out=True, trace="traces/empty.jsonl"),
            _row("m", "t", "cap-null", 7, timed_out=True, trace=None),
            _row("m", "t", "passed", 8, passed=True, timed_out=True, trace="traces/silent.jsonl"),
            _row("m", "t", "infra", 9, status="timeout", passed=None, timed_out=True, trace="traces/silent.jsonl"),
        ]
        rec = draw.run_draw(_dump(run, rows), n_pick="all")["m/t"]
        self.assertEqual(rec["status"], "IN")
        self.assertEqual([item["trial_id"] for item in rec["cap_cutoff_dropped"]], ["cap-silent"])
        eligible = ["silent-fail", "cap-status", "cap-output", "cap-later"]
        self.assertEqual([pick["trial_id"] for pick in rec["picks"]], spec_sample("m/t", eligible, "all"))
        self.assertEqual(rec["no_trace_count"], 3)
        self.assertEqual([item["trial_id"] for item in rec["no_trace_trials"]],
                         ["cap-missing", "cap-empty", "cap-null"])
        self.assertNotIn("passed", [pick["trial_id"] for pick in rec["picks"]])
        self.assertNotIn("infra", [item["trial_id"] for item in rec["cap_cutoff_dropped"]])

    def test_leaving_cap_cutoff_in_the_pool_would_change_the_picks(self):
        cell = "synthetic/cap-changes-draw"
        eligible = [f"f{i:02d}" for i in range(8)]
        cap_id = "c0"
        without = spec_sample(cell, eligible, 3)
        with_cap = spec_sample(cell, eligible + [cap_id], 3)
        self.assertNotEqual(with_cap, without)

        rows = [_row("synthetic", "cap-changes-draw", trial_id, slot) for slot, trial_id in enumerate(eligible)]
        rows.append(_row("synthetic", "cap-changes-draw", cap_id, 99, timed_out=True, trace="traces/silent.jsonl"))
        rec = draw.run_draw(new_run(rows))[cell]
        self.assertEqual([pick["trial_id"] for pick in rec["picks"]], without)
        self.assertNotEqual([pick["trial_id"] for pick in rec["picks"]], with_cap)
        self.assertEqual(rec["cap_cutoff_dropped"], [{"slot": 99, "trial_id": cap_id}])
        self.assertEqual(rec["eligible_pool"], len(eligible))


class SetAsideCap(unittest.TestCase):
    def test_any_cell_over_the_cap_is_excluded_and_three_stays_in(self):
        rows = []
        aside = {
            "three": ["provider_blocked"] * 3,
            "four": ["model_refused", "model_refused", "provider_blocked", "provider_blocked"],
            "five": ["provider_blocked"] * 5,
        }
        for task, kinds in aside.items():
            rows.append(_row("other-model", task, f"{task}-fail", 0))
            for i, kind in enumerate(kinds):
                rows.append(_row("other-model", task, f"{task}-aside-{i}", 10 + i, status=kind, passed=None, trace=None))
        # A patched copy of an admitted cell must not inherit the other patch's set-aside trials.
        rows.append(_row("other-model", "three", "patched-fail", 0, patch_id="patch-1"))
        for i in range(5):
            rows.append(_row("other-model", "three", f"patched-aside-{i}", 10 + i, status="provider_blocked",
                             passed=None, trace=None, patch_id="patch-1"))

        manifests = draw.run_draw(new_run(rows))
        self.assertEqual(manifests["other-model/three"]["status"], "IN")
        self.assertEqual(manifests["other-model/three"]["set_aside_count"], 3)
        self.assertEqual(manifests["other-model/three"]["picks"][0]["trial_id"], "three-fail")
        self.assertEqual(manifests["other-model/four"]["status"], "EXCLUDED")
        self.assertEqual(manifests["other-model/four"]["reason"],
                         "max_set_aside=3: 4 set-aside (model_refused, provider_blocked) trials > 3")
        self.assertEqual(manifests["other-model/five"]["status"], "EXCLUDED")
        self.assertEqual(manifests["other-model/five"]["picks"], [])
        patched = manifests["other-model/three@patch-1"]
        self.assertEqual(patched["status"], "EXCLUDED")
        self.assertEqual(patched["set_aside_count"], 5)
        self.assertIn("provider_blocked", patched["reason"])

        widened = draw.run_draw(new_run(rows), max_set_aside=4)
        self.assertEqual(widened["other-model/four"]["status"], "IN")
        self.assertEqual(widened["other-model/four"]["max_set_aside"], 4)
        self.assertEqual(widened["other-model/five"]["status"], "EXCLUDED")

    def test_config_and_cli_override_n_pick_and_the_cap(self):
        rows = [_row("m", "t", "a", 0), _row("m", "t", "b", 1)]
        for i in range(4):
            rows.append(_row("m", "t", f"aside-{i}", 10 + i, status="model_refused", passed=None, trace=None))
        run = new_run(rows)
        cfg = run / "draw.json"
        cfg.write_text(json.dumps({"n_pick": "all", "max_set_aside": 0}), encoding="utf-8")

        excluded = draw.run_draw(run, **{"n_pick": draw.resolve_config(cfg).n_pick,
                                         "max_set_aside": draw.resolve_config(cfg).max_set_aside})
        self.assertEqual(excluded["m/t"]["status"], "EXCLUDED")

        self.assertEqual(_quiet_main(["--run", str(run), "--config", str(cfg), "--max-set-aside", "4"]), 0)
        admitted = json.loads((run / "credit_draw.json").read_text(encoding="utf-8"))["m/t"]
        self.assertEqual(admitted["status"], "IN")
        self.assertEqual(admitted["max_set_aside"], 4)
        self.assertEqual(admitted["n_pick"], "all")
        self.assertEqual([pick["trial_id"] for pick in admitted["picks"]], spec_sample("m/t", ["a", "b"], "all"))

        self.assertEqual(_quiet_main(["--run", str(run), "--n-pick", "1", "--max-set-aside", "4"]), 0)
        one = json.loads((run / "credit_draw.json").read_text(encoding="utf-8"))["m/t"]
        self.assertEqual(len(one["picks"]), 1)
        self.assertEqual(one["picks"][0]["trial_id"], spec_sample("m/t", ["a", "b"], 1)[0])

        with self.assertRaises(SystemExit):
            _quiet_main(["--run", str(run), "--n-pick", "0"])
        with self.assertRaises(SystemExit):
            _quiet_main(["--run", str(run), "--n-pick", "maybe"])
        for raw in ({"n_pick": 0}, {"n_pick": True}, {"n_pick": "3"}, {"max_set_aside": -1}, {"extra": 1}):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                draw.DrawConfig.from_dict(raw)


if __name__ == "__main__":
    unittest.main()
