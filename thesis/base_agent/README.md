# Stage 4 base agent

One run loop with 13 interchangeable module slots. Each open-source harness is
expressed as a config, which picks an implementation for each slot, and is
checked against its real harness before any swap result counts. Spec:
[`briefs/stage4-prereg-base-agent.md`](../../briefs/stage4-prereg-base-agent.md).

Python standard library only, like the rest of the repo. Requires Python 3.11+
(`tomllib`).

## Layout

| File | What it holds |
|---|---|
| `slots.py` | M1-M13 and the 34 sheet rows mapped to them, with each row's status (swappable, fixed, infra) from section 2 of the brief. A test checks the rows against `prereg/harness-components-2026-10-24.csv`. |
| `interfaces.py` | One abstract class per slot, plus `Tool`, `RunContext`, `ModelClient`. |
| `modules.py` | Implementations, registered by `(slot, name)`, and the M2 tool catalog, keyed by `(family, name)`. |
| `tools.py` | File and shell primitives shared by every tool schema. |
| `agent.py` | The loop and an HTTP client for the counting proxy (`POST /v1/messages`, `X-OB-Call-Role` header). |
| `config.py` | Config loading, arm resolution, validation, version hashing. |
| `configs/fixed.toml` | Every fixed and infra row, pinned once. Fully fixed slots (M4, M12, M13) are defined only here. |
| `configs/base.toml` | The neutral base-agent defaults. This is the named swap baseline, not a real harness. |
| `configs/pi.toml`, `configs/opencode.toml` | Harness configs. Each one cites the sheet cell and source column for every swappable row. |
| `harness_pi.py`, `harness_opencode.py` | Harness-specific modules: prompt assemblers, tool schemas, editor, todo, subagent, title call. |
| `assets/` | Vendored MIT prompt and tool text with its upstream licences. `assets/SOURCE.md` gives the pins and upstream paths. |
| `build_check.py` | AC3 build check: captures the first request at a loopback stub and compares system and tool bytes against a real-harness capture. |
| `run.py` | Headless entry point: `python -m thesis.base_agent.run`. |

## Slots

| Slot | Interface | Sheet rows |
|---|---|---|
| M1 | PromptAssembler | 1, 2, 14 (fixed: memory off) |
| M2 | ToolRegistry | 3, 4, 5, 11, 12, 19 (fixed: web off), 20 (fixed: MCP off) |
| M3 | CachePolicy | 8 |
| M4 | SamplingPolicy | 9 (fixed) |
| M5 | SideCalls | 10 |
| M6 | ContextManager | 13 |
| M7 | Editor | 15 |
| M8 | Executor | 16, 17 |
| M9 | Planner | 21 |
| M10 | Delegation | 22 |
| M11 | LoopController | 23 (fixed: global cap), 25 |
| M12 | RetryPolicy | 24 (fixed) |
| M13 | Permissions | 26-29 (fixed) |

Infra rows 6, 7, 18 and 30-34 have no knob in the agent. Their pinned values
are recorded in `fixed.toml`.

M7, M9 and M10 contribute tools. M2 decides the order in which every tool
appears in the request, so a config can reproduce a harness's exact tool
order.

## Arms

`resolve(config, fixed, arm)`:

- **swap**: every fixed row in `fixed.toml` applies.
- **parity**: rows marked `parity = "harness"` keep the harness's own value,
  so the config reproduces the real harness for the parity gate. These are
  row 9 (sampling, through `[parity.M4]` in the harness config) and row 19
  (web tool schemas). Rows marked `enforce` apply in both arms: memory off,
  MCP off, the global step cap, retries, and permissions.

## Version record

`config.version_record()` returns the following. `Agent.run()` puts it in
every result as `version`.

- `base_agent_version`: 16 hex characters from a hash of the framework and
  the resolved config.
- `framework_hash`: sha256 over every code and prompt-asset file in this
  directory except `configs/` and this README.
- `config_hash`, `fixed_hash`, `resolved_hash`: canonical JSON with sorted
  keys and no whitespace.
