# Vendored harness text and captured tool specs

Pi and OpenCode are MIT-licensed. Each directory keeps its upstream
`LICENSE`. No Claude Code text is used anywhere. OpenCode's own Claude Code
identity header is deliberately left out (see `harness_opencode.py`).

## opencode/ (sst/opencode build ba54cee55e18b47fb70badc84ae2cbac7c83d258)

This is the build the #196 OpenCode cells ran (Researcher ruling, 2026-10-30).

| File here | Source |
|---|---|
| `anthropic.txt` | `packages/opencode/src/session/prompt/anthropic.txt`. Byte-identical at ba54cee5 and at the sheet's c10134729d. |
| `title.txt` | `packages/opencode/src/agent/prompt/title.txt`. Byte-identical at both pins. |
| `tools.json` | The `tools` array of the main request that the real ba54cee5 Linux binary (the one #196 ran, on thesis-h1-cpu) sent to a loopback stub (`thesis.ab.step8_stub_ready --capture`; no model was called). `cache_control` is removed, and the capture's working directory is replaced by `{{workdir}}`: the bash tool names its default directory, and `Agent.tools()` fills in the run's. The capture itself (`captures/opencode/real.requests.jsonl`, sha256 `e40ab22d…`) is committed in `captures/opencode/`. A test checks this file against it. |

## pi/ (badlogic/pi-mono @ d0aa218cb16c333c008f6aa3dcd670ac8b68383c)

| File here | Source |
|---|---|
| `tools.json` | The `tools` array of the request in `captures/pi/real.requests.jsonl`, with `cache_control` removed. The real Pi binary produced it at a stub, through `obench.adapters.pi_harness`. No model was called. |
| `LICENSE` | Pi's licence. |

The Pi prompt strings live in `harness_pi.py`. They are copied from
`packages/coding-agent/src/core/system-prompt.ts` and `core/tools/*.ts`.

A test (`test_stage4_build_check`) checks that each `tools.json` equals the
tools in its committed capture (with `{{workdir}}` filled in), so the asset
cannot drift from the evidence.
