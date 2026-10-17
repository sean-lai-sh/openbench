# Smoke #4838 (compaction prompt) @ 019ad6e / PR #8 packaging

**PASS** #4838 8-task A/B on tip `019ad6e` (host-runnable mid-era binary packaging).

- Worktree: `/workspace/openbench-ab` detached @ `019ad6e` (`fix(opencode): publish a host-runnable mid-era binary (#8)`)
- Parent SHA `ff609a52…` / Merge SHA `aaa31f02…` rebuilt after wiping musl-ENOENT bins; both `can_exec=True`, interp `/lib64/ld-linux-x86-64.so.2`, `--version` OK
- Command: `python3 -m thesis.ab.run_ab thesis/ab/fixtures/opencode-harness-prs.csv --pr 4838 --trials 3 --jobs 8 --out results/ab --cache …/opencode-src`
- Wall: 17:04:50–17:12:41 ET (~8m); exit 0; **launched 48**
- Cells: without n=24 pass=1.000 wall=51.4s tok/cell=181344 cost/cell=$0.258
- Cells: with    n=24 pass=1.000 wall=53.7s tok/cell=220593 cost/cell=$0.253
- Aggregate (setaside_stats line): pass 1.000→1.000; wall 51.4→53.7s; tok 181k→221k; cost $0.258→$0.253
- Primary (Researcher lock): out_tok 4696→4943; non-cache input (vendor) 15→16; proxy non-cache in 1270→1326; proxy out 4713→4960
- token_basis={'estimated': 48}; token_basis_proxy={'proxy_measured': 48}; failure_class={'solved': 48}; unmetered without=0 with=0
- ConnectionResetError_count=0
- No ENOENT / no infra sidecars; binaries host-runnable after PR #8 rebuild
- Toolchain without: {"ai": "5.0.97", "anthropic": "2.0.0", "bun": "1.3.3"}
- Toolchain with: {"ai": "5.0.97", "anthropic": "2.0.0", "bun": "1.3.3"}
- Spend: $464.36 → $476.62 (est. cell sum via setaside_stats); soft pause target $700
- Quarantine: old ENOENT infra → `results/ab-quarantine/pre-enont-4838/`; musl bins → `results/ab-quarantine/pre-enont-musl-bins/`

Smoke success criteria: binaries launch ✓, CR=0 ✓, metered (proxy_measured) ✓, not ENOENT/infra ✓.
