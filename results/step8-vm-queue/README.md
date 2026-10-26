# Step-8 VM queue (thesis-h1-cpu, ~/s8) — 1026 worktree preflight

Copies of the live VM files. `queue.sh.bak-1026` is the queue as it was before this change.

Changes in `queue.sh`:
- Runner check is the full sha c25856a78b626646882b553699939780d69c4728 (#143 provider pins), was 980e71b6.
- `OBENCH_RUNNER_COMMIT` is passed into the container, so with/without.jsonl rows carry runner_commit (the F03-1-pinned rows had null; backfilled in #145).
- Before each batch, `preflight.py check LABEL PRS` checks every side's worktree (`~/h1/opencode-src/worktrees/<sha>`; with = merge sha, without = parent sha): dir, package.json, packages/opencode/src/provider/provider.ts, the bun version it asks for at `~/h1/opencode-src/bun/<ver>/bun`, and a provider_pins.json entry for sha+side. Any miss writes HOLD, logs each missing path to driver.log and exits without launching.
- Post-run cleanup no longer removes new worktrees that any batch without DONE-<label> still needs (`preflight.py needed`); if that list can't be built, cleanup is skipped.
- `DRYRUN=1 [ONLY=<label>] bash queue.sh` runs the preflight only (no docker, no model calls).

node_modules is not required: the F03-1-pinned worktrees had none and ran 240/240 clean; the pin install uses the cached bun.

Dry runs on 2026-10-26: F03-1 8/8 sides ready; F03-2 0/22 ready (no worktrees built yet), see preflight-*.txt.
