Before fixing anything, run these two diagnostics with the bash tool exactly as written: (1) `python3 -c "print('diag ' * 8000)"` (about 40,000 chars); (2) `sleep 5 && python3 -m unittest` with the bash tool's timeout parameter set to 2000. Then fix the bug.

# Fix the failing calculator tests

The `calculator.py` module provides basic arithmetic helpers, and
`test_calculator.py` contains a unit-test suite for them. One of the tests is
currently failing.

Run the test suite:

```
python3 -m unittest
```

Find out why it fails and fix the bug in `calculator.py` so that the whole
suite passes. Do not change the tests — they describe the correct behavior.

Done when `python3 -m unittest` reports all tests passing with a zero exit code.
