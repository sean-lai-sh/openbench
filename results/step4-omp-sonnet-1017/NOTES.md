# Step 4: Oh My Pi on Sonnet 5.5 (notes, 2026-10-17, times ET)

Rows: the 15 OMP rows that have a screen on the scoreboard (15, 16, 19, 21, 28, 30, 31, 32, 33, 35, 36, 38, 39, 43, 44). The 14 AWAITING-SCREEN rows are step 7; 20/22/45 are not exercisable. Thinking pin mirrors the Opus screen: off for 19, 30, 31, 32; default for the rest. Task per row in omp-task-map.csv. Runner worktree /tmp/ob-step4 = origin/main d7462cd (runner code = #69). OMP A/A band (step 2, omp36-aa): +4.1% [-3.4%, +14.0%].

## Smoke 16:10-16:18 ET, 1 cell/side (INVALID as a screen; kept as-is)
- smoke-default (11 rows) $5.24, smoke-off (19, 30, 31 reached; 32 never started) $1.14. upstream_model = claude-sonnet-5-5 on every cell; strip status none (no sampling params sent, params_stripped_requests 0).
- **Environment defect:** run.sh did not put /workspace/openbench-ab/.venv/bin on PATH (step 2 ran under `uv run`, which does). System python3 has no pytest, so every pytest-checked cell failed as wrong_answer ("No module named pytest") and the agent itself saw no pytest. Only the trig-omp-image cells (39, 43) are valid: 1/1 solved both sides. run.sh fixed (PATH) for later runs. These cells must not be scored.
- omp-44: both builds failed (`incompatible`): pi-natives .node lacks the 18.3.0 version sentinel (`__piNativesV18_3_0`) at embed time. Needs a runner fix before omp-44 can run on Sonnet (the Opus run on 18.3.0 built earlier from a different natives fetch).
- smoke-off was stopped by hand at 16:18 ET (rc 143): free disk fell 33 GB -> 9.9 GB, about 1 GB per new OMP build (bun cache 17 -> 21 GB plus worktrees). Nothing deleted.
- Step 4 paused after this smoke on the PM's priority change (Opus reruns of six OpenCode PRs first).
