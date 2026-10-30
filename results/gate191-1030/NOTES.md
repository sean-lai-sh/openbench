# #191 gate, 2026-10-30 (FAIL)

Opus, PR 4204, torch-tensor-parallelism trial 1, both sides. Runner dd0eb6cb (#191 head). Agent image h1-env:1022 (sha256:3ef8e823...).
Researcher-approved run on the ORIGINAL OpenCode binaries in ~/h1/opencode-src/bin/<sha>/ (rebuilds are not byte-reproducible).

Pre-checks (all passed):
- Version stamp 0.0.0--202610170212 in both originals; every 4204 transcript (193 cell dirs across h2-hardsuite-1022, h2-deferred-1023, h2-deferred-opus-attempt1) carries only that stamp.
- mtimes 2026-10-17 02:12 UTC, before first 4204 cell start 2026-10-22T21:23:25Z.
- sha256 recorded post hoc from disk: see gate-row.json.

Result: both cells finished the agent phase (~52 s, $0.37 total) and the checker returned in 87 s / 97 s (limit 600 s), so no checker timeout.
But there was no real verdict: in both cells the checker's test script uv-downloaded torch 2.7.0 + CUDA wheels and died with
`No space left on device (os error 28)` (VM disk 96% full, ~9 GB free). The cells were recorded score 0, failure_class=wrong_answer,
env_failure=false. That classification is wrong: it should be an env failure. The staged checker venvs did not stop the download.

Also: driver spend.log read $0 because its glob missed out/opus/4204/4204/cells; real spend is $0.37.
Older 10-29 attempt moved aside on the VM as ~/gate191.attempt-1029 (not deleted).
