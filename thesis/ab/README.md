# Harness A/B

This directory builds OpenCode at the parent SHA and the merge SHA of each pull request, runs the same OpenBench tasks on both binaries, and writes a per-PR comparison. The checker is the judge. Harness self-reports are not scores.

## Pilot

From the repository root, with `GOOGLE_CLOUD_PROJECT` and `GOOGLE_APPLICATION_CREDENTIALS` set:

```bash
python -m thesis.ab.run_ab thesis/ab/fixtures/opencode-harness-prs.csv \
  --pr 22390,24974,23771,4838,12214,18140 \
  --trials 3 \
  --jobs 8 \
  --out results/ab
```

The model is `claude-opus-5-5`. The default route is one local proxy that speaks Anthropic `POST /v1/messages` and forwards it to Vertex on the global endpoint. OpenCode, Pi, and Oh My Pi share that proxy. `--model-route vertex` keeps OpenCode on the native `google-vertex-anthropic` provider. Set `GOOGLE_CLOUD_PROJECT` and application-default credentials before a real run.

PR 23771 in the fixture is a commit on the development branch, not GitHub's merge commit. The runner uses the SHAs in the CSV.

## Tasks

The default task set is every core task under `tasks/` that contains `checker.sh`, except `trig-*` copies. Imported Terminal-Bench tasks need Docker and stay out of the default set.

List the core tasks with either command.

```bash
obench validate --no-imported
```

```bash
python -c "from obench.validate_tasks import discover_tasks, build_task_roots; print('\n'.join(name for _, name, _ in discover_tasks(build_task_roots(include_imported=False))))"
```

Pass a subset with `--tasks make-it-run,fix-failing-test`. Repeat the flag or separate names with commas.

`trig-*` tasks are copies of those core tasks with one sentence prefixed to `instruction.md`. They stay out of the default set. `--tasks` can name them. `--task-map thesis/ab/fixtures/trigger-tasks.csv` runs each triggerable PR on the task named for that PR. Rows that still need a fixture are skipped unless `--pr` names one, which is an error.

The map's optional `options` column is a semicolon-separated `key=value` list applied to every cell of that PR. There is no separate CLI flag. Empty options are allowed. A typo is an error.

| Key | Effect |
|-----|--------|
| `context` | Sets every model `limit.context` in that cell's config (for example `72000`, so compaction's usable window is 40,000). |
| `fault` | Arms the cell proxy for the first `/v1/messages` POST: `http-529`, `http-429`, or `sse-server-error`. |
| `mode` | Passes `opencode run --mode <value>` when that binary's help lists `--mode`. |
| `permissions=workspace` | Omits `--auto` and `--dangerously-skip-permissions`, and writes the allow-map without `external_directory`. |
| `global-agents=1` | Writes `$XDG_CONFIG_HOME/opencode/AGENTS.md` (`Prefix every final answer with GLOBAL-RULE.`). |
| `lsp` | Installs `pyright`, `typescript` (`typescript@5.8.3` into the workspace), and/or `dotnet` (Roslyn with `--tool-path` into `$XDG_DATA_HOME/opencode/bin`; needs the .NET 10 SDK on PATH or `DOTNET_ROOT`) before the cell starts. A cell without that SDK fails closed. |
| `modalities=image` | Sets every model `modalities` to image input and text output, so the read tool attaches a PNG. |
| `webfetch=local` | Serves a one-pixel red PNG at `http://127.0.0.1:<port>/color.png` (`Content-Type: image/png`) and replaces `__OBENCH_WEBFETCH_URL__` in the prompt. No public image host. |
| `disable-tools` | Comma-separated names from `bash`, `write`, `edit`, `patch`, `webfetch`. Writes `mode.build.tools.{name}=false` into the cell's `opencode.json`. It does not write a `permission` key (the July 2025 schema rejects that key). Combine it with `mode=build` so the run passes `--mode build`. Quote the CSV cell when the value contains a comma. |

