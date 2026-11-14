# Reflection loop: OpenCode pin and per-step traces (SEA-104)

## The OpenCode pin

`opencode_pin.json` is the single record of the pin:

| | |
|---|---|
| Repo | `https://github.com/anomalyco/opencode` (fallback `sst/opencode`) |
| SHA | `ba54cee55e18b47fb70badc84ae2cbac7c83d258` (2026-02-12, "feat(tool): return image attachments from webfetch (#13331)") |
| Package version at the SHA | `1.1.61` (`packages/opencode/package.json`) |
| Install source | Built from source at the SHA by `thesis/ab/build_opencode.py`, not from npm or a release binary |
| Why this SHA | It is the OpenCode build the #196 harness comparison ran, so the reflection loop starts from the same snapshot |
| Run flags | `run --format json --thinking` |

Reproduce:

```bash
python3 -m thesis.ab.build_opencode ba54cee55e18b47fb70badc84ae2cbac7c83d258 --cache "$HOME/h1/opencode-src"
# -> $HOME/h1/opencode-src/bin/ba54cee55e18b47fb70badc84ae2cbac7c83d258/opencode (+ build-stamp.json)
```

`obench.reflection.opencode.verify_binary(path)` checks a binary before a run:
- it must sit in `bin/<sha>/` beside `build-stamp.json`;
- it must run.

It returns the SHA, the package version, the reported `--version` and the
build stamp for the run record. `--version` alone can't identify the pin,
because a source build reports `openbench` or `0.0.0-<channel>-<time>`.

`run_command(binary, instruction, model, variant=...)` builds
`opencode run --format json --thinking --model <model> [--variant <v>] <instruction>`.
At this SHA, `reasoning` events reach the JSON stream only with `--thinking`.

## Per-step traces

See [`TRACE_SCHEMA.md`](TRACE_SCHEMA.md). `trace.py` joins OpenCode's event
stream with one wire record per model call. Each wire record holds the request
body with its explicit thinking setting, the model actually served, and the
provider's response usage. The join produces one schema'd record per step.

Writing wire records for the Vertex routes (Gemini 4 Carbon, Claude Opus,
gpt-oss 120B) is SEA-105. `wire_records_from_proxy_ledger` already reads the
existing Vertex proxy ledger together with its raw request capture.

## Vertex models and the one-cell smoke (SEA-105)

The three models and their exact Vertex IDs, locations, endpoints, thinking
settings, prices and sources are in [`VERTEX_MODELS.md`](VERTEX_MODELS.md):
Gemini 4 Carbon, Claude Opus 5.5 and gpt-oss 120B, all on `global`.
`vertex_models.resolve()` accepts only those three keys. A missing,
misspelled, Sonnet or Qwen name raises, and nothing falls back.

`wire_proxy.py` is the only route. It checks that the client named the
route's model, sets the model's thinking explicitly, forwards to the fixed
Vertex URL with an ADC token, and writes one `wire/v1` record per call with
request, served model, usage and cost.

One-cell smoke per model. This is **paid**: run it on the thesis VM only, one
cell per model.

```bash
export GOOGLE_CLOUD_PROJECT=<project>   # ADC must be available (gcloud auth application-default login, or the VM's service account)
OPENCODE="$HOME/h1/opencode-src/bin/ba54cee55e18b47fb70badc84ae2cbac7c83d258/opencode"
for m in gemini-4-carbon claude-opus-5-5 gpt-oss-120b; do
  python3.11 -m obench.reflection.smoke --model "$m" --opencode "$OPENCODE" --out "$HOME/reflection-smoke/$m"
done
```

Each `--out` directory gets:
- `summary.json` with six checks: `model`, `traced`, `thinking_explicit`, `usage_thinking`, `cost` and `pin`;
- `trace.jsonl`, `wire.jsonl`, `opencode-events.jsonl` and `opencode-stderr.txt`.

**gpt-oss thinking counts aren't comparable with Carbon's and Opus's.**
Vertex reports 0 gpt-oss thinking tokens even when reasoning text comes back.
The trace keeps the usage value (0), flags it `reported_zero_text_present`,
and records the text, its length in characters and, if tiktoken is installed,
our own `o200k_harmony` count (`thinking.tokens_counted`, labelled computed,
never pooled with usage). Say so in any writeup that reports thinking tokens.

The default task is `tasks/fix-failing-test`, a small multi-step task run in a
copy of its workspace. `--out` must be outside `results/` and `data/`. Scrub
the files before they go into the separate smoke-data PR.
