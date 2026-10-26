# QUARANTINED: step-8 VM F03-1 (thesis-h1-cpu, n2-standard-16)

Status: quarantined. Do not pool these cells into step-8 analysis.

- Runner: 980e71b618 (from driver.log; per-cell `runner_commit` is None because the ~/ob-s8 worktree gitdir is not visible inside the container).
- Machine: thesis-h1-cpu, n2-standard-16, us-central1-a.
- Config: run_ab --trials 30 --jobs 4 --vertex-model claude-sonnet-5-5 --cell-meta --order interleave-seeded --seed 1016, PRs 3185,3192,3210,3225. Window 2026-10-25 23:41 to 2026-10-26 00:04 EDT. VM spend $12.84 (spend.log).
- Reason: VM-only infra failure `Error: Unhandled chunk type: custom` (early death under 10s). This error appears in 0 box step-8 cells. 3185 "with" and both sides of 3192 early-stopped as infra (see *.infra.json).
- Suspected cause (unconfirmed): provider and package versions resolved at runtime on the VM (`installed @ai-sdk/anthropic@2.0.0`, fresh bun install) differ from the box's.
- Environment deviations: container PATH uses go 1.24.6 from the cache (the box used 1.24.4) and node v20.19.2 at ~/h1/toolchain; 28 broken cache worktrees were removed before this run.
- setaside/F03-1-attempt3-broken-worktree: an earlier attempt that died on a broken worktree (git exit 128 on 3185 "without"), about $3.6 spent, not counted in the $12.84. Its 3185 "with" (30 solved) and 3192 cells show no chunk error.

| PR | with | without |
|---|---|---|
| 3185 | 3 infra (early-stopped) | 29 solved, 1 hang |
| 3192 | 2 infra, 1 wrong_answer (early-stopped) | 2 infra, 1 wrong_answer (early-stopped) |
| 3210 | 30 solved | 30 solved |
| 3225 | 29 solved, 1 hang | 30 solved |