```bash
python -m thesis.ab.run_ab thesis/ab/fixtures/opencode-harness-prs.csv \
  --pr 4838 \
  --task-map thesis/ab/fixtures/trigger-tasks.csv \
  --trials 5 \
  --out results/ab
```

A 5-trial A/B on PR 22390's trigger task, then the parent-vs-parent noise arm. `--aa` runs the parent build on sides `aa-1` and `aa-2` and reuses that cached binary. Those side names are not `without` / `with`.

```bash
python -m thesis.ab.run_ab thesis/ab/fixtures/opencode-harness-prs.csv \
  --pr 22390 \
  --task-map thesis/ab/fixtures/trigger-tasks.csv \
  --trials 5 \
  --out results/ab

python -m thesis.ab.run_ab thesis/ab/fixtures/opencode-harness-prs.csv \
  --pr 22390 \
  --task-map thesis/ab/fixtures/trigger-tasks.csv \
  --trials 5 \
  --aa \
  --out results/ab-aa
```

The default launch order runs every cell of side A, then every cell of side B. `--order interleave` alternates the two sides inside each trial, so a rate limit or a warm prompt cache hits both sides in the same window. `--order random --seed N` shuffles the cells inside each trial block and leaves the blocks themselves in trial order. `--seed N` with `--order interleave` does not shuffle: the order stays fixed, and the seed only drives per-cell randomness (for example the webfetch colour on PR 13331). Each cell records `run_seed` and a derived `cell_seed`. Both orders apply to a normal A/B and to `--aa`. `--jobs 1` runs that schedule one cell at a time. A higher `--jobs` still submits in that order.

```bash
python -m thesis.ab.run_ab thesis/ab/fixtures/opencode-harness-prs.csv \
  --pr 22390 \
  --task-map thesis/ab/fixtures/trigger-tasks.csv \
  --trials 5 \
  --order interleave \
  --out results/ab
```

```bash
python -m thesis.ab.run_ab thesis/ab/fixtures/opencode-harness-prs.csv \
  --pr 22390 \
  --task-map thesis/ab/fixtures/trigger-tasks.csv \
  --trials 5 \
  --aa \
  --order random \
  --seed 7 \
  --out results/ab-aa
```

`--with-aa` runs the A/B pair and the parent-vs-parent pair in one schedule. Each trial block is without, with, aa-1, and aa-2, shuffled when you pass `--seed`. `--order interleave` keeps that block in the fixed order without, with, aa-1, aa-2. The cells land in the same `--out` directory the summary already reads: `without.jsonl`, `with.jsonl`, `aa-1.jsonl`, `aa-2.jsonl`, and `arm.json`. `--aa` and `--with-aa` together are an error.

```bash
python -m thesis.ab.run_ab thesis/ab/fixtures/opencode-harness-prs.csv \
  --pr 22390 \
  --task-map thesis/ab/fixtures/trigger-tasks.csv \
  --trials 5 \
  --with-aa \
  --seed 7 \
  --out results/ab
```

PR 984's map row is `mode=build;disable-tools=bash,write` on `make-ci-green`. A one-trial smoke is two cells (without and with):

```bash
python -m thesis.ab.run_ab thesis/ab/fixtures/opencode-harness-prs.csv \
  --pr 984 \
  --task-map thesis/ab/fixtures/trigger-tasks.csv \
  --trials 1 \
  --order interleave \
  --out results/ab-984
```

After the cells exist, grep the transcript and the copied storage for that PR's pattern. The pattern file defaults to `thesis/ab/fixtures/trigger-evidence.csv` (the researcher's table, also stored as `trigger-tasks-34.md` and `trigger-tasks-34.csv` in that directory):

```bash
python -m thesis.ab.evidence results/ab
```

The cell gains `exercised` (`exercised`, `not exercised`, or `undeterminable` when no evidence file was copied). `results/ab/evidence-summary.json` counts those per PR and side.

