# sdk-pin gate cells, 2026-10-31 (quarantine=sdkpin_gate_1031, gate_cell=true)

Runner: main 94534ef9 (fresh worktree ~/wt-g1031 on thesis-h1-cpu). Image h2-env:1022 (sha256:72c59033...69ff). Task model-extraction-relu-logits, t1. OBENCH_GATE_CELL=1, explicit OBENCH_ANTHROPIC_PIN. Caps: $1.00 per pair, $8 total. Not scored data.

Pass rule: loaded_anthropic (from the request User-Agent, #218) == pin on both arms. A cell without it fails as unproven.

**Total spend: $1.7606** (proxy-ledger list price). 3.0.71/26821 ($0.6125) also counts toward the 26821 rerun $250 budget.

| pin | PR | model | installed (w / wo) | loaded_anthropic (w / wo) | functional (w / wo) | stop reasons end | $ pair | gate |
|---|---|---|---|---|---|---|---|---|
| 2.0.0-beta.5 | 913 | opus | beta.5 / beta.5 | none / none | pass / pass | end_turn / end_turn | 0.5954 | FAIL (unproven) |
| 2.0.0-beta.11 | 1109 | sonnet | beta.11 / beta.11 | none / none | pass / pass | end_turn / end_turn | 0.2830 | FAIL (unproven) |
| 3.0.71 | 26821 | opus | 3.0.71 / 3.0.71 | none / none | pass / pass | end_turn / end_turn | 0.6125 | FAIL (unproven) |
| 2.0.0-beta.4 | 795 | sonnet | beta.4 / - | none / - | with only | end_turn / - | 0.2696 | INCOMPLETE (stopped by hand) |
| 2.0.0 | 4204 | opus | - | - | - | - | 0 | NOT RUN |
| 2.0.25 | 3052 | opus | - | - | - | - | 0 | NOT RUN |
| 2.0.50 | 5140 | opus | - | - | - | - | 0 | NOT RUN |
| 2.0.58 | 13331 | opus | - | - | - | - | 0 | NOT RUN |
| 2.0.58 | 13090 | opus | - | - | - | - | 0 | NOT RUN (in pin-table-1030 plan) |

Why everything is unproven: these cells use `--vertex-model`, so requests go through `thesis/ab/vertex_anthropic_proxy.py`. #218 added User-Agent capture only to `obench/proxy.py`. The vertex proxy reads the UA (only to strip `claude-cli/`) and forwards `User-Agent: openbench`, but never writes `loaded_anthropic` to its ledger. So `loaded_anthropic` is null on every row, and run_ab warns "cell missing required fields ['loaded_anthropic', 'cell_image', 'runner_commit']" (the driver also did not set OBENCH_CELL_IMAGE / OBENCH_RUNNER_COMMIT; runner_commit.txt is empty because git rev-parse failed inside the container; driver.log records code=94534ef9 for every pair).

I stopped the driver at 09:39 EDT during 2.0.0-beta.4 (STOPPED) so the remaining pairs would not spend on cells that cannot pass. Rerun after the vertex proxy records `loaded_anthropic`.

Files: drive.sh / gate1.sh / gatewatch.py / pairs.txt (driver), driver.log, spend.log, quarantine.txt, per-pair cells, proxy-ledger, run.log, container.log.
