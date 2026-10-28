# Pi adapter

Pending [PR #134](https://github.com/sean-lai-sh/openbench/pull/134) (`cursor/pi-harness-adapter-4bc6`, open, not on `main`).

That PR adds the pinned Pi harness-comparison adapter. Pi is git commit `d0aa218cb16c333c008f6aa3dcd670ac8b68383c` (`@earendil-works/pi-coding-agent` at that commit). npm `@earendil-works/pi-coding-agent@1.4.0` is tag `v1.4.0` (`4a080252`), a different commit, and is not the pin. The comparison build uses the git commit. Upstream MIT text is `obench/adapters/pi_pin/`; no Pi source is vendored.

On `main` today, `obench/adapters/pi.py` is the subscription adapter (`openai-codex` / `gpt-5.5`, isolated `HOME`). The thesis A/B path still sets `OBENCH_PI_BIN` and `OBENCH_PI_VERTEX` from `thesis/ab/build_pi.py`. PR #134 leaves that path in place: when both are set, `OBENCH_PI_VERTEX` wins.

## Sub-features

- Headless flags `-p --mode json --no-approve`. Models `claude-opus-5-5` and `claude-sonnet-5-5` use shipped defaults (thinking medium, tools `read` / `bash` / `edit` / `write`).
- The cell proxy is `models.json` `baseUrl` without a `/v1` suffix. Pi posts to `/v1/messages`. A fetch wrapper sets `X-OB-Call-Role` from the system text so compaction summaries are `side:summary`.
- `data/pi-harness-smoke/cell.sh` builds the pin and runs one local cell per model on `polyglot-rust-c` (2400s). It unsets `OBENCH_PI_VERTEX`. Each `<model>.json` stores the `run_cell` row, the settings sidecar, and proxy totals (`all` / `main` / `side`).
- On main, `obench.tests.test_pi_ab` stubs the Anthropic/Vertex proxy on `127.0.0.1` and never calls a model. That is the stub stand-in until #134 merges. It does not exercise `pi_harness.py`.

## How to get to it (user POV)

Not available from `main`. After #134 merges, the live smoke (this spends on Vertex; it is not a stub proof) is:

```bash
bash data/pi-harness-smoke/cell.sh /h2/pi-harness-smoke
```

Needs `GOOGLE_CLOUD_PROJECT` (or `GCLOUD_PROJECT`) and application-default credentials. The script exports `PYTHONPATH=/ob` because `pip install -e /ob` only installs `obench*`, downloads Node `22.19.0` (the pin's `engines.node` floor), and checks `import thesis` and `node --version` before `cell.py` starts model calls.

The no-model test that lands with the PR:

```bash
python3 -m unittest obench.tests.test_pi_harness
```

## Driving it with verify-openbench

Mark the feature pending #134 when `obench/adapters/pi_harness.py` and `data/pi-harness-smoke/cell.sh` are absent on this branch. Do not check out the PR branch inside a verification of `main`, and do not run `cell.sh`. That script calls Vertex.

Stub drive on `main`:

```bash
env -u ANTHROPIC_API_KEY -u ANTHROPIC_BASE_URL -u OPENAI_API_KEY \
    -u GOOGLE_APPLICATION_CREDENTIALS -u GOOGLE_CLOUD_PROJECT -u GCLOUD_PROJECT \
  python3 -m unittest obench.tests.test_pi_ab
```

Pass is exit 0. The tests bind `127.0.0.1` and close it. Save the unittest summary in `results/verify-openbench/<date>/pi-ab-unittest.log`.

When #134 is merged, switch the drive to `python3 -m unittest obench.tests.test_pi_harness` and delete the pending note. Keep the live `cell.sh` smoke out of the stub proof.

## Gotchas

- `cell.sh` is a model run. A green stub suite does not mean the smoke cell solved `polyglot-rust-c`.
- The script's Node download is egress to `nodejs.org`, not to `api.anthropic.com`. Still do not run it for a no-spend proof.
- `test_pi_ab` on main covers the A/B proxy and `OBENCH_PI_VERTEX` path. It will not fail if `pi_harness.py` is missing, because that file is not on main.
- Pi talks to the proxy as Anthropic `POST /v1/messages`. It does not use the OpenAI chat-completions translator. A mid-stream Vertex error that the proxy drops is a known gap called out on #134 and is not part of this stub.
