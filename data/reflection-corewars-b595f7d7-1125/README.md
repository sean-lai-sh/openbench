# Opus winning-avg-corewars, uncensored cell `corewars-b595f7d7` (run id `opus-corewars-b595f7d7`, 2026-11-25)

The 30-trial Opus (`claude-opus-5-5`) `winning-avg-corewars` cell, re-run after the compaction fixes.

## Relation to pilot-3

This cell is **reported on its own and is not pooled with pilot-3**. It is the **uncensored** Opus corewars result.
Pilot-3's Opus corewars cell (`data/reflection-pilot3-1119`) stays labeled **compaction-censored**, with its three
readings unchanged: 27/30 retried (verdict), 19/30 first attempt, 18/30 sensitivity. Opus corewars enters credit
assignment from this cell once this data PR merges.

## Identity

| Field | Value |
|---|---|
| Code commit (main) | `b595f7d7df814cc93caed29629af8d6b6ebbc1f1` (#275 parser fix, on top of #274 `75ab94b2` targeted strip and #272 `e86a8f70` drop_block); `code_dirty` false on every row |
| Bench commit | `2fd12b88aafdd04a52c298e3940bcb189f9766d6` |
| OpenCode | stock pin `ba54cee55e18b47fb70badc84ae2cbac7c83d258` |
| Image | `openbench-tb2-winning-avg-corewars:pinned` = `sha256:78f1ae14c15e7e17819ebf2f90ab540799301a5e68e31212b2acb397af4f2685` (run with `--use-image-tag`) |
| `image_matches_pin` | **false** on all 30 rows (the host image is not the task.toml digest; recorded, and listed in `verdicts.json` `image_matches_pin_false`) |
| `--smoke-compaction` | **off** (default). `OBENCH_SMOKE_COMPACTION` unset. Every row has `smoke_compaction.enabled = false` (context_limit 200000, usable 168000) and `plan.json` has `smoke_compaction: false` |
| Host | `thesis-h1-cpu` (GCP VM, us-central1-a, 16 vCPU), 8 workers |
| Runner flags | `--cell --use-image-tag --workers 8 --retry-infra` (infra re-runs capped at 3 per slot; none were needed) |
| Started / finished | 2026-11-25 10:34 UTC / 11:59 UTC (05:34 / 06:59 ET) |
| Spend | $94.76 (`status.json`, state `done`); spend cap in config $120 |
| Gate at this commit | unit tests: same failure/error set as the 75ab94b2 baseline on this host (4 failures + 90 errors on the VM, identical names; 2574 tests vs 2567); `validate --no-imported` same set as baseline; `validate` exercism OK; terminal-bench `cancel-async-tasks` solution flaked once (known flake, seen in four earlier gate logs) and passed on re-run |

## Stop rules (watcher, `watch.log`)

The cell would have been stopped (SIGINT to the runner so it drains) on any of these:

- any wire call with `thinking_signature_reject = true`;
- any trial row with status `post_compaction_signature` (or `side_thinking_signature`);
- any compaction side call that did not return 200;
- a compaction loop (3+ compactions and more than half as many as main turns);
- a row with `smoke_compaction.enabled`, a commit other than `b595f7d7`, a dirty tree, or a different image;
- wire spend above $120.

**No stop rule fired.** No call anywhere had `thinking_signature_reject`, no call returned non-200, and the
runner finished with state `done`.

## Result

| Passes | Completed n | Set aside | Wilson 95% |
|---|---|---|---|
| **28** | **30** | **0** | **[0.787, 0.982]** |

All 30 slots settled on their first attempt (`attempt 0`; no infra re-runs, no `provider_blocked`, no `model_refused`).
The two fails (slots 12 and 14) hit the 1800 s cap with the agent still working (`timeout_detail.still_working`), so
they count as task fails under the status rules. 28/30 = 0.933 is above the 0.9 swap cutoff.

## Compaction

9 of 30 trials compacted, each exactly once (slots 1, 3, 5, 7, 9, 12, 13, 15, 26). All 9 compaction side calls returned
200 with `thinking_block_binding = drop_block`. The #274 strip removed 43 side-signed thinking blocks in total, exactly one on
each of the 43 main turns after a compaction, and none of those turns was rejected. The #275 parser recovered the
synthetic continue text on every compacting trial (`trace_warnings = ["implicit_text_before_step_start"]`,
`synthetic_continue_messages = 1`), so these rows have full `steps` and `thinking_tokens`.

## Zero-thinking rate (main steps with 0 or null thinking tokens)

| Turns | Zero-thinking / turns | Rate |
|---|---|---|
| After a compaction (main steps after the trial's compaction call) | 5/43 | 0.116 |
| No compaction, all (never-compacted trials + pre-compaction segments) | 151/1360 | 0.111 |
| — trials that never compacted | 98/851 | 0.115 |
| — pre-compaction segments of compacting trials | 53/509 | 0.104 |

Thinking tokens are the provider's `response_usage.output_tokens_details.thinking_tokens` (null counted as 0; no main step
reported null). The post-compaction sample is small (43 turns in 9 trials), but there is no sign that the strip suppresses thinking.

## Per-trial table

Main steps = main calls that returned 200 and were fully received (a call with `client_disconnected = true` is not a step);
compactions = compaction side calls that returned 200; stripped = `stripped_side_thinking_blocks` (row and wire agree on every
trial). Counts come from the row unless marked **wire-derived**, which means the row's `steps` is null and the counts are taken
from that trial's `wire.jsonl` (main calls with status 200; side calls with `side_kind = compaction`). No trial was set aside,
so the wire-derived rule for set-aside trials did not apply; the one wire-derived row is slot 14 (see note).

| Slot | trial_id | Result | Main steps | Compactions | Stripped | Zero-thinking (rate) | Zero-thinking after compaction | Cost | Wall s |
|---|---|---|---|---|---|---|---|---|---|
| 0 | `778e496d6fbd2a17` | pass | 15 | 0 | 0 | 0/15 (0.000) | - | $1.18 | 786 |
| 1 | `2e2b541df9b574ea` | pass | 59 | 1 | 3 | 5/59 (0.085) | 0/3 | $4.55 | 1677 |
| 2 | `f94c7666c1e1067d` | pass | 50 | 0 | 0 | 4/50 (0.080) | - | $3.19 | 1146 |
| 3 | `2a2caef9d1c3ab4c` | pass | 62 | 1 | 3 | 7/62 (0.113) | 0/3 | $4.85 | 1789 |
| 4 | `85a965cdb16836a3` | pass | 31 | 0 | 0 | 2/31 (0.065) | - | $2.21 | 813 |
| 5 | `3ff98b04799c77b6` | pass | 62 | 1 | 2 | 6/62 (0.097) | 0/2 | $4.78 | 1408 |
| 6 | `69d47c6b0e2fb245` | pass | 55 | 0 | 0 | 7/55 (0.127) | - | $3.44 | 1119 |
| 7 | `ad509f145ba5770a` | pass | 71 | 1 | 3 | 12/71 (0.169) | 1/3 | $4.88 | 1560 |
| 8 | `c41b7e4e7963f364` | pass | 42 | 0 | 0 | 7/42 (0.167) | - | $2.46 | 842 |
| 9 | `32035ff99486763a` | pass | 61 | 1 | 3 | 4/61 (0.066) | 0/3 | $4.28 | 1214 |
| 10 | `450c8b260d5d9e5e` | pass | 43 | 0 | 0 | 6/43 (0.140) | - | $3.50 | 1461 |
| 11 | `ad5c434083dbe2ea` | pass | 36 | 0 | 0 | 2/36 (0.056) | - | $2.20 | 891 |
| 12 | `5c9290e53a62da34` | fail (timeout, still working) | 58 | 1 | 6 | 5/58 (0.086) | 0/6 | $4.71 | 1804 |
| 13 | `4e3e585e54cb0520` | pass | 68 | 1 | 2 | 8/68 (0.118) | 1/2 | $4.84 | 1584 |
| 14 | `1b7779f54821930e` | fail (timeout, still working) | 63 wire-derived (client_disconnected_at_cap) | 0 wire-derived (client_disconnected_at_cap) | 0 | 8/63 (0.127) | - | $3.94 | 1806 |
| 15 | `f041efeaf2fadd77` | pass | 63 | 1 | 16 | 7/63 (0.111) | 3/16 | $4.50 | 1254 |
| 16 | `f2a431263181869c` | pass | 63 | 0 | 0 | 7/63 (0.111) | - | $3.89 | 1253 |
| 17 | `274aa6f175fd03b8` | pass | 37 | 0 | 0 | 8/37 (0.216) | - | $2.11 | 1198 |
| 18 | `010ebfac00fb3e0e` | pass | 56 | 0 | 0 | 5/56 (0.089) | - | $4.33 | 1775 |
| 19 | `35207839fa294aa2` | pass | 30 | 0 | 0 | 4/30 (0.133) | - | $1.38 | 600 |
| 20 | `6f76f34989059550` | pass | 48 | 0 | 0 | 6/48 (0.125) | - | $3.16 | 1661 |
| 21 | `c1a8c67e6c4446b9` | pass | 23 | 0 | 0 | 2/23 (0.087) | - | $1.55 | 897 |
| 22 | `c7a3399423e0136b` | pass | 33 | 0 | 0 | 6/33 (0.182) | - | $1.89 | 678 |
| 23 | `f4bd641918d81251` | pass | 23 | 0 | 0 | 4/23 (0.174) | - | $1.04 | 951 |
| 24 | `094021007f08468d` | pass | 19 | 0 | 0 | 1/19 (0.053) | - | $1.24 | 1375 |
| 25 | `be049425439b2b2d` | pass | 61 | 0 | 0 | 4/61 (0.066) | - | $4.07 | 1217 |
| 26 | `560bb650dc690982` | pass | 48 | 1 | 5 | 4/48 (0.083) | 0/5 | $3.75 | 967 |
| 27 | `029292e80a28df08` | pass | 62 | 0 | 0 | 9/62 (0.145) | - | $3.65 | 1047 |
| 28 | `d5dac0115189b70f` | pass | 15 | 0 | 0 | 1/15 (0.067) | - | $0.95 | 904 |
| 29 | `9a32d136c949e6b8` | pass | 46 | 0 | 0 | 5/46 (0.109) | - | $2.23 | 1140 |

**Slot 14 note (`wire-derived (client_disconnected_at_cap)`).** The row has `steps = null` and
`trace_warning = "step_call_mismatch: 64 main OpenCode steps but 63 main wire calls"`. It did not compact. The trial was cut at
the 1800 s cap while its 64th main call (call index 66) was streaming: that wire record has status 200 but
`client_disconnected = true`. A call the client never finished receiving is not a step, so slot 14 counts **63** main steps
(64 main status-200 wire records minus the disconnected one), and its zero-thinking rate is over those 63. This is the existing
step/call pairing check on a timeout, not the compaction path; changing the parser is left to a separate low-priority follow-up. The trial is a task fail
either way. `per-trial.csv` keeps both numbers (`wire_main200` 63, `wire_main200_incl_disconnected` 64, `disconnected_main_calls` [66]).

## Files

| File | What it is |
|---|---|
| `trials.jsonl` | All 30 trial rows as the runner wrote them (not rewritten). |
| `per-trial.csv` | The per-trial table above, with row vs wire counts side by side and a `count_source` column (`row` / `wire-derived` / `wire-derived (client_disconnected_at_cap)`). |
| `cell-report.json` | Summary (pass, n, set-aside, Wilson, zero-thinking splits) and per-trial detail computed from rows + wire. |
| `summary.jsonl`, `verdicts.json`, `set_aside.json`, `provider_blocked.json`, `swaps/`, `plan.json`, `status.json` | Runner outputs. |
| `wire-sha256.txt` | sha256 of every trial's `wire.jsonl` (relative to the run dir), so counts can be traced back. |
| `watch.log`, `run.log` | Watcher log (heartbeat spend, no trigger) and the runner start/exit lines. |

## What is not here

The per-trial dirs (`trials/claude-opus-5-5/winning-avg-corewars/<trial_id>/`: `wire.jsonl`, `opencode-events.jsonl`,
`cell.json`, `checker-output.txt`, `workspace/`, about 857 MB) stay on the VM at `~/corewars-b595f7d7/run/trials/`.
Every `trial_dir` in `trials.jsonl` is relative to `~/corewars-b595f7d7/run/`.

## Scrubbing

Checked with `obench/scrub.py --check` (VM username, home path, full host name) plus extra patterns (emails, AIza, ya29.,
Bearer, sk-, private keys, IPv4, home paths, GCP project id). No emails, keys, tokens, usernames, home paths or project id
were found. Remaining flags are not secrets and were kept: git SHAs and sha256 digests (hex-blob flags), `0.0.0.0` /
`169.254.169.254` (isolation rules in `plan.json`), and the short VM name `thesis-h1-cpu`. The full internal host name
was replaced with `thesis-h1-cpu`, and absolute VM paths were made relative or `~/`.
