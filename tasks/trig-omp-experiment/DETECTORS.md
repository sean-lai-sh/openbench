# Detectors: trig-omp-experiment (row 32)

- **Test files written (primary):** in the final workspace, new files matching `test_*.py`, `*_test.py`, or under a new `tests/` dir (fixture has none). Also count `write`/`edit` tool calls targeting such paths during the run even if later deleted.
- **Experiment run:** ≥1 bash/python tool call that imports `bench.sorts` (or `sorts`) and times it (`time`, `timeit`, `perf_counter`). Expected on both sides.
- **Leftover scaffolding:** other new files besides RESULT.md (throwaway scripts left behind).
- Tokens / tool calls per run as secondary metrics.
- Exercised = always (prompt rule in every request).
