# OpenCode gate cell, Sonnet id + --require-model-match (PR #189 head d8818021, 2026-10-29, VM thesis-h1-cpu)

Same procedure as results/pi-oc-gate-1029 (gate189.sh): image h1-env:1027-strace, OBENCH_ADC_METADATA=1, OpenCode sha ba54cee5, Node 20.19.2, bridge network, api.anthropic.com sinkholed. Launched with `-m anthropic/claude-sonnet-5-5`, `--vertex-model claude-sonnet-5-5 --require-model-match`.

**Result: GATE FAILED (off_protocol halt, exit 1).** Cell 47b2df8345ddb799.

| field | value |
|---|---|
| completed | true (wrong_answer, checker_exit 1) |
| requested_model | claude-haiku-4-5-20251001+claude-sonnet-5-5 (mixed) |
| upstream_model | claude-sonnet-5-5 (not mixed) |
| endpoint_location | global |
| off_protocol | **true** |
| proxy/trace/untraced | 4 / 3 / 1 |
| ledger in/out/cw/cr | 12 / 3623 / 50076 / 0 |
| proxy_cost_usd | 0.161444 |

Cause: the 1 untraced request (OpenCode's title-style side call) asks for `claude-haiku-4-5-20251001` (OpenCode's small_model default for the anthropic provider); the proxy serves it as Sonnet. The 3 main-loop requests all ask for claude-sonnet-5-5. Fix candidate: pin OpenCode `small_model` to anthropic/claude-sonnet-5-5 in the cell config (or disable the title call), then re-gate.