- `arm`, `harness`, `harness_pin`, `harness_values_kept`.
- `provisional_fixed_rows`: fixed values the Researcher has not ruled on
  yet: row 9 (sampling), row 23 (step cap) and row 24 (retries). These must
  be pinned before any scored cell.

Any change to code, a prompt asset, a fixed row, a config or the arm changes
`base_agent_version`.

## Harness configs (AC2)

| Config | Pin | First request (system / tools bytes, stub run) |
|---|---|---|
| `pi` | badlogic/pi-mono `d0aa218` (the sheet's pin and the #196 Pi pin) | ~2.7 KB / ~2.8 KB, 4 tools |
| `opencode` | sst/opencode build `ba54cee5`, the #196 build (Researcher ruling 2026-10-30) | ~8.6 KB / ~36.1 KB, 11 tools |

Each `[rows.N]` entry holds three fields. `value` is what the module
reproduces. `sheet` is the sheet's cell, copied exactly. `source` is the
sheet's `*_src` cell, or the SC-1 addendum where SC-1 resolved a "not found"
cell. A test checks every swappable row against
`prereg/harness-components-2026-10-24.csv`.

Each file's module docstring lists what the config does not reproduce yet
(for example Pi's `keepRecentTokens`, OpenCode's LSP diagnostics and
full-output files). The AC3 build check measures the request-side gaps
against a real-harness capture.

## Build check (AC3)

Brief section 1.6: the system-prompt and tool-schema bytes at the proxy must
be within 5% of the real harness's captured request. This is posted before any
scored cell.

Both sides are captured at a loopback stub that stands in for the counting
proxy and answers every request with end_turn "ok". No model is called and
nothing is billed. The capture format is the existing `*.requests.jsonl`
(`{method, path, headers, body}` per line).

```bash
# 1. Real OpenCode: the existing stub-readiness tool runs the real binary
#    through the cell adapter (prompt "Reply with ok.", model claude-opus-5-5).
python -m thesis.ab.step8_stub_ready --bin-root BIN_ROOT --cache CACHE \
    --binary oc-real=BIN_ROOT/<sha>/opencode=<sha> \
    --capture results/ac3/real --out results/ac3/real

# 2. Base config: same prompt and model.
python -m thesis.base_agent.build_check capture --config opencode --arm parity \
    --model claude-opus-5-5 --out results/ac3/base/opencode.requests.jsonl

# 3. Compare. Exits 0 on PASS, 1 on FAIL.
python -m thesis.base_agent.build_check compare --config opencode --arm parity \
    --base results/ac3/base/opencode.requests.jsonl \
    --real results/ac3/real/oc-real.requests.jsonl --out results/ac3/opencode-report.json
```

Each side's first main-loop request is used: the first `/messages` request
that carries tools and is not tagged as a side call. The check measures:

- **system**: UTF-8 bytes of all system text.
- **tools**: bytes of the tools array as canonical JSON, with sorted keys,
  no whitespace and `cache_control` removed.

A config passes when **system and tools are each** within 5% of the real
harness. The combined figure is reported but does not decide the result. The
report also shows:

- tool-name differences and whether the tool order matches;
- the sampling fields (`max_tokens`, temperature, thinking). Copy the real
  values into the config's `[parity.M4]`;
- the sha256 of both captures;
- the config's version record, so a posted report is tied to one
  `base_agent_version`.

Pi has no stub-capture runner yet. `step8_stub_ready` drives only the
OpenCode adapter. A Pi capture needs the same thing for `obench.adapters.pi`:
point Pi's provider base URL at `build_check.CaptureStub` and save
`stub.requests`.

## Implementation basis

Written from scratch. mini-swe-agent (github.com/SWE-agent/mini-swe-agent) is
MIT-licensed; we checked the licence through the GitHub API on 2026-10-30.
We kept its ideas: a small linear loop, and model and environment settings
kept out of the agent config. No mini-swe-agent code is copied. No Claude
Code code or prompt text is used.

## Tests

```bash
python3 -m unittest obench.tests.test_stage4_base_agent obench.tests.test_stage4_harness_configs \
    obench.tests.test_stage4_build_check -v
```

The tests use a scripted model. They make no paid or live model calls.
