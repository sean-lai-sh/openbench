# step8_gate

`python3 -m thesis.ab.step8_gate` decides whether a step-8 side loaded its pinned `@ai-sdk/anthropic` and whether the scored cells are complete. The launcher is `thesis/ab/launchers/step8_f032.sh`. It is not started by a stub proof.

## Sub-features

- Gate cells. One traced cell per side (`OBENCH_PROVIDER_TRACE=1`). `probe_method` is `strace` or `embedded`. A missing probe is unproven. These cells are infra evidence and are not scored (`scorable` is false when `strace_on` or `gate_cell` is set).
- Route. Every cell has `route` of `on:<how>` or `off:<how>`. More than 2 off-route cells halt that side. More than 2 halted sides halt the batch.
- Completeness. `--complete` keeps a side only when its PR passed the gate and it has 30 on-route scored cells. A `rerun=1` cell replaces its off-route original. A short side is `incomplete` and is not padded.
- Spend projection and cap. The launcher projects gate-cell cost times 30, holds if that plus current spend would pass `$60`, flags a file at `$50`, and hard-stops at `$60`. `run_ab --max-cost-usd` stops on its own once finished cells reach the cap (`over_budget`).

## How to get to it (user POV)

On the step-8 VM the launcher writes `$HOME/s8f032run/{gate,scored,rerun,gate.json,complete.json}`. Copy that tree back as `results/step8-f032-1027/` (data only, `git add -f`). Then:

```bash
python3 -m thesis.ab.step8_gate --complete \
  results/step8-f032-1027/scored \
  results/step8-f032-1027/gate.json \
  results/step8-f032-1027/rerun
```

Projection from the same gate file, matching the launcher (sum of passed PRs' gate-cell cost, times 30 scored cells):

```bash
python3 -c 'import json; d=json.load(open("results/step8-f032-1027/gate.json")); c=[x["cost"] or 0 for x in d["cells"] if x["pr"] in set(d.get("ok_prs") or [])]; print(round(sum(c)*30, 2))'
```

The three-argument form checks the traced gate cells against `thesis/ab/provider_pins.json` and a sides JSON of `{pr: {without: sha, with: sha}}`:

```bash
python3 -m thesis.ab.step8_gate \
  results/step8-f032-1027/gate \
  thesis/ab/provider_pins.json \
  results/step8-f032-1027/sides.json
```

## Driving it with verify-openbench

This checkout does not contain `results/step8-f032-1027`. The committed neighbours are notes under `results/step8/f03-2-*-20261027` and the pin dry run `results/step8-f032-dry-run-1026`. Those are not a scored `--complete` tree. Do not invent one.

Stub drive, no model call:

```bash
env -u ANTHROPIC_API_KEY -u ANTHROPIC_BASE_URL -u OPENAI_API_KEY \
    -u GOOGLE_APPLICATION_CREDENTIALS -u GOOGLE_CLOUD_PROJECT -u GCLOUD_PROJECT \
  python3 -m unittest \
    obench.tests.test_step8_conditions \
    obench.tests.test_probe_method_cell \
    obench.tests.test_cell_field_completeness \
    obench.tests.test_runab_cap_and_lsp
```

`test_runab_cap_and_lsp` is the spend-cap stub: cells already in the output directory count toward `--max-cost-usd`.

When `results/step8-f032-1027/scored` and `gate.json` are present, run the `--complete` command above and save the JSON under `results/verify-openbench/<date>/complete.json`. Pass means you read `complete` and `incomplete`. Exit 0 alone is not "every side finished".

## Gotchas

- `--complete` returns exit 0 even when every side is incomplete. The evaluate form exits 1 when more than 2 sides mismatch or fewer than 22 sides were seen. `--route` exits 1 when the batch should halt.
- Gate cells and traced cells are not scored. A side with 30 files can still be short if some are off-route or traced.
- The `$50` flag and `$60` hard stop live in `step8_f032.sh`, not in `step8_gate.py`. `over_budget` is the in-process cap on `run_ab`.
- Do not launch `step8_f032.sh` to produce a gate file for this proof. It spends on Vertex and requires `RUNNER_SHA` to match `~/ob-f032`.
- Applying `egress_block.sh` is a live-launch step. A stub drive does not add or remove those iptables rules.
