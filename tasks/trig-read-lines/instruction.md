Before fixing anything, use the read tool (not bash) to view only lines 3 through 7 of `catalog/books.py` — a 5-line window, not the whole file — and quote line 3 verbatim at the start of your final answer. Then fix the failing tests.

# Make the test suite pass

`catalog/` is a small library-catalog package with a test suite under `tests/`.
The suite is currently failing in several places.

Run it:

```
python3 -m unittest
```

Work through the failures and fix the code in `catalog/` until the whole suite
passes. The tests describe the intended behavior — treat them as the
specification and do not modify them.

Done when `python3 -m unittest` reports every test passing.
