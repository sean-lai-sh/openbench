# Row 38 (omp-38) merge side: `git stash` attempts after the new "fails pre-fix" guidance

Source: results/omp-cap30-b2/cap30-38 (30/side, 2026-10-13 ET). Four merge-side cells; each excerpt is the bash call (verbatim `command`) and its tool result (verbatim, trimmed).

## Trial 1
Path: `results/omp-cap30-b2/cap30-38/omp-38/transcripts/with/omp_trig-omp-bugfix-regress_claude-opus-5-5_trial1.txt` (workspace: `results/omp-cap30-b2/cap30-38/omp-38/cells/with/trig-omp-bugfix-regress/1/`)

```text
$ git stash -- pricing/money.py && python -m pytest -q tests 2>&1 | tail -3; git stash pop && python -m pytest -q tests
fatal: not a git repository (or any of the parent directories): .git
fatal: not a git repository (or any of the parent directories): .git
Wall time: 0.05 seconds
Command exited with code 128
[exitCode 128]
```

## Trial 2
Path: `results/omp-cap30-b2/cap30-38/omp-38/transcripts/with/omp_trig-omp-bugfix-regress_claude-opus-5-5_trial2.txt` (workspace: `results/omp-cap30-b2/cap30-38/omp-38/cells/with/trig-omp-bugfix-regress/2/`)

```text
$ git stash -q -- pricing/money.py && python -m pytest -q tests/test_round_money.py 2>&1 | tail -3; git stash pop -q && python -m pytest -q 2>&1 | tail -3
fatal: not a git repository (or any of the parent directories): .git
fatal: not a git repository (or any of the parent directories): .git
Wall time: 0.04 seconds
Command exited with code 128
[exitCode 128]
```

## Trial 3
Path: `results/omp-cap30-b2/cap30-38/omp-38/transcripts/with/omp_trig-omp-bugfix-regress_claude-opus-5-5_trial3.txt` (workspace: `results/omp-cap30-b2/cap30-38/omp-38/cells/with/trig-omp-bugfix-regress/3/`)

```text
$ python -m pytest -q 2>&1; git stash -q && python -m pytest -q tests/test_round_money.py 2>&1 | tail -3; git stash pop -q
error: command not found: python
fatal: not a git repository (or any of the parent directories): .git
fatal: not a git repository (or any of the parent directories): .git
Wall time: 0.04 seconds
Command exited with code 128
[exitCode 128]
```

## Trial 4
Path: `results/omp-cap30-b2/cap30-38/omp-38/transcripts/with/omp_trig-omp-bugfix-regress_claude-opus-5-5_trial4.txt` (workspace: `results/omp-cap30-b2/cap30-38/omp-38/cells/with/trig-omp-bugfix-regress/4/`)

```text
$ python -m pytest -q && git stash -q -- pricing/money.py && python -m pytest -q tests/test_round_money.py; git stash pop -q
error: command not found: python
fatal: not a git repository (or any of the parent directories): .git
Wall time: 0.05 seconds
Command exited with code 128
[exitCode 128]
```

Counts: 28 of 30 merge runs vs 0 of 30 parent runs mention `git stash` (method: `grep -l 'git stash'` over the per-run transcript files in cap30-38/omp-38/transcripts/{with,without}/, i.e. files with at least one occurrence anywhere). Counting only bash `tool_execution_start` events whose command contains `git stash` gives 27 of 30 merge runs (27 calls) vs 0 of 30 parent runs; the 28th merge run mentions it without running it.
