# D1: 25226 env-vs-prompt split (2026-10-22)
Two cut-down variants of OpenCode PR 25226 (merge 22839791, base 33f7f593), built from the upstream diff hunks:
- 925226 PERM-only = global.patch + agent.patch -> commit c0a007ba5829b8a4f5af135e31da4b769498680d
- 825226 PROMPT-only = global.patch + prompt.patch -> commit c436fc69eb039523795555f0ec88d32f20ea3292
global.patch only defines/creates <os.tmpdir()>/opencode (needed by both; the runner precreates it anyway).
Commits made on base with author/committer sean-lai-sh, date 2026-10-22T14:30:00-04:00 (reproducible SHAs).
Each row's without side is the base build 33f7f593 (so the base arm runs twice, 30 cells per row).
Run: --task-map task-map.csv --trials 30 --jobs 2 --vertex-model claude-sonnet-5-5 --order interleave-seeded --seed 1016.
