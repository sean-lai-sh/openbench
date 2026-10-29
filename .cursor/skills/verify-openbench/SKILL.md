---
name: verify-openbench
description: "Verify the OpenBench thesis benchmark harness from its CLI runners and the obench test suite (thesis.ab A/B runner and run_cell, step8 gate/launcher/scoring, Pi and OpenCode adapters). Use when changing those surfaces or when a proof must be a stub run with no model call and no api.anthropic.com egress."
---

# Verify OpenBench

OpenBench here is the thesis harness: `python -m thesis.ab.run_ab` runs one cell per side through `obench.run.run_cell`, `thesis/ab/launchers/step8_f032.sh` is the step-8 F03-2 launcher, and `thesis.ab.step8_gate` / `step8_scoring_parity` / `summarize` judge recorded cells. The checker and the saved cells are the judge. A harness self-report is not a score.

The primary surface is those CLI modules plus the test tree `obench/tests` (`pytest.ini` sets `testpaths = obench/tests` and `pythonpath = .`; CI collects the same tree with unittest). There is no web UI.

Feature map: [features/README.md](features/README.md).

Stub proof never calls a model, never needs a live API key, and never opens `api.anthropic.com`. `pip install -e .` installs only the `obench*` packages. `thesis` is imported from this checkout because the current directory is on `sys.path`. A copy under `~/ob-f032` or `site-packages` is the wrong tree.

## Launch

From the repo root:

```bash
python3 -m pip install -e .
python3 -m unittest discover -s obench/tests -v
```

`python3 -m pytest` collects the same tests when pytest is installed. The project has no third-party runtime dependencies (`requires-python >= 3.11`).

`obench.publish` treats the hostname `cursor` as PII and refuses the bundle. On a machine with that hostname the site and publish tests error (81 errors and 1 failure in a 1983-test run on 2026-10-28). That is not a model call and it does not touch `thesis.ab`. The modules in Drive are the harness proof; they passed 162 tests on that run. CI runners are not named `cursor`.

Stubbed A/B plan. This returns before any build, proxy, or model call (`drive` returns the plan when `dry_run` is set):

```bash
env -u ANTHROPIC_API_KEY -u ANTHROPIC_BASE_URL -u OPENAI_API_KEY \
    -u GOOGLE_APPLICATION_CREDENTIALS -u GOOGLE_CLOUD_PROJECT -u GCLOUD_PROJECT \
  python3 -m thesis.ab.run_ab thesis/ab/fixtures/opencode-harness-prs.csv \
    --pr 4204 \
    --task trig-subagent-followup \
    --task-map thesis/ab/fixtures/trigger-tasks.csv \
    --trials 1 \
    --dry-run
```

A passing plan prints one line for PR 4204, `tasks: per-pr`, `trials: 1`, `cells: 2`, `order: sides`, and exits 0.

The step-8 gate has no separate dry-run flag. Its no-model path is `python3 -m thesis.ab.step8_gate` on a recorded tree (see Drive) or the unit tests named in [features/step8-gate.md](features/step8-gate.md). Do not start `thesis/ab/launchers/step8_f032.sh` for a stub proof. That script builds cells against Vertex.

## Doctor

Read-only. Do not add iptables rules, do not curl `api.anthropic.com`, and do not start Docker.

```bash
python3 - <<'PY'
import os, pathlib, sys
root = pathlib.Path.cwd().resolve()
print("python", sys.version.split()[0])
if sys.version_info < (3, 11):
    raise SystemExit("need Python >= 3.11")
for name in ("thesis", "obench"):
    mod = __import__(name)
    path = pathlib.Path(mod.__file__).resolve()
    print(f"{name} {path}")
    if not path.is_relative_to(root):
        raise SystemExit(f"{name} is not this checkout: {path}")
    if "site-packages" in path.parts:
        raise SystemExit(f"{name} is a pinned site-packages copy: {path}")
base = os.environ.get("ANTHROPIC_BASE_URL", "")
if "api.anthropic.com" in base:
    raise SystemExit(f"ANTHROPIC_BASE_URL points at api.anthropic.com: {base}")
for key in ("ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL", "OPENAI_API_KEY",
            "GOOGLE_APPLICATION_CREDENTIALS", "GOOGLE_CLOUD_PROJECT", "GCLOUD_PROJECT"):
    print(f"{key}={'set' if os.environ.get(key) else 'unset'}")
print("stub runs do not read those keys")
PY
HEAD=$(git rev-parse HEAD)
RESOLVED=$(python3 -c 'from thesis.ab.run_ab import resolve_runner_commit; print(resolve_runner_commit() or "")')
echo "HEAD=$HEAD"
echo "resolve_runner_commit=$RESOLVED"
test "$RESOLVED" = "$HEAD" || { echo "runner commit is not this checkout"; exit 1; }
if [ -n "${RUNNER_SHA:-}" ] && [ "$RUNNER_SHA" != "$HEAD" ]; then
  echo "RUNNER_SHA=$RUNNER_SHA does not match HEAD"; exit 1
fi
if [ -n "${OBENCH_RUNNER_COMMIT:-}" ] && [ "$OBENCH_RUNNER_COMMIT" != "$HEAD" ]; then
  echo "OBENCH_RUNNER_COMMIT does not match HEAD"; exit 1
fi
test -f thesis/ab/launchers/egress_block.sh
echo "egress backstop present (not applied)"
```

