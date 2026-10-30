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

## off_protocol (added 2026-10-30)
Both gate rows (without/0d3d48bb, with/963a926d) are marked `off_protocol: true` in gate-row.json and kept as evidence only.
- Gate-fail reason: no real verdict. The checker died with `No space left on device (os error 28)` while uv-downloading torch.
- Root cause: the checker venv was effectively missing. Venv bin/python is an absolute symlink to /root/.local/share/uv/python/cpython-3.13.9-linux-x86_64-gnu/..., which the h2-checker-venvs artifact does not ship, so test.sh took its install fallback.
- Binary sha256: 0d3d48bb = 12d778e4a19fcd1b73d8053ddcc475bfda8028d075ff83fce31d73862eee31a1; 963a926d = b44f4f2360d664bc9785cf973325b55ada3a521d44b987517438e26b09506f61.
- Checker times: 86.5 s (without), 96.6 s (with); limit 600 s.
- Scoring: env_failure=true (env_cause checker_enospc, root cause checker_venv_missing), unscored, rerun required. Never wrong_answer or agent failure.
The raw cell files under h2/ are left byte-identical; the correction is only in gate-row.json and here.
