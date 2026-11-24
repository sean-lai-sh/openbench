# OpenBench Hard suites (reflection loop, SEA-106)

Task lists for the reflection loop, how to load them by id, and the per-model
harder-swap rule. Nothing here runs trials (that is SEA-107).

| File | What |
|---|---|
| `suites/pilot.toml` | The 10-task pilot, each task with its source, published frontier rate, domain and the reason it was chosen |
| `suites/pilot-pool.toml` | Harder replacements for the pilot |
| `suite.py` | `load_suite(name)`, `load_task(suite, id)` → `(tasks_dir, id)` for `obench.run.run_cell`; `SOURCES` records each source's in-repo tasks dir and upstream bench snapshot |
| `swap.py` | The swap rule: `initial_state`, `apply_results`, `passed`, `pool_capacity` |
| `config.py` | `PASS_CUTOFF = 0.90`, the only place the cutoff is set |

Bench snapshot: every task comes from Terminal-Bench 2 at commit
`2fd12b88aafdd04a52c298e3940bcb189f9766d6` (Apache-2.0). Tasks were imported
by `obench import harbor` into `data/packs/openbench-tb-hard`,
`data/packs/openbench-tb-mid` and `tasks-imported/terminal-bench-2`.
`frontier_rate` is the published frontier-panel solve rate from
`harborframework/terminal-bench-2-leaderboard@572b2614`
(`data/packs/openbench-tb-hard/tb2-frontier-rates.csv`). It is a difficulty
prior, not a pass result.

## Load

```python
from obench.hardsuite.suite import load_suite, load_task, resolve

pilot = load_suite("pilot")
tasks_dir, task_id = load_task("pilot", "dna-insert")   # -> run_cell(..., task_id, ..., tasks_dir, ...)
for task in pilot.tasks:
    tasks_dir, task_id = resolve(task)                  # fails if instruction.md or checker.sh is missing
```

## Pass cutoff and the swap rule

- A task **passes** for a model when `successes / trials >= cutoff`. The
  cutoff is `config.PASS_CUTOFF` (default **0.90**: 27/30 at N=30).
  `OBENCH_HARD_PASS_CUTOFF` overrides it for one run, and each swap records
  the cutoff it used.
- Each model keeps its own state (`initial_state(model, suite)`), one slot per
  planned task. `apply_results(state, {task: (successes, trials)}, suite, pool)`
  swaps every passing task, **for that model only**, for the easiest pool task
  that is strictly harder (lower frontier rate), skipping tasks the model
  already has or has retired. Other models keep the original until they pass
  it themselves.
- **The suite never shrinks.** If no eligible harder task is left,
  `apply_results` raises `PoolExhausted` and changes nothing; grow the pool.
  `pool_capacity(suite, pool)` shows, per slot, how many harder tasks the pool
  holds. The pilot pool has 7 tasks: enough for any one model to swap up to 7
  of its 10 slots.

## Add a task

1. Import it: `python3 -m obench.cli import harbor --from <task dir>` into one
   of the `SOURCES` directories, or add a new `SOURCES` entry with its tasks
   dir and upstream repo and commit.
2. Admit it: `python3 -m obench.cli validate --tasks-dir <dir>`. The checker
   must fail on the untouched workspace and pass with `solution/`.
3. Add a `[[task]]` with `id`, `source`, `frontier_rate`, `domain` and `why`
   to the suite file (or to the pool, if it is a harder replacement). A suite
   that changes size must update `planned_size`.
4. Run `python3.11 -m unittest obench.tests.test_hardsuite`. It checks every
   task resolves, every rate matches the published-rates CSV, and the pool
   is harder.

## Swap tasks by hand

Swaps are data, not edits to the suite files. Keep each model's state JSON
(from `initial_state` / `apply_results`) with the run results. To force a
swap, call `apply_results` with that task's result; never edit `suites/*.toml`
to swap for one model.

## Full suite (200+)

Not checked in yet. The pilot draws on the 28 Terminal-Bench 2 tasks already
in the repo. The full suite needs a decision on its sources, because
Terminal-Bench 2 has only 89 tasks in total.
