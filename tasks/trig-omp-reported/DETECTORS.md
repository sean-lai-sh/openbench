# Detectors: trig-omp-reported (row 36)

- **Reproduce-before-fix (primary):** did any bash/python call that runs the tests (`pytest`, `python -m pytest`, `unittest`) or calls `parse_date` happen before the first write/edit to `dates/parse.py`? Label yes/no per run.
- **Count of test runs** over the whole run, and wall time spent in them (each pytest run costs ≥8 s from conftest).
- **Verification after fix:** test run after the last edit (expected on both sides; the rule is about confirming the *reported* state, not post-fix checks).
- Exercised = always.
