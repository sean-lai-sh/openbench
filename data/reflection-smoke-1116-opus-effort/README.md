# Opus 5.5 re-smoke with explicit `effort: high` (2026-11-16)

The single-cell Opus re-smoke the Researcher required before the reflection pilot,
after #265 started sending Opus thinking effort explicitly.

| Field | Value |
|---|---|
| Code commit | `954286aa57955122c93a6ac184ac8654a460de71` (#265, branch `sea-111/cell-executor`; detached clean worktree) |
| Harness | `python3 -m obench.reflection.smoke --model claude-opus-5-5` (same entry point as the 1116 morning smokes at `caf7162d`; only the commit changed) |
| Agent | OpenCode pinned build `ba54cee5…` (package 1.1.61), `opencode run --format json --thinking` |
| Model / route | `vertex-claude-opus-5-5/claude-opus-5-5`, Vertex `global`, served `claude-opus-5-5` on every call |
| Task | `fix-failing-test` (calculator) |
| Run time | 2026-11-16 21:37:38–21:37:55 UTC (4:37 PM ET) on thesis-h1-cpu |
| Cost | $0.269095 (Vertex list prices, 6 calls) |
| Result | **pass** (`OBENCH_VERDICT: pass`, checker exit 0) |

## Thinking setting sent (every request, 6/6)

```json
{"thinking": {"type": "adaptive", "display": "summarized"}, "output_config": {"effort": "high"}}
```

Visible in each `wire.jsonl` row under `request.thinking` / `request.output_config` and
`thinking_enforced.effort = "high"`. The morning smoke at `caf7162d` sent only
`{"type": "adaptive"}` with no effort.

## Checks

| Check | Result |
|---|---|
| No 4xx | pass: 6/6 upstream calls HTTP 200 |
| Effort high in saved request body | pass: 6/6 |
| task_solved | pass (checker exit 0, 4/4 tests) |
| not_route_truncated | pass (no repairs) |
| model / pin / traced / cost / usage_thinking | pass |

## Per-step (main calls)

| Step | Finish | Output tokens | Thinking tokens | Cost USD |
|---|---|---|---|---|
| 1 | tool_use | 95 | 0 | 0.080216 |
| 2 | tool_use | 213 | 0 | 0.085223 |
| 3 | tool_use | 90 | 0 | 0.084948 |
| 4 | end_turn | 114 | 0 | 0.0083762 |

Plus 2 side calls (title generation, 17 output tokens each, 0 thinking, $0.005136 + $0.005196).
Thinking tokens are the reported `usage.output_tokens_details.thinking_tokens`. With effort high,
adaptive thinking still chose not to think on this easy task. Per the Researcher's rule that is
a covariate, not a fail.

## Retries

0. There are 6 wire rows, all status 200, so OpenCode did no 429 or other retries. Commit
`954286aa` has no explicit per-cell `retries` field yet. This number comes from the wire log.
A retry-count field still needs adding to the cell executor before the pilot, per the
Researcher's 4:4x PM ET call.

## Files

Scrubbed with `obench/scrub.py` (VM user/home/hostname overrides), and `--check` is CLEAN.
The hex rule redacts 40-char SHAs inside the files, including the `head=` line in `run.log`.
The commit above is the real one.

- `summary.json`: smoke checks
- `trace.jsonl`: per-step trace
- `wire.jsonl`: full request bodies and usage
- `checker-output.txt`
- `opencode-events.jsonl`, `opencode-stderr.txt`, `run.log`
- `work/`: the final task workspace