`RUNNER_SHA` is the pin `step8_f032.sh` compares to `git -C ~/ob-f032 rev-parse HEAD` before any cell. On a stub checkout the variable is usually unset; the recorded commit is this tree's HEAD via `resolve_runner_commit`. A set `RUNNER_SHA` or `OBENCH_RUNNER_COMMIT` that disagrees with HEAD means this process would record a different pin. Fail the doctor.

The live launcher blocks `api.anthropic.com` with `thesis/ab/launchers/egress_block.sh` (host REJECT plus a container sinkhole) and aborts unless `egress_verify` fails to reach the host. A stub doctor does not install those rules. Strip the key variables with `env -u` on every stub command so a key sitting in the environment is not used. After the command, no `vertex_anthropic_proxy` process and no container you started should be running.

## Drive

Run one feature end to end. Commands are real modules. Pass `--out` into the evidence directory so a replay does not rewrite `data/step8-pins/scoring-parity.csv`.

| Feature | Command |
| --- | --- |
| Unit tests for the runner, gate, and Pi A/B stubs | `python3 -m unittest obench.tests.test_ab obench.tests.test_pi_ab obench.tests.test_step8_conditions obench.tests.test_cell_field_completeness obench.tests.test_probe_method_cell obench.tests.test_runab_cap_and_lsp` |
| `run_cell` plan, no model | the Launch `--dry-run` |
| Step-8 completeness on a recorded batch | `python3 -m thesis.ab.step8_gate --complete results/step8-f032-1027/scored results/step8-f032-1027/gate.json results/step8-f032-1027/rerun` |
| Scoring parity replay | `python3 -m thesis.ab.step8_scoring_parity --out results/verify-openbench/<date>/scoring-parity.csv` |
| Summarize a recorded dir | `python3 -m thesis.ab.summarize results/step8-full413-1020/prs.csv --results results/step8-full413-1020-F03-1-rerun --out results/verify-openbench/<date>/summary` |

Details, user-facing entry, and gotchas: `features/`. The Pi comparison adapter's live smoke is pending [PR #134](https://github.com/sean-lai-sh/openbench/pull/134) and is not a stub.

## Evidence

Write the proof under `results/verify-openbench/<YYYY-MM-DD>/`:

- `launch.log` — install, unittest, dry-run, exit codes
- `doctor.log` — the doctor transcript
- the feature's own stdout and any file it wrote (`scoring-parity.csv`, `summary.md`, gate JSON)

`results/` is gitignored. Commit a small proof with `git add -f`. A file over 50MB stays out of git: add a `MANIFEST` row of `bytes`, `sha256`, and path.

A proof is a real CLI path, an exit code, and output from recorded cells or a stub. Quote the line that shows the result (`scoring_parity pass: 180/180 cells`, the dry-run `cells: 2` line, or `incomplete` from `--complete`). Do not treat a harness transcript as the score. Do not claim a model was called. Default parity inputs are the 180 saved cells in `results/step8-full413-1020-F03-1-rerun` (PRs 3006 and 3079) and `results/step8-full413-1020-F01` (PR 579).

`--complete` always exits 0. Read the JSON. `incomplete` sides are not padded. `evaluate` (the three-argument form) exits 1 when more than 2 sides fail or fewer than 22 sides were seen.

## Cleanup

Stop only processes this verification started. The dry-run and the parity replay are foreground and exit on their own. Do not `docker stop` or `docker rm` `s8-f032` unless this shell started that container. Do not run `egress_block.sh remove` unless this shell ran `egress_apply`. Leave `results/`, `data/step8-pins/`, and the proof directory in place.