PR 984 uses `classify_edit_only` in `thesis.ab.evidence`. A 984 cell is exercised only when the evidence has at least one edit call and zero `"tool": "bash"` or `"tool": "write"` parts. The pattern row still matches edit. The cell records `edit_calls` and `bash_write_calls`, each the largest count in any one evidence file.

## What each binary gets

The runner reads `opencode run --help` on that binary. It passes `--auto` when the help text lists it, and otherwise `--dangerously-skip-permissions` when that flag is listed. When neither flag exists and the config schema accepts a `permission` object, the per-run config sets edit, bash, webfetch, and the other tools to `allow`. A run that still sits on a permission prompt fails with `waiting on a permission prompt` instead of waiting out the task timeout.

The default config points the stock `anthropic` provider at the proxy. The model id is `claude-opus-5-5`, with a 1,000,000 token context limit and a 128,000 token output limit. Old trees read the base URL from `provider.anthropic.api`. Later trees read `options.baseURL`. A tree that rejects both gets `ANTHROPIC_BASE_URL` instead. The API key is the dummy value `proxy`. The proxy holds the Vertex credential.

Any checkout with an `@ai-sdk/anthropic` pin gets that package installed into the host cache before the cell, whether or not `needs_sdk` is set. `needs_sdk` is only true when `BUN_BE_BUN=1 <bin> install --help` still prints OpenCode help. v0.6 through v1.0.79 (PRs 2334, 3115, 3418, 4204) embed bun, so that check is false, and they still run `bun add --force --exact @ai-sdk/anthropic@latest` unless the cache version file matches `CACHE_VERSION` and `package.json` already records the dist-tag (`latest`, or `beta` on the July 2025 builds). The runner writes both, and sets `OPENCODE_DISABLE_DEFAULT_PLUGINS=1`, before the cell. After the cell, the toolchain's `anthropic` field is the version left in the cache, not the lockfile pin. A mismatch is `infra` with reason `sdk drift`.

Stock OpenCode from v1.0.123 (PR 4838) through v1.15.2 (PR 26821) imports `@ai-sdk/anthropic` as a bundled provider. The proxy route uses that import and does not resolve `@ai-sdk/anthropic@latest`, so those builds are not exposed to the 4.x jump. They still have a lockfile pin, so the same cache seed and drift check run. The process itself keeps using the bundled SDK. A custom provider npm that is not in `BUNDLED_PROVIDERS` still goes through `BunProc.install(pkg, "latest")`.

`--model-route vertex` is the previous path. The config defines `google-vertex-anthropic/claude-opus-5-5@default` when the binary does not already list it. A binary that still cannot load that provider is recorded as incompatible, with the reason, and that side is not scored.

## Results

Finished cells are `results/ab/<pr>/cells/<side>/<task>/<trial>.json`. The runner rewrites `results/ab/<pr>/without.jsonl` and `with.jsonl` from those files. `--aa` writes `aa-1.jsonl` and `aa-2.jsonl` instead, plus `arm.json` naming the parent SHA. `--with-aa` writes all four side files and `arm.json` in that same directory. The summary labels the aa sides parent-vs-parent noise and does not report them as a with-minus-without harness delta. An incompatible side writes `results/ab/<pr>/<side>.incompatible.json`. Each side also writes `<side>.toolchain.json` with the Bun version, the `ai` version, and the installed `@ai-sdk/anthropic` version. The same object is on each cell row. The summary prints both sides. When the installed SDK versions differ, it says `SDK changed: harness delta may be confounded`.

Each cell records `schedule_index` (its place in the launch schedule, from 0) and `started_at` (UTC timestamp when that cell process began).

Token totals count every model request the metering proxy attributed to the cell, including subagent and child sessions that used the same `/c/<cell-id>/` base URL. The cell stores:

