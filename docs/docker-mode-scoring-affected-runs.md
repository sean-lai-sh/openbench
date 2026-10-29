# Docker-mode cells affected by the /app mount and host checker

Harbor tasks tell the agent to write under `/app`. Docker cells mounted the
graded workspace at `/work`, and `run.py` rewrote `/app` only for local cells
(`OBENCH_HARBOR_APP_REWRITE=1`). The file the agent wrote inside the container
was discarded. `run_checker` then ran `checker.sh` on the host, which has no
`rustc`, so a correct `polyglot-rust-c` answer still failed.

This list is every stored result under `results/` whose row has
`exec_mode` `docker`. The scan walked JSON and JSONL under `results/`,
including objects nested under a `row` key, and skipped `transcripts/` and
`proxy-ledger/`. Flat cell files under `results/**/cells/` (15,762 files)
are all `exec_mode` `local` and are omitted here.

Workspace output was kept when `checker_workspace_files` contained anything
besides the untouched `.gitkeep`. Every docker-mode cell below has
`workspace_changed` false and a workspace of only `.gitkeep`.

| PR | Data path | Workspace output kept |
| --- | --- | --- |
| none (harness smoke; no OpenCode PR) | `results/pi-harness-bridge-smoke-1028c/attempt1-file-adc/opencode-harness-smoke-bridge3/claude-sonnet-5-5.json` | no |
| none (harness smoke; no OpenCode PR) | `results/pi-harness-bridge-smoke-1028c/attempt1-file-adc/pi-harness-smoke-bridge3/claude-sonnet-5-5.json` | no |
| none (harness smoke; no OpenCode PR) | `results/pi-harness-bridge-smoke-1028c/attempt2-metadata-adc/opencode-harness-smoke-bridge4/claude-sonnet-5-5.json` | no |
| none (harness smoke; no OpenCode PR) | `results/pi-harness-bridge-smoke-1028c/attempt2-metadata-adc/pi-harness-smoke-bridge4/claude-sonnet-5-5.json` | no |
| none (copy of attempt2 cell `362e87ae1e9a8384`) | `results/polyglot-rust-c-checker-1028/cell_opencode/claude-sonnet-5-5.json` | no |
| none (copy of attempt2 cell `f13363d84726bdb8`) | `results/polyglot-rust-c-checker-1028/cell_pi/claude-sonnet-5-5.json` | no |

All six rows are `polyglot-rust-c`, trial 1, `success` false, score 0. The
two `polyglot-rust-c-checker-1028` files repeat the attempt2 cell ids; the
distinct docker runs are the four bridge-smoke cells.

F03-2 PR 3424 is absent from this list. Its 62 cell files live under
`results/step8-f032-1027/scored/3424` and `results/step8-f032-1027/gate/3424`.
Each has `exec_mode` `local`, task `trig-plan-subagent`, and a non-empty
`checker_workspace_files` map, so the workspace output was kept. Nothing in
`results/` was rewritten for this note.
