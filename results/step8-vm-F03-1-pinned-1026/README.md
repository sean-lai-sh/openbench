# Step-8 VM F03-1 rerun with provider pins (2026-10-26)

VM thesis-h1-cpu (n2-standard-16), image h1-env:1022, runner c25856a78b626646882b553699939780d69c4728 (PR #143 merged).
PRs 3185, 3192, 3210, 3225; 30 trials/side, --jobs 4, interleave-seeded seed 1016, Vertex claude-sonnet-5-5, --max-cost-usd 25.
Spend: $21.60 (240 cells). Supersedes the quarantined run in results/step8-vm-F03-1-1025-QUARANTINED (PR #142).

## Gate
- `Unhandled chunk type`: 0 hits in all outputs.
- provider_pin_mismatch aborts: 0. Early stops: 0. Infra: 0/240.
- provider_versions: @ai-sdk/anthropic 2.0.0 on 240/240. upstream_model claude-sonnet-5-5 on 240/240.
- provider_pin_sha256, provider_versions, pin_source, machine, runner_commit: present on 240/240.
- pin_source: 3185/with = box_cache; other 7 sides = vm_quarantine_log.

See prep/gate.json and STATS.txt (scored with results/step8-full413-1020/stats.py).

## Notes
- runner_commit: the container's OBENCH_RUNNER_COMMIT was empty due to a launch-script error on my side, so cells were
  written with runner_commit null and then backfilled with thesis.ab.backfill_runner_commit from prep/driver-F03-1-pinned.log
  (the ~/ob-s8 worktree was verified at c25856a7 before launch). The per-PR with/without.jsonl files may still show null.
- setaside/F03-1-pinned-attempt0-emptycache: first attempt, 25 cells, $0, all `provider_pin_mismatch: empty cache`.
  The OpenCode worktrees had been removed by the queue cleanup, so no bun could be resolved to seed the pin. Fail-closed
  worked as designed. Worktrees for the 8 SHAs were re-added from the mirror (git worktree add) and the run relaunched.
- prep/provider_versions_vm*.txt: print_provider_versions output before (no worktrees) and after re-adding worktrees;
  manifest = locked = 2.0.0 for every side, matching thesis/ab/provider_pins.json.
- Box comparison: main only has one box F03-1 cell for these PRs (3185/with, partial, unscored, solved). No box data for
  the other sides, so the match-the-box check only applies to 3185/with.