| Field | Meaning |
| --- | --- |
| `requests_input_uncached`, `requests_output`, `requests_cache_read`, `requests_cache_write` | Sum of those buckets over every proxy request for the cell. |
| `requests_count` | How many of those requests carried usage. |
| `requests_cost_usd` | Those buckets at $4 / $20 / $0.20 / $5 per million tokens. |
| `tokens_input_uncached`, `tokens_output`, `tokens_cache_read`, `tokens_cache_write` | The same all-request totals. Cost and the summary read these. |
| `tokens_main_input_uncached`, `tokens_main_output`, `tokens_main_cache_read`, `tokens_main_cache_write`, `tokens_main_calls` | The main session only, from the harness event stream, when that split existed. |
| `tokens_proxy_*` | The proxy ledger split. It matches the `requests_*` buckets. |

A cell that dies in under 10 seconds with `Unhandled chunk type`, `ProviderInitError`, `DecimalError`, or `prepare wasm` in its output is `failure_class=infra`, not a wrong answer. If the first three cells of a side all die that way, the runner writes `<side>.infra.json` and does not launch the rest. Infra and incompatible cells are not scored.

`--no-progress-s` defaults to 300. The cell runner kills the agent process tree when stdout, the OpenCode data directory (`$XDG_DATA_HOME/opencode`, logs and storage), and the cell's proxy accounting are all idle for that many seconds. The cell JSON records `failure_class=infra`, `infra_reason=no_progress`, and `no_progress_idle_s` (how long it was idle). A fatal `Aborted(` or tree-sitter wasm ENOENT line kills the process immediately and records `infra_reason=wasm_abort`. `--no-progress-s 0` turns the watchdog off, including that immediate kill, because the process is not streamed. The summary counts `no_progress` kills on each side (`without`/`with`, and `aa-1`/`aa-2` on the noise arm).

Proxy progress uses the same per-cell ledger as the `requests_*` totals. A finished request appends `<cell>.jsonl` under the ledger directory, and that growth counts. A streaming request is not in that file until it ends, so each chunk also updates the sibling `<cell>.bytes` counter. Both files are written only for `/c/<cell_id>/...`, which is how the runner rewrites the base URL. A request that reaches the proxy without that prefix is not attributed to a cell. `--model-route vertex` does not send OpenCode through this proxy, so those cells are watched on stdout, logs, and storage only.

The longest gap between consecutive OpenCode log lines in a finished run is:

```bash
python -m thesis.ab.max_silent_gap results/ab
```

It prints each cell's longest gap and the max and nearest-rank p99 per side. The first log line's `+Nms` is from logger startup and is not a gap. Log files are preferred, then the transcript, then `output_tail`.

Each cell keeps a local transcript, plus that cell's OpenCode session storage and log directory, under `results/ab/<pr>/transcripts/`. Current builds are copied from `opencode/storage` and `opencode/log`. Builds from about PR 623 through PR 2334 keep sessions at `opencode/project/<id>/storage`, and that tree is copied too. A later `opencode/opencode.db` is copied when it exists. `--transcripts-dir` changes the root. Those files are local evidence for whether the changed code path ran. They are not published.

Summarize pass rate, score, time, turns, tokens, and cost. Each PR lists per-task deltas for time, turns, tokens, and cost, with a bootstrap interval. The headroom section lists tasks whose mean score is below 1.0 on either side and gives the pass-rate delta on only those tasks.

```bash
python -m thesis.ab.summarize thesis/ab/fixtures/opencode-harness-prs.csv --results results/ab
```

The per-PR section includes Title, Category, and Harness change.

## Cost, timeout, resume

`--timeout` defaults to 2400 seconds per cell. The runner caps each cell at 840 seconds, so a stuck call stops before 15 minutes. A shorter `--timeout` still wins. `--jobs` defaults to 1. The pilot above uses 8.

