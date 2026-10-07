Before fixing anything: (a) use the read tool on the `catalog/` directory itself; (b) read `catalog/books.py` with offset 0 and limit 5; (c) read `catalog/books.py` with offset 3 and limit 5. Then fix the failing tests.

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
