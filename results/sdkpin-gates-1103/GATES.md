# SDK-pin gates 11-03 (the 6 unproven gates from D-5)

- **Code:** main b4abce28 (worktree ~/ob-gate1103 on thesis-h1-cpu). Image h2-env:1022@sha256:72c59033….
- **Task:** model-extraction-relu-logits, 1 trial per arm, `OBENCH_GATE_CELL=1`. Driver `thesis/ab/h2env/sdkpin_gate_drive.sh`.
- **Caps:** PAIR_CAP raised $1.00 → $3.00 (5140 was cap-stopped at $1.01 in 1031-rerun), TOTAL_CAP $20 (step hard stop). Quarantine: gate rows, not scored.
- **Pins:** the same pins as #222 / D-5 (installed version of clean scored rows; build-date/lockfile fallback per #214).
- **Times:** EST, 2026-11-03.

| Pin | PR | Model | installed (w/wo) | load proof (w/wo) | Basis | Result | Pair $ |
|---|---|---|---|---|---|---|---|
| 2.0.0-beta.4 | 795 | sonnet | beta.4 / beta.4 | unproven / unproven ("module hook log missing") | module_hook | **unproven** | 0.2664 |
| 2.0.0-beta.5 | 913 | opus | beta.5 / beta.5 | unproven / unproven (hook log missing) | module_hook | **unproven** | 0.4058 |
| 2.0.0-beta.11 | 1109 | sonnet | beta.11 / beta.11 | unproven / unproven (hook log missing) | module_hook | **unproven** | 0.2795 |
| 2.0.0 | 4204 | opus | 2.0.0 / 2.0.0 | unproven / unproven (hook log missing) | module_hook | **unproven** | 0.5629 |
| 3.0.71 | 26821 | opus | 3.0.71 / 3.0.71 (embedded_version 3.0.71) | unproven / unproven (hook log missing) | module_hook | **unproven** | 0.8491 |
| 2.0.50 | 5140 | opus | 2.0.50 / 2.0.50 | pass / pass (ledgers 20× + 8× 2.0.50) | user_agent | **PASS** | 1.2337 |

**Total:** $3.5975 (gatewatch).

**4204 raw SSE:** every request (11) has one `message_stop`, last stop_reason tool_use/end_turn, 0 `event: error`. Stop reason is known, so the raw_sse fallback does not apply; the gate is unproven on load proof alone.

**Finding:** the `module_hook` plugin (#223) never wrote its log on any live opencode cell (old opencode configs glob `plugin/*.{ts,js}` under the config dir, so the location matches; cause not yet traced). Needs a runner fix + one-cell smoke before 795/913/1109/4204/26821 can pass.