`--max-cost-usd` prices finished rows at $4 per million uncached input tokens, $20 per million output tokens, $0.20 per million cache-read tokens, and $5 per million cache-write tokens. The runner stops launching new cells once that estimate reaches the cap. Cells already running are allowed to finish. A finished cell with a missing token count is unmetered and also stops new launches. Cells whose failure class is `infra` or `incompatible` do not.

Run the same command again to skip cells that already have a result file. `--dry-run` prints the plan and does not build OpenCode or call the model.

Build one SHA on its own with:

```bash
python -m thesis.ab.build_opencode <40-character-sha> --cache results/opencode-src
```

v1.0 checkouts (`packages/opencode/script/build.ts --single`, the November 2025 cluster including PR 4204 parent `0d3d48bb5964a95e939edcea3bb726a21823d1a1`) write four Linux x64 binaries under `dist/opencode-linux-x64*/bin/opencode`: glibc, glibc baseline, musl, and musl baseline. The musl file is mode 755. On a glibc host `exec` still returns ENOENT, because the ELF interpreter is `/lib/ld-musl-x86_64.so.1` and that linker is not installed. A `#!/usr/bin/env node` launcher in `packages/opencode/bin/opencode` fails the same way when `node` is not on `PATH`. The publisher keeps the dist binary whose interpreter exists here, and a cached `bin/<sha>/opencode` that fails that check is rebuilt. Smoke one ENOENT SHA with:

```bash
python -m thesis.ab.build_opencode 0d3d48bb5964a95e939edcea3bb726a21823d1a1 --cache results/opencode-src
results/opencode-src/bin/0d3d48bb5964a95e939edcea3bb726a21823d1a1/opencode --version
```

The version line is the check. The command compiles that upstream commit.

Older trees (no `script/build.ts`, and `packages/opencode/script/publish.ts` runs `bun build --compile`) import tree-sitter wasm with `type: "wasm"`. Bun 1.2 rewrites that to `/$bunfs/tree-sitter-<hash>.wasm` and does not embed the bytes, so the first bash tool call aborts with ENOENT and the process spins until the cell cap. The build step rewrites those imports to `type: "file"` before `bun build --compile`, which embeds the bytes and returns a path. The rewrite is skipped when `script/build.ts` exists, so the `Bun.build` era is left as upstream wrote it. #2334 and #2367 are in the publish.ts era and are rewritten. #3052 already has `script/build.ts`, so it is not. `--minify` stays off; that is the upstream command, and omitting it does not embed the wasm. A cached `bin/<sha>/opencode` is reused only when `build-stamp.json` beside it matches the current recipe. A missing stamp, a compile stamp that still says `minify: true`, or a compile stamp with no `tree_sitter_wasm` marker (`file` or `unchanged`) is rebuilt.

## Pi and Oh My Pi pilot

Pi is the `pi` command from `badlogic/pi-mono`. Oh My Pi is the `omp` command from `can1357/oh-my-pi`. Both use the same runner. The `Repo` column makes the run id `pi-3` or `omp-14`. The results record the two as separate harnesses.

Pi, Oh My Pi, and OpenCode use the same proxy. The runner starts it once and shares it across jobs.

```bash
python -m thesis.ab.run_ab thesis/ab/fixtures/pi-harness-prs.csv \
  --pr pi-3,pi-4,pi-5,pi-7,omp-14,omp-16,omp-20 \
  --trials 3 \
  --jobs 8 \
  --out results/ab
```

The pilot is three Pi rows and three Oh My Pi rows, plus one Pi control.

- `pi-3` changes the system prompt. It removes the identity line. This is also the oldest Pi commit that can load a custom model, v0.10.2.
- `pi-4` truncates large tool results and tells the model how to continue.
- `pi-5` adds fuzzy matching in the edit tool.
- `pi-7` expands the documentation block in the system prompt. The notes expect a small effect, so this is the control.
- `omp-14` changes the find tool to one `pattern` argument.
- `omp-16` puts each tool's description into the system prompt.
- `omp-20` rewrites the hashline edit prompt.

