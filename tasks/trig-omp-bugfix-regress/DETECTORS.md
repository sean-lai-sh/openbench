# Detectors: trig-omp-bugfix-regress (row 38)

- **Regression test kept (primary):** final workspace has a test (new file, or new function in tests/test_split.py) whose body calls `round_money` with an argument that fails pre-fix (e.g. 2.675, 1.005). Detect by AST: test functions under tests/ referencing `round_money`. Label yes/no per run.
- **Repro before fix:** a bash/python call that runs `round_money(2.675)` (or a test) before the first edit to pricing/money.py.
- **Throwaway scripts:** new non-test .py files outside tests/ left in the workspace.
- Exercised = always.
