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

The model is `claude-opus-5-5` on Vertex. `VERTEX_LOCATION` defaults to `global` when it is unset. The run calls Vertex from this machine. It does not start a GCP VM.

PR 23771 in the fixture is a commit on the development branch, not GitHub's merge commit. The runner uses the SHAs in the CSV.

## Tasks

The default task set is every core task under `tasks/` that contains `checker.sh`. Imported Terminal-Bench tasks need Docker and stay out of the default set.

List the core tasks with either command.

```bash
obench validate --no-imported
```

```bash
python -c "from obench.validate_tasks import discover_tasks, build_task_roots; print('\n'.join(name for _, name, _ in discover_tasks(build_task_roots(include_imported=False))))"
```

Pass a subset with `--tasks make-it-run,fix-failing-test`. Repeat the flag or separate names with commas.

## What each binary gets

The runner reads `opencode run --help` on that binary. It passes `--auto` when the help text lists it, and otherwise `--dangerously-skip-permissions` when that flag is listed. When neither flag exists and the config schema accepts a `permission` object, the per-run config sets edit, bash, webfetch, and the other tools to `allow`. A run that still sits on a permission prompt fails with `waiting on a permission prompt` instead of waiting out the task timeout.

When the binary does not already know `google-vertex-anthropic/claude-opus-5-5@default`, the same config defines that provider and a model entry with a 1,000,000 token context limit and a 128,000 token output limit. A binary that still cannot load the provider is recorded as incompatible, with the reason, and that side is not scored.

## Results

Finished cells are `results/ab/<pr>/cells/<side>/<task>/<trial>.json`. The runner rewrites `results/ab/<pr>/without.jsonl` and `with.jsonl` from those files. An incompatible side writes `results/ab/<pr>/<side>.incompatible.json`.

Summarize pass rate, score, time, tokens, and the per-task score delta:

```bash
python -m thesis.ab.summarize thesis/ab/fixtures/opencode-harness-prs.csv --results results/ab
```

The per-PR section includes Title, Category, and Harness change.

## Cost, timeout, resume

`--timeout` defaults to 2400 seconds per cell. `--jobs` defaults to 1. The pilot above uses 8.

`--max-cost-usd` prices finished rows at $4 per million uncached input tokens, $20 per million output tokens, $0.20 per million cache-read tokens, and $5 per million cache-write tokens. The runner stops launching new cells once that estimate reaches the cap. Cells already running are allowed to finish. A finished cell with a missing token count is unmetered and also stops new launches.

Run the same command again to skip cells that already have a result file. `--dry-run` prints the plan and does not build OpenCode or call the model.

Build one SHA on its own with:

```bash
python -m thesis.ab.build_opencode <40-character-sha> --cache results/opencode-src
```

## Pi and Oh My Pi pilot

Pi is the `pi` command from `badlogic/pi-mono`. Oh My Pi is the `omp` command from `can1357/oh-my-pi`. Both use the same runner. The `Repo` column makes the run id `pi-3` or `omp-14`. The results record the two as separate harnesses.

Every Pi cell and every Oh My Pi cell, on both sides, talks to one local proxy. The proxy accepts Anthropic `POST /v1/messages` and forwards it to Vertex `claude-opus-5-5` on the global endpoint. The runner starts that proxy once and shares it across jobs. Set `GOOGLE_CLOUD_PROJECT` and application-default credentials before a real run.

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

The Pi build compiles the TypeScript committed at that SHA. It does not refetch the live model list, because that list drops providers the commit still imports. A lockfile that omits the Linux `tsgo` package gets that package installed before the compile.

Build one SHA on its own with either command.

```bash
python -m thesis.ab.build_pi <40-character-sha> --cache results/harness-src
```

```bash
python -m thesis.ab.build_omp <40-character-sha> --cache results/harness-src
```

## Oldest OpenCode commit in the fixture

The oldest parent SHA is `b99565959bb7a094e339802076d6ad6fd7d7f83c`, the parent of PR 623 (nearest tag v0.1.180). `python -m thesis.ab.build_opencode` compiles that commit with the `package.json` Bun (1.2.14) and Go 1.24.6. The binary runs, and `opencode --version` prints `openbench`. `opencode run --help` lists `-m` / `--model` and does not list `--auto` or `--dangerously-skip-permissions`. The config schema rejects a `permission` key, so the runner does not write one. Loading `google-vertex-anthropic/claude-opus-5-5@default` fails with `ProviderInitError` because the process cannot resolve `@ai-sdk/google-vertex/anthropic`. That failure happens before any Vertex request. The runner records the side as incompatible and does not score it.