`pi-1` and `pi-2` are v0.7.8. Those trees have no models file. The runner marks both sides incompatible with the reason `no custom-model support` and does not score them. They are not in the pilot.

The CSV stores full SHAs. The runner uses those SHAs. It does not look up old Oh My Pi tags, because that history was rewritten. Builds are cached under `results/harness-src` by repo and SHA.

The Pi build compiles the TypeScript committed at that SHA. It does not refetch the live model list, because that list drops providers the commit still imports. A lockfile that names a version and omits the tarball URL still installs that version under `npm ci`. Linux packages the lockfile skipped, including `tsgo` and `@parcel/watcher`, are unpacked from their own tarballs. An `npm install` of those packages is not used, because it moves `@google/genai` off the locked 1.30.0 and the committed `FinishReason` switch no longer typechecks.

`0397dd44c838f5dba88a315c784976cb975c62cc`, the parent of `pi-3`, builds with that pin. `pi --version` opens the v0.10.1 banner. `pi-4` has the same exhaustive switch. `pi-1` and `pi-2` have it too, and they are still incompatible before compile because they have no models file. `pi-5` and later no longer use that switch.

Build one SHA on its own with either command.

```bash
python -m thesis.ab.build_pi <40-character-sha> --cache results/harness-src
```

```bash
python -m thesis.ab.build_omp <40-character-sha> --cache results/harness-src
```

## Oldest OpenCode commit in the fixture

The oldest parent SHA is `b99565959bb7a094e339802076d6ad6fd7d7f83c`, the parent of PR 623 (nearest tag v0.1.180). `python -m thesis.ab.build_opencode` compiles that commit with the `package.json` Bun (1.2.14) and Go 1.24.6. The binary runs, and `opencode --version` prints `openbench`. `opencode run --help` lists `-m` / `--model` and does not list `--auto` or `--dangerously-skip-permissions`. The config schema rejects a `permission` key, so the runner does not write one.

`opencode models` lists `anthropic/claude-opus-5-5` after the proxy config is installed. A `run` against a stub upstream posts `POST /v1/messages` with `"model":"claude-opus-5-5"` and `"max_tokens":128000`. The compiled binary treats `bun install` as its own help text and exits 0, so the runner installs `@ai-sdk/anthropic` with that checkout's Bun before the run. The version is the lockfile pin when it depends on the same `@ai-sdk/provider` release as `ai`. When the locked anthropic package is from an older provider generation, the runner picks the newest `@ai-sdk/anthropic` that depends on `ai`'s provider. v0.14 and v0.15 lock `@ai-sdk/anthropic@2.0.0` next to `ai@5.0.8`. That release reports token counts as numbers. `@ai-sdk/anthropic@latest` reports them as objects, and those builds then die in `new Decimal(usage.inputTokens)` with `DecimalError`. The cache `package.json` records the dist-tag that binary passes to `BunProc.install` (`latest`, or `beta` on the July 2025 builds) after the pin is installed. The binary skips its own install only when that string matches. The npm `beta` tag is a different release and is not the pin. A side that fails the short preflight, or whose cells report a provider stream error or `DecimalError` and no tokens, is incompatible and is not scored. A preflight that exits before any metered call is incompatible. A side whose finished cells have no metered tokens is infra and is not scored. Tokens the proxy measured count, including when the harness did not emit usage. An exec failure, including a musl binary on a glibc host, is infra. The build selects the host platform, architecture, and libc, preferring the non-baseline glibc binary.

PRs 623, 913, 984, 1248, 2334, and 2367 do not mention `@ai-sdk/google-vertex/anthropic` under `packages/opencode`. Those are the rows the native Vertex route cannot load. Every SHA in the fixture, including those six, has the custom `provider` field in `config.ts`. The proxy route uses that field. This check is the source tree, not a build of all 34 rows. `--model-route vertex` still records a side as incompatible when that provider package does not resolve.
