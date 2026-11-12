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
